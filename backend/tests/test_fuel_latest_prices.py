"""최신 유가 테이블(`fuel_latest_prices`)의 증분 upsert 계약을 검증한다."""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.core.time_utils import now_utc
from app.models import FuelLatestPrice, FuelPriceSnapshot, FuelStation
from app.services.transport_collection import upsert_latest_fuel_prices


def _station(identity_key: str) -> FuelStation:
    observed_at = now_utc()
    return FuelStation(
        source="opinet", identity_key=identity_key, name="최신 유가 주유소",
        query_level="sigungu", sido_value="11", sido_name="서울", sigungu_value="110",
        sigungu_name="종로", source_kinds=[], latitude=37.57, longitude=126.98,
        first_seen_at=observed_at, last_seen_at=observed_at,
    )


def test_latest_price_upsert_and_null_price_filter(client) -> None:
    async def seed() -> int:
        async with client.app.state.session_factory() as session:
            observed_at = now_utc()
            station = _station("latest-test-station")
            session.add(station)
            await session.flush()
            session.add(FuelPriceSnapshot(
                fuel_station_id=station.id, source="opinet", product_code="B027", price=1700,
                observed_at=observed_at, collected_at=observed_at,
            ))
            await session.flush()
            await upsert_latest_fuel_prices(session, collected_at=observed_at)
            await session.commit()
            return station.id

    station_id = asyncio.run(seed())
    first = client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "product_code": "B027", "limit": 10,
    })
    assert first.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == [station_id]
    assert first.json()["items"][0]["latest_price"] == 1700

    async def remove_latest_price() -> None:
        async with client.app.state.session_factory() as session:
            observed_at = now_utc() + timedelta(seconds=1)
            session.add(FuelPriceSnapshot(
                fuel_station_id=station_id, source="opinet", product_code="B027", price=None,
                observed_at=observed_at, collected_at=observed_at,
            ))
            await session.flush()
            await upsert_latest_fuel_prices(session, collected_at=observed_at)
            await session.commit()

    asyncio.run(remove_latest_price())
    filtered = client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "product_code": "B027", "limit": 10,
    })
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 0
    fuel = client.get("/v1/transport/fuel/stations", params={"days": 2, "limit": 10})
    assert fuel.status_code == 200
    assert fuel.json()["items"][0]["prices"][0]["price"] is None


def test_older_batch_never_overwrites_a_newer_latest_price(client) -> None:
    """늦게 커밋된 과거 배치나 낮은 ID가 최신 행을 되돌리지 않는다(MV 시절의 대조 대상)."""

    async def exercise() -> tuple[float, float, float]:
        async with client.app.state.session_factory() as session:
            station = _station("ordering-station")
            session.add(station)
            await session.flush()
            newer = now_utc()
            older = newer - timedelta(hours=8)
            session.add(FuelPriceSnapshot(id=9000, fuel_station_id=station.id, source="opinet",
                product_code="B027", price=1800, observed_at=newer, collected_at=newer))
            await session.flush()
            await upsert_latest_fuel_prices(session, collected_at=newer)
            # 낮은 ID의 과거 배치가 뒤늦게 반영된다.
            session.add(FuelPriceSnapshot(id=8000, fuel_station_id=station.id, source="opinet",
                product_code="B027", price=1500, observed_at=older, collected_at=older))
            await session.flush()
            await upsert_latest_fuel_prices(session, collected_at=older)
            after_old = await session.scalar(select(FuelLatestPrice.price))
            # 같은 행의 제자리 재수집(가격 정정)은 반영된다.
            row = await session.get(FuelPriceSnapshot, 9000)
            row.price = 1850
            await session.flush()
            await upsert_latest_fuel_prices(session, collected_at=newer)
            after_fix = await session.scalar(select(FuelLatestPrice.price))
            # 전체 재계산도 같은 결과다.
            await session.execute(FuelLatestPrice.__table__.delete())
            await upsert_latest_fuel_prices(session)
            rebuilt = await session.scalar(select(FuelLatestPrice.price))
            await session.commit()
            return float(after_old), float(after_fix), float(rebuilt)

    assert asyncio.run(exercise()) == (1800.0, 1850.0, 1850.0)
