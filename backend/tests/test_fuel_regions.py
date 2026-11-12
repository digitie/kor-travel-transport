import asyncio
from datetime import datetime, timezone

import pytest

from test_fuel_statistics import seed
from app.services.fuel_statistics import OPINET, publish_fuel_statistics


@pytest.mark.parametrize("zoom", [7, 9])
@pytest.mark.parametrize("query", ["주유소0", "검증브랜드"])
def test_low_zoom_search_preserves_matching_station_clusters(client, zoom, query):
    """지역명과 다른 상호·브랜드 검색도 검색 지점과 확대 경로를 남긴다."""
    from sqlalchemy import update
    from app.models import FuelStation

    async def setup():
        async with client.app.state.session_factory() as session:
            stamp = datetime.now(timezone.utc)
            await seed(session, stamp)
            await session.execute(update(FuelStation).where(FuelStation.id == 2).values(brand_name="검증브랜드"))
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
    asyncio.run(setup())
    result = client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "zoom": zoom, "query": query,
        "min_longitude": 126.9, "max_longitude": 127.1,
        "min_latitude": 37, "max_latitude": 38,
    })
    assert result.status_code == 200
    payload = result.json()
    assert payload["total"] == 1
    assert payload["kind_totals"] == {"fuel_station": 1}
    assert payload["fuel_regions"] == []
    assert sum(item["count"] for item in payload["clusters"]) == 1
    assert payload["clusters"][0]["kind_counts"] == {"fuel_station": 1}


def test_regional_prices_use_entire_region_not_bbox_or_marker_limit(client):
    async def setup():
        async with client.app.state.session_factory() as session:
            stamp = datetime.now(timezone.utc)
            await seed(session, stamp)
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
    asyncio.run(setup())
    params = {"kind": "fuel_station", "limit": 1, "zoom": 7,
              "min_longitude": 127, "max_longitude": 127.8,
              "min_latitude": 37, "max_latitude": 38}
    result = client.get("/v1/transport/features/places", params=params)
    assert result.status_code == 200
    region = result.json()["fuel_regions"][0]
    assert region["scope"] == "sido"
    assert region["station_count"] == 3  # 세 번째 주유소는 bbox 밖이어도 같은 지역이다.
    assert region["average_price"] == pytest.approx(5000 / 3)
    assert result.json()["clusters"] == []
    params["zoom"] = 8
    assert client.get("/v1/transport/features/places", params=params).json()["fuel_regions"][0]["scope"] == "sigungu"
    params["zoom"] = 12
    assert client.get("/v1/transport/features/places", params=params).json()["fuel_regions"] == []
    params.update(zoom=7, source="missing")
    assert client.get("/v1/transport/features/places", params=params).json()["fuel_regions"] == []


def test_regions_are_frozen_until_successful_publication_and_history_is_permanent(client):
    from datetime import timedelta
    from sqlalchemy import func, select, update
    from app.models import FuelLatestPrice, FuelRegionSummary
    from app.services.fuel_regions import regional_fuel_prices

    async def exercise():
        async with client.app.state.session_factory() as session:
            stamp = datetime.now(timezone.utc)
            await seed(session, stamp)
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
            args = dict(zoom=7, bounds=(124,32,132,39), sources=[], products=[], query=None)
            before = await regional_fuel_prices(session, **args)
            latest = await session.get(FuelLatestPrice, (2, "B027"))
            latest.price = 2200
            await session.commit()
            assert await regional_fuel_prices(session, **args) == before
            await session.execute(update(FuelLatestPrice).values(collected_at=stamp + timedelta(days=40)))
            await publish_fuel_statistics(session, OPINET, stamp + timedelta(days=40))
            await session.commit()
            after = await regional_fuel_prices(session, **args)
            assert float(after[0]["average_price"]) == 1866.6667
            assert await session.scalar(select(func.count()).select_from(FuelRegionSummary)) == 4
    asyncio.run(exercise())
