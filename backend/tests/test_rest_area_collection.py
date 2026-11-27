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


def test_rest_area_fuel_prices_outside_storable_range_are_stored_as_missing(tmp_path: Path, caplog) -> None:
    """저장 경계 검사(PR #302): 정수가 아니거나 1억 이상인 휴게소 가격은 미제공(null)으로 둔다. 0·음수는 예전처럼 그대로다.

    예전에는 2^31 이상이면 수집 transaction이, 1억 이상이면 통계 공개 transaction이 실패했다."""
    from datetime import datetime, timezone

    from app.models import RestAreaFuelPrice
    from app.services.fuel_statistics import STATISTICS_PRICE_LIMIT

    settings = _settings(tmp_path)
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    stamp = datetime(2026, 11, 27, 3, tzinfo=timezone.utc)

    def item(code: str, gasoline, diesel, lpg):
        return SimpleNamespace(service_area_code=code, service_area_code2=None, service_area_name=code, route_code="0010",
            route_name="경부선", direction="상행", oil_company=None, has_lpg=lpg is not None, phone_number=None, address=None,
            gasoline_price=gasoline, diesel_price=diesel, lpg_price=lpg, raw={"code": code, "gasoline": gasoline})

    async def run() -> None:
        await init_database(engine)
        service = RestAreaCollectionService(settings)
        async with session_factory() as session:
            stored = await service._store_fuel_prices(session, (
                item("A", 1700, STATISTICS_PRICE_LIMIT - 1, None),
                item("B", STATISTICS_PRICE_LIMIT, 2**31, 0),
                item("C", -5, True, 1100),
            ), stamp)
            await session.commit()
            rows = {row.service_area_code: (row.gasoline_price, row.diesel_price, row.lpg_price, row.raw_item_json["gasoline"])
                    for row in await session.scalars(select(RestAreaFuelPrice))}
        assert stored == 3
        assert rows == {"A": (1700, STATISTICS_PRICE_LIMIT - 1, None, 1700),
                        "B": (None, None, 0, STATISTICS_PRICE_LIMIT),
                        "C": (-5, None, 1100, -5)}
        await engine.dispose()

    with caplog.at_level("WARNING", logger="app.services.rest_area_collection"):
        asyncio.run(run())
    messages = [record.getMessage() for record in caplog.records]
    assert sum("rest_area_fuel_price_out_of_range" in message for message in messages) == 1
    assert any("rest_area_fuel_prices_out_of_range count=3" in message for message in messages)
