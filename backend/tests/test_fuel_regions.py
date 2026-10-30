import asyncio
from datetime import datetime, timezone

import pytest

from test_fuel_statistics import seed


def test_regional_prices_use_entire_region_not_bbox_or_marker_limit(client):
    async def setup():
        async with client.app.state.session_factory() as session:
            await seed(session, datetime.now(timezone.utc))
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
