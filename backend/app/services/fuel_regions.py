"""지도는 성공한 공개 세대의 지역 요약만 읽는다. 원본 가격 집계는 하지 않는다."""
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelRegionSummary, FuelStation, FuelStatisticsPoint, FuelStatisticsState
from app.services.fuel_station_filters import OPINET, FuelStationFilters, published_points_with_station


async def regional_fuel_prices(session: AsyncSession, *, zoom: int, bounds: tuple,
                               sources: list[str], products: list[str], query: str | None,
                               filters: FuelStationFilters | None = None) -> list[dict]:
    if filters is not None and filters.active:
        return await _filtered_regional_fuel_prices(session, zoom=zoom, bounds=bounds, sources=sources,
                                                    products=products, query=query, filters=filters)
    region, state = FuelRegionSummary, FuelStatisticsState
    conditions = [region.scope == ("sigungu" if zoom >= 8 else "sido"),
                  region.longitude.between(bounds[0], bounds[2]),
                  region.latitude.between(bounds[1], bounds[3])]
    if sources:
        conditions.append(region.source.in_(sources))
    if products:
        conditions.append(region.product_code.in_(products))
    if query and query.strip():
        # 지역 카드는 전체 지역 통계다. 이름 검색으로 부분 표본의 평균을 만들지 않는다.
        conditions.append(region.label.icontains(query.strip(), autoescape=True))
    rows = (await session.scalars(select(region).join(state, and_(
        region.source == state.source, region.generated_at == state.generated_at,
    )).where(*conditions).order_by(region.region_key, region.product_code))).all()
    return [{"scope": row.scope, "region_key": row.region_key, "label": row.label,
             "source": row.source, "product_code": row.product_code,
             "longitude": row.longitude, "latitude": row.latitude,
             "average_price": row.average_price, "station_count": row.station_count} for row in rows]


async def _filtered_regional_fuel_prices(session: AsyncSession, *, zoom: int, bounds: tuple, sources: list[str],
                                         products: list[str], query: str | None, filters: FuelStationFilters) -> list[dict]:
    """공개 화면 필터가 켜지면 사전집계 지역 카드 대신 같은 공개 세대 point를 필터 조건으로 다시 묶는다.

    지역 전체(화면 밖 포함) 평균이라는 카드 의미는 같다. 위치는 필터를 통과한 주유소 좌표의 평균이며 그 위치가 화면 안인 지역만 낸다.
    상호·주소 검색은 사전집계 카드처럼 지역 이름 검색으로 다룬다.
    """
    if sources and OPINET not in sources:
        return []
    p, s = FuelStatisticsPoint, FuelStation
    sigungu = zoom >= 8
    keys = [s.sido_value] + ([s.sigungu_value] if sigungu else [])
    names = [func.max(s.sido_name).label("sido_name")] + ([func.max(s.sigungu_name).label("sigungu_name")] if sigungu else [])
    located = and_(p.longitude.between(-180, 180), p.latitude.between(-90, 90))
    conditions = [s.sido_value != "", *filters.station_conditions(), *filters.point_conditions()]
    if sigungu:
        conditions.append(s.sigungu_value != "")
    if products:
        conditions.append(p.product_code.in_(products))
    grouped = published_points_with_station().with_only_columns(
        *keys, *names, p.product_code, func.count().label("station_count"), func.avg(p.price).label("average_price"),
        func.avg(p.longitude).filter(located).label("longitude"), func.avg(p.latitude).filter(located).label("latitude"),
    ).where(*conditions).group_by(*keys, p.product_code).subquery()
    g = grouped.c
    statement = select(grouped).where(g.longitude.between(bounds[0], bounds[2]), g.latitude.between(bounds[1], bounds[3]))
    rows = (await session.execute(statement.order_by(g.sido_value, *( [g.sigungu_value] if sigungu else []), g.product_code))).mappings().all()
    result = []
    for row in rows:
        label = f"{row['sido_name'] or row['sido_value']} {row['sigungu_name'] or row['sigungu_value']}".strip() if sigungu             else row["sido_name"] or row["sido_value"]
        if query and query.strip() and query.strip().casefold() not in label.casefold():
            continue
        region_key = ":".join([OPINET, row["sido_value"]] + ([row["sigungu_value"]] if sigungu else []))
        result.append({"scope": "sigungu" if sigungu else "sido", "region_key": region_key, "label": label,
                       "source": OPINET, "product_code": row["product_code"],
                       "longitude": float(row["longitude"]), "latitude": float(row["latitude"]),
                       "average_price": float(row["average_price"]), "station_count": int(row["station_count"])})
    return result
