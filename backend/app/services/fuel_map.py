"""유가 지도 전용 PostgreSQL JSON 투영. 최종 Pydantic 검증은 API가 그대로 수행한다.

5천 장소/2만5천 가격을 Python 행·dict·datetime으로 반복 변환하지 않고 DB의 집합 연산으로
읽는다. 원본 JSON이나 provider I/O는 없으며 기존 필드·유종 순서·UTC·NULL 판정을 유지한다.
"""

from sqlalchemy import JSON, Text, case, cast, func, literal, select
from sqlalchemy.dialects.postgresql import aggregate_order_by, array

from app.models import FuelLatestPrice


def fuel_map_items_statement(station_query):
    stations = station_query.cte("selected_fuel_stations").prefix_with("MATERIALIZED")
    p = FuelLatestPrice

    def timestamp(column):
        return case(
            (
                column.is_not(None),
                func.to_char(
                    func.timezone("UTC", column), 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
                ),
            ),
            else_=None,
        )

    code = p.product_code.collate("C")
    prices = (
        select(
            p.fuel_station_id,
            func.json_agg(
                aggregate_order_by(
                    func.json_build_object(
                        "product_code",
                        p.product_code,
                        "price",
                        p.price,
                        "provider_updated_at",
                        timestamp(p.provider_updated_at),
                        "observed_at",
                        timestamp(p.observed_at),
                        "collected_at",
                        timestamp(p.collected_at),
                    ),
                    code,
                )
            ).label("prices"),
            func.count().filter(p.product_code == "B027").label("has_regular"),
            func.max(p.price).filter(p.product_code == "B027").label("regular_price"),
            func.array_agg(aggregate_order_by(p.price, code)).label("ordered_prices"),
            func.array_agg(aggregate_order_by(p.product_code, code)).label(
                "ordered_codes"
            ),
        )
        .where(p.fuel_station_id.in_(select(stations.c.id)))
        .group_by(p.fuel_station_id)
        .cte("selected_fuel_prices")
    )
    latest = case(
        (prices.c.has_regular > 0, prices.c.regular_price),
        else_=prices.c.ordered_prices[1],
    )
    product = case(
        (prices.c.has_regular > 0, literal("B027")), else_=prices.c.ordered_codes[1]
    )
    s = stations.c
    facilities = func.array_remove(
        array(
            [
                case((s[field].is_(True), literal(label)), else_=None)
                for field, label in [
                    ("is_self", "셀프"),
                    ("is_24h", "24시간"),
                    ("has_carwash", "세차"),
                    ("has_maintenance", "정비"),
                    ("has_cvs", "편의점"),
                ]
            ]
        ),
        None,
    )
    item = func.json_build_object(
        "id",
        s.id,
        "kind",
        "fuel_station",
        "source",
        s.source,
        "name",
        s.name,
        "longitude",
        s.longitude,
        "latitude",
        s.latitude,
        "subtitle",
        s.address,
        "brand_name",
        s.brand_name,
        "brand_code",
        s.brand_code,
        "latest_price",
        latest,
        "price_product_code",
        product,
        "address",
        s.address,
        "prices",
        func.coalesce(prices.c.prices, cast(literal("[]"), JSON)),
        "phone",
        s.phone,
        "facilities",
        facilities,
        "updated_at",
        timestamp(s.last_seen_at),
    )
    return select(
        func.coalesce(
            func.json_agg(aggregate_order_by(item, s.last_seen_at.desc(), s.id.desc())),
            cast(literal("[]"), JSON),
        ).cast(Text),
        func.count(),
    ).select_from(stations.outerjoin(prices, prices.c.fuel_station_id == s.id))
