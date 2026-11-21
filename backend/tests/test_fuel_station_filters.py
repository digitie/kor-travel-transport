"""공개 유가 서버 필터: 마커·통계·지역 카드·시군구 칩·가격 분포가 같은 조건을 쓰는지, 지역 이동 목록."""
import asyncio
from datetime import datetime, timezone

import pytest

from app.models import FuelPriceSnapshot, FuelStation
from app.services.fuel_statistics import OPINET, publish_fuel_statistics
from app.services.transport_collection import upsert_latest_fuel_prices

# (id, 시군구, 경도, 휘발유, 셀프, 24시, 세차, 품질인증, 상표)
STATIONS = [
    (201, ("01", "서울", "0101", "종로구"), 126.98, 1600, True, False, True, True, "SKE"),
    (202, ("01", "서울", "0101", "종로구"), 126.99, 1640, False, True, False, False, "GSC"),
    (203, ("01", "서울", "0101", "종로구"), 127.00, 1700, True, True, False, True, "RTO"),
    (204, ("01", "서울", "0101", "종로구"), 127.01, 1720, True, False, True, False, "RTE"),
    (205, ("01", "서울", "0102", "중구"), 127.02, 1800, False, False, False, False, None),
    (206, ("01", "서울", "0102", "중구"), 127.03, 1900, True, False, False, False, "XYZ"),
]
BOX = {"min_longitude": 126.9, "max_longitude": 127.1, "min_latitude": 37, "max_latitude": 38}


async def seed(session, stamp):
    for station_id, (sido, sido_name, sigungu, sigungu_name), longitude, price, self_, h24, wash, kpetro, brand in STATIONS:
        session.add(FuelStation(id=station_id, source=OPINET, identity_key=str(station_id), name=f"필터{station_id}",
            address=f"{sido_name} {sigungu_name}", query_level="sigungu", source_kinds=[], brand_code=brand,
            sido_value=sido, sido_name=sido_name, sigungu_value=sigungu, sigungu_name=sigungu_name,
            longitude=longitude, latitude=37.5, is_self=self_, is_24h=h24, has_carwash=wash, is_kpetro=kpetro,
            first_seen_at=stamp, last_seen_at=stamp))
        await session.flush()
        session.add(FuelPriceSnapshot(fuel_station_id=station_id, source=OPINET, product_code="B027",
                                      price=price, observed_at=stamp, collected_at=stamp))
    await session.flush()
    await upsert_latest_fuel_prices(session, collected_at=stamp)


@pytest.fixture
def published(client):
    async def setup():
        async with client.app.state.session_factory() as session:
            stamp = datetime.now(timezone.utc)
            await seed(session, stamp)
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
    asyncio.run(setup())
    return client


def places(client, **params):
    response = client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "zoom": 12, "include_fuel_statistics": True, "include_viewport_sigungu": True, **BOX, **params})
    assert response.status_code == 200, response.text
    return response.json()


def ids(body):
    return sorted(item["id"] for item in body["items"])


def test_flag_filters_apply_to_markers_statistics_and_sigungu(published):
    body = places(published, self_only=True)
    assert ids(body) == [201, 203, 204, 206]
    stats = body["fuel_statistics"][0]
    assert stats["station_count"] == 4 and stats["minimum_price"] == 1600 and stats["maximum_price"] == 1900
    assert {row["sigungu_name"]: row["station_count"] for row in body["fuel_viewport_sigungu"]} == {"종로구": 3, "중구": 1}
    both = places(published, self_only=True, kpetro=True)
    assert ids(both) == [201, 203] and both["fuel_statistics"][0]["station_count"] == 2
    assert ids(places(published, open_24h=True, carwash=True)) == []
    assert places(published, open_24h=True, carwash=True)["fuel_statistics"] == []
    unfiltered = places(published)
    assert len(unfiltered["items"]) == 6 and unfiltered["fuel_statistics"][0]["station_count"] == 6


def test_brand_groups_include_self_run_alddeul_and_other(published):
    assert ids(places(published, brands="ALT")) == [203, 204]
    assert ids(places(published, brands="ETC")) == [205, 206]  # 미제공·목록 밖 상표
    assert ids(places(published, brands="SKE,GSC")) == [201, 202]
    every = "SKE,GSC,HDO,SOL,ALT,NHO,RTX,NCO,SKG,E1G,ETC"
    assert ids(places(published, brands=every)) == [201, 202, 203, 204, 205, 206]
    assert published.get("/v1/transport/features/places", params={"kind": "fuel_station", "brands": "BAD"}).status_code == 422


def test_near_min_uses_visible_minimum_of_other_filters(published):
    body = places(published, near_min=50, product_codes="B027")
    assert ids(body) == [201, 202]  # 화면 최저 1600 + 50
    assert body["fuel_statistics"][0]["maximum_price"] == 1640
    self_body = places(published, near_min=20, product_codes="B027", self_only=True, min_longitude=126.995)
    assert ids(self_body) == [203, 204]  # 화면 안 셀프 최저 1700 + 20
    assert self_body["fuel_viewport_sigungu"] == [
        {"sido_value": "01", "sido_name": "서울", "sigungu_value": "0101", "sigungu_name": "종로구", "station_count": 2}]
    for bad in ({"near_min": 50}, {"near_min": 50, "product_codes": "B027,D047"}, {"near_min": 33, "product_codes": "B027"}):
        assert published.get("/v1/transport/features/places", params={"kind": "fuel_station", "zoom": 12, **BOX, **bad}).status_code == 422


def test_filters_reject_mixed_kinds_and_keep_low_zoom_consistent(published):
    assert published.get("/v1/transport/features/places", params={"kinds": "fuel_station,rail_station", "self_only": True}).status_code == 422
    low = published.get("/v1/transport/features/places", params={"kind": "fuel_station", "zoom": 9, "self_only": True, **BOX}).json()
    assert low["kind_totals"] == {"fuel_station": 4}
    regions = {row["label"]: row["station_count"] for row in low["fuel_regions"]}
    assert regions == {"서울 종로구": 3, "서울 중구": 1}
    plain = published.get("/v1/transport/features/places", params={"kind": "fuel_station", "zoom": 9, **BOX}).json()
    assert {row["label"]: row["station_count"] for row in plain["fuel_regions"]} == {"서울 종로구": 4, "서울 중구": 2}


def test_price_distribution_applies_station_filters(published):
    body = published.get("/v1/transport/fuel/price-distribution", params={
        "sido_value": "01", "sigungu_value": "0101", "self_only": True, "near_min": 50}).json()
    assert body["sigungu"]["station_count"] == 3  # 셀프만, 화면 최저가 상한은 분포에 적용하지 않는다
    assert body["nationwide"]["station_count"] == 4
    assert body["filters_applied"] == ["셀프"]
    station = published.get("/v1/transport/fuel/price-distribution", params={"station_id": 204, "brands": "ALT"}).json()
    assert station["station"]["comparisons"][0]["station_count"] == 2
    assert station["filters_applied"] == ["상표 1종"]


def test_area_catalog_lists_sido_sigungu_with_bounds(published):
    body = published.get("/v1/transport/fuel/area-catalog").json()
    assert [row["sido_name"] for row in body["items"]] == ["서울"]
    sigungu = body["items"][0]["sigungu"]
    assert [row["sigungu_name"] for row in sigungu] == ["종로구", "중구"]
    assert sigungu[0]["station_count"] == 4
    assert sigungu[0]["bounds"] == [126.98, 37.5, 127.01, 37.5]
