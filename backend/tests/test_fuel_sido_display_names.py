"""시도 화면 이름 통일: 같은 시도 코드라도 오피넷 원문 이름이 행마다 짧은/정식으로 섞여 있다(운영 2026-11-23).

지역 이동 목록·지도 중심 칩·화면 안 시군구·가격 분포 제목·지역 카드가 모두 짧은 이름 하나를 쓴다.
"""
import asyncio
from datetime import datetime, timezone

import pytest

from app.models import FuelPriceSnapshot, FuelStation
from app.services.fuel_regions import display_region_label
from app.services.fuel_station_filters import sido_display_name
from app.services.fuel_statistics import OPINET, publish_fuel_statistics
from app.services.transport_collection import upsert_latest_fuel_prices

SEOUL, GYEONGGI = "서울특별시", "경기도"
# (id, 시도 코드, 원문 시도 이름, 시군구 코드, 시군구 이름, 경도, 위도). 첫 행이 정식 이름이라 예전 목록은 "서울특별시"였다.
STATIONS = [
    (201, SEOUL, "서울특별시", "S01", "종로구", 126.98, 37.57),
    (202, SEOUL, "서울", "S01", "종로구", 126.985, 37.571),
    (203, SEOUL, "서울", "S01", "종로구", 126.99, 37.572),
    (204, SEOUL, "서울", "S01", "종로구", 126.995, 37.573),
    (205, GYEONGGI, "경기도", "G01", "수원시", 127.01, 37.27),
    (206, GYEONGGI, "경기", "G01", "수원시", 127.02, 37.271),
    (207, GYEONGGI, "경기", "G01", "수원시", 127.03, 37.272),
]


def test_sido_display_name_maps_full_and_short_names_to_one_short_name():
    assert sido_display_name(SEOUL, "서울특별시") == sido_display_name(SEOUL, "서울") == "서울"
    assert sido_display_name("전남광주통합특별시", "전남광주통합특별시") == "전남광주"
    assert sido_display_name("강원특별자치도", "강원특별자치도") == "강원"
    # 모르는 코드는 원문 그대로(없으면 코드).
    assert sido_display_name("01", "서울") == "서울"
    assert sido_display_name("99", None) == "99"


def test_region_card_labels_use_short_sido_names():
    assert display_region_label("sido", f"{OPINET}:{GYEONGGI}", "경기도") == "경기"
    assert display_region_label("sigungu", f"{OPINET}:{GYEONGGI}:G01", "경기도 수원시") == "경기 수원시"
    assert display_region_label("sigungu", f"{OPINET}:{SEOUL}:S01", "서울 종로구") == "서울 종로구"
    assert display_region_label("sido", f"{OPINET}:01", "서울") == "서울"


@pytest.fixture
def mixed_names(client):
    async def setup():
        async with client.app.state.session_factory() as session:
            stamp = datetime.now(timezone.utc)
            for station_id, sido, sido_name, sigungu, sigungu_name, longitude, latitude in STATIONS:
                session.add(FuelStation(id=station_id, source=OPINET, identity_key=str(station_id), name=f"주유소{station_id}",
                    address=f"{sido_name} {sigungu_name}", query_level="sigungu", source_kinds=[],
                    sido_value=sido, sido_name=sido_name, sigungu_value=sigungu, sigungu_name=sigungu_name,
                    longitude=longitude, latitude=latitude, first_seen_at=stamp, last_seen_at=stamp))
                await session.flush()
                session.add(FuelPriceSnapshot(fuel_station_id=station_id, source=OPINET, product_code="B027",
                                              price=1600 + station_id % 7, observed_at=stamp, collected_at=stamp))
            await session.flush()
            await upsert_latest_fuel_prices(session, collected_at=stamp)
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
    asyncio.run(setup())
    return client


def test_area_catalog_chip_and_distribution_share_short_sido_names(mixed_names):
    client = mixed_names
    catalog = client.get("/v1/transport/fuel/area-catalog").json()["items"]
    assert {row["sido_value"]: row["sido_name"] for row in catalog} == {GYEONGGI: "경기", SEOUL: "서울"}

    body = client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "zoom": 7, "min_longitude": 126.5, "min_latitude": 37.0, "max_longitude": 127.5,
        "max_latitude": 38.0, "include_viewport_sigungu": "true", "center_longitude": 126.981, "center_latitude": 37.57,
    }).json()
    assert body["fuel_center_sigungu"]["sido_name"] == "서울"
    # 원문 이름이 섞여도 한 시군구는 한 줄이다(예전에는 이름까지 묶어 "서울특별시 종로구"·"서울 종로구"로 갈렸다).
    rows = [(row["sido_name"], row["sigungu_name"], row["station_count"]) for row in body["fuel_viewport_sigungu"]]
    assert sorted(rows) == [("경기", "수원시", 3), ("서울", "종로구", 4)]
    assert body["fuel_regions"] and {region["label"] for region in body["fuel_regions"]} == {"서울", "경기"}

    by_region = client.get("/v1/transport/fuel/price-distribution",
                           params={"product_code": "B027", "sido_value": SEOUL, "sigungu_value": "S01"}).json()
    assert (by_region["sido_name"], by_region["sido"]["label"]) == ("서울", "서울")
    by_station = client.get("/v1/transport/fuel/price-distribution", params={"product_code": "B027", "station_id": 205}).json()
    assert (by_station["sido_name"], by_station["sido"]["label"]) == ("경기", "경기")
    assert by_station["sigungu"]["station_count"] == 3
