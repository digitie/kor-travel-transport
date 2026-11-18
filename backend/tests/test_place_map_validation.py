"""전체 장소 바이트 재사용의 정밀도·신선도·기존 DTO 동등성."""
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app import main
from app.core.time_utils import now_utc
from app.models import (
    FuelLatestPrice,
    FuelPriceSnapshot,
    FuelStation,
    RestAreaReference,
)
from app.schemas import TransportPlaceMapResponse
from app.services import fuel_map_validation as validation
from app.services.transport_collection import upsert_latest_fuel_prices
from pydantic_core import to_json
from sqlalchemy import update
from test_read_performance import seed_places


async def _seed_places_and_prices(session):
    await seed_places(session)
    timestamp = now_utc()
    for i in range(3):
        station = FuelStation(
            source="opinet", identity_key=f"fuel-{i}", name=f"주유소-{i}",
            longitude=127.12345678901234, latitude=37.12345678901234 if i else None,
            query_level="sigungu", sido_value="11", sido_name="서울", sigungu_value="110",
            sigungu_name="검산구", source_kinds=[], first_seen_at=timestamp,
            last_seen_at=timestamp, is_self=True, has_cvs=True,
        )
        session.add(station)
        await session.flush()
        for code, price in (("B027", Decimal("1700.35")), ("D047", None)):
            session.add(FuelPriceSnapshot(
                fuel_station_id=station.id, source="opinet", product_code=code, price=price,
                observed_at=timestamp, collected_at=timestamp,
            ))
    await session.flush()
    await upsert_latest_fuel_prices(session)


def _data(response):
    assert response.status_code == 200, response.text
    body = response.json()
    body.pop("generated_at")
    return body


def _digest(body):
    return hashlib.sha256(to_json(body)).hexdigest()


@pytest.mark.parametrize("number", [
    Decimal("1700.1234567890123456789"), Decimal(9007199254740993),
    Decimal("0.000000000000000000123456789"), None,
])
def test_all_kind_bytes_match_python_dto_precision_and_attributes(number):
    timestamp = datetime(2026, 11, 18, 9, 0, 1, 123456, tzinfo=UTC)
    kinds = ["fuel_station", "rail_station", "ferry_port", "bus_terminal",
             "airport", "rest_area", "highway_incident", "public_parking_lot"]
    items = [{
        "id": i, "kind": kind, "source": "검산", "provider_id": "공급자", "city_name": "도시",
        "name": "한글 · \"이름\"\n둘째 줄", "longitude": 127.12345678901234,
        "latitude": 37.12345678901234 if i else None, "subtitle": "부제",
        "brand_name": "상표", "brand_code": "S", "latest_price": number, "price_product_code": "B027",
        "prices": [{"product_code": "B027", "price": number, "provider_updated_at": None,
                     "observed_at": timestamp, "collected_at": timestamp}],
        "phone": "02-123", "facilities": ["셀프"], "station_type": "종류", "line_names": ["노선"],
        "address": "주소", "updated_at": timestamp, "location_source": "admin_manual",
        "manual_location_revision": "revision", "location_point_count": 2,
        "parking_capacity": 0, "parking_fee_info": "무료",
    } for i, kind in enumerate(kinds)]
    cache = validation.ValidatedFuelMapItems()
    raw = to_json(items)
    payload, count = cache.read(raw)
    expected = TransportPlaceMapResponse(generated_at=timestamp, items=items)
    assert json.loads(payload) == json.loads(expected.model_dump_json())["items"]
    assert count == len(kinds)
    assert cache.read(raw)[0] is payload
    # UTC microseconds, NULL and the coordinate pair validator are preserved.
    assert json.loads(payload)[0]["updated_at"] == "2026-11-18T09:00:01.123456Z"
    assert json.loads(payload)[0]["longitude"] is None


@pytest.mark.parametrize("params", [
    {"limit": 5000}, {"limit": 1}, {"limit": 8},
    {"kinds": "fuel_station,rail_station", "product_codes": "B027,D047"},
    {"sources": "fixture,opinet", "include_unlocated": True},
    {"query": "%"},
    {"kinds": "ferry_port,bus_terminal", "include_unlocated": True},
    {"min_longitude": 127.15, "max_longitude": 128,
     "min_latitude": 37.55, "max_latitude": 38},
])
def test_reused_items_keep_previous_response_sha_order_filters_and_quota(client, monkeypatch, params):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 다중 장소 경로")
    async def seed():
        async with client.app.state.session_factory() as session:
            await _seed_places_and_prices(session)
            await session.commit()
    asyncio.run(seed())
    monkeypatch.setattr(validation, "_validated_items", validation.ValidatedFuelMapItems())
    first = _data(client.get("/v1/transport/features/places", params=params))
    warm = _data(client.get("/v1/transport/features/places", params=params))
    async def fallback(*args):
        return None
    monkeypatch.setattr(main, "read_place_plans", fallback)
    previous = _data(client.get("/v1/transport/features/places", params=params))
    assert _digest(first) == _digest(warm) == _digest(previous)
    assert first == warm == previous


def test_cached_items_read_price_changes_and_independent_metadata_immediately(client, monkeypatch):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 다중 장소 경로")
    async def seed():
        async with client.app.state.session_factory() as session:
            await _seed_places_and_prices(session)
            await session.commit()
    asyncio.run(seed())
    cache = validation.ValidatedFuelMapItems()
    monkeypatch.setattr(validation, "_validated_items", cache)
    path = "/v1/transport/features/places?limit=8"
    first = _data(client.get(path))
    first_payload = next(reversed(cache.entries.values()))[1]
    assert _data(client.get(path)) == first
    assert next(reversed(cache.entries.values()))[1] is first_payload

    async def metadata_only():
        async with client.app.state.session_factory() as session:
            timestamp = now_utc()
            # 동일 이름이면 새 ID가 뒤에 와서 collation과 무관하게 quota 밖에 남는다.
            session.add(RestAreaReference(
                source="new-source", identity_key="extra-rest", name="휴게소-0",
                longitude=127, latitude=37, first_seen_at=timestamp, last_seen_at=timestamp,
                raw_item_json={},
            ))
            await session.commit()
    asyncio.run(metadata_only())
    metadata = _data(client.get(path))
    assert metadata["items"] == first["items"]
    assert next(reversed(cache.entries.values()))[1] is first_payload
    assert metadata["total"] == first["total"] + 1
    assert metadata["kind_totals"]["rest_area"] == first["kind_totals"]["rest_area"] + 1
    assert "new-source" in metadata["available_sources"]

    async def change_price():
        async with client.app.state.session_factory() as session:
            await session.execute(update(FuelLatestPrice).values(price=Decimal("1800.25")))
            await session.commit()
    asyncio.run(change_price())
    changed = _data(client.get(path))
    assert changed["items"] != metadata["items"]
    assert next(reversed(cache.entries.values()))[1] is not first_payload
    station = next(item for item in changed["items"] if item["kind"] == "fuel_station")
    assert station["latest_price"] == 1800.25
    assert all(price["price"] == 1800.25 for price in station["prices"])

    async def fallback(*args):
        return None
    monkeypatch.setattr(main, "read_place_plans", fallback)
    assert changed == _data(client.get(path))


@pytest.mark.parametrize("longitude,latitude", [
    (37.4, 126.4), (181, 37), (-181, 37), (127, -91),
    (float("inf"), 37), (127, float("nan")), (None, 37), (127, None),
    (180, 90), (-180, -90), (127, 37), (0, 0),
])
def test_bytes_reuse_preserves_coordinate_pair_normalization(longitude, latitude):
    timestamp = now_utc()
    items = [{"id": 1, "kind": "rail_station", "source": "검산", "name": "역",
                  "longitude": longitude, "latitude": latitude, "updated_at": timestamp}]
    expected = TransportPlaceMapResponse(generated_at=timestamp, items=items)
    cache = validation.ValidatedFuelMapItems()
    payload, _ = cache.read(to_json(items))
    assert json.loads(payload) == json.loads(expected.model_dump_json())["items"]
    assert cache.read(to_json(items))[0] is payload

@pytest.mark.parametrize("products,expected_code,expected_price", [
    ([("D047", None), ("C004", "1800.25"), ("B027", "1700.35")], "B027", 1700.35),
    ([("D047", None), ("C004", "1800.25")], "C004", 1800.25),
    ([("D047", "1800.25"), ("B027", None)], "B027", None),
    ([("B027", "0.00")], "B027", 0),
    ([], None, None),
])
def test_mixed_price_projection_keeps_order_null_fallback_and_utc(
    client, products, expected_code, expected_price,
):
    from datetime import timedelta, timezone

    timestamp = datetime(2026, 11, 19, 12, 34, 56, 123456, tzinfo=timezone(timedelta(hours=9)))

    async def seed():
        async with client.app.state.session_factory() as session:
            station = FuelStation(
                source="price-projection-fixture", identity_key="ordered-prices", name='검산 "주유소"',
                longitude=127, latitude=37, query_level="sigungu", source_kinds=[],
                sido_value="11", sido_name="서울", sigungu_value="110", sigungu_name="검산구",
                first_seen_at=timestamp, last_seen_at=timestamp,
            )
            session.add(station)
            await session.flush()
            for code, value in products:
                session.add(FuelPriceSnapshot(
                    fuel_station_id=station.id, source=station.source, product_code=code,
                    price=Decimal(value) if value is not None else None,
                    provider_updated_at=timestamp if code == "B027" else None,
                    observed_at=timestamp, collected_at=timestamp,
                ))
            await session.flush()
            await upsert_latest_fuel_prices(session)
            await session.commit()
    asyncio.run(seed())
    params = {"kinds": "fuel_station,rail_station", "source": "price-projection-fixture", "limit": 8}
    first = _data(client.get("/v1/transport/features/places", params=params))
    assert _data(client.get("/v1/transport/features/places", params=params)) == first
    assert first["kind_totals"] == {"fuel_station": 1, "rail_station": 0}
    assert first["total"] == 1 and first["truncated"] is False
    item, = first["items"]
    assert item["name"] == '검산 "주유소"'
    assert item["latest_price"] == expected_price and item["price_product_code"] == expected_code
    assert item["prices"] == [
        {"product_code": code, "price": float(value) if value is not None else None,
         "provider_updated_at": "2026-11-19T03:34:56.123456Z" if code == "B027" else None,
         "observed_at": "2026-11-19T03:34:56.123456Z", "collected_at": "2026-11-19T03:34:56.123456Z"}
        for code, value in sorted(products)
    ]
    assert item["updated_at"] == "2026-11-19T03:34:56.123456Z"
