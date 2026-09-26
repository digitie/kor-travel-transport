from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from kric import DomesticFerryPort, FerryShipType, FerryTerminal, FileStationInfo, PortGuidelineLocation
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
            "port_guideline_object_stored": 0,
        }
        await engine.dispose()

    asyncio.run(run())


def test_maritime_reference_links_port_to_keyless_guideline_location(tmp_path: Path) -> None:
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
        assert (port.latitude, port.longitude, port.location_source, port.location_point_count) == (35.1, 129.0, "data_go_kr_port_guideline", 2)
        assert summary["port_location_count"] == 1
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
        ferry_timetable_min_interval_seconds=1,
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
        ferry_timetable_min_interval_seconds=1,
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


def test_ferry_timetable_default_budget_includes_interval_and_timeout() -> None:
    settings = Settings()

    assert settings.ferry_timetable_collection_max_provider_calls == 280
    with pytest.raises(ValidationError, match="3.5-hour ferry collection runtime budget"):
        Settings(ferry_timetable_collection_max_provider_calls=281)


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
