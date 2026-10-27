from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.core.time_utils import ensure_tz
from app.main import create_app
from app.models import Airport, AnalyticsCache, ParkingLot, ParkingSnapshot
from app.services import analytics_cache as cache
from app.services.analytics import (
    build_threshold_insights,
    build_special_day_patterns,
    build_time_series,
    build_weekday_hour_patterns,
    deduplicate_snapshot_rows,
    deduplicate_snapshots,
    detect_threshold_events,
)
from app.services.holidays import HolidayItem, HolidayLookupResult

NOW = datetime(2026, 10, 27, 0, 5, 30, tzinfo=timezone.utc)


def _utc_payload(value):
    if isinstance(value, list):
        return [_utc_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: _utc_payload(item) for key, item in value.items()}
    if isinstance(value, str) and "T" in value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except ValueError:
            pass
    return value


@pytest.fixture
def analytics_app(test_settings, monkeypatch):
    settings = test_settings.model_copy(update={
        "seed_sample_data": False, "scheduler_mode": "dagster", "airport_codes_csv": "GMP,PUS",
        "transport_map_current_enabled": False,
    })
    monkeypatch.setattr(cache, "now_utc", lambda: NOW)
    monkeypatch.setattr("app.main.now_utc", lambda: NOW)
    monkeypatch.setattr("app.services.analytics.now_utc", lambda: NOW)
    with TestClient(create_app(settings)) as client:
        async def seed():
            async with client.app.state.session_factory() as session:
                airports = []
                lots = []
                for code, name in [("GMP", "김포국제공항"), ("PUS", "김해국제공항")]:
                    airport = Airport(code=code, name_ko=name, source="test", created_at=NOW, updated_at=NOW)
                    session.add(airport)
                    await session.flush()
                    airports.append(airport)
                    for index in range(4):
                        lot = ParkingLot(airport_id=airport.id, source_lot_id=f"{code}-{index}",
                            name=f"{name} 주차장 {index}", is_active=index != 2, created_at=NOW, updated_at=NOW)
                        session.add(lot)
                        await session.flush()
                        lots.append(lot)
                        if index == 3:  # 활성이나 관측이 없는 범위도 네 metric을 저장한다.
                            continue
                        dates = []
                        for days, buffer in [(7, 0), (7, 10), (14, 0), (21, 0), (21, 10)]:
                            boundary = NOW - timedelta(days=days, minutes=buffer)
                            dates.extend(boundary + timedelta(microseconds=offset) for offset in [-1, 0, 1])
                        dates.extend([datetime(2026, 10, 25, 14, 59, tzinfo=timezone.utc),
                                      datetime(2026, 10, 25, 15, 0, tzinfo=timezone.utc)])
                        dates.extend(NOW - timedelta(minutes=5 * i) for i in range(40, 0, -1))
                        for ordinal, observed in enumerate(sorted(set(dates))):
                            available = 70 if ordinal % 2 else 5
                            session.add(ParkingSnapshot(airport_id=airport.id, parking_lot_id=lot.id,
                                source="live", observed_at=observed, collected_at=NOW - timedelta(minutes=1),
                                available_spaces=available, occupied_spaces=100-available, total_spaces=100,
                                raw_item_json={"provider_unused": "x" * 8192}))
                        for minute, options in [
                            (31, [("live", NOW-timedelta(hours=1), 70), ("migration_http", NOW+timedelta(hours=1), 0)]),
                            (32, [("live_a", NOW, 80), ("live_b", NOW, 20)]),
                            (33, [("migrationX", NOW, 60), ("migration_http", NOW+timedelta(hours=1), 0)]),
                            (34, [("live_a", NOW-timedelta(minutes=2), 90), ("live_b", NOW-timedelta(minutes=1), 10)]),
                        ]:
                            for source, collected, available in options:
                                session.add(ParkingSnapshot(airport_id=airport.id, parking_lot_id=lot.id,
                                    source=source, observed_at=NOW-timedelta(minutes=minute), collected_at=collected,
                                    available_spaces=available, occupied_spaces=100-available, total_spaces=100,
                                    raw_item_json={"provider_unused": "x" * 8192}))
                await session.commit()
                return [airport.id for airport in airports], [lot.id for lot in lots]

        airport_ids, lot_ids = asyncio.run(seed())
        yield client, settings, airport_ids, lot_ids


def _legacy_payloads(airport, lot_id, snapshots, lots):
    """변경 전 ORM·Python 중복 제거/창 선택으로 전체 네 payload를 독립 계산한다."""
    scoped = [s for s in snapshots if s.airport_id == airport.id and (lot_id is None or s.parking_lot_id == lot_id)]

    def window(days, buffer=0):
        cutoff = NOW-timedelta(days=days, minutes=buffer)
        return deduplicate_snapshots([s for s in scoped if ensure_tz(s.observed_at, "UTC") >= cutoff])

    events = deduplicate_snapshot_rows([
        (s, lots[s.parking_lot_id], airport) for s in scoped
        if ensure_tz(s.observed_at, "UTC") >= NOW-timedelta(days=14) and s.parking_lot_id in lots
    ])
    insights = build_threshold_insights(build_time_series(window(21, 10), days=21, interval_minutes=10))
    return cache.serialize_json_payload({
        "timeseries": {"generated_at": NOW, "airport_code": airport.code, "parking_lot_id": lot_id,
            "days": 7, "interval_minutes": 10, "future_hours": 0,
            "items": build_time_series(window(7, 10), days=7, interval_minutes=10)},
        "weekday_hour": build_weekday_hour_patterns(window(14)),
        "threshold_events": detect_threshold_events(events, limit=20),
        "threshold_insights": {"generated_at": NOW, "airport_code": airport.code, "parking_lot_id": lot_id,
            "days": 21, "interval_minutes": 10, **insights},
    })


def test_every_compact_scope_matches_legacy_payload_and_metadata(analytics_app):
    client, settings, _, _ = analytics_app

    async def check():
        async with client.app.state.session_factory() as session:
            airports = (await session.scalars(select(Airport).order_by(Airport.id))).all()
            lots = {lot.id: lot for lot in (await session.scalars(select(ParkingLot))).all()}
            snapshots = (await session.scalars(select(ParkingSnapshot))).all()
            expected = {}
            for airport in airports:
                for lot_id in [None, *(lot.id for lot in lots.values() if lot.airport_id == airport.id and lot.is_active)]:
                    expected[(airport.code, lot_id)] = _legacy_payloads(airport, lot_id, snapshots, lots)
            assert await cache.refresh_default_analytics_cache(session, settings) == len(expected)*4
            await session.flush()
            rows = (await session.scalars(select(AnalyticsCache))).all()
            assert len(rows) == len(expected)*4
            for row in rows:
                assert row.payload_json == expected[(row.airport_code, row.parking_lot_id)][row.metric]
                assert ensure_tz(row.generated_at, "UTC") == NOW
                airport = next(a for a in airports if a.code == row.airport_code)
                source_times = [ensure_tz(s.observed_at, "UTC") for s in snapshots if s.airport_id == airport.id
                                and (row.parking_lot_id is None or s.parking_lot_id == row.parking_lot_id)]
                assert (ensure_tz(row.source_observed_at, "UTC") if row.source_observed_at else None) == max(source_times, default=None)
            events = expected[("GMP", None)]["threshold_events"]
            assert len(events) == 20
            assert all(item["airport_name"] == "김포국제공항" and "주차장" in item["parking_lot_name"] for item in events)
            await session.rollback()

    asyncio.run(check())


def test_refresh_reads_compact_observations_once_per_airport(analytics_app):
    client, settings, airports, _ = analytics_app
    statements = []
    engine = client.app.state.engine.sync_engine

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        async def check():
            async with client.app.state.session_factory() as session:
                assert await cache.refresh_default_analytics_cache(session, settings) == 32
                await session.rollback()
        asyncio.run(check())
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    snapshot_queries = [sql for sql in statements if "parking_snapshots" in sql and sql.lstrip().startswith("select")]
    assert snapshot_queries
    assert all("raw_item_json" not in sql for sql in snapshot_queries)
    raw_value_reads = [sql for sql in snapshot_queries if "parking_snapshots.available_spaces" in sql]
    assert len(raw_value_reads) == len(airports)


def test_compact_projection_preserves_literal_source_priority_and_output_order(analytics_app):
    client, _, _, _ = analytics_app

    async def check():
        async with client.app.state.session_factory() as session:
            original = (await session.scalars(select(ParkingSnapshot))).all()
            expected = deduplicate_snapshots(original)
            actual = await cache.load_compact_analytics_snapshots(session, [])
            assert [(s.id, s.parking_lot_id, ensure_tz(s.observed_at, "UTC"), s.available_spaces) for s in actual] == [
                (s.id, s.parking_lot_id, ensure_tz(s.observed_at, "UTC"), s.available_spaces) for s in expected]
            assert all(set(vars(s)) == {"id", "airport_id", "parking_lot_id", "observed_at",
                                      "occupied_spaces", "total_spaces", "available_spaces"} for s in actual)
            for minute, available in [(31, 70), (32, 20), (33, 60), (34, 10)]:
                at = NOW-timedelta(minutes=minute)
                assert all(s.available_spaces == available for s in actual if ensure_tz(s.observed_at, "UTC") == at)

    asyncio.run(check())


@pytest.mark.parametrize("scope", ["airport", "lot_overrides_airport"])
def test_cold_dashboard_uses_compact_values_and_preserves_names(analytics_app, scope):
    client, _, _, lot_ids = analytics_app
    airport_code = "GMP" if scope == "airport" else "PUS"
    lot_id = None if scope == "airport" else lot_ids[0]

    async def expected_payload():
        async with client.app.state.session_factory() as session:
            airport = await session.scalar(select(Airport).where(Airport.code == "GMP"))
            lots = {lot.id: lot for lot in (await session.scalars(select(ParkingLot))).all()}
            snapshots = (await session.scalars(select(ParkingSnapshot))).all()
            return _legacy_payloads(airport, lot_id, snapshots, lots)

    expected = asyncio.run(expected_payload())
    statements = []
    engine = client.app.state.engine.sync_engine
    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())
    event.listen(engine, "before_cursor_execute", capture)
    try:
        params = {"airport_code": airport_code}
        if lot_id is not None:
            params["parking_lot_id"] = lot_id
        response = client.get("/v1/dashboard/analytics", params=params)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    payload = response.json()
    assert _utc_payload(payload["time_series"]["items"]) == expected["timeseries"]["items"]
    assert payload["weekday_hour_patterns"] == expected["weekday_hour"]
    assert _utc_payload(payload["threshold_events"]) == expected["threshold_events"]
    for key in ["weekday_items", "history_items"]:
        assert _utc_payload(payload["threshold_insights"][key]) == expected["threshold_insights"][key]
    assert all("raw_item_json" not in sql for sql in statements if "parking_snapshots" in sql)


def test_unscoped_cold_weekday_and_events_keep_every_airport(analytics_app):
    client, _, _, _ = analytics_app
    weekday = client.get("/v1/parking/analytics/by-weekday-hour")
    events = client.get("/v1/parking/analytics/threshold-events", params={"limit": 100})
    assert weekday.status_code == events.status_code == 200
    assert {row["airport_code"] for row in events.json()} == {"GMP", "PUS"}
    assert sum(row["observations"] for row in weekday.json()) > 0


def test_refresh_generation_stays_before_first_snapshot_read(analytics_app, monkeypatch):
    client, settings, _, _ = analytics_app
    engine = client.app.state.engine.sync_engine
    reads = []

    def advance_clock(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith("select") and "parking_snapshots" in statement:
            reads.append(statement)
            monkeypatch.setattr(cache, "now_utc", lambda: NOW + timedelta(minutes=11))

    event.listen(engine, "before_cursor_execute", advance_clock)
    try:
        async def check():
            async with client.app.state.session_factory() as session:
                assert await cache.refresh_default_analytics_cache(session, settings) == 32
                await session.flush()
                rows = (await session.scalars(select(AnalyticsCache))).all()
                assert all(ensure_tz(row.generated_at, "UTC") == NOW for row in rows)
                await session.rollback()
        asyncio.run(check())
    finally:
        event.remove(engine, "before_cursor_execute", advance_clock)
    assert reads


@pytest.mark.parametrize("lot_overrides_airport", [False, True])
def test_cold_special_dates_preserve_kst_boundaries_and_compact_projection(
    analytics_app, monkeypatch, lot_overrides_airport,
):
    client, _, _, lot_ids = analytics_app
    selected_dates = [date(2026, 10, 25), date(2026, 10, 26)]
    special_days = [(day, "검증 공휴일", "holiday") for day in selected_dates]

    async def holidays(_start, _end):
        return HolidayLookupResult(
            source="sample", status="success", error_message=None,
            items=[HolidayItem(day, "검증 공휴일") for day in selected_dates],
        )

    monkeypatch.setattr(client.app.state.holiday_service, "get_holidays", holidays)
    lot_id = lot_ids[0] if lot_overrides_airport else None

    async def expected_items():
        async with client.app.state.session_factory() as session:
            airport = await session.scalar(select(Airport).where(Airport.code == "GMP"))
            conditions = [ParkingSnapshot.airport_id == airport.id]
            if lot_id is not None:
                conditions.append(ParkingSnapshot.parking_lot_id == lot_id)
            originals = (await session.scalars(select(ParkingSnapshot).where(*conditions))).all()
            return build_special_day_patterns(deduplicate_snapshots(originals), special_days)

    expected = asyncio.run(expected_items())
    engine = client.app.state.engine.sync_engine
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        params = {"airport_code": "PUS" if lot_overrides_airport else "GMP", "limit": 2}
        if lot_id is not None:
            params["parking_lot_id"] = lot_id
        response = client.get("/v1/parking/analytics/holiday-patterns", params=params)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert response.json()["items"] == expected
    assert {row["local_date"] for row in expected} == {day.isoformat() for day in selected_dates}
    assert all(row["observations"] > 0 for row in expected)
    snapshot_queries = [sql for sql in statements if "parking_snapshots" in sql]
    assert snapshot_queries and all("raw_item_json" not in sql for sql in snapshot_queries)
