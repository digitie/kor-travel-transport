"""저장된 KRIC 시간표를 여행자에게 제공한다. KRIC 네트워크 요청은 하지 않는다."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc, to_seoul
from app.models import KricStationCode, KricTimetableSnapshot, RailServiceDay, RailStationReference
from app.schemas import RailDepartureItem, RailTimetableItem, RailTimetableResponse
from app.services.kric_collection import aware


async def stored_rail_timetables(session: AsyncSession, places: list[RailStationReference], day_code: str | None, *, summary_only: bool = False) -> RailTimetableResponse:
    now = now_utc()
    local = to_seoul(now)
    basis = "selected_period"
    if day_code is None:
        # 0~4시의 00시 표기는 전일 운행의 연장인지 확인되지 않았다. 날짜를 추정하지 않는다.
        if local.hour < 5:
            basis = "overnight_unresolved"
        else:
            calendar = await session.get(RailServiceDay, local.date())
            if calendar is None or now - aware(calendar.verified_at) > timedelta(hours=48):
                basis = "calendar_unavailable"
            else:
                basis = "calendar"
                day_code = calendar.day_code
    codes = (await session.scalars(select(KricStationCode).where(KricStationCode.active.is_(True)))).all()
    linked = {row.rail_station_id: row for row in codes if row.rail_station_id is not None}
    names = {(row.operator_code, row.line_code, row.station_code): row.station_name for row in codes}
    station_ids = [linked[place.id].id for place in places if place.id in linked]
    snapshots = {row.station_id: row for row in (await session.scalars(select(KricTimetableSnapshot).where(
        KricTimetableSnapshot.station_id.in_(station_ids), KricTimetableSnapshot.day_code == day_code,
    ))).all()} if day_code is not None else {}
    result = []
    for place in places:
        code = linked.get(place.id)
        snapshot = snapshots.get(code.id) if code else None
        item = RailTimetableItem(place_id=place.id, station_name=place.station_name or "이름 없는 역",
            line_name=place.operating_line_name, status="unlinked" if not code else "day_unresolved" if day_code is None else "stored" if snapshot else "not_collected")
        if snapshot and code:
            item.collected_at = aware(snapshot.collected_at)
            item.stale = now - item.collected_at > timedelta(hours=48)
            item.departure_count = len(snapshot.items_json)
            def departure(row):
                return RailDepartureItem(train_number=row.get("train_number"),
                    departure_time=row.get("departure_time"), arrival_time=row.get("arrival_time"),
                    origin_name=names.get((code.operator_code, code.line_code, row.get("origin_station_code"))),
                    destination_name=names.get((code.operator_code, code.line_code, row.get("terminal_station_code"))))
            if not summary_only:
                item.items = sorted((departure(row) for row in snapshot.items_json), key=lambda row: row.departure_time or "999999")
            if basis == "calendar" and not item.stale:
                current_clock = local.strftime("%H%M%S")
                # 날짜가 없는 계획 시각은 같은 한국 날짜의 05~23시 범위만 다음 열차로 표시한다.
                # 원문이 확정 범위 밖이면 전체 시간표에는 남기되 다음 열차로 추정하지 않는다.
                next_row = min((row for row in snapshot.items_json
                    if isinstance(value := row.get("departure_time"), str)
                    and len(value) == 6 and value.isascii() and value.isdecimal()
                    and "05" <= value[:2] <= "23" and value[2:4] < "60"
                    and value[4:] < "60" and value >= current_clock),
                    key=lambda row: row["departure_time"], default=None)
                item.next_departure = departure(next_row) if next_row else None
        result.append(item)
    return RailTimetableResponse(generated_at=now, day_code=day_code, basis=basis, items=result)
