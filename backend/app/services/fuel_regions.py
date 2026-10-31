"""낮은 축척의 행정구역별 유가. 화면/marker limit에 잘린 표본을 평균내지 않는다."""
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelLatestPrice, FuelStation


async def regional_fuel_prices(session: AsyncSession, *, zoom: int, bounds: tuple,
                               sources: list[str], products: list[str], query: str | None) -> list[dict]:
    station, price = FuelStation, FuelLatestPrice
    district = zoom >= 8
    keys = [station.source, station.sido_value]
    if district:
        keys.append(station.sigungu_value)
    located = and_(station.latitude.between(-90, 90), station.longitude.between(-180, 180))
    conditions = [station.sido_value != "", price.price > 0]
    if district:
        conditions.append(station.sigungu_value != "")
    if sources:
        conditions.append(station.source.in_(sources))
    if products:
        conditions.append(price.product_code.in_(products))
    if query and query.strip():
        conditions.append(or_(*(c.icontains(query.strip(), autoescape=True)
                                for c in (station.name, station.brand_name, station.address))))
    rows = (await session.execute(select(
        *keys, price.product_code, func.max(station.sido_name).label("sido"),
        func.max(station.sigungu_name).label("sigungu"),
        func.avg(case((located, station.longitude))).label("longitude"), func.avg(case((located, station.latitude))).label("latitude"),
        func.avg(price.price).label("average_price"), func.count().label("station_count"),
    ).join(price, price.fuel_station_id == station.id).where(*conditions)
      .group_by(*keys, price.product_code).order_by(*keys, price.product_code))).mappings().all()
    return [{"scope": "sigungu" if district else "sido",
             "region_key": ":".join(str(r[k.key]) for k in keys),
             "label": f"{r['sido']} {r['sigungu']}" if district else r["sido"],
             "source": r["source"], "product_code": r["product_code"],
             "longitude": r["longitude"], "latitude": r["latitude"],
             "average_price": r["average_price"], "station_count": r["station_count"]}
            for r in rows if r["longitude"] is not None and r["latitude"] is not None and bounds[0] <= r["longitude"] <= bounds[2]
            and bounds[1] <= r["latitude"] <= bounds[3]]
