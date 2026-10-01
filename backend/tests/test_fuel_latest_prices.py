"""최신 유가 물질화 뷰의 PostgreSQL 계약을 검증한다."""

import asyncio
import os
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.time_utils import now_utc
from app.models import FuelPriceSnapshot, FuelStation


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="전용 PostgreSQL DB에서만 실행")
def test_fuel_latest_view_refresh_and_null_price_filter(client) -> None:
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 물질화 뷰가 필요합니다")

    async def seed_and_refresh() -> int:
        async with client.app.state.session_factory() as session:
            observed_at = now_utc()
            station = FuelStation(
                source="opinet", identity_key="mv-test-station", name="물질화 뷰 주유소",
                query_level="sigungu", sido_value="11", sido_name="서울", sigungu_value="110",
                sigungu_name="종로", source_kinds=[], latitude=37.57, longitude=126.98,
                first_seen_at=observed_at, last_seen_at=observed_at,
            )
            session.add(station)
            await session.flush()
            session.add(FuelPriceSnapshot(
                fuel_station_id=station.id, source="opinet", product_code="B027", price=1700,
                observed_at=observed_at, collected_at=observed_at,
            ))
            await session.flush()
            await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY fuel_latest_prices"))
            await session.commit()
            return station.id

    station_id = asyncio.run(seed_and_refresh())
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
            await session.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY fuel_latest_prices"))
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
