"""연료 전용 실제 축척 경계와 기존 지도 reader의 범위·개수·읽기 계약."""

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from app.services.fuel_statistics import OPINET, publish_fuel_statistics
from test_fuel_statistics import seed
from test_fuel_public_gateway_contract import KIND_QUERY_CASES


@pytest.fixture
def published_fuel(client):
    async def setup():
        async with client.app.state.session_factory() as session:
            stamp = datetime.now(timezone.utc)
            await seed(session, stamp)
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
    asyncio.run(setup())
    return client


def request_map(client, zoom, **extra):
    return client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "zoom": zoom, "limit": 20, "include_sources": "false",
        "include_fuel_statistics": "true",
        "min_longitude": 126, "max_longitude": 129,
        "min_latitude": 37, "max_latitude": 38, **extra,
    })


@pytest.mark.parametrize("zoom", [9, 10, 11, 12])
def test_fuel_detail_breakup_uses_actual_zoom_ten(published_fuel, zoom):
    response = request_map(published_fuel, zoom)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind_totals"] == {"fuel_station": 3}
    assert body["total"] == 3
    if zoom < 10:
        assert body["clustered"] is True and body["items"] == []
        assert body["fuel_regions"] and body["fuel_regions"][0]["scope"] == "sigungu"
    else:
        assert body["clustered"] is False and body["fuel_regions"] == []
        assert len(body["items"]) == 3 and not body["truncated"]
        assert all(item["kind"] == "fuel_station" and item["prices"] for item in body["items"])
        assert body["fuel_statistics"]


@pytest.mark.parametrize("zoom", [10, 11, 12])
def test_fuel_detail_limit_preserves_total_prices_and_viewport(published_fuel, zoom):
    full = request_map(published_fuel, 12).json()
    limited = request_map(published_fuel, zoom, limit=1).json()
    assert limited["total"] == full["total"] == 3 and limited["truncated"]
    assert limited["items"] == full["items"][:1]
    assert limited["fuel_statistics"] == full["fuel_statistics"]
    empty = request_map(published_fuel, zoom, min_longitude=130, max_longitude=131).json()
    assert empty["total"] == 0 and empty["items"] == [] and not empty["truncated"]


@pytest.mark.parametrize("kinds", ["rail_station", "fuel_station,rail_station"])
@pytest.mark.parametrize("zoom", [10, 11, 12])
def test_other_or_mixed_kinds_keep_original_twelve_boundary(published_fuel, kinds, zoom):
    params = {
        "kinds": kinds, "zoom": zoom, "include_sources": "false",
        "min_longitude": 126, "max_longitude": 129, "min_latitude": 37, "max_latitude": 38,
    }
    response = published_fuel.get("/v1/transport/features/places", params=params)
    assert response.status_code == 200, response.text
    assert response.json()["clustered"] is (zoom < 12)


def test_fuel_viewport_get_never_writes_or_collects(published_fuel, monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("공개 지도 읽기는 수집하지 않는다")
    monkeypatch.setattr(published_fuel.app.state.transport_collection_service, "collect", forbidden)
    writes = []
    engine = published_fuel.app.state.session_factory.kw["bind"].sync_engine
    def observe(_conn, _cursor, sql, *_args):
        if sql.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "TRUNCATE", "ALTER", "CREATE", "DROP"}:
            writes.append(sql.split(None, 1)[0])
    event.listen(engine, "before_cursor_execute", observe)
    try:
        for zoom in [9, 10, 11, 12]:
            assert request_map(published_fuel, zoom).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert writes == []


@pytest.mark.parametrize("query,expected", KIND_QUERY_CASES)
def test_public_alias_effective_query_uses_real_fastapi_parser(published_fuel, query, expected):
    # 실제 nginx와 같은 마지막 query 고정. kind/kinds는 정규식으로 삭제하지 않는다.
    params = ("min_longitude=126&max_longitude=129&min_latitude=37&max_latitude=38"
              "&zoom=10&include_sources=false&" + query + "&kind=fuel_station")
    response = published_fuel.get("/v1/transport/features/places?" + params)
    assert response.status_code == expected, response.text
    if expected == 200:
        body = response.json()
        assert body["kind"] == "fuel_station"
        assert body["kind_totals"] == {"fuel_station": 3}
        assert body["clustered"] is False
        assert all(row["kind"] == "fuel_station" for row in body["items"])
