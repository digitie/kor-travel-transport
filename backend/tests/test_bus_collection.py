from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from datagokr import TagoBusTerminal
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory, init_database
from app.models import BusTerminalReference, CollectionRun
from app.services.bus_collection import BusReferenceCollectionService


class _BusProvider:
    def __init__(self, service_type: str) -> None:
        self.service_type = service_type

    async def iter_terminals(self, *, num_of_rows: int, max_pages: int):
        assert (num_of_rows, max_pages) == (100, 100)
        yield TagoBusTerminal(
            terminalId=f"{self.service_type}-terminal",
            terminalNm=f"{self.service_type}-터미널",
            cityName="테스트시",
        )

    async def city_list(self):
        return SimpleNamespace(items=(SimpleNamespace(),))

    async def class_list(self):
        return SimpleNamespace(items=(SimpleNamespace(),))


class _BusClient:
    def __init__(self, **_kwargs: object) -> None:
        self.express_bus = _BusProvider("express")
        self.intercity_bus = _BusProvider("intercity")

    async def __aenter__(self) -> "_BusClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_bus_reference_collection_stores_terminal_reference_only(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'bus-reference.sqlite3'}",
        seed_sample_data=False,
        enable_scheduler=False,
        bus_reference_collection_enabled=True,
        data_go_kr_service_key="test-key",
    )
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        service = BusReferenceCollectionService(settings, client_factory=_BusClient)
        async with session_factory() as session:
            first = await service.collect(session)
        async with session_factory() as session:
            second = await service.collect(session)
        async with session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(BusTerminalReference)) == 2
            assert await session.scalar(select(func.count()).select_from(CollectionRun)) == 1
        assert first["status"] == "success"
        assert first["express_terminal_count"] == 1
        assert first["intercity_terminal_count"] == 1
        assert second == {"status": "skipped", "reason": "TAGO bus reference is not due for 72 hours"}
        await engine.dispose()

    asyncio.run(run())


class _FailingBusProvider:
    async def iter_terminals(self, **_kwargs: object):
        raise RuntimeError("TAGO unavailable")
        yield None


class _FailingBusClient:
    def __init__(self, **_kwargs: object) -> None:
        self.express_bus = _FailingBusProvider()
        self.intercity_bus = _FailingBusProvider()

    async def __aenter__(self) -> "_FailingBusClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def test_failed_bus_reference_collection_preserves_failure_reason(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'bus-reference.sqlite3'}",
        seed_sample_data=False,
        enable_scheduler=False,
        bus_reference_collection_enabled=True,
        data_go_kr_service_key="test-key",
    )
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        service = BusReferenceCollectionService(settings, client_factory=_FailingBusClient)
        async with session_factory() as session:
            with pytest.raises(RuntimeError, match="TAGO unavailable"):
                await service.collect(session)
        async with session_factory() as session:
            failed = await session.scalar(select(CollectionRun))
        assert failed is not None
        assert failed.status == "failed"
        assert failed.error_message == "RuntimeError"
        await engine.dispose()

    asyncio.run(run())
