from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
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

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.main import create_app
from app.models import FuelPriceSnapshot, FuelStation, HighwayIncidentSnapshot, HighwayTrafficSnapshot, TransportCollectionState
from app.services.transport_collection import (
    HighwayPayload,
    INCIDENT_SOURCE,
    OPINET_SOURCE,
    TRAFFIC_SOURCE,
    LiveTransportProvider,
    TransportCollectionService,
    _collect_krex_pages,
    _traffic_identity,
)


class FakeTransportProvider:
    mode = "fixture"
    enabled_sources = (TRAFFIC_SOURCE, INCIDENT_SOURCE, OPINET_SOURCE)

    def __init__(self) -> None:
        self.observed_at = now_utc()
        self.incident_process_status = "처리중"

    async def collect_highway(self, *, sources=(TRAFFIC_SOURCE, INCIDENT_SOURCE)) -> HighwayPayload:
        return HighwayPayload(
            traffic=(
                TrafficFlow(
                    conzone_id="1001",
                    conzone_name="테스트 구간",
                    route_no="001",
                    route_name="테스트고속도로",
                    direction=Direction.EAST,
                    speed=82.0,
                    free_flow_speed=100.0,
                    congestion_level=CongestionLevel.SMOOTH,
                    updated_at=self.observed_at.strftime("%Y%m%d%H%M%S"),
                    raw={"routeNo": "001"},
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
        async with session_factory() as session:
            second = await service.collect(session, scope="highway", trigger="test")
        async with session_factory() as session:
            snapshot = await session.scalar(select(HighwayTrafficSnapshot))
            assert snapshot is not None
            second_snapshot = (snapshot.collection_run_id, snapshot.collected_at)
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
    assert {item["source"] for item in status.json()["sources"]} == {
        TRAFFIC_SOURCE,
        INCIDENT_SOURCE,
        OPINET_SOURCE,
    }
    assert status.json()["last_run"]["status"] == "success"
    assert status.json()["last_run"]["trigger"] == "transport_test"


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
