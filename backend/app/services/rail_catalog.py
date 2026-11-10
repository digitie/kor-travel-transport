"""철도 코드 카탈로그의 응답 전용 투영. 원천 파싱은 기존 KRIC 라이브러리를 사용한다."""

from kric import parse_station_file_facilities
from sqlalchemy import select

from app.core.time_utils import now_utc
from app.models import KricStationCode, RailStationReference
from app.schemas import MetroStationCatalog, TransportPlaceMapItem


async def metro_station_catalog(session) -> MetroStationCatalog:
    code, place = KricStationCode.__table__.c, RailStationReference.__table__.c
    rows = (await session.execute(select(
        code.id, code.operator_code, code.line_code, code.station_code, code.operator_name,
        code.line_name, code.station_name, code.last_seen_at, place.longitude, place.latitude,
        place.road_address, place.lot_address, place.station_phone_number, place.raw_item_json,
    ).select_from(KricStationCode.__table__.outerjoin(
        RailStationReference.__table__, code.rail_station_id == place.id,
    )).where(code.active.is_(True)).order_by(code.operator_code, code.line_code, code.station_code))).mappings()
    return MetroStationCatalog(generated_at=now_utc(), items=[TransportPlaceMapItem(
        id=row["id"], kind="rail_station", source="kric_station_codes",
        provider_id=f"{row['operator_code']}/{row['line_code']}/{row['station_code']}",
        name=row["station_name"], subtitle=row["operator_name"], line_names=[row["line_name"]],
        longitude=row["longitude"], latitude=row["latitude"],
        address=row["road_address"] or row["lot_address"], phone=row["station_phone_number"],
        facilities=list(parse_station_file_facilities(row["raw_item_json"] or {})), updated_at=row["last_seen_at"],
    ) for row in rows])
