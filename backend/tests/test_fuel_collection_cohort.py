"""이번 성공 수집의 통계와 이전 원본·세대 보존, 구 모집단의 원자 정정."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import func, select

from app.models import (
    FuelLatestPrice, FuelPriceSnapshot, FuelRegionSummary, FuelStatisticsDaily,
    FuelStatisticsPoint, FuelStatisticsState, TransportCollectionState,
)
from app.services.fuel_statistics import OPINET, publish_fuel_statistics, try_publish_fuel_statistics
from test_fuel_statistics import seed


async def two_generations(session):
    stamp = datetime.now(timezone.utc)
    old = stamp - timedelta(days=2)
    await seed(session, old)
    await publish_fuel_statistics(session, OPINET, old)
    await session.commit()
    for station_id in (2, 3):
        row = await session.get(FuelLatestPrice, (station_id, "B027"))
        row.collected_at = stamp
    session.add(TransportCollectionState(source=OPINET, last_success_at=stamp, updated_at=stamp))
    await session.commit()
    await publish_fuel_statistics(session, OPINET, stamp)
    await session.commit()
    return old, stamp


def test_successful_collection_only_excludes_old_price_without_deleting_history(client):
    async def exercise():
        async with client.app.state.session_factory() as session:
            old, stamp = await two_generations(session)
            current = (await session.scalars(select(FuelRegionSummary).where(FuelRegionSummary.generated_at == stamp))).all()
            assert len(current) == 2
            assert all(row.station_count == 2 and float(row.average_price) == 1700 for row in current)
            history = (await session.scalars(select(FuelRegionSummary).where(FuelRegionSummary.generated_at == old))).all()
            assert len(history) == 2 and all(row.station_count == 3 for row in history)
            assert await session.scalar(select(func.count()).select_from(FuelPriceSnapshot)) == 3
            assert await session.scalar(select(func.count()).select_from(FuelLatestPrice)) == 3
            assert float((await session.get(FuelLatestPrice, (10, "B027"))).price) == 1600
    asyncio.run(exercise())
    total = client.get("/v1/transport/fuel/statistics").json()["items"][0]
    assert total["station_count"] == 2 and total["average_price"] == 1700
    result = client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "zoom": 7, "include_fuel_statistics": True,
        "min_longitude": 124, "max_longitude": 132, "min_latitude": 32, "max_latitude": 39,
    })
    assert result.status_code == 200
    assert result.json()["fuel_regions"][0]["station_count"] == 2
    assert result.json()["fuel_statistics"][0]["station_count"] == 2


def test_repairs_legacy_current_cohort_once_and_keeps_prior_generations(client):
    async def exercise():
        async with client.app.state.session_factory() as session:
            old, stamp = await two_generations(session)
            # 기존 버전이 현재 공개 세대에 이전 관측값까지 포함한 상태를 재현한다.
            if await session.get(FuelStatisticsPoint, (OPINET, "10", "B027", stamp)) is None:
                session.add(FuelStatisticsPoint(source=OPINET, station_key="10", product_code="B027",
                    generated_at=stamp, name="주유소2", address="서울 도로2", longitude=128, latitude=37.5, price=1600))
            for row in (await session.scalars(select(FuelRegionSummary).where(FuelRegionSummary.generated_at == stamp))).all():
                row.station_count = 3
                row.average_price = 5000 / 3
                row.metrics_json = {**row.metrics_json, "station_count": 3, "average_price": 1666.67}
            for row in (await session.scalars(select(FuelStatisticsDaily).where(FuelStatisticsDaily.generated_at == stamp))).all():
                row.metrics_json = {**row.metrics_json, "station_count": 3, "average_price": 1666.67}
            await session.commit()
            before = [(row.region_key, row.station_count, float(row.average_price)) for row in
                (await session.scalars(select(FuelRegionSummary).where(FuelRegionSummary.generated_at == old))).all()]
            with patch("app.services.fuel_statistics._Accumulator.metrics", side_effect=RuntimeError("fixture failure")):
                assert not await try_publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
            assert await session.scalar(select(func.count()).select_from(FuelStatisticsPoint).where(
                FuelStatisticsPoint.generated_at == stamp)) == 3
            assert all(row.station_count == 3 for row in (await session.scalars(select(FuelRegionSummary).where(
                FuelRegionSummary.generated_at == stamp))).all())
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
            assert await session.scalar(select(func.count()).select_from(FuelStatisticsPoint).where(
                FuelStatisticsPoint.generated_at == stamp)) == 2
            current = (await session.scalars(select(FuelRegionSummary).where(FuelRegionSummary.generated_at == stamp))).all()
            assert all(row.station_count == 2 and float(row.average_price) == 1700 for row in current)
            assert [(row.region_key, row.station_count, float(row.average_price)) for row in
                (await session.scalars(select(FuelRegionSummary).where(FuelRegionSummary.generated_at == old))).all()] == before
            pointer = await session.get(FuelStatisticsState, OPINET)
            assert pointer.generated_at.replace(tzinfo=timezone.utc) == stamp
            assert await session.scalar(select(func.count()).select_from(FuelPriceSnapshot)) == 3
            with patch.object(session, "execute", wraps=session.execute) as execute:
                await publish_fuel_statistics(session, OPINET, stamp)
                await session.commit()
            assert not any(getattr(call.args[0], flag, False) for call in execute.call_args_list
                           for flag in ("is_insert", "is_delete", "is_update"))
    asyncio.run(exercise())
