"""지도는 성공한 공개 세대의 지역 요약만 읽는다. 원본 가격 집계는 하지 않는다."""
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelRegionSummary, FuelStatisticsState


async def regional_fuel_prices(session: AsyncSession, *, zoom: int, bounds: tuple,
                               sources: list[str], products: list[str], query: str | None) -> list[dict]:
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
