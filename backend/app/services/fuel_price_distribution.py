"""공개 유가 세대로 시군구 가격 분포와 주유소의 상대 위치를 계산한다.

원천은 지도 통계와 같은 공개 세대(`fuel_statistics_points` + `fuel_statistics_states`)다.
시군구 한 곳의 가격(수십~수백 행)만 내려받아 구간·분위를 Python에서 만들고, 시도·전국은
한 SQL의 집계(count/min/avg/max와 가격 이하 개수)로 읽는다. 새 테이블이나 사전집계는 두지
않는다(2026-11-22 측정: 아래 문서 docs/fuel-statistics.md "시군구 가격 분포").
"""
from __future__ import annotations

import math
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc
from app.models import FuelStation, FuelStatisticsPoint, FuelStatisticsState, TransportCollectionState
from app.schemas import FuelPriceDistributionResponse

OPINET = "opinet_browser"
# 표본이 이보다 적으면 분포·등급을 만들지 않는다(1~2곳의 "최저/최고"는 비교가 아니다).
MINIMUM_SAMPLE = 3
QUANTILE_PERCENTS = tuple(range(0, 101, 10))
HISTOGRAM_TARGET_BINS = 10
VIEWPORT_SIGUNGU_LIMIT = 40
_sigungu_cache: OrderedDict[tuple, tuple[float, tuple[list[dict], int]]] = OrderedDict()

# 등급 규칙(단일 정본). percentile은 "이 가격보다 싼 주유소 비율"의 중간 순위 백분위다:
#   percentile = 100 × (더 싼 곳 수 + 0.5 × 같은 가격 곳 수) / 전체 곳 수
# 0에 가까울수록 싸다. 아래 상한(미만)을 처음 만족하는 등급을 준다. 표본이 MINIMUM_SAMPLE 미만이면 등급 없음.
GRADE_RULE: tuple[tuple[float, str, str], ...] = (
    (10, "A+", "제일싸요"),
    (25, "A", "저렴해요"),
    (40, "B+", "조금 싸요"),
    (60, "B", "평범해요"),
    (75, "C+", "조금 비싸요"),
    (90, "C", "비싸요"),
    (math.inf, "D", "제일 비싸요"),
)


def grade_for(percentile: float) -> tuple[str, str]:
    for upper, grade, label in GRADE_RULE:
        if percentile < upper:
            return grade, label
    return GRADE_RULE[-1][1], GRADE_RULE[-1][2]


def mid_rank_percentile(below: int, equal: int, count: int) -> float:
    return round(100 * (below + 0.5 * equal) / count, 1)


def _nice_width(raw: float) -> float:
    if raw <= 0:
        return 10.0
    magnitude = 10 ** math.floor(math.log10(raw))
    for step in (1, 2, 5, 10):
        if step * magnitude >= raw:
            return max(1.0, float(step * magnitude))
    return max(1.0, float(10 * magnitude))


def price_histogram(prices: Sequence[float], target_bins: int = HISTOGRAM_TARGET_BINS) -> tuple[float, list[dict]]:
    """오름차순 가격을 1·2·5×10^k원 폭의 반열린 구간 [start, end)로 센다. 마지막 구간은 최고가를 포함한다."""
    if not prices:
        return 0.0, []
    low, high = min(prices), max(prices)
    width = _nice_width((high - low) / target_bins) if high > low else 10.0
    start = math.floor(low / width) * width
    count = int(math.floor((high - start) / width)) + 1
    bins = [{"start": start + index * width, "end": start + (index + 1) * width, "count": 0} for index in range(count)]
    for price in prices:
        bins[min(count - 1, int((price - start) // width))]["count"] += 1
    return width, bins


def price_quantiles(sorted_prices: Sequence[float]) -> list[dict]:
    """0·10·…·100% 지점의 선형 보간 분위(PostgreSQL percentile_cont와 같은 정의)."""
    if not sorted_prices:
        return []
    last = len(sorted_prices) - 1
    points = []
    for percent in QUANTILE_PERCENTS:
        position = percent / 100 * last
        lower = math.floor(position)
        upper = min(last, lower + 1)
        value = sorted_prices[lower] + (sorted_prices[upper] - sorted_prices[lower]) * (position - lower)
        points.append({"percent": percent, "price": round(value, 2)})
    return points


def _published_points(product_code: str | None = None):
    p, state = FuelStatisticsPoint, FuelStatisticsState
    statement = select(p).join(state, and_(p.source == state.source, p.generated_at == state.generated_at)).join(
        FuelStation, FuelStation.id == cast(p.station_key, Integer),
    ).where(p.source == OPINET, p.price > 0)
    if product_code is not None:
        statement = statement.where(p.product_code == product_code)
    return statement


async def viewport_sigungu(session: AsyncSession, bounds: tuple[float, float, float, float],
                           sources: list[str], products: list[str], query: str | None,
                           limit: int = VIEWPORT_SIGUNGU_LIMIT) -> tuple[list[dict], int]:
    """현재 화면 안 공개 세대 주유소를 시군구로 묶어 주유소가 많은 순으로 돌려준다.

    경계 폴리곤이 아니라 화면에 실제로 보이는 주유소 기준이다(지도 통계와 같은 모집단).
    """
    if sources and OPINET not in sources:
        return [], 0
    published = await session.get(FuelStatisticsState, OPINET)
    if published is None:
        return [], 0
    key = (session.bind, serialize_utc(published.generated_at), bounds, tuple(sorted(products)), (query or "").strip(), limit)
    cached = _sigungu_cache.get(key)
    if cached and cached[0] > time.monotonic():
        _sigungu_cache.move_to_end(key)
        return cached[1]
    p, s, state = FuelStatisticsPoint, FuelStation, FuelStatisticsState
    conditions = [p.source == OPINET, p.price > 0,
                  p.longitude.between(bounds[0], bounds[2]), p.latitude.between(bounds[1], bounds[3])]
    if products:
        conditions.append(p.product_code.in_(products))
    if query and query.strip():
        conditions.append(or_(*(column.icontains(query.strip(), autoescape=True)
                                for column in (p.name, p.brand_name, p.address))))
    # 화면 안 주유소 id를 먼저 한 번씩만 뽑고(유종 행 중복 제거) 그다음 시군구로 묶는다.
    # 전국 화면(약 3.2만 가격 행)에서 가격 행 전체를 주유소와 조인해 count(distinct)하는 것보다 싸다.
    visible = select(cast(p.station_key, Integer).label("station_id")).join(state, and_(
        p.source == state.source, p.generated_at == state.generated_at,
    )).where(*conditions).distinct().subquery()
    station_count = func.count().label("station_count")
    grouped = select(
        s.sido_value, s.sido_name, s.sigungu_value, s.sigungu_name, station_count,
        func.count().over().label("region_total"),
    ).select_from(visible).join(s, s.id == visible.c.station_id).where(
        s.sido_value != "", s.sigungu_value != "",
    ).group_by(s.sido_value, s.sido_name, s.sigungu_value, s.sigungu_name).order_by(
        func.count().desc(), s.sido_value, s.sigungu_value,
    ).limit(limit)
    rows = (await session.execute(grouped)).mappings().all()
    total = int(rows[0]["region_total"]) if rows else 0
    result = ([{"sido_value": row["sido_value"], "sido_name": row["sido_name"] or row["sido_value"],
                "sigungu_value": row["sigungu_value"], "sigungu_name": row["sigungu_name"] or row["sigungu_value"],
                "station_count": int(row["station_count"])} for row in rows], total)
    # 같은 공개 세대·같은 화면의 반복 요청(재렌더·되돌아가기)만 10초 재사용한다. 세대가 바뀌면 키가 달라진다.
    _sigungu_cache[key] = (time.monotonic() + 10, result)
    while len(_sigungu_cache) > 64:
        _sigungu_cache.popitem(last=False)
    return result


def _summary(scope: str, label: str, count: int, minimum: Any, average: Any, maximum: Any) -> dict | None:
    if not count:
        return None
    return {"scope": scope, "label": label, "station_count": int(count), "minimum_price": float(minimum),
            "average_price": round(float(average), 2), "maximum_price": float(maximum)}


def _comparison(summary: dict | None, price: float, below: int, equal: int) -> dict | None:
    if summary is None:
        return None
    count = summary["station_count"]
    sufficient = count >= MINIMUM_SAMPLE
    percentile = mid_rank_percentile(below, equal, count)
    grade, label = grade_for(percentile) if sufficient else (None, None)
    return {**summary, "price": price, "difference": round(price - summary["average_price"], 2),
            "percentile": percentile, "grade": grade, "grade_label": label, "sufficient": sufficient}


async def price_distribution(session: AsyncSession, *, product_code: str, sido_value: str | None,
                             sigungu_value: str | None, station_id: int | None) -> dict:
    p, s = FuelStatisticsPoint, FuelStation
    state = await session.get(FuelStatisticsState, OPINET)
    station = None
    if station_id is not None:
        station = await session.get(FuelStation, station_id)
        if station is None or station.source != OPINET:
            raise HTTPException(status_code=404, detail="오피넷 주유소만 지역 가격 비교를 제공합니다.")
        sido_value, sigungu_value = station.sido_value, station.sigungu_value
    if not sido_value or not sigungu_value:
        raise HTTPException(status_code=422, detail="시도·시군구 또는 주유소를 지정해 주세요.")
    collection = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == OPINET))
    generated_at = state.generated_at if state is not None else None
    response: dict[str, Any] = {
        "product_code": product_code, "generated_at": generated_at,
        "update_pending": bool(collection and collection.last_success_at and (
            generated_at is None or serialize_utc(collection.last_success_at) > serialize_utc(generated_at))),
        "minimum_sample": MINIMUM_SAMPLE, "sido_value": sido_value, "sigungu_value": sigungu_value,
        "sido_name": station.sido_name if station else None, "sigungu_name": station.sigungu_name if station else None,
        "grade_rule": [{"grade": grade, "label": label, "percentile_below": None if math.isinf(upper) else upper}
                       for upper, grade, label in GRADE_RULE],
        "sigungu": None, "sido": None, "nationwide": None, "station": None,
    }
    if generated_at is None:
        return response
    region_rows = (await session.execute(_published_points(product_code).with_only_columns(
        p.price, s.sido_name, s.sigungu_name,
    ).where(s.sido_value == sido_value, s.sigungu_value == sigungu_value).order_by(p.price))).all()
    prices = [float(row.price) for row in region_rows]
    if region_rows:
        response["sido_name"] = response["sido_name"] or region_rows[0].sido_name
        response["sigungu_name"] = response["sigungu_name"] or region_rows[0].sigungu_name
    if response["sido_name"] is None or response["sigungu_name"] is None:
        names = (await session.execute(select(s.sido_name, s.sigungu_name).where(
            s.source == OPINET, s.sido_value == sido_value, s.sigungu_value == sigungu_value,
        ).limit(1))).first()
        if names is None:
            raise HTTPException(status_code=404, detail="해당 시군구의 주유소가 없습니다.")
        response["sido_name"] = response["sido_name"] or names.sido_name
        response["sigungu_name"] = response["sigungu_name"] or names.sigungu_name
    sido_label = response["sido_name"] or sido_value
    sigungu_label = response["sigungu_name"] or sigungu_value
    station_price = None
    station_products: list[str] = []
    if station is not None:
        station_rows = (await session.execute(_published_points().with_only_columns(p.product_code, p.price)
                                              .where(p.station_key == str(station.id)))).all()
        station_products = sorted(row.product_code for row in station_rows)
        station_price = next((float(row.price) for row in station_rows if row.product_code == product_code), None)
    in_sido = s.sido_value == sido_value
    columns = [func.count(), func.min(p.price), func.avg(p.price), func.max(p.price),
               func.count().filter(in_sido), func.min(p.price).filter(in_sido),
               func.avg(p.price).filter(in_sido), func.max(p.price).filter(in_sido)]
    if station_price is not None:
        columns += [func.count().filter(p.price < station_price), func.count().filter(p.price == station_price),
                    func.count().filter(and_(in_sido, p.price < station_price)),
                    func.count().filter(and_(in_sido, p.price == station_price))]
    aggregate = (await session.execute(_published_points(product_code).with_only_columns(*columns))).one()
    nationwide = _summary("nationwide", "전국", *aggregate[0:4])
    sido = _summary("sido", sido_label, *aggregate[4:8])
    response["nationwide"], response["sido"] = nationwide, sido
    if prices:
        width, bins = price_histogram(prices)
        response["sigungu"] = {**_summary("sigungu", sigungu_label, len(prices), prices[0],
                                          sum(prices) / len(prices), prices[-1]),
                               "sufficient": len(prices) >= MINIMUM_SAMPLE, "bin_width": width,
                               "histogram": bins, "quantiles": price_quantiles(prices)}
    if station is not None:
        comparisons = []
        if station_price is not None:
            local = response["sigungu"]
            if local is not None:
                comparisons.append(_comparison({k: local[k] for k in (
                    "scope", "label", "station_count", "minimum_price", "average_price", "maximum_price")},
                    station_price, sum(1 for price in prices if price < station_price),
                    sum(1 for price in prices if price == station_price)))
            comparisons.append(_comparison(sido, station_price, aggregate[10], aggregate[11]))
            comparisons.append(_comparison(nationwide, station_price, aggregate[8], aggregate[9]))
        response["station"] = {"station_id": station.id, "name": station.name, "price": station_price,
                               "sells_product": station_price is not None, "products": station_products,
                               "comparisons": [row for row in comparisons if row is not None]}
    return response


def build_fuel_price_distribution_router(get_db: Callable[..., AsyncIterator[AsyncSession]]) -> APIRouter:
    router = APIRouter()

    @router.get("/transport/fuel/price-distribution", response_model=FuelPriceDistributionResponse,
                responses={404: {}, 422: {}})
    async def fuel_price_distribution(
        product_code: str = Query(default="B027", min_length=1, max_length=20, description="유종 코드 하나"),
        sido_value: str | None = Query(default=None, min_length=1, max_length=40, description="오피넷 시도 코드"),
        sigungu_value: str | None = Query(default=None, min_length=1, max_length=80, description="오피넷 시군구 코드"),
        station_id: int | None = Query(default=None, gt=0, le=2_147_483_647,
                                       description="지정하면 그 주유소의 시군구를 쓰고 시군구·시도·전국 대비 위치를 함께 반환"),
        session: AsyncSession = Depends(get_db),
    ) -> dict:
        """공개된 최신 유가 통계 세대의 시군구 가격 분포(구간·정렬 분위)와 시도·전국 최저/평균/최고.

        station_id를 주면 그 주유소의 같은 세대 가격으로 시군구·시도·전국 백분위와 등급을 계산한다.
        그 유종을 팔지 않거나 이번 세대에 가격이 없으면 station.price=null, comparisons=[]이다.
        표본이 minimum_sample 미만이면 sufficient=false이고 등급은 null이다.
        """
        if station_id is None and (sido_value is None or sigungu_value is None):
            raise HTTPException(status_code=422, detail="시도·시군구 또는 주유소를 지정해 주세요.")
        return await price_distribution(session, product_code=product_code.strip(),
                                        sido_value=sido_value.strip() if sido_value else None,
                                        sigungu_value=sigungu_value.strip() if sigungu_value else None,
                                        station_id=station_id)

    return router
