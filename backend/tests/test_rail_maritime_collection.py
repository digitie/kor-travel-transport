from __future__ import annotations

import asyncio
from pathlib import Path

from kric import DomesticFerryPort, FerryShipType, FerryTerminal, FileStationInfo, PortGuidelineLocation
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory, init_database
from app.models import (
    BusTerminalReference,
    CollectionRun,
    FerryPort,
    FerryShipTypeReference,
    FerryTerminalReference,
    RailStationReference,
)
from app.services.bus_collection import BusReferenceCollectionService
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
        await engine.dispose()

    asyncio.run(run())


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


class _BusClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.express_bus = self
        self.intercity_bus = self
        self.fail = fail

    async def __aenter__(self) -> "_BusClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def iter_terminals(self, *, num_of_rows: int, max_pages: int):
        assert (num_of_rows, max_pages) == (100, 100)
        if self.fail:
            raise RuntimeError("TAGO unavailable")
        yield type("Terminal", (), {"terminal_id": "T001", "terminal_name": "테스트터미널", "city_name": "서울", "raw": {"terminalId": "T001"}})()

    async def city_list(self):
        return type("Page", (), {"items": (object(),)})()

    async def class_list(self):
        return type("Page", (), {"items": (object(),)})()


def test_bus_reference_collection_stores_terminal_reference_only(tmp_path: Path) -> None:
    settings = _settings(tmp_path, bus_reference_collection_enabled=True, data_go_kr_service_key="test-key")
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        service = BusReferenceCollectionService(settings, client_factory=lambda **_kwargs: _BusClient())
        async with session_factory() as session:
            summary = await service.collect(session)
        async with session_factory() as session:
            terminal = await session.scalar(select(BusTerminalReference))
            assert await session.scalar(select(func.count()).select_from(CollectionRun)) == 1
        assert summary == {
            "status": "success", "run_id": 1,
            "express_terminal_count": 1, "express_city_count": 1, "express_class_count": 1,
            "intercity_terminal_count": 1, "intercity_city_count": 1, "intercity_class_count": 1,
        }
        assert terminal is not None
        assert terminal.raw_item_json == {"terminalId": "T001"}
        await engine.dispose()

    asyncio.run(run())


def test_failed_bus_reference_collection_preserves_failure_reason(tmp_path: Path) -> None:
    settings = _settings(tmp_path, bus_reference_collection_enabled=True, data_go_kr_service_key="test-key")
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        service = BusReferenceCollectionService(settings, client_factory=lambda **_kwargs: _BusClient(fail=True))
        async with session_factory() as session:
            with pytest.raises(RuntimeError, match="TAGO unavailable"):
                await service.collect(session)
        async with session_factory() as session:
            failed = await session.scalar(select(CollectionRun))
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error_message == "RuntimeError: TAGO unavailable"
        await engine.dispose()

    asyncio.run(run())
