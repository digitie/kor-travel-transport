from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from kric import DomesticFerryPort, FerryShipType, FerryTerminal, FileStationInfo, KricRateLimitError, PortGuidelineLocation
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.time_utils import now_utc, to_seoul
from app.db.session import create_engine_and_session_factory, init_database
from app.models import (
    CollectionRun,
    FerryPort,
    FerryShipTypeReference,
    FerryTerminalReference,
    FerryTimetableSnapshot,
    RailStationReference,
)
from app.services.rail_maritime_collection import RailMaritimeCollectionService


def _settings(tmp_path: Path, **values: object) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'rail-maritime.sqlite3'}",
        seed_sample_data=False,
        enable_scheduler=False,
        **values,
    )


def _station() -> FileStationInfo:
    return FileStationInfo(
        rail_operator_name="테스트운영사",
        operating_line_name="테스트선",
        station_type="도시철도",
        station_number="101",
        station_name="테스트역",
        english_name="Test Station",
        romanized_name=None,
        japanese_name=None,
        simplified_chinese_name=None,
        traditional_chinese_name=None,
        sub_station_name=None,
        longitude=127.1,
        latitude=37.5,
        lot_address="서울특별시 테스트구",
        road_address="서울특별시 테스트로 1",
        station_phone_number="02-0000-0000",
        data_reference_date="2026-09-01",
        raw={"역명(한글)": "테스트역"},
    )


def test_rail_reference_collection_upserts_public_file_rows(tmp_path: Path) -> None:
    settings = _settings(tmp_path, rail_reference_collection_enabled=True)
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def fetch() -> tuple[FileStationInfo, ...]:
        return (_station(),)

    async def run() -> None:
        await init_database(engine)
        service = RailMaritimeCollectionService(settings, rail_fetcher=fetch)
        async with session_factory() as session:
            first = await service.collect_rail_reference(session)
        async with session_factory() as session:
            second = await service.collect_rail_reference(session)
        async with session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(RailStationReference)) == 1
            assert await session.scalar(select(func.count()).select_from(CollectionRun)) == 1
        assert first["status"] == "success"
        assert first["station_count"] == 1
        assert second == {"status": "skipped", "reason": "KRIC rail reference is not due for 48 hours"}
        await engine.dispose()

    asyncio.run(run())


class _MaritimeClient:
    async def __aenter__(self) -> "_MaritimeClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def iter_ports(self, *, page_size: int, max_pages: int):
        assert (page_size, max_pages) == (100, 20)
        yield DomesticFerryPort(port_id="P001", port_name="테스트항", raw={"nodeId": "P001"})

    async def iter_ferry_terminals(self, *, page_size: int, max_pages: int):
        assert (page_size, max_pages) == (100, 20)
        yield FerryTerminal(
            terminal_id="T001",
            terminal_name="테스트터미널",
            address="부산광역시 테스트구",
            telephone="051-000-0000",
            raw={"terminalId": "T001"},
        )

    async def iter_ferry_ship_types(self, *, page_size: int, max_pages: int):
        assert (page_size, max_pages) == (100, 20)
        yield FerryShipType(ship_type_id="S001", ship_type_name="카페리", raw={"shipKndId": "S001"})


def test_maritime_reference_collection_stores_only_stable_reference_data(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        maritime_reference_collection_enabled=True,
        port_guideline_collection_enabled=False,
        data_go_kr_service_key="test-key",
    )
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    def client_factory(_key: str, *, timeout: float) -> _MaritimeClient:
        assert timeout == settings.api_timeout_seconds
        return _MaritimeClient()

    async def run() -> None:
        await init_database(engine)
        service = RailMaritimeCollectionService(settings, maritime_client_factory=client_factory)
        async with session_factory() as session:
            summary = await service.collect_maritime_reference(session)
        async with session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(FerryPort)) == 1
            assert await session.scalar(select(func.count()).select_from(FerryTerminalReference)) == 1
            assert await session.scalar(select(func.count()).select_from(FerryShipTypeReference)) == 1
        assert summary == {
            "status": "success",
            "run_id": 1,
            "port_count": 1,
            "terminal_count": 1,
            "ship_type_count": 1,
            "port_location_count": 0,
            "port_location_deferred_count": 0,
            "port_guideline_object_stored": 0,
            "port_location_failed_calls": 0,
        }
        await engine.dispose()

    asyncio.run(run())


def test_maritime_quota_cooldown_keeps_later_runs_partial_without_retrying(tmp_path: Path) -> None:
    settings = _settings(tmp_path, maritime_reference_collection_enabled=True,
                         port_guideline_collection_enabled=False, data_go_kr_service_key="test-key")
    calls = 0

    class Client(_MaritimeClient):
        async def iter_ports(self, **_kwargs):
            yield DomesticFerryPort("SEA10100", "인천", {})
            yield DomesticFerryPort("SEA42010", "부산", {})

        async def get_port_calls(self, **_kwargs):
            nonlocal calls
            calls += 1
            raise KricRateLimitError("quota")

    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = RailMaritimeCollectionService(settings, maritime_client_factory=lambda *_args, **_kwargs: Client())
        try:
            async with factory() as session:
                first = await service.collect_maritime_reference(session)
                second = await service.collect_maritime_reference(session)
                assert first["status"] == second["status"] == "partial_success"
                assert first["port_location_failed_calls"] == 1
                assert second["port_location_failed_calls"] == 0
                assert first["port_location_deferred_count"] == second["port_location_deferred_count"] == 2
                assert calls == 1
                assert await session.scalar(select(func.count()).select_from(FerryPort)) == 2
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_maritime_reference_does_not_use_guideline_waypoint_as_port(tmp_path: Path) -> None:
    settings = _settings(tmp_path, maritime_reference_collection_enabled=True, data_go_kr_service_key="test-key")
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def locations() -> tuple[PortGuidelineLocation, ...]:
        return (
            PortGuidelineLocation("t", "r", "2", "테스트항", 35.2, 129.1, None, None, {}),
            PortGuidelineLocation("t", "r", "1", "테스트항", 35.1, 129.0, None, None, {}),
        )

    async def run() -> None:
        await init_database(engine)
        service = RailMaritimeCollectionService(
            settings, maritime_client_factory=lambda _key, *, timeout: _MaritimeClient(), port_guideline_fetcher=locations,
        )
        async with session_factory() as session:
            summary = await service.collect_maritime_reference(session)
        async with session_factory() as session:
            port = await session.scalar(select(FerryPort))
        assert port is not None
        assert (port.latitude, port.longitude, port.location_source, port.location_point_count) == (None, None, None, 0)
        assert summary["port_location_count"] == 0
        await engine.dispose()

    asyncio.run(run())


def test_reference_collections_are_explicitly_disabled_by_default(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        service = RailMaritimeCollectionService(settings)
        async with session_factory() as session:
            assert (await service.collect_rail_reference(session))["status"] == "skipped"
            assert (await service.collect_maritime_reference(session))["status"] == "skipped"
            assert (await service.collect_ferry_timetables(session))["status"] == "skipped"
        await engine.dispose()

    asyncio.run(run())


def test_ferry_timetable_collection_stores_horizon_and_reuses_future_snapshots(tmp_path: Path) -> None:
    class TimetableClient:
        calls: list[tuple[str, object]] = []

        async def __aenter__(self) -> "TimetableClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get_domestic_ship_operations(self, *, departure_port_id: str, departure_date: object):
            type(self).calls.append((departure_port_id, departure_date))
            return (
                SimpleNamespace(
                    vessel_name="테스트호",
                    departure_port_name="테스트항",
                    arrival_port_name="도착항",
                    departure_planned_time="09:00",
                    arrival_planned_time="10:00",
                    fare="10000",
                ),
            )

    settings = _settings(
        tmp_path,
        ferry_timetable_collection_enabled=True,
        ferry_timetable_storage_days=2,
        ferry_timetable_collection_interval_seconds=1,
        data_go_kr_service_key="test-key",
    )
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        today = to_seoul(now).date()
        async with session_factory() as session:
            session.add(FerryPort(source="data_go_kr_maritime", port_id="P001", port_name="테스트항", latitude=None, longitude=None, location_source=None, location_point_count=0, first_seen_at=now, last_seen_at=now, raw_item_json=None))
            session.add(FerryTimetableSnapshot(source="data_go_kr_maritime", departure_port_id="P001", service_date=today - timedelta(days=1), collected_at=now, items_json=[]))
            session.add(FerryTimetableSnapshot(source="data_go_kr_maritime", departure_port_id="P001", service_date=today + timedelta(days=10), collected_at=now, items_json=[]))
            await session.commit()
        service = RailMaritimeCollectionService(settings, maritime_client_factory=lambda _key, *, timeout: TimetableClient())
        async with session_factory() as session:
            first = await service.collect_ferry_timetables(session)
        async with session_factory() as session:
            second = await service.collect_ferry_timetables(session)
        async with session_factory() as session:
            snapshots = (await session.execute(select(FerryTimetableSnapshot).order_by(FerryTimetableSnapshot.service_date))).scalars().all()
        assert first["provider_calls"] == 2
        assert first["service_date_count"] == 2
        assert first["operation_count"] == 2
        assert second["provider_calls"] == 0
        assert second["reused_snapshot_count"] == 2
        assert len(TimetableClient.calls) == 2
        assert len(snapshots) == 2
        assert snapshots[0].items_json[0]["vessel_name"] == "테스트호"
        await engine.dispose()

    asyncio.run(run())


def test_ferry_timetable_collection_keeps_completed_snapshots_when_later_call_fails(tmp_path: Path) -> None:
    class PartiallyFailingClient:
        calls = 0

        async def __aenter__(self) -> "PartiallyFailingClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get_domestic_ship_operations(self, **_kwargs):
            type(self).calls += 1
            if type(self).calls == 2:
                raise RuntimeError("provider timeout")
            return ()

    settings = _settings(
        tmp_path,
        ferry_timetable_collection_enabled=True,
        ferry_timetable_storage_days=2,
        ferry_timetable_collection_interval_seconds=1,
        data_go_kr_service_key="test-key",
    )
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with session_factory() as session:
            session.add(FerryPort(source="data_go_kr_maritime", port_id="P001", port_name="테스트항", latitude=None, longitude=None, location_source=None, location_point_count=0, first_seen_at=now, last_seen_at=now, raw_item_json=None))
            await session.commit()
        service = RailMaritimeCollectionService(settings, maritime_client_factory=lambda _key, *, timeout: PartiallyFailingClient())
        async with session_factory() as session:
            with pytest.raises(RuntimeError, match="provider timeout"):
                await service.collect_ferry_timetables(session)
        async with session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(FerryTimetableSnapshot)) == 1
            run = await session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()))
        assert run is not None
        assert run.status == "failed"
        await engine.dispose()

    asyncio.run(run())


def test_ferry_timetable_collection_resumes_after_provider_call_budget(tmp_path: Path) -> None:
    class BudgetedClient:
        calls = 0

        async def __aenter__(self) -> "BudgetedClient":
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get_domestic_ship_operations(self, **_kwargs):
            type(self).calls += 1
            return ()

    settings = _settings(
        tmp_path,
        ferry_timetable_collection_enabled=True,
        ferry_timetable_storage_days=2,
        ferry_timetable_collection_max_provider_calls=1,
        data_go_kr_service_key="test-key",
    )
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with session_factory() as session:
            session.add(FerryPort(source="data_go_kr_maritime", port_id="P001", port_name="테스트항", latitude=None, longitude=None, location_source=None, location_point_count=0, first_seen_at=now, last_seen_at=now, raw_item_json=None))
            await session.commit()
        service = RailMaritimeCollectionService(settings, maritime_client_factory=lambda _key, *, timeout: BudgetedClient())
        async with session_factory() as session:
            first = await service.collect_ferry_timetables(session)
        async with session_factory() as session:
            second = await service.collect_ferry_timetables(session)
        async with session_factory() as session:
            count = await session.scalar(select(func.count()).select_from(FerryTimetableSnapshot))
        assert first["provider_calls"] == 1
        assert first["deferred_snapshot_count"] == 1
        assert second["provider_calls"] == 1
        assert second["deferred_snapshot_count"] == 0
        assert BudgetedClient.calls == 2
        assert count == 2
        await engine.dispose()

    asyncio.run(run())


def test_ferry_budget_fills_every_port_today_before_future_days(tmp_path: Path) -> None:
    calls = []
    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def get_domestic_ship_operations(self, **kwargs):
            calls.append((kwargs["departure_port_id"], kwargs["departure_date"]))
            return ()
    settings = _settings(tmp_path, ferry_timetable_collection_enabled=True,
        ferry_timetable_storage_days=2, ferry_timetable_collection_max_provider_calls=1,
        data_go_kr_service_key="test-key")
    engine, factory = create_engine_and_session_factory(settings.database_url)
    async def run():
        await init_database(engine)
        now = now_utc()
        today = to_seoul(now).date()
        async with factory() as session:
            for port_id in ["P001", "P999"]:
                session.add(FerryPort(source="data_go_kr_maritime", port_id=port_id,
                    port_name=port_id, first_seen_at=now, last_seen_at=now))
            await session.commit()
        service = RailMaritimeCollectionService(settings, maritime_client_factory=lambda *_args, **_kwargs: FakeClient())
        for remaining in [3, 2, 1, 0]:
            async with factory() as session:
                result = await service.collect_ferry_timetables(session)
                assert result["provider_calls"] == 1
                assert result["deferred_snapshot_count"] == remaining
        assert calls == [("P001", today), ("P999", today),
            ("P001", today + timedelta(days=1)), ("P999", today + timedelta(days=1))]
        await engine.dispose()
    asyncio.run(run())


def test_ferry_timetable_default_budget_includes_interval_and_timeout() -> None:
    settings = Settings()

    assert settings.ferry_timetable_collection_max_provider_calls == 280
    assert settings.ferry_timetable_collection_interval_seconds == 2
    assert settings.ferry_timetable_min_interval_seconds == 30
    Settings(ferry_timetable_collection_max_provider_calls=280)
    for call_budget in (281, 400, 741, 1000):
        with pytest.raises(ValidationError, match="less than or equal to 280"):
            Settings(ferry_timetable_collection_max_provider_calls=call_budget)
    with pytest.raises(ValidationError, match="3.5-hour ferry collection runtime budget"):
        Settings(ferry_timetable_collection_max_provider_calls=280, ferry_timetable_collection_interval_seconds=31)
    # UI 보호 간격이 커도 배치의 실행시간 예산과 섞이지 않는다.
    Settings(ferry_timetable_min_interval_seconds=3600)
    with pytest.raises(ValidationError):
        Settings(ferry_timetable_collection_interval_seconds=0)


@pytest.mark.parametrize('failure_kind', ['transient', 'continuous', 'quota', 'auth'])
@pytest.mark.parametrize('batch_interval', [2, 7])
def test_ferry_network_failures_are_bounded_and_do_not_become_empty_success(tmp_path, monkeypatch, failure_kind, batch_interval):
    from unittest.mock import AsyncMock
    from kric import KricAuthError, KricNetworkError, KricRateLimitError
    delays = AsyncMock()
    monkeypatch.setattr('app.services.rail_maritime_collection.asyncio.sleep', delays)
    calls = []
    class Client(_MaritimeClient):
        async def get_domestic_ship_operations(self, **kwargs):
            calls.append(kwargs['departure_date'])
            if failure_kind == 'continuous' or (failure_kind == 'transient' and len(calls) == 1):
                raise KricNetworkError('temporary network failure')
            if failure_kind == 'quota':
                raise KricRateLimitError('quota')
            if failure_kind == 'auth':
                raise KricAuthError('auth')
            return ()
    settings = _settings(tmp_path, ferry_timetable_collection_enabled=True,
        ferry_timetable_storage_days=5, ferry_timetable_collection_max_provider_calls=3,
        ferry_timetable_collection_interval_seconds=batch_interval,
        ferry_timetable_min_interval_seconds=30,
        data_go_kr_service_key='test-key')
    engine, factory = create_engine_and_session_factory(settings.database_url)
    async def exercise():
        await init_database(engine)
        now = now_utc()
        async with factory() as session:
            session.add(FerryPort(source='data_go_kr_maritime',port_id='P1',port_name='항구',
                first_seen_at=now,last_seen_at=now,location_point_count=0))
            await session.commit()
        service=RailMaritimeCollectionService(settings,maritime_client_factory=lambda *a,**kw:Client())
        async with factory() as session:
            if failure_kind == 'transient':
                result=await service.collect_ferry_timetables(session)
                assert result['status']=='partial_success'
                assert result['provider_calls']==3
                assert result['failed_provider_calls']==1
                assert result['deferred_snapshot_count']==3
            else:
                error={'continuous':KricNetworkError,'quota':KricRateLimitError,'auth':KricAuthError}[failure_kind]
                with pytest.raises(error):
                    await service.collect_ferry_timetables(session)
        async with factory() as session:
            snapshots=(await session.scalars(select(FerryTimetableSnapshot))).all()
            assert len(snapshots)==(2 if failure_kind=='transient' else 0)
            assert all(s.service_date!=to_seoul(now).date() for s in snapshots)
            run=await session.scalar(select(CollectionRun))
            assert run.status==('partial_success' if failure_kind=='transient' else 'failed')
        assert len(calls)==(3 if failure_kind in {'transient','continuous'} else 1)
        assert len(set(calls))==len(calls)
        assert delays.await_count==max(0,len(calls)-1)
        assert all(batch_interval - 1 < call.args[0] <= batch_interval for call in delays.await_args_list)
        await engine.dispose()
    asyncio.run(exercise())


def test_enabled_rail_reference_collection_requires_rustfs_configuration(tmp_path: Path) -> None:
    settings = _settings(tmp_path, rail_reference_collection_enabled=True)
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        service = RailMaritimeCollectionService(settings)
        async with session_factory() as session:
            with pytest.raises(RuntimeError, match="RustFS configuration"):
                await service.collect_rail_reference(session)
        await engine.dispose()

    asyncio.run(run())


def test_cancelled_rail_collection_marks_its_durable_run_failed(tmp_path: Path) -> None:
    settings = _settings(tmp_path, rail_reference_collection_enabled=True)
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def cancelled_fetch() -> tuple[FileStationInfo, ...]:
        raise asyncio.CancelledError()

    async def run() -> None:
        await init_database(engine)
        service = RailMaritimeCollectionService(settings, rail_fetcher=cancelled_fetch)
        async with session_factory() as session:
            with pytest.raises(asyncio.CancelledError):
                await service.collect_rail_reference(session)
        async with session_factory() as session:
            persisted = await session.scalar(select(CollectionRun))
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.finished_at is not None
        assert persisted.error_message == "CancelledError: "
        await engine.dispose()

    asyncio.run(run())
