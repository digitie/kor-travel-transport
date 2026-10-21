"""성공한 수집의 최신 가격을 한 번만 집계하고 작은 7일 일별 통계를 보관한다."""
from __future__ import annotations

import json
import logging
import math
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Float, and_, cast, delete, func, insert, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc
from app.models import (
    FuelLatestPrice, FuelStation, FuelStatisticsDaily, FuelStatisticsPoint,
    FuelStatisticsState, RestAreaFuelPrice, TransportCollectionState,
)

OPINET = "opinet_browser"
HIGHWAY = "krex_rest_area_fuel"
SCOPES = {"nationwide", "sido", "sigungu", "highways", "highway", "highway_direction"}
logger = logging.getLogger(__name__)
_viewport_cache: OrderedDict[tuple, tuple[float, list[dict]]] = OrderedDict()


async def lock_fuel_statistics(session: AsyncSession, source: str) -> None:
    if session.bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 420061 if source == OPINET else 420062})


def _key(*values: str) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


class _Accumulator:
    def __init__(self, label: str) -> None:
        self.label = label
        self.count = 0
        self.total = 0.0
        self.squares = 0.0
        self.minimum = math.inf
        self.maximum = 0.0
        self.cheapest: dict | None = None
        self.cheapest_count = 0

    def add(self, point: dict) -> None:
        price = float(point["price"])
        self.count += 1
        self.total += price
        self.squares += price * price
        self.maximum = max(self.maximum, price)
        if price < self.minimum:
            self.minimum, self.cheapest_count = price, 1
            self.cheapest = {k: point[k] for k in ("station_key", "name", "address", "longitude", "latitude")}
        elif price == self.minimum:
            self.cheapest_count += 1
            if self.cheapest is not None and point["station_key"] < self.cheapest["station_key"]:
                self.cheapest = {k: point[k] for k in ("station_key", "name", "address", "longitude", "latitude")}

    def metrics(self) -> dict:
        average = self.total / self.count
        return _metrics(self.count, average, self.minimum, self.maximum,
                        self.squares / self.count, self.cheapest, self.cheapest_count)


def _metrics(count: int, average: float, minimum: float, maximum: float,
             mean_square: float, cheapest: dict | None, cheapest_count: int) -> dict:
    return {
        "station_count": count, "average_price": round(average, 2),
        "minimum_price": minimum, "maximum_price": maximum,
        "price_spread": round(maximum - minimum, 2),
        "standard_deviation": round(math.sqrt(max(0, mean_square - average * average)), 2),
        "saving_50l": round((average - minimum) * 50, 2),
        "cheapest_station": cheapest, "cheapest_station_count": cheapest_count,
    }


async def publish_fuel_statistics(session: AsyncSession, source: str, collected_at: datetime) -> None:
    """호출자의 트랜잭션/원천 잠금을 공유한다. 원본 이력은 읽지 않고 배치 500개만 메모리에 둔다."""
    await session.flush()
    state = await session.get(FuelStatisticsState, source)
    stamp = serialize_utc(collected_at)
    if state is not None and serialize_utc(state.generated_at) >= stamp:
        return
    day = stamp.astimezone(ZoneInfo("Asia/Seoul")).date()
    await session.execute(delete(FuelStatisticsPoint).where(FuelStatisticsPoint.source == source))
    groups: dict[tuple[str, str, str], _Accumulator] = {}
    pending: list[dict] = []

    async def consume(point: dict, scopes: list[tuple[str, str, str]]) -> None:
        pending.append(point)
        for scope, scope_key, label in scopes:
            key = (scope, scope_key, point["product_code"])
            group = groups.get(key)
            if group is None:
                group = groups[key] = _Accumulator(label)
            group.add(point)
        if len(pending) >= 500:
            await session.execute(insert(FuelStatisticsPoint), pending)
            pending.clear()

    if source == OPINET:
        statement = select(
            FuelStation.id, FuelStation.name, FuelStation.address, FuelStation.brand_name,
            FuelStation.longitude, FuelStation.latitude, FuelStation.sido_value, FuelStation.sido_name,
            FuelStation.sigungu_value, FuelStation.sigungu_name, FuelLatestPrice.product_code, FuelLatestPrice.price,
        ).join(FuelLatestPrice, FuelLatestPrice.fuel_station_id == FuelStation.id).where(
            FuelStation.source == source, FuelLatestPrice.price > 0,
        ).order_by(FuelStation.id, FuelLatestPrice.product_code).execution_options(yield_per=500)
        stream = await session.stream(statement)
        async for row in stream:
            point = {"source": source, "station_key": str(row.id), "generated_at": stamp,
                     "name": row.name, "address": row.address, "brand_name": row.brand_name,
                     "longitude": row.longitude, "latitude": row.latitude,
                     "product_code": row.product_code, "price": float(row.price)}
            scopes = [("nationwide", "all", "전국")]
            if row.sido_value:
                scopes.append(("sido", _key(row.sido_value), row.sido_name or "시도 미제공"))
            if row.sido_value and row.sigungu_value:
                scopes.append(("sigungu", _key(row.sido_value, row.sigungu_value),
                               f"{row.sido_name or row.sido_value} {row.sigungu_name or row.sigungu_value}".strip()))
            await consume(point, scopes)
    elif source == HIGHWAY:
        stream = await session.stream(select(RestAreaFuelPrice).where(
            RestAreaFuelPrice.source == source, RestAreaFuelPrice.last_seen_at == collected_at,
        ).order_by(RestAreaFuelPrice.service_area_code).execution_options(yield_per=500))
        async for row in stream.scalars():
            route = row.route_name or "노선 미제공"
            route_key = row.route_code or route
            direction = row.direction or "방향 미제공"
            for product, price in (("B027", row.gasoline_price), ("D047", row.diesel_price), ("K015", row.lpg_price)):
                if price is None or price <= 0:
                    continue
                await consume({"source": source, "station_key": row.service_area_code, "generated_at": stamp,
                               "name": row.service_area_name or row.service_area_code, "address": row.address,
                               "brand_name": row.oil_company, "longitude": None, "latitude": None,
                               "product_code": product, "price": float(price)}, [
                    ("highways", "all", "고속도로 전체"),
                    ("highway", _key(route_key), route),
                    ("highway_direction", _key(route_key, direction), f"{route} · {direction}"),
                ])
    else:
        raise ValueError("지원하지 않는 유가 원천입니다.")
    if pending:
        await session.execute(insert(FuelStatisticsPoint), pending)
    # 같은 KST 일자는 마지막 정상 수집만 남긴다. 사라진 범주의 당일 값도 남기지 않는다.
    await session.execute(delete(FuelStatisticsDaily).where(
        FuelStatisticsDaily.source == source,
        or_(FuelStatisticsDaily.day == day, FuelStatisticsDaily.day < day - timedelta(days=6)),
    ))
    rows = [{"source": source, "scope": scope, "scope_key": key, "product_code": product,
             "day": day, "generated_at": stamp, "label": group.label, "metrics_json": group.metrics()}
            for (scope, key, product), group in groups.items()]
    for offset in range(0, len(rows), 250):
        await session.execute(insert(FuelStatisticsDaily), rows[offset:offset + 250])
    if state is None:
        session.add(FuelStatisticsState(source=source, generated_at=stamp, day=day))
    else:
        state.generated_at, state.day = stamp, day
    await session.flush()


async def try_publish_fuel_statistics(session: AsyncSession, source: str, collected_at: datetime) -> None:
    # 통계 실패가 오래 걸린 원본 수집 성공을 취소하지 않게 savepoint로 격리한다.
    try:
        async with session.begin_nested():
            await publish_fuel_statistics(session, source, collected_at)
    except Exception as exc:
        logger.warning("fuel statistics publication deferred source=%s error=%s", source, type(exc).__name__)


async def fuel_statistics_page(session: AsyncSession, scope: str, product_code: str,
                               scope_key: str | None = None) -> dict:
    source = OPINET if scope in {"nationwide", "sido", "sigungu"} else HIGHWAY
    current = (await session.execute(select(FuelStatisticsDaily).join(FuelStatisticsState, and_(
        FuelStatisticsDaily.source == FuelStatisticsState.source,
        FuelStatisticsDaily.day == FuelStatisticsState.day,
        FuelStatisticsDaily.generated_at == FuelStatisticsState.generated_at,
    )).where(FuelStatisticsDaily.source == source, FuelStatisticsDaily.scope == scope,
             FuelStatisticsDaily.product_code == product_code).order_by(FuelStatisticsDaily.scope_key))).scalars().all()
    current_keys = {row.scope_key for row in current}
    selected_key = scope_key if scope_key in current_keys else (current[0].scope_key if current else None)
    history = []
    if current and selected_key is not None:
        end = current[0].day
        rows = (await session.execute(select(FuelStatisticsDaily).where(
            FuelStatisticsDaily.source == source, FuelStatisticsDaily.scope == scope,
            FuelStatisticsDaily.product_code == product_code, FuelStatisticsDaily.scope_key == selected_key,
            FuelStatisticsDaily.day.between(end - timedelta(days=6), end),
            FuelStatisticsDaily.generated_at <= current[0].generated_at,
        ).order_by(FuelStatisticsDaily.day))).scalars()
        history = [{"day": row.day, "generated_at": row.generated_at,
                    "average_price": row.metrics_json["average_price"],
                    "station_count": row.metrics_json["station_count"]} for row in rows]
    state = await session.get(FuelStatisticsState, source)
    collection = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == source))
    # 집계 SELECT와 뒤의 상태 SELECT 사이 발행이 커밋되어도 헤더는 실제 반환 행의 세대다.
    generated_at = current[0].generated_at if current else state.generated_at if state else None
    pending = bool(collection and collection.last_success_at and (
        generated_at is None or serialize_utc(collection.last_success_at) > serialize_utc(generated_at)))
    return {"scope": scope, "product_code": product_code, "history_scope_key": selected_key,
            "generated_at": generated_at, "update_pending": pending,
            "items": [{"scope_key": row.scope_key, "label": row.label, "generated_at": row.generated_at,
                       **row.metrics_json} for row in current], "history": history}


async def viewport_fuel_statistics(session: AsyncSession, bounds: tuple[float, float, float, float],
                                   sources: list[str], products: list[str], query: str | None) -> list[dict]:
    """현재 화면 전체를 한 SQL로 집계한다. marker limit/cluster/원본 이력과 무관하다."""
    state = await session.get(FuelStatisticsState, OPINET)
    if state is None or (sources and OPINET not in sources):
        return []
    key = (session.bind, serialize_utc(state.generated_at), bounds, tuple(sorted(products)), (query or "").strip())
    cached = _viewport_cache.get(key)
    if cached and cached[0] > time.monotonic():
        _viewport_cache.move_to_end(key)
        return cached[1]
    p = FuelStatisticsPoint
    conditions = [p.source == OPINET, p.longitude.between(bounds[0], bounds[2]),
                  p.latitude.between(bounds[1], bounds[3])]
    if products:
        conditions.append(p.product_code.in_(products))
    if query and query.strip():
        conditions.append(or_(*(column.icontains(query.strip(), autoescape=True)
                                for column in (p.name, p.brand_name, p.address))))
    # 가격·코드만 물질화해 큰 문자열 정렬과 전체 행 row_number를 피한다.
    candidates = select(p.product_code, p.price, p.station_key).join(FuelStatisticsState, and_(
        p.source == FuelStatisticsState.source, p.generated_at == FuelStatisticsState.generated_at,
    )).where(*conditions).cte("fuel_candidates")
    c = candidates.c
    aggregates = select(
        c.product_code, func.count().label("count"), func.avg(c.price).label("average"),
        func.min(c.price).label("minimum"), func.max(c.price).label("maximum"),
        func.avg(cast(c.price, Float) * cast(c.price, Float)).label("mean_square"),
    ).group_by(c.product_code).cte("fuel_aggregates")
    a = aggregates.c
    cheapest = select(c.product_code, func.min(c.station_key).label("station_key"),
                      func.count().label("cheapest_count")).join(aggregates, and_(
        c.product_code == a.product_code, c.price == a.minimum,
    )).group_by(c.product_code).cte("fuel_cheapest")
    rows = (await session.execute(select(
        a, cheapest.c.cheapest_count, p.generated_at,
        p.station_key, p.name, p.address, p.longitude, p.latitude,
    ).join(cheapest, cheapest.c.product_code == a.product_code).join(p, and_(
        p.source == OPINET, p.product_code == a.product_code, p.station_key == cheapest.c.station_key,
    )).order_by(a.product_code))).mappings()
    result = [{"product_code": row["product_code"], "generated_at": row["generated_at"],
               **_metrics(row["count"], float(row["average"]), float(row["minimum"]), float(row["maximum"]),
                          float(row["mean_square"]), {name: row[name] for name in
                          ("station_key", "name", "address", "longitude", "latitude")}, row["cheapest_count"])}
              for row in rows]
    _viewport_cache[key] = (time.monotonic() + 10, result)
    _viewport_cache.move_to_end(key)
    while len(_viewport_cache) > 64:
        _viewport_cache.popitem(last=False)
    return result
