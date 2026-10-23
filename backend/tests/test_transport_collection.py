from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from krex import CongestionLevel, Direction, Incident, KrexQuotaExceededError, TrafficFlow
from opinet import ProductCode, StationType
from opinet.experimental import (
    BrowserFuelPrice,
    BrowserRegion,
    BrowserStation,
    OpinetBrowserCollector,
    OpinetBrowserSnapshot,
    parse_browser_response,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.main import cached_transport_statistics, create_app
from app.models import (
    CollectionRun,
    FuelLatestPrice,
    FuelPriceSnapshot,
    FuelStation,
    HighwayIncidentSnapshot,
    HighwayTrafficFiveMinuteStatistic,
    HighwayTrafficSnapshot,
    TransportCollectionState,
)
from app.services.transport_collection import (
    HighwayPayload,
    INCIDENT_SOURCE,
    OPINET_SOURCE,
    TRAFFIC_SOURCE,
    LiveTransportProvider,
    TransportCollectionService,
    _collect_krex_pages,
    _traffic_identity,
    upsert_latest_fuel_prices,
)


class FakeTransportProvider:
    mode = "fixture"
    enabled_sources = (TRAFFIC_SOURCE, INCIDENT_SOURCE, OPINET_SOURCE)

    def __init__(self) -> None:
        self.observed_at = now_utc()
        self.incident_process_status = "처리중"
        self.traffic_speed = 82.0
        self.traffic_raw = {"routeNo": "001"}

    async def collect_highway(self, *, sources=(TRAFFIC_SOURCE, INCIDENT_SOURCE)) -> HighwayPayload:
        return HighwayPayload(
            traffic=(
                TrafficFlow(
                    conzone_id="1001",
                    conzone_name="테스트 구간",
                    route_no="001",
                    route_name="테스트고속도로",
                    direction=Direction.EAST,
                    speed=self.traffic_speed,
                    free_flow_speed=100.0,
                    congestion_level=CongestionLevel.SMOOTH,
                    updated_at=self.observed_at.strftime("%Y%m%d%H%M%S"),
                    raw=self.traffic_raw,
                ),
            ),
            incidents=(
                Incident(
                    occurred_date=self.observed_at.strftime("%Y%m%d"),
                    occurred_time=self.observed_at.strftime("%H%M"),
                    incident_type="사고",
                    incident_type_code="01",
                    direction="서울방향",
                    message="테스트 돌발",
                    point_name="테스트 IC",
                    route_no="001",
                    route_name="테스트고속도로",
                    process_status=self.incident_process_status,
                    process_status_code="01",
                    latitude=37.4,
                    longitude=127.1,
                    congestion_length=1.2,
                    series_no=10,
                    raw={"seriesNM": "10"},
                ),
            ),
        )

    async def collect_fuel(self) -> OpinetBrowserSnapshot:
        region = BrowserRegion(
            sido_value="11",
            sido_name="서울",
            sigungu_value="110",
            sigungu_name="테스트구",
        )
        station = BrowserStation(
            region=region,
            query_level="sigungu",
            source_kinds=("station",),
            station_id="S-1",
            name="테스트주유소",
            brand_code="SKE",
            brand_name="테스트",
            phone="02-000-0000",
            address="서울 테스트구",
            business_number="123-45-67890",
            cb_code="CB-1",
            station_type=StationType.GAS_STATION,
            katec_x=950000.0,
            katec_y=1950000.0,
            lon=127.1,
            lat=37.4,
            prices=(
                BrowserFuelPrice(
                    product_code=ProductCode.GASOLINE,
                    price=1700.5,
                    updated_at=self.observed_at,
                ),
            ),
            is_illegal=False,
            is_self=True,
            is_24h=True,
            is_kpetro=True,
            is_electronic=True,
            is_good=False,
            is_good_strong=False,
            is_region_franchise=False,
            has_carwash=True,
            has_maintenance=False,
            has_cvs=True,
            cs_yn=True,
            discount_info=None,
            save_event_info=None,
            representative_event_info=None,
            on_event_info=None,
            other_business_info=None,
            raw={"UNI_ID": "S-1"},
        )
        return OpinetBrowserSnapshot(
            collected_at=self.observed_at,
            source_url="https://www.opinet.co.kr/searRgSelect.do",
            regions=(region,),
            stations=(station,),
        )

    def next_fuel_interval(self) -> timedelta:
        return timedelta(hours=10)

    async def aclose(self) -> None:
        return None


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'transport.sqlite3'}",
        seed_sample_data=False,
        enable_scheduler=False,
        transport_collection_enabled=True,
        use_sample_client_when_no_key=True,
        transport_collect_interval_seconds=300,
    )


def test_lifespan_cancels_both_transport_tasks_before_closing_provider(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path)
    settings.enable_scheduler = True
    started: set[str] = set()
    cancelled: set[str] = set()
    ready = asyncio.Event()
    original_close = TransportCollectionService.close

    async def parking_scheduler(app):
        await asyncio.Event().wait()

    async def transport_scheduler(app, scope):
        started.add(scope)
        if started == {"highway", "fuel"}:
            ready.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.add(scope)

    async def close(service):
        assert cancelled == {"highway", "fuel"}
        await original_close(service)

    monkeypatch.setattr("app.main._run_scheduler", parking_scheduler)
    monkeypatch.setattr("app.main._run_transport_scheduler", transport_scheduler)
    monkeypatch.setattr(TransportCollectionService, "close", close)
    with TestClient(create_app(settings)) as client:
        client.portal.call(asyncio.wait_for, ready.wait(), 5)
    assert cancelled == started == {"highway", "fuel"}


def test_transport_collection_stores_and_deduplicates_snapshots(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    provider = FakeTransportProvider()

    async def run() -> tuple[dict, dict, tuple[int | None, datetime], tuple[int | None, datetime]]:
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with session_factory() as session:
            first = await service.collect(session, trigger="test")
        async with session_factory() as session:
            snapshot = await session.scalar(select(HighwayTrafficSnapshot))
            assert snapshot is not None
            first_snapshot = (snapshot.collection_run_id, snapshot.collected_at)
        # 중복 행 처리도 실제 provider 재호출 뒤에만 일어난다. 연속 실행 보호를
        # 우회하는 것이 아니라, 테스트에서 고속도로 소스의 다음 실행 시각만 지난
        # 시각으로 옮겨 두 번째 수집을 의도적으로 수행한다.
        async with session_factory() as session:
            states = (await session.scalars(select(TransportCollectionState))).all()
            for state in states:
                if state.source in {TRAFFIC_SOURCE, INCIDENT_SOURCE}:
                    state.next_due_at = now_utc() - timedelta(seconds=1)
            await session.commit()
        provider.traffic_speed = 71.0
        provider.traffic_raw = {"routeNo": "001", "snapshot": "refreshed"}
        async with session_factory() as session:
            second = await service.collect(session, scope="highway", trigger="test")
        async with session_factory() as session:
            snapshot = await session.scalar(select(HighwayTrafficSnapshot))
            assert snapshot is not None
            second_snapshot = (snapshot.collection_run_id, snapshot.collected_at)
            assert snapshot.speed == 71.0
            assert snapshot.raw_item_json is not None
            assert snapshot.raw_item_json["raw"] == {"routeNo": "001", "snapshot": "refreshed"}
        await service.close()
        await engine.dispose()
        return first, second, first_snapshot, second_snapshot

    first, second, first_snapshot, second_snapshot = asyncio.run(run())

    assert first["status"] == "success"
    assert first["traffic_snapshot_count"] == 1
    assert first["incident_snapshot_count"] == 1
    assert first["fuel_station_count"] == 1
    assert first["fuel_price_count"] == 1
    assert second["traffic_snapshot_count"] == 0
    assert second["incident_snapshot_count"] == 0
    assert second["fuel_station_count"] == 0
    assert second["fuel_price_count"] == 0
    assert second_snapshot[0] != first_snapshot[0]
    assert second_snapshot[1] > first_snapshot[1]
    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/transport/highways/traffic", params={"route_no": "001"})
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["speed"] == 71.0


def test_transport_scopes_store_independently(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    engine, factory = create_engine_and_session_factory(settings.database_url)
    provider = FakeTransportProvider()
    provider.collect_fuel = AsyncMock(wraps=provider.collect_fuel)
    provider.collect_highway = AsyncMock(wraps=provider.collect_highway)

    async def run() -> None:
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with factory() as session:
            highway = await service.collect(session, scope="highway")
        assert highway["traffic_snapshot_count"] == 1
        assert highway["fuel_station_count"] == 0
        provider.collect_fuel.assert_not_awaited()
        async with factory() as session:
            fuel = await service.collect(session, scope="fuel")
        assert fuel["traffic_snapshot_count"] == 0
        assert fuel["fuel_price_count"] == 1
        provider.collect_highway.assert_awaited_once()
        provider.collect_fuel.assert_awaited_once()
        await engine.dispose()

    asyncio.run(run())


def test_slow_fuel_does_not_hold_highway_operation_lock(tmp_path: Path) -> None:
    async def run() -> None:
        service = TransportCollectionService(build_settings(tmp_path), FakeTransportProvider())
        fuel_started = asyncio.Event()
        release_fuel = asyncio.Event()

        async def collect_unlocked(session, trigger, scope):
            if scope == "fuel":
                fuel_started.set()
                await release_fuel.wait()
            return {"scope": scope}

        service._collect_unlocked = collect_unlocked
        service._acquire_database_lock = AsyncMock()
        fuel = asyncio.create_task(service.collect(AsyncMock(), scope="fuel"))
        try:
            await asyncio.wait_for(fuel_started.wait(), 1)
            result = await asyncio.wait_for(service.collect(AsyncMock(), scope="highway"), 1)
            assert result == {"scope": "highway"}
        finally:
            release_fuel.set()
            await fuel

    asyncio.run(run())


def test_transport_database_locks_are_scoped() -> None:
    async def run() -> None:
        session = SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
            execute=AsyncMock(),
        )
        await TransportCollectionService._acquire_database_lock(session, "highway")
        await TransportCollectionService._acquire_database_lock(session, "fuel")
        assert [call.args[1]["lock_key"] for call in session.execute.await_args_list] == [420040, 420041]

    asyncio.run(run())


def test_postgres_slow_fuel_releases_transaction_and_reservation_excludes_duplicate(client) -> None:
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL advisory lock 검증")

    async def run() -> None:
        provider = FakeTransportProvider()
        fuel_started = asyncio.Event()
        release_fuel = asyncio.Event()
        original_collect_fuel = provider.collect_fuel

        async def slow_fuel():
            fuel_started.set()
            await release_fuel.wait()
            return await original_collect_fuel()

        provider.collect_fuel = AsyncMock(side_effect=slow_fuel)
        first = TransportCollectionService(client.app.state.settings, provider)
        second = TransportCollectionService(client.app.state.settings, provider)

        async def collect(service, scope):
            async with client.app.state.session_factory() as session:
                return await service.collect(session, scope=scope)

        fuel = asyncio.create_task(collect(first, "fuel"))
        try:
            await asyncio.wait_for(fuel_started.wait(), 5)
            highway = await asyncio.wait_for(collect(second, "highway"), 5)
            assert highway["traffic_snapshot_count"] == 1
            duplicate = await asyncio.wait_for(collect(second, "fuel"), 5)
            assert duplicate["status"] == "skipped"
            async with client.app.state.session_factory() as session:
                state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE))
                assert state.last_started_at is not None
                assert serialize_utc(state.next_due_at) > now_utc() + timedelta(hours=7)
        finally:
            release_fuel.set()
            await fuel
        provider.collect_fuel.assert_awaited_once()

    client.portal.call(run)


def test_cancelled_fuel_keeps_durable_reservation_and_has_no_open_transaction(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        started = asyncio.Event()
        provider = FakeTransportProvider()
        async with factory() as session:
            async def collect_fuel():
                assert not session.in_transaction()
                started.set()
                await asyncio.Event().wait()

            provider.collect_fuel = AsyncMock(side_effect=collect_fuel)
            service = TransportCollectionService(settings, provider)
            task = asyncio.create_task(service.collect(session, scope="fuel"))
            await asyncio.wait_for(started.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        async with factory() as session:
            replacement = TransportCollectionService(settings, provider)
            result = await replacement.collect(session, scope="fuel")
            assert result["status"] == "skipped"
            assert await replacement.next_collection_delay(session, "fuel") > 7 * 3600
            state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE))
            assert state.last_error == "collection cancelled"
        provider.collect_fuel.assert_awaited_once()
        await engine.dispose()

    asyncio.run(run())


def test_highway_next_due_is_anchored_to_start_and_scheduler_uses_remaining_delay(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        service = TransportCollectionService(settings, FakeTransportProvider())
        started = now_utc() - timedelta(seconds=20)
        async with factory() as session:
            for source in (TRAFFIC_SOURCE, INCIDENT_SOURCE):
                state = await service._get_or_create_state(session, source)
                state.last_started_at = started
                await service._mark_source_success(session, source, now_utc())
                assert serialize_utc(state.next_due_at) == started + timedelta(seconds=300)
            await session.commit()
            delay = await service.next_collection_delay(session, "highway")
            assert 275 < delay <= 280
        await engine.dispose()

    asyncio.run(run())


def test_parking_status_excludes_every_transport_trigger(client) -> None:
    from app.main import _load_collection_run_statuses
    from app.models import CollectionRun

    async def run() -> None:
        async with client.app.state.session_factory() as session:
            for trigger in ("transport_scheduler", "transport_highway_scheduler", "transport_fuel_scheduler", "transport_test"):
                session.add(CollectionRun(started_at=now_utc(), finished_at=now_utc(), status="success", trigger=trigger))
            await session.commit()
            statuses = await _load_collection_run_statuses(session)
            assert all(not item.trigger.startswith("transport_") for item in statuses)

    client.portal.call(run)


def test_krex_pagination_reads_all_pages_and_validates_total_count() -> None:
    pages = {
        1: SimpleNamespace(items=("a", "b"), num_of_rows=2, total_count=3),
        2: SimpleNamespace(items=("c",), num_of_rows=2, total_count=3),
    }
    requested_pages: list[int] = []

    async def fetch(page_no: int) -> SimpleNamespace:
        requested_pages.append(page_no)
        return pages[page_no]

    items = asyncio.run(_collect_krex_pages(fetch, "traffic.flow"))

    assert items == ("a", "b", "c")
    assert requested_pages == [1, 2]


def test_live_highway_reads_flow_once_and_applies_both_filters(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings.transport_route_nos_csv = "001"
    settings.transport_conzone_ids_csv = "1001"

    async def run() -> None:
        payload = await FakeTransportProvider().collect_highway()
        first = payload.traffic[0].model_copy(update={"vds_id": "000001"})
        second = first.model_copy(update={"vds_id": "000002"})
        excluded = first.model_copy(update={"conzone_id": "9999"})
        provider = LiveTransportProvider(settings)
        await provider.krex.aclose()
        provider.krex = SimpleNamespace(
            traffic=SimpleNamespace(
                flow_all=AsyncMock(return_value=SimpleNamespace(items=(first, second, excluded))),
                incident=AsyncMock(return_value=SimpleNamespace(items=(), total_count=0)),
            ),
            aclose=AsyncMock(),
        )
        try:
            result = await provider.collect_highway()
            provider.krex.traffic.flow_all.assert_awaited_once_with()
            assert result.traffic == (first, second)
            assert _traffic_identity(first, "S") != _traffic_identity(second, "S")
        finally:
            await provider.aclose()

    asyncio.run(run())


def test_krex_quota_failure_persists_backoff(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings.transport_quota_backoff_seconds = 3600

    class QuotaProvider(FakeTransportProvider):
        async def collect_highway(self, *, sources=(TRAFFIC_SOURCE, INCIDENT_SOURCE)) -> HighwayPayload:
            raise KrexQuotaExceededError("quota exceeded")

    async def run() -> tuple[dict, list[TransportCollectionState]]:
        engine, session_factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, QuotaProvider())
        async with session_factory() as session:
            summary = await service.collect(session, trigger="test")
            states = list((await session.execute(select(TransportCollectionState))).scalars().all())
        await service.close()
        await engine.dispose()
        return summary, states

    summary, states = asyncio.run(run())

    assert summary["status"] == "partial_success"
    highway_state = next(state for state in states if state.source == TRAFFIC_SOURCE)
    assert highway_state.next_due_at is not None
    assert highway_state.last_error == "quota exceeded"


def test_highway_source_failure_preserves_other_source_and_backoff(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    settings.transport_quota_backoff_seconds = 3600

    async def run() -> None:
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        payload = await FakeTransportProvider().collect_highway()
        provider = LiveTransportProvider(settings)
        await provider.krex.aclose()
        flow = AsyncMock(return_value=SimpleNamespace(items=payload.traffic))
        incident = AsyncMock(side_effect=KrexQuotaExceededError("quota exceeded"))
        provider.krex = SimpleNamespace(
            traffic=SimpleNamespace(flow_all=flow, incident=incident), aclose=AsyncMock()
        )
        service = TransportCollectionService(settings, provider)
        try:
            async with factory() as session:
                result = await service.collect(session, scope="highway")
                assert result["status"] == "partial_success"
                assert result["traffic_snapshot_count"] == 1
                states = {s.source: s for s in (await session.scalars(select(TransportCollectionState))).all()}
                assert states[TRAFFIC_SOURCE].last_error is None
                assert states[INCIDENT_SOURCE].last_error == "quota exceeded"
                states[TRAFFIC_SOURCE].next_due_at = now_utc() - timedelta(seconds=1)
                await session.commit()
                await service.collect(session, scope="highway")
                assert flow.await_count == 2
                assert incident.await_count == 1
        finally:
            await service.close()
            await engine.dispose()

    asyncio.run(run())


def test_highway_backoff_wait_and_status_ignore_skipped_attempt(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    provider = FakeTransportProvider()
    provider.collect_highway = AsyncMock(side_effect=KrexQuotaExceededError("quota exceeded"))

    async def run() -> None:
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with factory() as session:
            failed = await service.collect(session, scope="highway")
            assert failed["status"] == "failed"
            assert await service.next_collection_delay(session, "highway") > 3500
            skipped = await service.collect(session, scope="highway")
            assert skipped["status"] == "skipped"
            assert (await service.status(session))["last_run"]["id"] == failed["collection_run_id"]
        await service.close()
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("slow_source", [TRAFFIC_SOURCE, INCIDENT_SOURCE])
def test_live_highway_timeout_keeps_the_other_source(tmp_path: Path, monkeypatch, slow_source: str) -> None:
    monkeypatch.setattr("app.services.transport_collection.HIGHWAY_FETCH_TIMEOUT_SECONDS", 0.05)

    async def run() -> None:
        payload = await FakeTransportProvider().collect_highway()
        provider = LiveTransportProvider(build_settings(tmp_path))
        await provider.krex.aclose()

        async def stall(*args, **kwargs):
            await asyncio.Event().wait()

        provider.krex = SimpleNamespace(
            traffic=SimpleNamespace(
                flow_all=AsyncMock(side_effect=stall) if slow_source == TRAFFIC_SOURCE else AsyncMock(
                    return_value=SimpleNamespace(items=payload.traffic)),
                incident=AsyncMock(side_effect=stall) if slow_source == INCIDENT_SOURCE else AsyncMock(
                    return_value=SimpleNamespace(items=payload.incidents, total_count=1, num_of_rows=1000)),
            ), aclose=AsyncMock(),
        )
        try:
            result = await provider.collect_highway()
            if slow_source == TRAFFIC_SOURCE:
                assert isinstance(result.traffic, TimeoutError)
                assert result.incidents == payload.incidents
            else:
                assert result.traffic == payload.traffic
                assert isinstance(result.incidents, TimeoutError)
        finally:
            await provider.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("lpg_first", [False, True], ids=["gasoline-first", "lpg-first"])
def test_opinet_cross_region_uid_merge_preserves_stored_prices_and_sources(client, monkeypatch, lpg_first) -> None:
    """실제 provider 병합 결과가 전역 UID 저장에서도 가격·출처를 보존해야 한다."""
    first_region = BrowserRegion(
        sido_value="11", sido_name="서울", sigungu_value="R1", sigungu_name="첫검색지역"
    )
    later_region = replace(first_region, sigungu_value="R2", sigungu_name="다음검색지역")
    gasoline_updated = "2026-09-19 10:00:00"
    lpg_updated = "2026-09-19 11:00:00"
    first_row = {
        "UNI_ID": "S-CROSS-REGION",
        "OS_NM": "지역경계주유소",
        "B034_P": "99999",
        "B027_P": "1700",
        "D047_P": "99999",
        "C004_P": "99999",
        "K015_P": "99999",
        "B027_DT": gasoline_updated,
        "LPG_YN": "N",
    }
    later_row = {
        **first_row,
        "B027_P": "99999",
        "K015_P": "1100",
        "K015_DT": lpg_updated,
        "LPG_YN": "Y",
    }
    if lpg_first:
        first_row, later_row = later_row, first_row
    first_stations = parse_browser_response(
        {"list": [first_row]}, region=first_region, station_kind="station", query_level="sigungu"
    )
    later_stations = parse_browser_response(
        {"list": [later_row]}, region=later_region, station_kind="lpg", query_level="sigungu"
    )
    expected_prices = {
        "B027": (1700, (later_stations if lpg_first else first_stations)[0]
                 .price_by_product[ProductCode.GASOLINE].updated_at),
        "K015": (1100, (first_stations if lpg_first else later_stations)[0]
                 .price_by_product[ProductCode.LPG].updated_at),
    }
    collector = OpinetBrowserCollector()
    page = object()
    discover = AsyncMock(return_value=[first_region, later_region])
    activate = AsyncMock()
    search = AsyncMock(side_effect=[first_stations, (), (), later_stations])
    # 네트워크/브라우저 경계만 대체하고 collect_page의 UID 병합은 실제 구현을 사용한다.
    monkeypatch.setattr(collector, "_discover_regions", discover)
    monkeypatch.setattr(collector, "_activate_tab", activate)
    monkeypatch.setattr(collector, "_search_region", search)
    provider = FakeTransportProvider()
    provider.enabled_sources = (OPINET_SOURCE,)
    service = client.app.state.transport_collection_service
    service.provider = provider

    async def collect_and_verify() -> None:
        snapshot = await collector.collect_page(page)
        provider.collect_fuel = AsyncMock(return_value=snapshot)
        async with client.app.state.session_factory() as session:
            result = await service.collect(session, scope="fuel", trigger="test")
        assert result["status"] == "success"
        assert result["fuel_station_count"] == 1
        # 새 세션에서 commit된 저장값을 검사한다. provider 병합을 backend에서 재구현하지 않는다.
        async with client.app.state.session_factory() as session:
            stations = (await session.scalars(select(FuelStation))).all()
            assert len(stations) == 1
            station = stations[0]
            prices = (await session.scalars(select(FuelPriceSnapshot).where(
                FuelPriceSnapshot.fuel_station_id == station.id
            ))).all()
            for product_code, (expected_price, expected_updated_at) in expected_prices.items():
                product_prices = [price for price in prices if price.product_code == product_code]
                assert len(product_prices) == 1
                price = product_prices[0]
                assert price.price == expected_price
                assert serialize_utc(price.provider_updated_at) == serialize_utc(expected_updated_at)
                assert serialize_utc(price.observed_at) == serialize_utc(expected_updated_at)
            assert station.source_station_id == "S-CROSS-REGION"
            assert station.source_kinds == ["station", "lpg"]
            assert station.station_type == StationType.BOTH.value
            # region은 실제 소재지가 아니라 최초 검색지역이라는 provider 계약이다.
            assert (station.sido_value, station.sigungu_value) == ("11", "R1")
            assert station.sigungu_name == first_region.sigungu_name
        assert len(snapshot.stations) == 1
        provider.collect_fuel.assert_awaited_once_with()
        discover.assert_awaited_once_with(page)
        assert [(call.args[1], call.kwargs["station_kind"]) for call in search.await_args_list] == [
            (first_region, "station"), (later_region, "station"),
            (first_region, "lpg"), (later_region, "lpg"),
        ]

    client.portal.call(collect_and_verify)


def test_station_only_opinet_snapshot_is_not_a_fuel_success(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    provider = FakeTransportProvider()

    async def run() -> None:
        snapshot = await provider.collect_fuel()
        provider.collect_fuel = AsyncMock(return_value=replace(
            snapshot, stations=tuple(replace(station, prices=()) for station in snapshot.stations)
        ))
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with factory() as session:
            result = await service.collect(session, scope="fuel")
            assert result["status"] == "failed"
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE
            ))
            assert state.last_success_at is None
            assert state.last_error is not None
        await service.close()
        await engine.dispose()

    asyncio.run(run())


def test_empty_opinet_snapshot_does_not_mark_fuel_success(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    class EmptyFuelProvider(FakeTransportProvider):
        async def collect_fuel(self) -> OpinetBrowserSnapshot:
            return OpinetBrowserSnapshot(
                collected_at=self.observed_at,
                source_url="https://www.opinet.co.kr/searRgSelect.do",
                regions=(),
                stations=(),
            )

    async def run() -> tuple[dict, TransportCollectionState | None]:
        engine, session_factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, EmptyFuelProvider())
        async with session_factory() as session:
            summary = await service.collect(session, trigger="test")
            fuel_state = await session.scalar(
                select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE)
            )
        await service.close()
        await engine.dispose()
        return summary, fuel_state

    summary, fuel_state = asyncio.run(run())

    assert summary["status"] == "partial_success"
    assert fuel_state is not None
    assert fuel_state.last_success_at is None
    assert fuel_state.last_error is not None


def test_incident_status_change_is_stored_as_a_new_snapshot(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    provider = FakeTransportProvider()

    async def run() -> list[HighwayIncidentSnapshot]:
        engine, session_factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with session_factory() as session:
            await service.collect(session, trigger="test")
            provider.incident_process_status = "처리완료"
            states = list((await session.execute(select(TransportCollectionState))).scalars().all())
            for state in states:
                if state.source in {TRAFFIC_SOURCE, INCIDENT_SOURCE}:
                    state.next_due_at = now_utc() - timedelta(seconds=1)
            await session.commit()
            await service.collect(session, trigger="test")
            incidents = list((await session.execute(select(HighwayIncidentSnapshot))).scalars().all())
        await service.close()
        await engine.dispose()
        return incidents

    incidents = asyncio.run(run())

    assert [item.process_status for item in incidents] == ["처리중", "처리완료"]


def test_transport_collection_dml_runs_against_application_database(client) -> None:
    """CI supplies PostgreSQL through TEST_DATABASE_URL; local runs use SQLite fallback."""
    service = client.app.state.transport_collection_service
    service.provider = FakeTransportProvider()

    async def collect() -> None:
        async with client.app.state.session_factory() as session:
            await service.collect(session, trigger="test")

    asyncio.run(collect())

    response = client.get("/v1/transport/highways/traffic", params={"route_no": "001"})

    assert response.status_code == 200
    assert response.json()["items"][0]["route_no"] == "001"


def test_same_conzone_vds_rows_survive_database_and_public_api(client) -> None:
    service = client.app.state.transport_collection_service
    provider = FakeTransportProvider()

    async def collect() -> None:
        base = await provider.collect_highway()
        provider.collect_highway = AsyncMock(return_value=HighwayPayload(
            traffic=tuple(base.traffic[0].model_copy(update={"vds_id": value}) for value in ("0001", "0002")),
            incidents=(),
        ))
        service.provider = provider
        async with client.app.state.session_factory() as session:
            summary = await service.collect(session, scope="highway")
            assert summary["traffic_snapshot_count"] == 2

    client.portal.call(collect)
    response = client.get("/v1/transport/highways/traffic", params={"route_no": "001"})
    assert response.status_code == 200
    assert {item["identity_key"] for item in response.json()["items"]} == {"vds:0001:E", "vds:0002:E"}


def test_transport_openapi_returns_stored_data_and_statistics(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        service = client.app.state.transport_collection_service
        provider = FakeTransportProvider()
        service.provider = provider

        async def collect() -> None:
            async with client.app.state.session_factory() as session:
                await service.collect(session, trigger="test")

        asyncio.run(collect())

        traffic = client.get("/v1/transport/highways/traffic", params={"route_no": "001"})
        incidents = client.get("/v1/transport/highways/incidents", params={"route_no": "001"})
        fuel = client.get("/v1/transport/fuel/stations", params={"sido_value": "11"})
        statistics = client.get("/v1/transport/statistics", params={"route_no": "001"})
        status = client.get("/v1/transport/collector-status")

    assert traffic.status_code == 200
    assert traffic.json()["items"][0]["route_no"] == "001"
    assert incidents.status_code == 200
    assert incidents.json()["items"][0]["occurred_time"] == provider.observed_at.strftime("%H%M")
    assert fuel.status_code == 200
    assert fuel.json()["items"][0]["prices"][0]["product_code"] == "B027"
    assert statistics.status_code == 200
    assert statistics.json()["traffic"][0]["observations"] == 1
    assert statistics.json()["fuel_prices"][0]["average_price"] == 1700.5
    assert status.status_code == 200
    expected_sources = {
        TRAFFIC_SOURCE,
        INCIDENT_SOURCE,
        OPINET_SOURCE,
    }
    assert {item["source"] for item in status.json()["sources"]} == expected_sources
    assert status.json()["last_run"]["status"] == "success"
    assert status.json()["last_run"]["trigger"] == "transport_test"
    assert status.json()["recent_runs"][0]["id"] == status.json()["last_run"]["id"]


def test_transport_collector_status_keeps_older_running_run_visible(client) -> None:
    async def seed() -> int:
        async with client.app.state.session_factory() as session:
            running = CollectionRun(started_at=now_utc() - timedelta(minutes=1),
                                    status="running", trigger="transport_dagster_highway")
            session.add(running)
            await session.flush()
            running_id = running.id
            for index in range(12):
                session.add(CollectionRun(started_at=now_utc() + timedelta(seconds=index),
                                          finished_at=now_utc(), status="success",
                                          trigger="transport_dagster_fuel"))
            await session.commit()
            return running_id

    running_id = asyncio.run(seed())
    payload = client.get("/v1/transport/collector-status").json()
    assert payload["last_run"]["status"] == "success"
    assert all(run["id"] != running_id for run in payload["recent_runs"])
    assert payload["running_run_count"] == 1
    assert any(run["id"] == running_id and run["status"] == "running"
               for run in payload["running_runs"])


def test_fuel_collection_upserts_latest_prices(client) -> None:
    service = client.app.state.transport_collection_service
    service.provider = FakeTransportProvider()

    async def collect() -> dict:
        async with client.app.state.session_factory() as session:
            return await service.collect(session, scope="fuel", trigger="test")

    result = asyncio.run(collect())
    assert result["status"] == "success"
    fuel = client.get("/v1/transport/fuel/stations", params={"sido_value": "11"})
    assert fuel.status_code == 200
    assert fuel.json()["items"][0]["prices"][0]["price"] == 1700.5
    place = client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "product_code": "B027",
    })
    assert place.status_code == 200
    assert place.json()["total"] == 1
    assert place.json()["items"][0]["latest_price"] == 1700.5


def test_fuel_freshness_follows_the_opinet_collection_state(client) -> None:
    """최신 유가는 원본과 함께 커밋되므로 stale은 수집 실패·정체만 뜻한다(0022)."""
    service = client.app.state.transport_collection_service
    service.provider = FakeTransportProvider()
    empty = client.get("/v1/transport/fuel/stations").json()
    assert empty["items"] == [] and empty["fuel_prices_stale"] is False

    async def collect() -> None:
        async with client.app.state.session_factory() as session:
            assert (await service.collect(session, scope="fuel", trigger="fresh"))["status"] == "success"

    asyncio.run(collect())
    fresh = client.get("/v1/transport/features/places?kind=fuel_station").json()
    assert fresh["fuel_prices_stale"] is False
    assert fresh["fuel_prices_last_refreshed_at"] is not None

    async def set_state(**values) -> None:
        async with client.app.state.session_factory() as session:
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE,
            ))
            for key, value in values.items():
                setattr(state, key, value)
            await session.commit()

    asyncio.run(set_state(last_error="opinet browser failed"))
    assert client.get("/v1/transport/fuel/stations").json()["fuel_prices_stale"] is True
    assert client.get("/v1/transport/collector-status").json()["fuel_prices_stale"] is True
    asyncio.run(set_state(last_error=None, last_success_at=now_utc() - timedelta(hours=25)))
    assert client.get("/v1/transport/features/places?kind=fuel_station").json()["fuel_prices_stale"] is True
    asyncio.run(set_state(last_success_at=now_utc()))
    assert client.get("/v1/transport/fuel/stations").json()["fuel_prices_stale"] is False


def test_highway_job_does_not_touch_fuel_history(client, monkeypatch) -> None:
    """고속도로 job은 더 이상 유가 이력 전체를 읽지 않는다(n150 60초 timeout의 원인)."""
    service = client.app.state.transport_collection_service
    service.provider = FakeTransportProvider()
    statements: list[str] = []
    original_execute = AsyncSession.execute
    original_scalar = AsyncSession.scalar

    async def record_execute(self, statement, *args, **kwargs):
        statements.append(str(statement))
        return await original_execute(self, statement, *args, **kwargs)

    async def record_scalar(self, statement, *args, **kwargs):
        statements.append(str(statement))
        return await original_scalar(self, statement, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "execute", record_execute)
    monkeypatch.setattr(AsyncSession, "scalar", record_scalar)

    async def collect() -> dict:
        async with client.app.state.session_factory() as session:
            return await service.collect(session, scope="highway", trigger="highway_only")

    assert asyncio.run(collect())["status"] == "success"
    assert not any("fuel_price_snapshots" in statement or "fuel_latest_prices" in statement
                   for statement in statements)


def test_transport_statistics_reads_preaggregated_traffic_when_available(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        bucket = now_utc().replace(second=0, microsecond=0)

        async def add_aggregate() -> None:
            async with client.app.state.session_factory() as session:
                session.add(
                    HighwayTrafficFiveMinuteStatistic(
                        bucket_start=bucket,
                        route_no_key="001",
                        direction_key="상행",
                        observations=7,
                        speed_observations=6,
                        speed_sum=420.0,
                        minimum_speed=55.0,
                        maximum_speed=85.0,
                        free_flow_speed_observations=6,
                        free_flow_speed_sum=600.0,
                        latest_observed_at=bucket,
                    )
                )
                await session.commit()

        asyncio.run(add_aggregate())
        statistics = client.get("/v1/transport/statistics", params={"route_no": "001", "days": 1})

    assert statistics.status_code == 200
    assert statistics.json()["traffic"] == [{
        "route_no": "001",
        "direction": "상행",
        "observations": 7,
        "average_speed": 70.0,
        "minimum_speed": 55.0,
        "maximum_speed": 85.0,
        "average_free_flow_speed": 100.0,
        "latest_observed_at": serialize_utc(bucket).isoformat().replace("+00:00", "Z"),
    }]


def test_transport_statistics_uses_short_lived_response_cache(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        service = client.app.state.transport_collection_service
        service.provider = FakeTransportProvider()

        async def collect() -> None:
            async with client.app.state.session_factory() as session:
                await service.collect(session, trigger="test")

        asyncio.run(collect())
        first = client.get("/v1/transport/statistics", params={"route_no": "001", "days": 7})

        async def remove_snapshots() -> None:
            async with client.app.state.session_factory() as session:
                await session.execute(text("DELETE FROM fuel_price_snapshots"))
                await session.execute(text("DELETE FROM highway_incident_snapshots"))
                await session.execute(text("DELETE FROM highway_traffic_snapshots"))
                await session.commit()

        asyncio.run(remove_snapshots())
        cached = client.get("/v1/transport/statistics", params={"route_no": "001", "days": 7})

    assert first.status_code == 200
    assert cached.status_code == 200
    assert cached.json() == first.json()


def test_opinet_latest_wait_policy_is_explicitly_forwarded(tmp_path, monkeypatch):
    from unittest.mock import Mock
    collector = Mock()
    monkeypatch.setattr('app.services.transport_collection.OpinetBrowserCollector', collector)
    provider = LiveTransportProvider(build_settings(tmp_path))
    assert provider.settings.opinet_browser_timeout_ms == 60_000
    assert collector.call_args.kwargs['timeout_ms'] == 60_000
    assert collector.call_args.kwargs['query_level'] == 'sigungu'
    asyncio.run(provider.aclose())


def test_transport_statistics_cache_coalesces_and_evicts_lru_entries() -> None:
    calls = 0
    state = SimpleNamespace(
        settings=SimpleNamespace(transport_statistics_cache_seconds=60, transport_statistics_timeout_seconds=20),
        transport_statistics_cache=OrderedDict(),
        transport_statistics_locks={},
        transport_statistics_miss_semaphore=asyncio.Semaphore(2),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    async def handler(*, request, route_no, days, session):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return {"route_no": route_no, "days": days}

    cached_handler = cached_transport_statistics(handler)

    async def exercise() -> list[dict[str, object]]:
        simultaneous = await asyncio.gather(
            *(cached_handler(request=request, route_no="001", days=7, session=None) for _ in range(8))
        )
        for index in range(129):
            await cached_handler(request=request, route_no=f"route-{index}", days=7, session=None)
        return simultaneous

    simultaneous = asyncio.run(exercise())

    assert calls == 130
    assert simultaneous == [{"route_no": "001", "days": 7}] * 8
    assert len(state.transport_statistics_cache) == 128
    assert ("route-0", 7) not in state.transport_statistics_cache
    assert ("route-128", 7) in state.transport_statistics_cache


def test_transport_statistics_cache_limits_distinct_cache_misses() -> None:
    active = maximum_active = 0
    state = SimpleNamespace(
        settings=SimpleNamespace(transport_statistics_cache_seconds=60, transport_statistics_timeout_seconds=20),
        transport_statistics_cache=OrderedDict(),
        transport_statistics_locks={},
        transport_statistics_miss_semaphore=asyncio.Semaphore(2),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=state))

    async def handler(*, request, route_no, days, session):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return {"route_no": route_no, "days": days}

    cached_handler = cached_transport_statistics(handler)
    async def exercise() -> list[object]:
        return await asyncio.gather(
            *(cached_handler(request=request, route_no=f"route-{index}", days=90, session=None) for index in range(4)),
            return_exceptions=True,
        )

    results = asyncio.run(exercise())

    assert maximum_active == 2
    assert sum(isinstance(result, HTTPException) and result.status_code == 429 for result in results) == 2

def test_transport_status_exposes_a_durable_failed_run(client) -> None:
    service = client.app.state.transport_collection_service
    service.provider = FakeTransportProvider()
    service._store_traffic = AsyncMock(side_effect=RuntimeError("database flush failed"))
    service._store_incidents = AsyncMock(side_effect=RuntimeError("database flush failed"))
    service._store_fuel_snapshot = AsyncMock(side_effect=RuntimeError("database flush failed"))

    async def collect() -> None:
        async with client.app.state.session_factory() as session:
            await service.collect(session, trigger="test")

    asyncio.run(collect())

    status = client.get("/v1/transport/collector-status")

    assert status.status_code == 200
    assert status.json()["last_run"]["status"] == "failed"
    assert status.json()["last_run"]["trigger"] == "transport_test"
    assert status.json()["last_run"]["error"] == "collection_failed"


@pytest.mark.parametrize("failed_source", [INCIDENT_SOURCE, OPINET_SOURCE])
def test_source_database_constraint_failure_keeps_committed_traffic(client, failed_source: str) -> None:
    service = client.app.state.transport_collection_service
    service.provider = FakeTransportProvider()

    async def fail_constraint(session, *args):
        await session.execute(text(
            "INSERT INTO transport_collection_states (source, updated_at) VALUES (NULL, CURRENT_TIMESTAMP)"
        ))

    setattr(service, "_store_incidents" if failed_source == INCIDENT_SOURCE else "_store_fuel_snapshot",
            AsyncMock(side_effect=fail_constraint))

    async def run() -> None:
        async with client.app.state.session_factory() as session:
            result = await service.collect(session, trigger="test")
            assert result["status"] == "partial_success"
            assert result["traffic_snapshot_count"] == 1
        async with client.app.state.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(HighwayTrafficSnapshot)) == 1
            states = {state.source: state for state in (await session.scalars(select(TransportCollectionState))).all()}
            assert states[TRAFFIC_SOURCE].last_success_at is not None
            assert states[TRAFFIC_SOURCE].last_error is None
            assert states[failed_source].last_success_at is None
            assert states[failed_source].last_error is not None

    client.portal.call(run)


def test_cancel_during_incident_storage_preserves_committed_traffic(client) -> None:
    service = client.app.state.transport_collection_service
    service.provider = FakeTransportProvider()
    service._store_incidents = AsyncMock(side_effect=asyncio.CancelledError())

    async def run() -> None:
        async with client.app.state.session_factory() as session:
            with pytest.raises(asyncio.CancelledError):
                await service.collect(session, scope="highway")
        async with client.app.state.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(HighwayTrafficSnapshot)) == 1
            states = {state.source: state for state in (await session.scalars(select(TransportCollectionState))).all()}
            assert states[TRAFFIC_SOURCE].last_success_at is not None
            assert states[TRAFFIC_SOURCE].last_error is None
            assert states[INCIDENT_SOURCE].last_error == "collection cancelled"

    client.portal.call(run)


def test_transport_status_redacts_collection_errors(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        async def set_error() -> None:
            async with client.app.state.session_factory() as session:
                state = TransportCollectionState(
                    source=OPINET_SOURCE,
                    last_error="secret-key=do-not-return",
                    updated_at=now_utc(),
                )
                session.add(state)
                await session.commit()

        asyncio.run(set_error())
        status = client.get("/v1/transport/collector-status")

    assert status.status_code == 200
    assert status.json()["last_fuel_error"] == "collection_failed"
    opinet_status = next(item for item in status.json()["sources"] if item["source"] == OPINET_SOURCE)
    assert opinet_status["last_error"] == "collection_failed"


def test_fuel_openapi_returns_only_the_latest_price_per_product(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        service = client.app.state.transport_collection_service
        provider = FakeTransportProvider()
        service.provider = provider

        async def collect_and_add_history() -> None:
            async with client.app.state.session_factory() as session:
                await service.collect(session, trigger="test")
                station = await session.scalar(select(FuelStation))
                assert station is not None
                session.add_all(
                    [
                        FuelPriceSnapshot(
                            fuel_station_id=station.id,
                            source=OPINET_SOURCE,
                            product_code="B027",
                            price=1600,
                            provider_updated_at=provider.observed_at - timedelta(hours=1),
                            observed_at=provider.observed_at - timedelta(hours=1),
                            collected_at=provider.observed_at,
                        ),
                        FuelPriceSnapshot(
                            fuel_station_id=station.id,
                            source=OPINET_SOURCE,
                            product_code="B027",
                            price=1800,
                            provider_updated_at=provider.observed_at - timedelta(days=10),
                            observed_at=provider.observed_at - timedelta(days=10),
                            collected_at=provider.observed_at + timedelta(minutes=1),
                        ),
                    ]
                )
                await session.flush()
                # 읽기 모델은 수집기 저장 경로의 증분 upsert로만 갱신된다(0022).
                await upsert_latest_fuel_prices(session)
                await session.commit()

        asyncio.run(collect_and_add_history())
        fuel = client.get("/v1/transport/fuel/stations", params={"sido_value": "11"})

    assert fuel.status_code == 200
    assert fuel.json()["items"][0]["prices"] == [
        {
            "product_code": "B027",
            "price": 1800.0,
            "provider_updated_at": (provider.observed_at - timedelta(days=10)).isoformat().replace(
                "+00:00", "Z"
            ),
            "observed_at": (provider.observed_at - timedelta(days=10)).isoformat().replace(
                "+00:00", "Z"
            ),
            "collected_at": (provider.observed_at + timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
        }
    ]



def test_live_krex_calls_pass_the_data_ex_waf_with_the_library_user_agent(tmp_path, monkeypatch) -> None:
    """운영 경로(LiveTransportProvider → krex가 직접 만든 session)가 WAF에 막히지 않는 UA를 보낸다.

    data.ex.co.kr WAF는 2026-10-08부터 `python-httpx/*`·`curl/*` 기본 UA를 400 Request Blocked로
    막았고, 그때 highway 수집이 전부 실패했다. python-krex-api가 `python-krex-api/<version>`을 보낸다.
    """
    seen: list[str] = []

    def waf_like(request: httpx.Request) -> httpx.Response:
        user_agent = request.headers.get("user-agent", "")
        seen.append(user_agent)
        if user_agent.startswith(("python-httpx/", "curl/")):
            return httpx.Response(400, text="<HTML><HEAD><TITLE>400 Bad Request</TITLE></HEAD>"
                                            "<BODY><H1>Request Blocked</H1></BODY></HTML>")
        return httpx.Response(200, json={"count": 0, "realTimeSMSList": []})

    factory = httpx.AsyncClient

    class WafClient(factory):
        def __init__(self, **kwargs) -> None:
            super().__init__(transport=httpx.MockTransport(waf_like), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", WafClient)
    settings = build_settings(tmp_path)
    settings.kex_ex_api_key = "ex-key"
    provider = LiveTransportProvider(settings)

    async def collect():
        try:
            return await provider.collect_highway(sources=(INCIDENT_SOURCE,))
        finally:
            await provider.aclose()

    payload = asyncio.run(collect())
    assert payload.incidents == ()
    assert seen and all(agent.startswith("python-krex-api/") for agent in seen)


def _run_fuel_with_store(tmp_path: Path, store) -> tuple[dict, CollectionRun, TransportCollectionState, AsyncMock]:
    """유가 수집을 한 번 돌린다. `store`가 `_store_fuel_snapshot`을 대신한다(원래 함수를 인자로 받는다)."""
    settings = build_settings(tmp_path)
    provider = FakeTransportProvider()
    provider.collect_fuel = AsyncMock(wraps=provider.collect_fuel)

    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        original = service._store_fuel_snapshot
        service._store_fuel_snapshot = lambda *args: store(original, *args)
        async with factory() as session:
            result = await service.collect(session, trigger="test", scope="fuel")
            run_row = await session.get(CollectionRun, result["collection_run_id"])
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE))
        await service.close()
        await engine.dispose()
        return result, run_row, state

    result, run_row, state = asyncio.run(run())
    return result, run_row, state, provider.collect_fuel


def test_fuel_store_retries_once_after_a_transient_database_timeout(tmp_path: Path) -> None:
    """2026-10-07·10-10 유가 실패: 브라우저 수집(30~50분)을 마친 뒤 저장 단계에서 asyncpg command_timeout이
    메시지 없는 내장 TimeoutError로 올라와 스냅샷 전체를 버렸다. 공급자를 다시 부르지 않고 저장만 한 번 더 한다."""
    calls = []

    async def flaky_store(original, *args):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise TimeoutError()
        return await original(*args)

    result, run_row, state, collect_fuel = _run_fuel_with_store(tmp_path, flaky_store)
    assert calls == [1, 2]
    collect_fuel.assert_awaited_once()
    assert result["status"] == "success"
    assert result["errors"] == []
    assert result["fuel_price_count"] == 1
    assert run_row.error_message is None
    assert state.last_success_at is not None and state.last_error is None


def test_fuel_store_repeated_timeout_is_recorded_with_its_location(tmp_path: Path) -> None:
    """두 번째도 실패하면 실패로 기록하되 "TimeoutError" 한 단어가 아니라 발생 위치를 남긴다."""
    calls = []

    async def failing_store(original, *args):
        calls.append(1)
        raise TimeoutError()

    result, run_row, state, collect_fuel = _run_fuel_with_store(tmp_path, failing_store)
    assert len(calls) == 2
    collect_fuel.assert_awaited_once()
    assert result["status"] == "failed"
    assert len(result["errors"]) == 1
    message = result["errors"][0]
    assert message.startswith("TimeoutError at tests/test_transport_collection.py:")
    assert "in failing_store" in message
    assert "(from app/services/transport_collection.py:" in message and "in _collect_unlocked)" in message
    assert run_row.error_message == message
    assert state.last_error == message and state.last_success_at is None


def test_fuel_store_does_not_retry_a_deterministic_error(tmp_path: Path) -> None:
    calls = []

    async def broken_store(original, *args):
        calls.append(1)
        raise ValueError("price column overflow")

    result, run_row, _state, _collect_fuel = _run_fuel_with_store(tmp_path, broken_store)
    assert len(calls) == 1
    assert result["status"] == "failed"
    assert result["errors"] == ["price column overflow"]


def test_transient_database_error_classification() -> None:
    from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

    from app.services.transport_collection import _is_transient_database_error

    assert _is_transient_database_error(TimeoutError())
    assert _is_transient_database_error(ConnectionResetError())
    assert _is_transient_database_error(OperationalError("SELECT 1", {}, Exception("x"), connection_invalidated=True))
    assert not _is_transient_database_error(OperationalError("SELECT 1", {}, Exception("x")))
    assert not _is_transient_database_error(IntegrityError("INSERT", {}, Exception("dup")))
    assert not _is_transient_database_error(DBAPIError("INSERT", {}, Exception("x")))
    assert not _is_transient_database_error(ValueError("bad"))


def test_safe_error_keeps_messages_and_locates_empty_ones() -> None:
    from app.services.transport_collection import _safe_error

    settings = Settings(kex_ex_api_key="ex-secret", data_go_kr_service_key="go-secret")
    assert _safe_error(RuntimeError("blocked ex-secret go-secret"), settings) == "blocked <redacted> <redacted>"
    # 던져진 적 없는 예외는 위치가 없으니 종류 이름만 남는다(이전 동작).
    assert _safe_error(TimeoutError(), settings) == "TimeoutError"

    def raise_empty():
        raise TimeoutError()

    try:
        raise_empty()
    except TimeoutError as exc:
        located = _safe_error(exc, settings)
    assert located.startswith("TimeoutError at tests/test_transport_collection.py:")
    assert located.endswith("in raise_empty")

@pytest.mark.parametrize("failed_table", ["fuel_price_snapshots", "fuel_latest_prices"])
def test_fuel_store_retries_same_snapshot_after_price_write_rollback(tmp_path: Path, monkeypatch, failed_table) -> None:
    """가격 INSERT까지 실행된 실패도 주유소·가격을 되돌리고 원본으로 재시도한다."""
    execute = AsyncSession.execute
    price_writes = []
    snapshots = []
    empty_on_entry = []

    async def fail_first_price_write(session, statement, *args, **kwargs):
        result = await execute(session, statement, *args, **kwargs)
        if getattr(getattr(statement, "table", None), "name", None) == failed_table:
            price_writes.append(1)
            if len(price_writes) == 1:
                raise TimeoutError("after fixture price write")
        return result

    monkeypatch.setattr(AsyncSession, "execute", fail_first_price_write)

    async def observe_store(original, session, run_id, snapshot):
        snapshots.append((id(snapshot), repr(snapshot)))
        empty_on_entry.append((
            await session.scalar(select(func.count()).select_from(FuelStation)),
            await session.scalar(select(func.count()).select_from(FuelPriceSnapshot)),
            await session.scalar(select(func.count()).select_from(FuelLatestPrice)),
        ))
        return await original(session, run_id, snapshot)

    result, run_row, state, collect_fuel = _run_fuel_with_store(tmp_path, observe_store)
    assert empty_on_entry == [(0, 0, 0), (0, 0, 0)]
    assert len(snapshots) == 2 and snapshots[0] == snapshots[1]
    assert len(price_writes) == 2
    collect_fuel.assert_awaited_once()
    assert result["status"] == "success"
    assert result["fuel_price_count"] == 1
    assert run_row.error_message is None
    assert state.last_success_at is not None and state.last_error is None


def _fuel_state(tmp_path: Path, provider):
    """유가 수집을 한 번 돌리고 오피넷 상태를 돌려준다."""
    settings = build_settings(tmp_path)

    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with factory() as session:
            started = now_utc()
            result = await service.collect(session, trigger="test", scope="fuel")
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE))
        await service.close()
        await engine.dispose()
        return result, state, started

    return asyncio.run(run())


def test_fuel_next_due_is_measured_from_the_collection_start(tmp_path: Path) -> None:
    """2026-10-23 소유자 결정: 성공한 유가 수집의 다음 예정은 시작 + 주기(조금 당김)다. 수집이 1~2시간 걸려도
    다음 8시간 tick을 건너뛰지 않는다(옛 규칙은 완료 + 주기라 실제 주기가 16시간이었다)."""
    from app.services.transport_collection import FUEL_NEXT_DUE_START_SLACK

    provider = FakeTransportProvider()
    result, state, started = _fuel_state(tmp_path, provider)
    assert result["status"] == "success"
    interval = provider.next_fuel_interval()
    started_at = serialize_utc(state.last_started_at)
    assert started <= started_at <= now_utc()
    assert serialize_utc(state.next_due_at) == started_at + interval - FUEL_NEXT_DUE_START_SLACK
    assert timedelta(0) < FUEL_NEXT_DUE_START_SLACK <= timedelta(minutes=30)


def test_in_process_fuel_scheduler_still_waits_a_full_interval(tmp_path: Path) -> None:
    """tick 없는 in-process scheduler는 당긴 폭을 되돌려 기다린다 — 시작 간격 8시간 이상(하루 3회 이하)."""
    provider = FakeTransportProvider()
    provider.next_fuel_interval = lambda: timedelta(hours=8)
    settings = build_settings(tmp_path)

    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with factory() as session:
            assert (await service.collect(session, trigger="test", scope="fuel"))["status"] == "success"
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE))
            delay = await service.next_collection_delay(session, "fuel")
            next_start = now_utc() + timedelta(seconds=delay)
            assert next_start - serialize_utc(state.last_started_at) >= timedelta(hours=8)
        await service.close()
        await engine.dispose()

    asyncio.run(run())


def test_fuel_failure_keeps_the_claimed_start_reservation(tmp_path: Path) -> None:
    """실패 후 시작 기준 예약을 보존해 다음 8시간 tick을 건너뛰지 않는다."""
    provider = FakeTransportProvider()
    provider.collect_fuel = AsyncMock(side_effect=RuntimeError("opinet down"))
    result, state, _started = _fuel_state(tmp_path, provider)
    assert result["status"] == "failed"
    due = serialize_utc(state.next_due_at)
    interval = provider.next_fuel_interval()
    assert due == serialize_utc(state.last_started_at) + interval or abs(
        due - serialize_utc(state.last_started_at) - interval
    ) < timedelta(seconds=1)


def test_eight_hourly_ticks_keep_one_failure_inside_the_export_grace(tmp_path: Path, monkeypatch) -> None:
    """8시간 tick 타임라인: 00:00 tick 성공(완료 01:40) → 08:00 tick이 건너뛰지 않고 돈다 → 시간 초과 실패 →
    16:00 tick은 실패 + 8시간 예약으로 건너뜀 → 다음 00:00 tick이 마지막 성공에서 24시간 안에 다시 돈다.

    시작 지연은 run마다 다르다(00:00 tick은 5분, 08:00 tick은 30초). 그래도 08:00 tick이 due여야 한다.
    """
    from app.service_exports import REFERENCE_STALE_AFTER
    from app.services import transport_collection

    day = datetime(2026, 10, 23, 15, 0, tzinfo=timezone.utc)  # 00:00 KST tick
    clock = {"now": day}
    monkeypatch.setattr(transport_collection, "now_utc", lambda: clock["now"])
    settings = build_settings(tmp_path)
    settings.scheduler_mode = "dagster"
    provider = FakeTransportProvider()
    provider.next_fuel_interval = lambda: timedelta(hours=8)  # 운영 provider 기본값

    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)

        async def state(session):
            return await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE))

        async with factory() as session:
            # 00:00 tick, 5분 늦게 시작, 01:40에 수집 완료 → 성공.
            clock["now"] = day + timedelta(minutes=5)
            provider.observed_at = day + timedelta(hours=1, minutes=40)
            assert (await service.collect(session, trigger="test", scope="fuel"))["status"] == "success"
            success_at = serialize_utc((await state(session)).last_success_at)

            # 08:00 tick, 30초 늦게 시작 → due여야 한다(옛 규칙이면 09:40까지 건너뜀).
            clock["now"] = day + timedelta(hours=8, seconds=30)
            assert await service._fuel_is_due(session)

            async def timeout_at_1130():
                clock["now"] = day + timedelta(hours=11, minutes=30)
                raise TimeoutError()
            provider.collect_fuel = timeout_at_1130
            assert (await service.collect(session, trigger="test", scope="fuel"))["status"] == "failed"

            # 16:00 tick은 원래 시작 + 8시간 예약으로 재시도할 수 있다.
            clock["now"] = day + timedelta(hours=16, seconds=30)
            assert await service._fuel_is_due(session)
            # 다음 00:00 tick은 due이고, 그때 마지막 성공은 아직 export 유예(24시간) 안이다.
            clock["now"] = day + timedelta(hours=24, seconds=30)
            assert await service._fuel_is_due(session)
            assert clock["now"] - success_at < REFERENCE_STALE_AFTER[OPINET_SOURCE]
        await service.close()
        await engine.dispose()

    asyncio.run(run())


def test_fuel_fetch_timeout_fits_inside_job_budget() -> None:
    """2026-10-23 소유자 결정: odroid 성공 수집 5,946~6,371초, 7,200초 상한에서 시간 초과 반복 → 12,600초.

    유가 수집 상한과 저장 여유(최소 20분)가 job 전체 상한(`MAX_RUNTIME_SECONDS - 60`)과 Dagster run 상한 안에
    들어야 한다. 그렇지 않으면 수집이 끝나기 전에 job이 끊겨 실패가 durable하게 남지 않는다.
    """
    from app.dagster.definitions import MAX_RUNTIME_SECONDS
    from app.services import transport_collection

    # odroid 성공 수집 최댓값(6,371초)의 거의 두 배를 넘겨야 상한이 다시 실패 원인이 되지 않는다.
    assert transport_collection.FUEL_FETCH_TIMEOUT_SECONDS >= 12_600
    assert MAX_RUNTIME_SECONDS <= 14_400
    # step 기동(spawn·import) 여유를 더 빼도 저장 여유 20분이 남아야 한다.
    step_startup_reserve = 120
    assert (transport_collection.FUEL_FETCH_TIMEOUT_SECONDS + 20 * 60 + step_startup_reserve
            <= MAX_RUNTIME_SECONDS - 60)


def test_fuel_fetch_timeout_is_enforced_and_logged(tmp_path: Path, monkeypatch, caplog) -> None:
    """상한을 넘긴 브라우저 수집은 실패로 남고, 시작·끝·경과 시간이 진행 로그에 남는다."""
    from app.services import transport_collection

    monkeypatch.setattr(transport_collection, "FUEL_FETCH_TIMEOUT_SECONDS", 0.05)
    settings = build_settings(tmp_path)
    provider = FakeTransportProvider()

    async def slow_fuel():
        await asyncio.sleep(5)

    provider.collect_fuel = AsyncMock(side_effect=slow_fuel)

    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with factory() as session:
            result = await service.collect(session, trigger="test", scope="fuel")
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE))
        await service.close()
        await engine.dispose()
        return result, state

    with caplog.at_level("INFO", logger="app.services.transport_collection"):
        result, state = asyncio.run(run())
    assert result["status"] == "failed"
    assert state.last_success_at is None and state.last_error
    messages = [record.getMessage() for record in caplog.records]
    assert any(m.startswith("fuel browser collection started run_id=") and "timeout=0.05s" in m for m in messages)
    assert any(m.startswith("fuel browser collection failed run_id=") and "elapsed=" in m for m in messages)
    assert any(m.startswith("fuel snapshot store skipped run_id=") for m in messages)


def test_fuel_success_logs_fetch_and_store_progress(tmp_path: Path, caplog) -> None:
    with caplog.at_level("INFO", logger="app.services.transport_collection"):
        result, _run_row, _state, _collect = _run_fuel_with_store(
            tmp_path, lambda original, *args: original(*args))
    assert result["status"] == "success"
    messages = [record.getMessage() for record in caplog.records]
    assert any(m.startswith("fuel browser collection finished run_id=") for m in messages)
    assert any(m.startswith("fuel snapshot store finished run_id=") and "prices=1" in m for m in messages)


@pytest.mark.parametrize("first_size,next_size,complete,status", [
    (0, 0, False, "failed"), (1, 1, False, "failed"), (106, 106, False, "success"),
    (0, 106, False, "success"), (0, 0, True, "success"), (1, 1, True, "success"),
    (0, 1, True, "failed"),
])
def test_highway_empty_or_reduced_response_is_reconfirmed_before_success(
    client, first_size, next_size, complete, status,
):
    from app.models import RawApiResponse

    service = client.app.state.transport_collection_service
    provider = FakeTransportProvider()
    provider.enabled_sources = (INCIDENT_SOURCE,)
    service.provider = provider

    async def run():
        original = await FakeTransportProvider().collect_highway()
        all_items = tuple(original.incidents[0].model_copy(update={"series_no": index})
                          for index in range(106))
        good = HighwayPayload(traffic=None, incidents=all_items)
        candidate = HighwayPayload(traffic=None, incidents=all_items[:next_size],
                                   complete_sources=(INCIDENT_SOURCE,) if complete else ())
        first_candidate = replace(candidate, incidents=all_items[:first_size])
        provider.collect_highway = AsyncMock(side_effect=[good, first_candidate, candidate])
        async with client.app.state.session_factory() as session:
            first = await service.collect(session, scope="highway")
            assert first["status"] == "success"
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == INCIDENT_SOURCE))
            previous_success = state.last_success_at
            state.next_due_at = now_utc() - timedelta(seconds=1)
            await session.commit()
            second = await service.collect(session, scope="highway")
            assert second["status"] == status
            await session.refresh(state)
            if status == "failed":
                assert state.last_success_at == previous_success
                assert "unconfirmed" in state.last_error
                retained = await session.scalar(select(func.count()).select_from(
                    HighwayIncidentSnapshot).where(
                        HighwayIncidentSnapshot.collected_at == previous_success))
                assert retained == 106
            else:
                assert state.last_error is None
                assert state.last_success_at >= previous_success
            successful_raw = list((await session.scalars(select(RawApiResponse).where(
                RawApiResponse.source == INCIDENT_SOURCE, RawApiResponse.status_code == 200,
            ))).all())
            assert len(successful_raw) == (1 if status == "failed" else 2)
        assert provider.collect_highway.await_count == (2 if first_size == 106 else 3)
        assert provider.collect_highway.await_args.kwargs["sources"] == (INCIDENT_SOURCE,)

    client.portal.call(run)


def test_highway_first_empty_without_complete_evidence_is_not_success(client):
    service = client.app.state.transport_collection_service
    provider = FakeTransportProvider()
    provider.enabled_sources = (INCIDENT_SOURCE,)
    provider.collect_highway = AsyncMock(return_value=HighwayPayload(traffic=None, incidents=()))
    service.provider = provider

    async def run():
        async with client.app.state.session_factory() as session:
            result = await service.collect(session, scope="highway")
            assert result["status"] == "failed"
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == INCIDENT_SOURCE))
            assert state.last_success_at is None
            assert state.last_error
        assert provider.collect_highway.await_count == 2

    client.portal.call(run)


def test_krex_only_explicit_complete_total_provides_empty_confirmation():
    async def run():
        for total, expected in ((None, []), (0, [0])):
            complete = []
            async def fetch(_page):
                return SimpleNamespace(items=(), total_count=total, num_of_rows=1000)
            assert await _collect_krex_pages(fetch, "incident", on_complete=complete.append) == ()
            assert complete == expected
    asyncio.run(run())


def test_live_highway_marks_only_validated_incident_totals_complete(tmp_path):
    async def run():
        provider = LiveTransportProvider(build_settings(tmp_path))
        await provider.krex.aclose()
        provider.krex = SimpleNamespace(
            traffic=SimpleNamespace(incident=AsyncMock(return_value=SimpleNamespace(
                items=(), total_count=None, num_of_rows=1000))), aclose=AsyncMock(),
        )
        unknown = await provider.collect_highway(sources=(INCIDENT_SOURCE,))
        assert unknown.complete_sources == ()
        provider.krex.traffic.incident.return_value.total_count = 0
        confirmed = await provider.collect_highway(sources=(INCIDENT_SOURCE,))
        assert confirmed.complete_sources == (INCIDENT_SOURCE,)
        await provider.aclose()
    asyncio.run(run())


def test_highway_retry_failure_keeps_independent_traffic_success(client):
    service = client.app.state.transport_collection_service
    provider = FakeTransportProvider()
    provider.enabled_sources = (TRAFFIC_SOURCE, INCIDENT_SOURCE)
    service.provider = provider

    async def run():
        original = await FakeTransportProvider().collect_highway()
        provider.collect_highway = AsyncMock(side_effect=[
            replace(original, incidents=()), TimeoutError("bounded reconfirm timeout"),
        ])
        async with client.app.state.session_factory() as session:
            result = await service.collect(session, scope="highway")
            assert result["status"] == "partial_success"
            assert result["traffic_snapshot_count"] == 1
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == TRAFFIC_SOURCE))
            assert state.last_success_at is not None and state.last_error is None
        assert provider.collect_highway.await_args.kwargs["sources"] == (INCIDENT_SOURCE,)
    client.portal.call(run)


def test_highway_comparison_does_not_reuse_another_filter_scope(client):
    service = client.app.state.transport_collection_service
    provider = FakeTransportProvider()
    provider.enabled_sources = (TRAFFIC_SOURCE,)
    service.provider = provider

    async def run():
        original = await FakeTransportProvider().collect_highway()
        many = tuple(original.traffic[0].model_copy(update={"vds_id": str(index)})
                     for index in range(12))
        provider.collect_highway = AsyncMock(side_effect=[
            HighwayPayload(traffic=many, incidents=None),
            HighwayPayload(traffic=original.traffic, incidents=None),
        ])
        async with client.app.state.session_factory() as session:
            assert (await service.collect(session, scope="highway"))["status"] == "success"
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == TRAFFIC_SOURCE))
            state.next_due_at = now_utc() - timedelta(seconds=1)
            await session.commit()
            service.settings.transport_route_nos_csv = "new-scope"
            assert (await service.collect(session, scope="highway"))["status"] == "success"
        assert provider.collect_highway.await_count == 2
    client.portal.call(run)


def test_flow_not_found_converted_to_empty_is_not_complete_evidence(tmp_path):
    async def run():
        provider = LiveTransportProvider(build_settings(tmp_path))
        await provider.krex.aclose()
        provider.krex = SimpleNamespace(traffic=SimpleNamespace(flow_all=AsyncMock(
            return_value=SimpleNamespace(items=(), total_count=0, raw=None))), aclose=AsyncMock())
        payload = await provider.collect_highway(sources=(TRAFFIC_SOURCE,))
        assert payload.complete_sources == ()
        service = TransportCollectionService(build_settings(tmp_path), provider)
        confirmed = await service._confirm_highway_payload(payload, (TRAFFIC_SOURCE,),
                                                            {TRAFFIC_SOURCE: None})
        assert isinstance(confirmed.traffic, ValueError)
        assert provider.krex.traffic.flow_all.await_count == 2
        await provider.aclose()
    asyncio.run(run())


def test_highway_retry_source_timeout_does_not_discard_recovered_peer(tmp_path, monkeypatch):
    import app.services.transport_collection as module

    async def run():
        monkeypatch.setattr(module, "HIGHWAY_FETCH_TIMEOUT_SECONDS", 0.03)
        original = await FakeTransportProvider().collect_highway()
        provider = LiveTransportProvider(build_settings(tmp_path))
        await provider.krex.aclose()
        async def stall(**kwargs):
            await asyncio.sleep(1)
        provider.krex = SimpleNamespace(traffic=SimpleNamespace(
            flow_all=AsyncMock(return_value=SimpleNamespace(items=original.traffic)),
            incident=stall,
        ), aclose=AsyncMock())
        service = TransportCollectionService(build_settings(tmp_path), provider)
        result = await service._confirm_highway_payload(
            HighwayPayload(traffic=(), incidents=()), (TRAFFIC_SOURCE, INCIDENT_SOURCE),
            {TRAFFIC_SOURCE: None, INCIDENT_SOURCE: None},
        )
        assert result.traffic == original.traffic
        assert isinstance(result.incidents, TimeoutError)
        await provider.aclose()
    asyncio.run(run())


def test_highway_malformed_empty_parse_error_is_reconfirmed_once(tmp_path):
    from krex import KrexParseError

    async def run():
        provider = FakeTransportProvider()
        original = await provider.collect_highway()
        original = replace(original, incidents=tuple(
            original.incidents[0].model_copy(update={"series_no": index}) for index in range(106)))
        provider.collect_highway = AsyncMock(return_value=original)
        service = TransportCollectionService(build_settings(tmp_path), provider)
        result = await service._confirm_highway_payload(
            replace(original, incidents=KrexParseError("missing complete envelope")),
            (INCIDENT_SOURCE,), {INCIDENT_SOURCE: 106},
        )
        assert result.incidents == original.incidents
        provider.collect_highway.assert_awaited_once_with(sources=(INCIDENT_SOURCE,))
    asyncio.run(run())
