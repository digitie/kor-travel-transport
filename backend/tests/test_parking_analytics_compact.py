from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.core.time_utils import ensure_tz, to_seoul
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
            # 원문 JSON·출처 등 계산 밖 열을 싣지 않는 고정 7필드 행이다.
            assert all(type(s) is cache.CompactSnapshot for s in actual)
            assert set(cache.CompactSnapshot._fields) == {"id", "airport_id", "parking_lot_id", "observed_at",
                                                         "occupied_spaces", "total_spaces", "available_spaces"}
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


def test_refresh_loads_existing_cache_once_without_rewriting_equal_payloads(analytics_app):
    client, settings, _, _ = analytics_app
    async def warm():
        async with client.app.state.session_factory() as session:
            assert await cache.refresh_default_analytics_cache(session, settings) == 32
            await session.commit()
    asyncio.run(warm())
    statements = []
    payload_updates = []
    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lower().lstrip()
        if normalized.startswith("select") and "analytics_caches" in normalized:
            statements.append(normalized)
        if normalized.startswith("update analytics_caches") and "payload_json=" in normalized:
            payload_updates.append(normalized)
    engine = client.app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        asyncio.run(warm())
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert not payload_updates


def _strip_generated(value):
    if isinstance(value, dict):
        return {key: _strip_generated(item) for key, item in value.items() if key != "generated_at"}
    if isinstance(value, list):
        return [_strip_generated(item) for item in value]
    return value


def _capture_source_reads(client):
    """관측 값을 읽는 SELECT(원본 중복 제거 행 또는 DB 집계)를 모은다."""
    statements = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        normalized = statement.lower()
        if normalized.lstrip().startswith("select") and "parking_snapshots.available_spaces" in normalized:
            statements.append(normalized)

    return statements, capture


@pytest.mark.parametrize("lot_scope", [False, True])
def test_cold_dashboard_reads_source_once_and_matches_single_routes(analytics_app, lot_scope):
    client, _, _, lot_ids = analytics_app
    params = {"airport_code": "GMP"}
    if lot_scope:
        params["parking_lot_id"] = lot_ids[1]
    statements, capture = _capture_source_reads(client)
    engine = client.app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        bundle = client.get("/v1/dashboard/analytics", params=params)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert bundle.status_code == 200
    # 네 기본 분석은 한 번의 원본 읽기를 공유하고, 특수일 패턴만 따로 읽는다(이전: 4+1회).
    assert len(statements) == 2
    assert sum(" or " in sql for sql in statements) == 1  # 특수일 날짜 구간 조건

    payload = bundle.json()
    single = {
        "threshold_events": client.get("/v1/parking/analytics/threshold-events", params=params).json(),
        "threshold_insights": client.get("/v1/parking/analytics/threshold-insights", params=params).json(),
        "weekday_hour_patterns": client.get("/v1/parking/analytics/by-weekday-hour", params=params).json(),
        "time_series": client.get("/v1/parking/analytics/timeseries", params=params).json(),
    }
    for key, expected in single.items():
        assert _strip_generated(payload[key]) == _strip_generated(expected), key
    assert payload["threshold_events"] and payload["time_series"]["items"]


def test_dashboard_source_memo_follows_cache_freshness_contract(analytics_app, monkeypatch):
    client, _, airport_ids, lot_ids = analytics_app
    # 시드의 migration 행은 NOW+1h에 적재됐다. 그 뒤 시각에서 재사용 조건을 확인한다.
    clock = {"now": NOW + timedelta(hours=2)}
    monkeypatch.setattr(cache, "now_utc", lambda: clock["now"])
    monkeypatch.setattr("app.main.now_utc", lambda: clock["now"])
    monkeypatch.setattr("app.services.analytics.now_utc", lambda: clock["now"])
    statements, capture = _capture_source_reads(client)
    engine = client.app.state.engine.sync_engine
    params = {"airport_code": "GMP"}

    def bundle_reads():
        statements.clear()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            response = client.get("/v1/dashboard/analytics", params=params)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert response.status_code == 200
        # 특수일 패턴 읽기를 빼고 네 기본 분석의 원본 읽기만 센다.
        return response.json(), len([sql for sql in statements if " or " not in sql])

    first, reads = bundle_reads()
    assert reads == 1
    again, reads = bundle_reads()
    assert reads == 0
    assert again == first

    # 새 commit은 범위와 무관하게 원본 지문을 바꿔 다시 계산하게 한다(수집은 모든 공항을 함께 적재한다).
    async def add_observation(airport_id, lot_id, available):
        async with client.app.state.session_factory() as session:
            session.add(ParkingSnapshot(
                airport_id=airport_id, parking_lot_id=lot_id, source="live",
                observed_at=clock["now"] - timedelta(minutes=1), collected_at=clock["now"] + timedelta(seconds=1),
                available_spaces=available, occupied_spaces=100 - available, total_spaces=100,
                raw_item_json={},
            ))
            await session.commit()

    asyncio.run(add_observation(airport_ids[1], lot_ids[4], 33))
    clock["now"] += timedelta(seconds=2)
    _, reads = bundle_reads()
    assert reads == 1
    _, reads = bundle_reads()
    assert reads == 0

    # 같은 범위에 생성 뒤 적재된 관측은 다시 계산하게 한다.
    asyncio.run(add_observation(airport_ids[0], lot_ids[0], 37))
    clock["now"] += timedelta(seconds=2)
    refreshed, reads = bundle_reads()
    assert reads == 1
    assert refreshed["time_series"]["items"][-1]["available_spaces"] != first["time_series"]["items"][-1]["available_spaces"]

    # 생성 10분이 지나면 새 적재가 없어도 다시 계산한다.
    _, reads = bundle_reads()
    assert reads == 0
    clock["now"] += cache.MAX_ANALYTICS_CACHE_AGE + timedelta(seconds=1)
    _, reads = bundle_reads()
    assert reads == 1


def test_postgres_special_day_patterns_aggregate_in_database(analytics_app, monkeypatch):
    client, settings, _, _ = analytics_app
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 집계 경로")
    selected_dates = [date(2026, 10, 25), date(2026, 10, 26)]

    async def holidays(_start, _end):
        return HolidayLookupResult(source="sample", status="success", error_message=None,
                                   items=[HolidayItem(day, "검증 공휴일") for day in selected_dates])

    monkeypatch.setattr(client.app.state.holiday_service, "get_holidays", holidays)
    statements, capture = _capture_source_reads(client)
    engine = client.app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get("/v1/parking/analytics/holiday-patterns", params={"airport_code": "GMP", "limit": 2})
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    # 관측 행을 API로 옮기지 않고 DB가 (현지 날짜, 시)별 개수·합·최소·최대만 돌려준다.
    assert len(statements) == 1
    sql = statements[0]
    assert "timezone(" in sql and "count(*)" in sql and "group by" in sql
    assert "raw_item_json" not in sql


def test_dashboard_source_memo_for_lot_outside_airport_tracks_the_lot(analytics_app, monkeypatch):
    """주차장이 다른 공항 소속이어도 원본은 그 주차장을 읽으므로 그 주차장의 새 적재로 무효화한다."""
    client, _, airport_ids, lot_ids = analytics_app
    clock = {"now": NOW + timedelta(hours=2)}
    monkeypatch.setattr(cache, "now_utc", lambda: clock["now"])
    monkeypatch.setattr("app.main.now_utc", lambda: clock["now"])
    monkeypatch.setattr("app.services.analytics.now_utc", lambda: clock["now"])
    statements, capture = _capture_source_reads(client)
    engine = client.app.state.engine.sync_engine
    params = {"airport_code": "PUS", "parking_lot_id": lot_ids[0]}  # GMP 주차장

    def source_reads():
        statements.clear()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            assert client.get("/v1/dashboard/analytics", params=params).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        return len([sql for sql in statements if " or " not in sql])

    assert source_reads() == 1
    assert source_reads() == 0

    async def add_observation():
        async with client.app.state.session_factory() as session:
            session.add(ParkingSnapshot(
                airport_id=airport_ids[0], parking_lot_id=lot_ids[0], source="live",
                observed_at=clock["now"] - timedelta(minutes=1), collected_at=clock["now"] + timedelta(seconds=1),
                available_spaces=41, occupied_spaces=59, total_spaces=100, raw_item_json={},
            ))
            await session.commit()

    asyncio.run(add_observation())
    clock["now"] += timedelta(seconds=2)
    assert source_reads() == 1


def test_postgres_dashboard_source_memo_sees_rows_stamped_before_a_late_commit(analytics_app, monkeypatch):
    """수집기는 삽입 때 collected_at을 찍고 나중에 commit한다. 그 사이 계산한 memo도 commit 뒤 무효다."""
    client, settings, airport_ids, lot_ids = analytics_app
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("동시 transaction 가시성은 PostgreSQL에서 검증")
    clock = {"now": NOW + timedelta(hours=2)}
    monkeypatch.setattr(cache, "now_utc", lambda: clock["now"])
    monkeypatch.setattr("app.main.now_utc", lambda: clock["now"])
    monkeypatch.setattr("app.services.analytics.now_utc", lambda: clock["now"])
    statements, capture = _capture_source_reads(client)
    engine = client.app.state.engine.sync_engine
    params = {"airport_code": "GMP"}

    def source_reads():
        statements.clear()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            response = client.get("/v1/dashboard/analytics", params=params)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert response.status_code == 200
        return response.json(), len([sql for sql in statements if " or " not in sql])

    async def scenario():
        async with client.app.state.session_factory() as writer:
            writer.add(ParkingSnapshot(
                airport_id=airport_ids[0], parking_lot_id=lot_ids[0], source="live",
                observed_at=clock["now"] - timedelta(minutes=1), collected_at=clock["now"],
                available_spaces=43, occupied_spaces=57, total_spaces=100, raw_item_json={},
            ))
            await writer.flush()  # 삽입했지만 아직 commit 전
            clock["now"] += timedelta(seconds=5)
            before, reads = await asyncio.to_thread(source_reads)
            assert reads == 1
            assert before["time_series"]["items"][-1]["available_spaces"] != 43
            await writer.commit()
        clock["now"] += timedelta(seconds=5)
        after, reads = await asyncio.to_thread(source_reads)
        assert reads == 1
        assert after["time_series"]["items"][-1]["available_spaces"] == 43

    asyncio.run(scenario())


@pytest.mark.parametrize("lot_scope", [False, True])
def test_postgres_special_day_aggregate_values_match_python(analytics_app, lot_scope):
    client, settings, airport_ids, lot_ids = analytics_app
    if not settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 집계 경로")
    from app.services.analytics import special_day_hour_aggregates
    days = [date(2026, 10, 25), date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 20)]
    special_days = [(day, "", "") for day in days]
    tz = "Asia/Seoul"

    async def check():
        async with client.app.state.session_factory() as session:
            from zoneinfo import ZoneInfo
            ranges = []
            for day in days:
                start = datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo(tz)).astimezone(timezone.utc)
                ranges.append((ParkingSnapshot.observed_at >= start) & (ParkingSnapshot.observed_at < start + timedelta(days=1)))
            from sqlalchemy import or_
            conditions = [or_(*ranges)]
            conditions.append(ParkingSnapshot.parking_lot_id == lot_ids[0] if lot_scope
                              else ParkingSnapshot.airport_id == airport_ids[0])
            actual = await cache.aggregate_special_day_hours(session, conditions, tz)
            originals = (await session.scalars(select(ParkingSnapshot).where(*conditions))).all()
            expected = special_day_hour_aggregates(deduplicate_snapshots(originals), special_days, tz_name=tz)
            assert actual == expected
            assert actual and all(type(value) is int for aggregate in actual.values() for value in aggregate)

    asyncio.run(check())


def test_cold_dashboard_computes_off_the_event_loop_thread(analytics_app, monkeypatch):
    """운영 2026-11-24: ICN 원본 계산(25~30초)이 event loop를 막아 같은 프로세스의 다른 공항 요청까지 504였다.

    원본 읽기 뒤 계산은 thread에서 한다 — 계산 함수가 event loop thread가 아닌 곳에서 불린다.
    """
    import threading

    import app.main as main_module

    client, _, _, _ = analytics_app
    loop_threads = []
    compute_threads = []
    original = main_module.compact_rows_with_references

    async def loop_marker():
        loop_threads.append(threading.get_ident())

    def recording(rows):
        compute_threads.append(threading.get_ident())
        return original(rows)

    monkeypatch.setattr(main_module, "compact_rows_with_references", recording)
    client.portal.call(loop_marker)
    response = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
    assert response.status_code == 200
    assert response.headers["x-analytics-source"] == "source"
    assert compute_threads and loop_threads
    assert loop_threads[0] not in compute_threads


def test_special_day_aggregate_is_reused_briefly_unless_today_is_included(analytics_app, monkeypatch):
    client, _, _, _ = analytics_app
    past_dates = [date(2026, 10, 25), date(2026, 10, 26)]
    selected = list(past_dates)

    async def holidays(_start, _end):
        return HolidayLookupResult(source="sample", status="success", error_message=None,
                                   items=[HolidayItem(day, "검증 공휴일") for day in selected])

    monkeypatch.setattr(client.app.state.holiday_service, "get_holidays", holidays)
    statements, capture = _capture_source_reads(client)
    engine = client.app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        params = {"airport_code": "GMP", "limit": 2}
        first = client.get("/v1/parking/analytics/holiday-patterns", params=params)
        reads = len(statements)
        second = client.get("/v1/parking/analytics/holiday-patterns", params=params)
        assert reads >= 1 and len(statements) == reads  # 지난 특수일만이면 짧게 재사용한다.
        assert _strip_generated(first.json()) == _strip_generated(second.json())
        # 오늘(현지)이 특수일이면 오늘분만 매번 집계하고 지난 날짜분은 보관한 것을 쓴다(주말·공휴일 사전 리뷰 P1).
        selected[:] = [to_seoul(NOW).date()]
        client.get("/v1/parking/analytics/holiday-patterns", params=params)
        reads = len(statements)
        client.get("/v1/parking/analytics/holiday-patterns", params=params)
        assert len(statements) - reads == 1
        today_sql = statements[-1]
        client.get("/v1/parking/analytics/holiday-patterns", params=params)
        assert len(statements) - reads == 2 and statements[-1] == today_sql
    finally:
        event.remove(engine, "before_cursor_execute", capture)
