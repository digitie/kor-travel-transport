"""시군구 가격 분포·주유소 상대 위치 API와 화면 안 시군구 목록 계약."""
import asyncio
from datetime import datetime, timezone

import pytest

from app.models import FuelPriceSnapshot, FuelStation
from app.services.fuel_price_distribution import (
    GRADE_RULE, MINIMUM_SAMPLE, grade_for, mid_rank_percentile, price_histogram, price_quantiles,
)
from app.services.fuel_statistics import OPINET, publish_fuel_statistics
from app.services.transport_collection import upsert_latest_fuel_prices

# (id, 시도, 시도명, 시군구, 시군구명, 경도, {유종: 가격})
STATIONS = [
    (101, "01", "서울", "0101", "종로구", 126.98, {"B027": 1600, "D047": 1500}),
    (102, "01", "서울", "0101", "종로구", 126.99, {"B027": 1650}),
    (103, "01", "서울", "0101", "종로구", 127.00, {"B027": 1700}),
    (104, "01", "서울", "0101", "종로구", 127.01, {"B027": 1700, "D047": 1550}),
    (105, "01", "서울", "0101", "종로구", 127.02, {"B027": 1800, "D047": 1600}),
    (106, "01", "서울", "0102", "중구", 127.03, {"B027": 1900}),
    (107, "01", "서울", "0102", "중구", 127.04, {"B027": 2000}),
    (108, "15", "충북", "1501", "옥천군", 127.60, {"B027": 1500}),
    (109, "15", "충북", "1501", "옥천군", 127.61, {"B027": 1550}),
    (110, "15", "충북", "1501", "옥천군", 127.62, {"B027": 1600}),
]


async def seed(session, stamp):
    for station_id, sido, sido_name, sigungu, sigungu_name, longitude, prices in STATIONS:
        session.add(FuelStation(id=station_id, source=OPINET, identity_key=str(station_id), name=f"주유소{station_id}",
            address=f"{sido_name} {sigungu_name}", query_level="sigungu", source_kinds=[],
            sido_value=sido, sido_name=sido_name, sigungu_value=sigungu, sigungu_name=sigungu_name,
            longitude=longitude, latitude=37.5, first_seen_at=stamp, last_seen_at=stamp))
        await session.flush()
        for product, price in prices.items():
            session.add(FuelPriceSnapshot(fuel_station_id=station_id, source=OPINET, product_code=product,
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


def test_grade_rule_boundaries_are_half_open_and_ordered():
    uppers = [upper for upper, _, _ in GRADE_RULE]
    assert uppers == sorted(uppers)
    assert grade_for(0) == ("A+", "제일싸요")
    assert grade_for(9.9) == ("A+", "제일싸요")
    assert grade_for(10) == ("A", "저렴해요")
    assert grade_for(59.9) == ("B", "평범해요")
    assert grade_for(60) == ("C+", "조금 비싸요")
    assert grade_for(100) == ("D", "제일 비싸요")
    # 중간 순위: 29곳 중 단독 최저가는 1.7%, 모두 같은 가격이면 50%.
    assert mid_rank_percentile(0, 1, 29) == 1.7
    assert mid_rank_percentile(0, 5, 5) == 50


def test_histogram_uses_nice_widths_and_counts_every_price():
    prices = [1819, 1830, 1850, 1875, 1880, 1885, 1890, 1998]
    width, bins = price_histogram(prices)
    assert width == 20
    assert bins[0]["start"] == 1800 and bins[-1]["end"] > 1998
    assert sum(row["count"] for row in bins) == len(prices)
    assert all(row["end"] - row["start"] == width for row in bins)
    # 모두 같은 가격이면 한 구간.
    assert price_histogram([1700, 1700, 1700]) == (10.0, [{"start": 1700, "end": 1710, "count": 3}])
    assert price_histogram([]) == (0.0, [])


def test_quantiles_match_percentile_cont():
    points = price_quantiles([1600, 1650, 1700, 1700, 1800])
    assert [row["percent"] for row in points] == list(range(0, 101, 10))
    assert points[0]["price"] == 1600 and points[-1]["price"] == 1800
    assert points[5]["price"] == 1700  # 중앙값
    assert points[1]["price"] == 1620  # 0.4 위치: 1600 + 0.4×50


def test_sigungu_distribution_and_national_lines(published):
    response = published.get("/v1/transport/fuel/price-distribution",
                             params={"sido_value": "01", "sigungu_value": "0101", "product_code": "B027"})
    assert response.status_code == 200
    body = response.json()
    assert body["sido_name"] == "서울" and body["sigungu_name"] == "종로구"
    local = body["sigungu"]
    assert local["station_count"] == 5 and local["sufficient"] is True
    assert (local["minimum_price"], local["average_price"], local["maximum_price"]) == (1600, 1690, 1800)
    assert sum(row["count"] for row in local["histogram"]) == 5
    assert local["quantiles"][0]["price"] == 1600 and local["quantiles"][-1]["price"] == 1800
    assert body["sido"]["station_count"] == 7
    assert body["sido"]["average_price"] == pytest.approx(12350 / 7, abs=0.01)
    assert body["nationwide"] == {"scope": "nationwide", "label": "전국", "station_count": 10,
                                  "minimum_price": 1500, "average_price": 1700, "maximum_price": 2000}
    assert body["station"] is None
    assert body["minimum_sample"] == MINIMUM_SAMPLE
    assert [row["grade"] for row in body["grade_rule"]] == [grade for _, grade, _ in GRADE_RULE]
    assert body["generated_at"] is not None


def test_station_position_per_scope(published):
    body = published.get("/v1/transport/fuel/price-distribution",
                         params={"station_id": 104, "product_code": "B027"}).json()
    station = body["station"]
    assert station["price"] == 1700 and station["sells_product"] is True
    assert station["products"] == ["B027", "D047"]
    scopes = {row["scope"]: row for row in station["comparisons"]}
    assert list(scopes) == ["sigungu", "sido", "nationwide"]
    assert scopes["sigungu"]["difference"] == 10
    assert scopes["sigungu"]["percentile"] == 60  # (2 + 0.5×2) / 5
    assert (scopes["sigungu"]["grade"], scopes["sigungu"]["grade_label"]) == ("C+", "조금 비싸요")
    assert scopes["sido"]["percentile"] == 42.9  # (2 + 1) / 7
    assert scopes["sido"]["grade"] == "B"
    assert scopes["sido"]["difference"] == pytest.approx(1700 - 12350 / 7, abs=0.01)
    assert scopes["nationwide"]["percentile"] == 60  # (5 + 1) / 10
    assert scopes["nationwide"]["difference"] == 0
    cheapest = published.get("/v1/transport/fuel/price-distribution",
                             params={"station_id": 108, "product_code": "B027"}).json()["station"]["comparisons"]
    assert cheapest[0]["grade"] == "A" and cheapest[0]["percentile"] == 16.7  # 3곳 중 단독 최저
    assert cheapest[-1]["grade"] == "A+" and cheapest[-1]["percentile"] == 5


def test_station_without_product_and_small_sigungu(published):
    body = published.get("/v1/transport/fuel/price-distribution",
                         params={"station_id": 102, "product_code": "D047"}).json()
    assert body["station"]["sells_product"] is False and body["station"]["price"] is None
    assert body["station"]["comparisons"] == []
    assert body["sigungu"]["station_count"] == 3  # 지역 분포는 그대로 제공한다
    small = published.get("/v1/transport/fuel/price-distribution",
                          params={"station_id": 106, "product_code": "B027"}).json()
    assert small["sigungu"]["sufficient"] is False
    local = small["station"]["comparisons"][0]
    assert local["scope"] == "sigungu" and local["grade"] is None and local["sufficient"] is False
    assert small["station"]["comparisons"][1]["grade"] is not None  # 시도는 7곳이라 등급이 있다


def test_distribution_rejects_missing_region_and_unknown_station(published):
    assert published.get("/v1/transport/fuel/price-distribution", params={"sido_value": "01"}).status_code == 422
    assert published.get("/v1/transport/fuel/price-distribution", params={"station_id": 999}).status_code == 404
    assert published.get("/v1/transport/fuel/price-distribution",
                         params={"sido_value": "99", "sigungu_value": "9999"}).status_code == 404
    empty = published.get("/v1/transport/fuel/price-distribution",
                          params={"sido_value": "01", "sigungu_value": "0101", "product_code": "K015"}).json()
    assert empty["sigungu"] is None and empty["nationwide"] is None


def test_distribution_before_first_publication_is_empty(client):
    async def setup():
        async with client.app.state.session_factory() as session:
            await seed(session, datetime.now(timezone.utc))
            await session.commit()
    asyncio.run(setup())
    body = client.get("/v1/transport/fuel/price-distribution",
                      params={"sido_value": "01", "sigungu_value": "0101"}).json()
    assert body["generated_at"] is None and body["sigungu"] is None


def test_viewport_sigungu_is_opt_in_and_counts_visible_stations(published):
    params = {"kind": "fuel_station", "zoom": 12, "include_fuel_statistics": True,
              "min_longitude": 126.985, "max_longitude": 127.035, "min_latitude": 37, "max_latitude": 38}
    plain = published.get("/v1/transport/features/places", params=params).json()
    assert "fuel_viewport_sigungu" not in plain and "fuel_viewport_sigungu_total" not in plain
    body = published.get("/v1/transport/features/places", params={**params, "include_viewport_sigungu": True}).json()
    assert body["fuel_viewport_sigungu_total"] == 2
    assert body["fuel_viewport_sigungu"] == [
        {"sido_value": "01", "sido_name": "서울", "sigungu_value": "0101", "sigungu_name": "종로구", "station_count": 4},
        {"sido_value": "01", "sido_name": "서울", "sigungu_value": "0102", "sigungu_name": "중구", "station_count": 1},
    ]
    diesel = published.get("/v1/transport/features/places", params={
        **params, "include_viewport_sigungu": True, "product_codes": "D047"}).json()
    assert diesel["fuel_viewport_sigungu"] == [
        {"sido_value": "01", "sido_name": "서울", "sigungu_value": "0101", "sigungu_name": "종로구", "station_count": 2},
    ]
    zoomed_out = published.get("/v1/transport/features/places", params={
        **params, "zoom": 7, "include_viewport_sigungu": True,
        "min_longitude": 124, "max_longitude": 132, "min_latitude": 33, "max_latitude": 39}).json()
    assert zoomed_out["fuel_viewport_sigungu_total"] == 3
    assert [row["station_count"] for row in zoomed_out["fuel_viewport_sigungu"]] == [5, 3, 2]
    other_source = published.get("/v1/transport/features/places", params={
        **params, "include_viewport_sigungu": True, "source": "krex_rest_area_fuel"}).json()
    assert other_source["fuel_viewport_sigungu"] == []
