"""공개 유가 세대로 시군구 가격 분포와 주유소의 상대 위치를 계산한다.

원천은 지도 통계와 같은 공개 세대(`fuel_statistics_points` + `fuel_statistics_states`)다.
시군구 한 곳의 가격(수십~수백 행)만 내려받아 구간·분위를 Python에서 만들고, 시도·전국은
한 SQL의 집계(count/min/avg/max와 가격 이하 개수)로 읽는다. 새 테이블이나 사전집계는 두지
않는다(2026-11-22 측정: 아래 문서 docs/fuel-statistics.md "시군구 가격 분포").
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field, replace
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc
from app.models import FuelStation, FuelStatisticsPoint, FuelStatisticsState, TransportCollectionState
from app.schemas import FuelPriceDistributionResponse
from app.services.fuel_station_filters import (
    FuelStationFilters, fuel_station_filter_params, point_station_id, sido_display_name, station_for_point,
)

OPINET = "opinet_browser"
# 표본이 이보다 적으면 분포·등급을 만들지 않는다(1~2곳의 "최저/최고"는 비교가 아니다).
MINIMUM_SAMPLE = 3
QUANTILE_PERCENTS = tuple(range(0, 101, 10))
HISTOGRAM_TARGET_BINS = 10
VIEWPORT_SIGUNGU_LIMIT = 40
_sigungu_cache: OrderedDict[tuple, tuple[float, tuple[list[dict], int]]] = OrderedDict()
# 공개 세대·유종·필터별 전국 가격 색인. 세대는 공개 뒤 바뀌지 않는다(새 세대는 새 키). 주유소 행 조건(셀프·상표)이
# 세대 안에서 바뀔 수 있어 TTL로 오래된 조건 결과를 버린다. 한 항목은 전국 한 유종 약 1.1만 가격이다.
PRICE_INDEX_SECONDS = 600
PRICE_INDEX_SIZE = 8
_price_index_cache: OrderedDict[tuple, tuple[float, "_PriceIndex"]] = OrderedDict()

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


def _published_points(generated_at, product_code: str | None = None, filters: FuelStationFilters | None = None):
    """한 공개 세대(generated_at 고정)의 양수 가격 point와 주유소. 응답 안 여러 SELECT가 같은 세대를 읽는다.

    조인은 오피넷 point 키를 정수 주유소 id로 바꿔 기본키로 찾는다(`station_for_point`, 고속도로 point는 NULL이라 빠진다).
    """
    p = FuelStatisticsPoint
    statement = select(p).join(FuelStation, station_for_point(p)).where(
        p.source == OPINET, p.generated_at == generated_at, p.price > 0)
    if product_code is not None:
        statement = statement.where(p.product_code == product_code)
    if filters is not None and filters.active:
        statement = statement.where(*filters.station_conditions(), *filters.point_conditions())
    return statement


@dataclass
class _PriceIndex:
    """한 세대·유종·필터의 전국 가격(오름차순)을 시도·시군구로도 나눠 둔다. 분포·백분위는 이것만으로 계산한다."""
    national: list[float] = field(default_factory=list)
    sido: dict[str, list[float]] = field(default_factory=dict)
    sigungu: dict[tuple[str, str], list[float]] = field(default_factory=dict)
    names: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)


async def _price_index(session: AsyncSession, generated_at, product_code: str,
                       filters: FuelStationFilters | None) -> _PriceIndex:
    """전국 가격을 한 번 읽어(시도·시군구 코드와 함께) 세대·유종·필터별로 프로세스에 둔다.

    예전에는 요청마다 시군구 가격 SELECT와 전국·시도 집계 SELECT를 따로 보냈고, 앞의 것이 새 세대의 "1행" 추정으로
    중첩 루프에 빠져 운영에서 평균 13.8초였다(2026-11-23 pg_stat_statements). 지금은 한 SELECT(정수 조인)로 읽고
    같은 세대의 다음 요청은 SQL 없이 답한다.
    """
    key = (session.bind, serialize_utc(generated_at), product_code, filters.key() if filters is not None else ())
    cached = _price_index_cache.get(key)
    if cached and cached[0] > time.monotonic():
        _price_index_cache.move_to_end(key)
        return cached[1]
    p, s = FuelStatisticsPoint, FuelStation
    rows = (await session.execute(_published_points(generated_at, product_code, filters).with_only_columns(
        s.sido_value, s.sigungu_value, s.sido_name, s.sigungu_name, p.price,
    ).order_by(p.price))).all()
    index = _PriceIndex()
    for row in rows:
        price = float(row.price)
        index.national.append(price)
        index.sido.setdefault(row.sido_value, []).append(price)
        region = (row.sido_value, row.sigungu_value)
        index.sigungu.setdefault(region, []).append(price)
        index.names.setdefault(region, (sido_display_name(row.sido_value, row.sido_name),
                                        row.sigungu_name or row.sigungu_value))
    _price_index_cache[key] = (time.monotonic() + PRICE_INDEX_SECONDS, index)
    _price_index_cache.move_to_end(key)
    while len(_price_index_cache) > PRICE_INDEX_SIZE:
        _price_index_cache.popitem(last=False)
    return index


def _sorted_summary(scope: str, label: str, prices: list[float]) -> dict | None:
    return _summary(scope, label, len(prices), prices[0], sum(prices) / len(prices), prices[-1]) if prices else None


def _below_equal(prices: list[float], price: float) -> tuple[int, int]:
    below = bisect.bisect_left(prices, price)
    return below, bisect.bisect_right(prices, price) - below


def viewport_sigungu_statement(generated_at, bounds: tuple[float, float, float, float], products: list[str],
                               query: str | None, limit: int, filters: FuelStationFilters | None):
    """화면 안 주유소를 시군구로 묶는 문장. 회귀 시험이 이 문장의 실행 계획을 그대로 검사한다."""
    p, s = FuelStatisticsPoint, FuelStation
    conditions = [p.source == OPINET, p.generated_at == generated_at, p.price > 0,
                  p.longitude.between(bounds[0], bounds[2]), p.latitude.between(bounds[1], bounds[3])]
    if products:
        conditions.append(p.product_code.in_(products))
    if query and query.strip():
        conditions.append(or_(*(column.icontains(query.strip(), autoescape=True)
                                for column in (p.name, p.brand_name, p.address))))
    # 화면 안 주유소 id를 먼저 한 번씩만 뽑고(유종 행 중복 제거) 그다음 시군구로 묶는다.
    # 전국 화면(약 3.2만 가격 행)에서 가격 행 전체를 주유소와 조인해 count(distinct)하는 것보다 싸다.
    station_id = point_station_id(p).label("station_id")
    visible = select(station_id).where(*conditions)
    if filters is not None and filters.active:
        # 공개 화면 필터(셀프·상표 등)는 주유소 행 조건, 화면 최저가 상한은 가격 조건이다.
        visible = visible.join(s, station_for_point(p)).where(*filters.station_conditions(), *filters.point_conditions())
    visible = visible.distinct().subquery()
    # 이름은 묶음 키가 아니다. 같은 시군구라도 시도 이름이 행마다 달라(짧은/정식) 한 시군구가 두 줄로 나뉘었다.
    return select(
        s.sido_value, func.max(s.sido_name).label("sido_name"), s.sigungu_value,
        func.max(s.sigungu_name).label("sigungu_name"), func.count().label("station_count"),
        func.count().over().label("region_total"),
    ).select_from(visible).join(s, s.id == visible.c.station_id).where(
        s.sido_value != "", s.sigungu_value != "",
    ).group_by(s.sido_value, s.sigungu_value).order_by(
        func.count().desc(), s.sido_value, s.sigungu_value,
    ).limit(limit)


async def viewport_sigungu(session: AsyncSession, bounds: tuple[float, float, float, float],
                           sources: list[str], products: list[str], query: str | None,
                           limit: int = VIEWPORT_SIGUNGU_LIMIT, filters: FuelStationFilters | None = None) -> tuple[list[dict], int]:
    """현재 화면 안 공개 세대 주유소를 시군구로 묶어 주유소가 많은 순으로 돌려준다.

    경계 폴리곤이 아니라 화면에 실제로 보이는 주유소 기준이다(지도 통계와 같은 모집단).
    """
    if sources and OPINET not in sources:
        return [], 0
    published = await session.get(FuelStatisticsState, OPINET)
    if published is None:
        return [], 0
    key = (session.bind, serialize_utc(published.generated_at), bounds, tuple(sorted(products)), (query or "").strip(), limit,
           filters.key() if filters is not None else ())
    cached = _sigungu_cache.get(key)
    if cached and cached[0] > time.monotonic():
        _sigungu_cache.move_to_end(key)
        return cached[1]
    grouped = viewport_sigungu_statement(published.generated_at, bounds, products, query, limit, filters)
    rows = (await session.execute(grouped)).mappings().all()
    total = int(rows[0]["region_total"]) if rows else 0
    result = ([{"sido_value": row["sido_value"], "sido_name": sido_display_name(row["sido_value"], row["sido_name"]),
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
                             sigungu_value: str | None, station_id: int | None,
                             filters: FuelStationFilters | None = None) -> dict:
    # 화면 최저가 상한(near_min)은 화면이 있는 조회에만 뜻이 있다. 분포에는 주유소 행 조건만 적용한다.
    filters = replace(filters, near_min=None, price_ceiling=None, ceiling_product=None) if filters else None
    p, s = FuelStatisticsPoint, FuelStation
    state = await session.get(FuelStatisticsState, OPINET)
    station = None
    if station_id is not None:
        station = await session.get(FuelStation, station_id)
        if station is None or station.source != OPINET:
            raise HTTPException(status_code=404, detail="오피넷 주유소만 지역 가격 비교를 제공합니다.")
        sido_value, sigungu_value = station.sido_value, station.sigungu_value
        if not sido_value or not sigungu_value:
            raise HTTPException(status_code=404, detail="지역 정보가 없는 주유소입니다.")
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
        "filters_applied": filters.labels() if filters else [],
    }
    if generated_at is None:
        return response
    index = await _price_index(session, generated_at, product_code, filters)
    prices = index.sigungu.get((sido_value, sigungu_value), [])
    names = index.names.get((sido_value, sigungu_value))
    if station is not None:
        response["sido_name"] = sido_display_name(sido_value, station.sido_name)
    elif names is not None:
        response["sido_name"], response["sigungu_name"] = names
    if response["sido_name"] is None or response["sigungu_name"] is None:
        row = (await session.execute(select(s.sido_name, s.sigungu_name).where(
            s.source == OPINET, s.sido_value == sido_value, s.sigungu_value == sigungu_value,
        ).limit(1))).first()
        if row is None:
            raise HTTPException(status_code=404, detail="해당 시군구의 주유소가 없습니다.")
        response["sido_name"] = response["sido_name"] or sido_display_name(sido_value, row.sido_name)
        response["sigungu_name"] = response["sigungu_name"] or row.sigungu_name
    sido_label = response["sido_name"] or sido_value
    sigungu_label = response["sigungu_name"] or sigungu_value
    station_price = None
    station_products: list[str] = []
    if station is not None:
        # 기본키 앞부분(source, station_key)으로 이 주유소의 point만 읽고 세대는 여기서 고른다. 세대 조건을 SQL에 넣으면
        # 통계에 없는 새 세대를 "1행"으로 추정해 세대 색인으로 3만 행을 훑는 계획이 나왔다.
        station_rows = (await session.execute(select(p.product_code, p.price, p.generated_at).where(
            p.source == OPINET, p.station_key == str(station.id), p.price > 0,
        ))).all()
        current = [row for row in station_rows if serialize_utc(row.generated_at) == serialize_utc(generated_at)]
        station_products = sorted(row.product_code for row in current)
        station_price = next((float(row.price) for row in current if row.product_code == product_code), None)
    nationwide = _sorted_summary("nationwide", "전국", index.national)
    sido_prices = index.sido.get(sido_value, [])
    sido = _sorted_summary("sido", sido_label, sido_prices)
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
            comparisons.append(_comparison(sido, station_price, *_below_equal(sido_prices, station_price)))
            comparisons.append(_comparison(nationwide, station_price, *_below_equal(index.national, station_price)))
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
        filters: FuelStationFilters = Depends(fuel_station_filter_params),
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
                                        station_id=station_id, filters=filters)

    return router
