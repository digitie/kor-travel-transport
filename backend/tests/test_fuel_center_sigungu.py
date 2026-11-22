"""공개 유가 지도 중심 시군구(가장 가까운 오피넷 주유소의 시군구 근사) 계약."""
import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import update

from app.models import FuelStation
from app.services import fuel_center_sigungu as center_module
from app.services.fuel_statistics import OPINET, publish_fuel_statistics

# 가격 분포 시험과 같은 시드: 종로구 126.98~127.02, 중구 127.03·127.04, 옥천군 127.60~127.62(모두 위도 37.5).
from test_fuel_price_distribution import seed

PLACES = "/v1/transport/features/places"
BASE = {"kind": "fuel_station", "zoom": 12, "include_fuel_statistics": True, "include_viewport_sigungu": True,
        "min_longitude": 126.9, "max_longitude": 127.7, "min_latitude": 37, "max_latitude": 38}


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


@pytest.fixture(autouse=True)
def clear_center_cache():
    center_module._cache.clear()
    yield
    center_module._cache.clear()


def center_of(client, longitude, latitude, **extra):
    response = client.get(PLACES, params={**BASE, **extra, "center_longitude": longitude, "center_latitude": latitude})
    assert response.status_code == 200
    return response.json()


def test_center_resolves_to_nearest_station_sigungu(published):
    body = center_of(published, 127.004, 37.5)
    center = body["fuel_center_sigungu"]
    assert {key: center[key] for key in ("sido_value", "sido_name", "sigungu_value", "sigungu_name", "method")} == {
        "sido_value": "01", "sido_name": "서울", "sigungu_value": "0101", "sigungu_name": "종로구", "method": "nearest_station"}
    # 127.00(주유소 103)까지 약 0.004° × cos(37.5°) ≈ 350 m.
    assert 300 <= center["distance_m"] <= 400
    # 화면 안 주유소가 가장 많은 곳 목록은 그대로 함께 온다(화면의 대체 경로).
    assert body["fuel_viewport_sigungu"][0]["sigungu_name"] == "종로구"
    # 중심이 옥천군 쪽이면 화면 1순위(종로구)와 달리 옥천군이다.
    assert center_of(published, 127.61, 37.5)["fuel_center_sigungu"]["sigungu_name"] == "옥천군"
    assert center_of(published, 127.039, 37.5)["fuel_center_sigungu"]["sigungu_name"] == "중구"


def test_center_widens_search_and_returns_null_far_from_stations(published):
    # 가장 가까운 주유소가 약 23 km(0.206°) 떨어져 첫 두 상자에 없으면 다음 상자에서 찾는다.
    far = center_of(published, 127.3, 37.5)["fuel_center_sigungu"]
    assert far["sigungu_name"] == "중구" and 22_000 <= far["distance_m"] <= 24_000
    # 반경(약 33 km) 안에 주유소가 없으면(바다) null — 화면은 "주유소가 가장 많은 시군구"로 되돌아간다.
    sea = center_of(published, 125.0, 35.0)
    assert sea["fuel_center_sigungu"] is None
    assert sea["fuel_viewport_sigungu"]


def test_center_ignores_product_filters_and_stations_without_region(published):
    # 지역의 정체는 유종·필터와 무관하다: 경유를 팔지 않는 중구(106·107) 사이 127.035에서 경유를 골라도 중구.
    # (필터를 적용했다면 경유를 파는 가장 가까운 105(127.02, 종로구)가 됐을 것이다.)
    assert center_of(published, 127.035, 37.5, product_codes="D047")["fuel_center_sigungu"]["sigungu_name"] == "중구"

    async def clear_region():
        async with published.app.state.session_factory() as session:
            await session.execute(update(FuelStation).where(FuelStation.id == 106).values(sigungu_value=""))
            await session.commit()
    asyncio.run(clear_region())
    # 106(127.03, 중구)은 시군구가 비어 제외 → 127.029에서 가장 가까운 곳은 105(127.02, 종로구).
    assert center_of(published, 127.029, 37.5)["fuel_center_sigungu"]["sigungu_name"] == "종로구"


def test_center_on_clustered_zoom_and_validation(published):
    clustered = center_of(published, 127.61, 37.5, zoom=7, min_longitude=124, max_longitude=132,
                          min_latitude=33, max_latitude=39)
    assert clustered["clustered"] is True
    assert clustered["fuel_center_sigungu"]["sigungu_name"] == "옥천군"
    for params in ({"center_longitude": 127.0}, {"center_latitude": 37.5}):
        assert published.get(PLACES, params={**BASE, **params}).status_code == 422
    assert published.get(PLACES, params={**BASE, "center_longitude": 181, "center_latitude": 37.5}).status_code == 422


@pytest.mark.parametrize("zoom", [7, 12])
def test_center_not_requested_keeps_existing_response(published, zoom):
    """중심을 주지 않으면(관리 지도·기존 공개 화면) 새 필드가 없고 나머지 응답은 중심을 준 응답과 같다."""
    params = {"kind": "fuel_station", "zoom": zoom, "include_fuel_statistics": True, "include_viewport_sigungu": True,
              "min_longitude": 126.985, "max_longitude": 127.035, "min_latitude": 37, "max_latitude": 38}
    plain = published.get(PLACES, params=params).json()
    with_center = published.get(PLACES, params={**params, "center_longitude": 127.0, "center_latitude": 37.5}).json()
    assert "fuel_center_sigungu" not in plain
    assert with_center.pop("fuel_center_sigungu")["sigungu_name"] == "종로구"
    for body in (plain, with_center):
        body.pop("generated_at")
    assert plain == with_center
    admin = published.get(PLACES, params={"kind": "fuel_station", "zoom": zoom, "min_longitude": 126.985,
                                          "max_longitude": 127.035, "min_latitude": 37, "max_latitude": 38}).json()
    assert "fuel_center_sigungu" not in admin and "fuel_viewport_sigungu" not in admin


def _add_station(session, station_id, sigungu_name, longitude, latitude):
    stamp = datetime.now(timezone.utc)
    session.add(FuelStation(id=station_id, source=OPINET, identity_key=str(station_id), name=f"주유소{station_id}",
        address=f"경남 {sigungu_name}", query_level="sigungu", source_kinds=[],
        sido_value="16", sido_name="경남", sigungu_value=f"16{station_id}", sigungu_name=sigungu_name,
        longitude=longitude, latitude=latitude, first_seen_at=stamp, last_seen_at=stamp))


def test_center_accepts_only_inscribed_circle_and_scales_longitude(client):
    """상자 모서리의 더 먼 곳을 받지 않고(내접원), 경도 폭을 cos(위도)로 넓힌다 — 위도가 다른 주유소로 확인한다."""
    import math
    scale = math.cos(math.radians(35.0))

    async def setup():
        async with client.app.state.session_factory() as session:
            # 중심 (128.5, 35.0): A는 첫 상자(반경 0.02) 모서리, 평면 거리 약 0.0255 > 0.02.
            # B는 첫 상자 바로 밖(위도 차 0.021)이지만 거리 0.021로 A보다 가깝다 → 정답 B.
            _add_station(session, 901, "모서리군", 128.5 + 0.018 / scale, 35.018)
            _add_station(session, 902, "바깥군", 128.5, 34.979)
            # 중심 (129.0, 35.0): C는 경도 차 0.022°(평면 0.018), D는 위도 차 0.0195 → 정답 C.
            # 경도 폭을 cos로 넓히지 않으면 C가 첫 상자 밖이라 D를 고른다.
            _add_station(session, 903, "경도군", 129.022, 35.0)
            _add_station(session, 904, "위도군", 129.0, 35.0195)
            await session.commit()
    asyncio.run(setup())
    params = {"kind": "fuel_station", "zoom": 12, "min_longitude": 128.4, "max_longitude": 129.1,
              "min_latitude": 34.9, "max_latitude": 35.1}
    corner = client.get(PLACES, params={**params, "center_longitude": 128.5, "center_latitude": 35.0}).json()
    assert corner["fuel_center_sigungu"]["sigungu_name"] == "바깥군"
    assert 2_200 <= corner["fuel_center_sigungu"]["distance_m"] <= 2_400
    wide = client.get(PLACES, params={**params, "center_longitude": 129.0, "center_latitude": 35.0}).json()
    assert wide["fuel_center_sigungu"]["sigungu_name"] == "경도군"
