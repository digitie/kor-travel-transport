from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from krex import RestArea
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory, init_database
from app.models import CollectionRun, RestAreaReference
from app.services.rest_area_collection import RestAreaCollectionService


def _settings(tmp_path: Path, **values: object) -> Settings:
    defaults: dict[str, object] = {
        "database_url": f"sqlite+aiosqlite:///{tmp_path / 'rest-area.sqlite3'}",
        "seed_sample_data": False,
        "enable_scheduler": False,
        "rest_area_collection_enabled": True,
        "data_go_kr_service_key": "test-key",
    }
    return Settings(
        **(defaults | values),
    )


def _rest_area() -> RestArea:
    return RestArea(
        name="테스트휴게소",
        route_name="테스트고속도로",
        direction="서울방향",
        lat=37.5,
        lon=127.1,
        has_gas_station=True,
        has_lpg_station=False,
        has_ev_charger=True,
        phone_number="02-0000-0000",
        reference_date=date(2026, 9, 1),
        raw={"restAreaNm": "테스트휴게소"},
    )


def test_rest_area_collection_upserts_saved_map_reference_without_duplicate_places(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def fetch(**_kwargs):
        return SimpleNamespace(items=(_rest_area(),), total_count=1)

    async def close():
        pass

    def client_factory(**_kwargs):
        return SimpleNamespace(restarea=SimpleNamespace(list_all=fetch), aclose=close)

    async def run() -> None:
        await init_database(engine)
        service = RestAreaCollectionService(settings, client_factory=client_factory)
        async with session_factory() as session:
            first = await service.collect_references(session)
        async with session_factory() as session:
            second = await service.collect_references(session)
        async with session_factory() as session:
            row = await session.scalar(select(RestAreaReference))
            assert row is not None
            assert (row.name, row.route_name, row.direction, row.latitude, row.longitude) == (
                "테스트휴게소", "테스트고속도로", "서울방향", 37.5, 127.1
            )
            assert await session.scalar(select(func.count()).select_from(CollectionRun)) == 2
        assert first == {"status": "success", "run_id": 1, "received": 1, "stored": 1}
        assert second == {"status": "success", "run_id": 2, "received": 1, "stored": 1}
        await engine.dispose()

    asyncio.run(run())


def test_rest_area_collection_is_disabled_without_explicit_setting(tmp_path: Path) -> None:
    settings = _settings(tmp_path, rest_area_collection_enabled=False)
    engine, session_factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        async with session_factory() as session:
            assert (await RestAreaCollectionService(settings).collect_references(session))["status"] == "skipped"
        await engine.dispose()

    asyncio.run(run())
