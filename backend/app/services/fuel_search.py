"""MCP의 읽기 전용 유가 검색. 가격 전체를 Python으로 읽지 않는다."""
from __future__ import annotations

import math
from sqlalchemy import Float, String, and_, case, cast, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc, serialize_utc
from app.models import FuelStatisticsDaily, FuelStatisticsPoint, FuelStatisticsState, TransportCollectionState
from app.schemas import (
    FuelSearchCollection, FuelSearchProduct, FuelSearchRegion, FuelSearchResponse,
    FuelSearchStation, NearbyFuelQuery, RegionalFuelQuery,
)
from app.services.fuel_statistics import OPINET, _key
from app.services.transport_collection import FUEL_STALE_AFTER

PRODUCT_NAMES = {"B027": "휘발유", "B034": "고급휘발유", "D047": "경유", "C004": "등유", "K015": "LPG"}
EARTH_RADIUS_M = 6371008.8


async def begin_fuel_search(session: AsyncSession) -> None:
    if session.bind.dialect.name == "postgresql":
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL statement_timeout = '5000ms'"))


def distance_expression(latitude, longitude, origin_latitude: float, origin_longitude: float):
    """평균 지구 반지름의 대권 직선거리. 도로 주행거리가 아니다."""
    lat = cast(latitude, Float) * (math.pi / 180)
    lon = cast(longitude, Float) * (math.pi / 180)
    origin_lat = math.radians(origin_latitude)
    a = func.pow(func.sin((lat - origin_lat) / 2), 2) + (
        math.cos(origin_lat) * func.cos(lat) * func.pow(func.sin((lon - math.radians(origin_longitude)) / 2), 2)
    )
    bounded = case((a < 0, 0.0), (a > 1, 1.0), else_=a)
    return 2 * EARTH_RADIUS_M * func.asin(func.sqrt(bounded))


def radius_bounds(latitude: float, longitude: float, radius_m: int):
    delta = radius_m / EARTH_RADIUS_M
    lat_delta = math.degrees(delta)
    if abs(latitude) + lat_delta >= 90:
        return max(-90, latitude - lat_delta), min(90, latitude + lat_delta), 180.0
    lon_delta = math.degrees(math.asin(min(1, math.sin(delta) / math.cos(math.radians(latitude)))))
    return latitude - lat_delta, latitude + lat_delta, lon_delta


async def collection_metadata(session: AsyncSession) -> FuelSearchCollection:
    state = await session.get(FuelStatisticsState, OPINET)
    collection = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == OPINET))
    generation = serialize_utc(state.generated_at) if state else None
    success = serialize_utc(collection.last_success_at) if collection and collection.last_success_at else None
    return FuelSearchCollection(
        status="ready" if generation else "unavailable", reason=None if generation else "no_published_generation",
        generated_at=generation, last_success_at=success,
        update_pending=bool(success and (generation is None or success > generation)),
        stale=bool(generation and now_utc() - generation > FUEL_STALE_AFTER),
        last_attempt_failed=bool(collection and collection.last_error),
    )


def empty_products(codes, *, ready: bool):
    return {code: FuelSearchProduct(product_code=code, product_name=PRODUCT_NAMES[code],
            station_count=0 if ready else None, cheapest_station_count=0 if ready else None)
            for code in dict.fromkeys(codes)}


async def nearby_fuel(session: AsyncSession, query: NearbyFuelQuery) -> FuelSearchResponse:
    metadata = await collection_metadata(session)
    products = empty_products(query.product_codes, ready=metadata.status == "ready")
    if metadata.generated_at is not None:
        p = FuelStatisticsPoint
        south, north, lon_delta = radius_bounds(query.latitude, query.longitude, query.radius_m)
        longitude_conditions = p.longitude.between(query.longitude - lon_delta, query.longitude + lon_delta)
        if query.longitude - lon_delta < -180:
            longitude_conditions |= p.longitude >= query.longitude - lon_delta + 360
        if query.longitude + lon_delta > 180:
            longitude_conditions |= p.longitude <= query.longitude + lon_delta - 360
        distance = distance_expression(p.latitude, p.longitude, query.latitude, query.longitude)
        located = select(p.product_code, p.station_key, p.name, p.address, p.brand_name,
                         p.latitude, p.longitude, p.price, distance.label("distance_m")).where(
            p.source == OPINET, p.generated_at == metadata.generated_at,
            p.product_code.in_(products), p.price > 0,
            cast(p.price, String).not_in(("NaN", "Infinity", "-Infinity")),
            p.latitude.between(max(-90, south), min(90, north)), longitude_conditions,
            p.longitude.between(-180, 180),
        ).cte("located_fuel")
        candidates = select(located).where(located.c.distance_m <= query.radius_m).cte("radius_fuel")
        c = candidates.c
        totals = select(c.product_code, func.count().label("station_count"),
                        func.avg(c.price).label("average_price"), func.min(c.price).label("minimum_price"),
                        ).group_by(c.product_code).cte("radius_totals")
        t = totals.c
        cheapest = select(candidates,
            func.count().over(partition_by=c.product_code).label("tie_count"),
            func.row_number().over(partition_by=c.product_code,
                order_by=(c.distance_m, c.station_key)).label("rank"),
        ).join(totals, and_(c.product_code == t.product_code, c.price == t.minimum_price)).cte("radius_cheapest")
        rows = (await session.execute(select(totals, cheapest).join(cheapest,
            cheapest.c.product_code == t.product_code).where(cheapest.c.rank <= query.limit_per_product)
            .order_by(t.product_code, cheapest.c.rank))).mappings()
        for row in rows:
            product = products[row["product_code"]]
            product.station_count = row["station_count"]
            product.average_price = round(float(row["average_price"]), 2)
            product.minimum_price = float(row["minimum_price"])
            product.cheapest_station_count = row["tie_count"]
            product.truncated = row["tie_count"] > query.limit_per_product
            product.cheapest_stations.append(FuelSearchStation(**{
                key: row[key] for key in ("station_key", "name", "address", "brand_name", "latitude", "longitude", "price")
            }, distance_m=round(float(row["distance_m"]), 2)))
    return FuelSearchResponse(scope="radius", collection=metadata, products=list(products.values()),
                              latitude=query.latitude, longitude=query.longitude, radius_m=query.radius_m)


async def regional_fuel(session: AsyncSession, query: RegionalFuelQuery,
                        region: FuelSearchRegion | None = None) -> FuelSearchResponse:
    metadata = await collection_metadata(session)
    ready = metadata.status == "ready" and (query.scope == "nationwide" or (region and region.status == "resolved"))
    products = empty_products(query.product_codes, ready=bool(ready))
    if ready:
        key = "all" if query.scope == "nationwide" else _key(region.sido_value, region.sigungu_value)
        d, state = FuelStatisticsDaily, FuelStatisticsState
        distance = None
        if query.latitude is not None:
            lat = d.metrics_json["cheapest_station"]["latitude"].as_float()
            lon = d.metrics_json["cheapest_station"]["longitude"].as_float()
            distance = case((and_(lat.between(-90, 90), lon.between(-180, 180)),
                distance_expression(lat, lon, query.latitude, query.longitude)), else_=None)
        statement = select(d.product_code, d.label, d.metrics_json, distance.label("distance_m") if distance is not None else literal(None).label("distance_m")).join(state, and_(
            d.source == state.source, d.generated_at == state.generated_at, d.day == state.day,
        )).where(d.source == OPINET, d.scope == query.scope, d.scope_key == key, d.product_code.in_(products))
        for row in (await session.execute(statement)).mappings():
            metrics = row["metrics_json"]
            product = products[row["product_code"]]
            product.station_count = metrics["station_count"]
            product.average_price = metrics["average_price"]
            product.minimum_price = metrics["minimum_price"]
            product.cheapest_station_count = metrics["cheapest_station_count"]
            product.truncated = metrics["cheapest_station_count"] > 1
            if metrics.get("cheapest_station"):
                product.cheapest_stations = [FuelSearchStation(**metrics["cheapest_station"],
                    price=metrics["minimum_price"], distance_m=round(float(row["distance_m"]), 2) if row["distance_m"] is not None else None)]
            if region:
                region.label = row["label"]
    return FuelSearchResponse(scope=query.scope, collection=metadata, products=list(products.values()),
                              region=region, latitude=query.latitude, longitude=query.longitude)
