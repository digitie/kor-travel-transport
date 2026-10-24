"""입차 예정 시각과 같은 요일·시간의 과거 관측을 DB에서 집계한다."""
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc, to_seoul
from app.models import Airport, ParkingLot, ParkingSnapshot
from app.schemas import ParkingOutlookLot, ParkingOutlookResponse


async def parking_outlook(session: AsyncSession, airport: Airport, arrival_at: datetime, days: int) -> ParkingOutlookResponse:
    now = now_utc()
    local = to_seoul(arrival_at)
    today = to_seoul(now).date()
    windows = []
    for offset in range(1, days + 1):
        day = today - timedelta(days=offset)
        if day.weekday() == local.weekday():
            start = datetime.combine(day, time(local.hour), tzinfo=ZoneInfo("Asia/Seoul")).astimezone(UTC)
            windows.append((start, start + timedelta(hours=1), day.isoformat()))
    # airport_id + 시각 범위 조건을 window 함수 앞에 둔다. 기존 history_cover 인덱스로
    # 필요한 시간대만 읽고 ORM 원시 이력·raw JSON을 메모리에 올리지 않는다.
    conditions = [(ParkingSnapshot.observed_at >= start) & (ParkingSnapshot.observed_at < end) for start, end, _ in windows]
    cohort_day = case(*[(condition, label) for condition, (_, _, label) in zip(conditions, windows, strict=True)])
    ranked = select(
        ParkingSnapshot.parking_lot_id.label("lot"),
        ParkingSnapshot.observed_at.label("observed"),
        ParkingSnapshot.available_spaces.label("available"),
        ParkingSnapshot.total_spaces.label("capacity"),
        cohort_day.label("day"),
        func.row_number().over(partition_by=(ParkingSnapshot.parking_lot_id, ParkingSnapshot.observed_at), order_by=(
            case((ParkingSnapshot.source.startswith("migration_", autoescape=True), 1), else_=0),
            ParkingSnapshot.collected_at.desc(), ParkingSnapshot.id.desc(),
        )).label("rank"),
    ).where(ParkingSnapshot.airport_id == airport.id, or_(*conditions)).subquery()
    daily = select(
        ranked.c.lot, ranked.c.day,
        func.count().label("observations"), func.avg(ranked.c.available).label("mean"),
        func.min(ranked.c.available).label("low"), func.max(ranked.c.available).label("high"),
        func.min(ranked.c.capacity).label("min_capacity"), func.max(ranked.c.capacity).label("max_capacity"),
        func.max(ranked.c.observed).label("latest"),
    ).where(ranked.c.rank == 1, ranked.c.capacity > 0).group_by(ranked.c.lot, ranked.c.day).subquery()
    query = select(
        daily.c.lot, ParkingLot.name,
        func.count().label("sample_days"), func.sum(daily.c.observations).label("observations"),
        func.avg(daily.c.mean).label("mean"), func.min(daily.c.low).label("low"), func.max(daily.c.high).label("high"),
        func.sum(case((daily.c.low == 0, 1), else_=0)).label("full_days"),
        func.min(daily.c.min_capacity).label("min_capacity"), func.max(daily.c.max_capacity).label("max_capacity"),
        func.max(daily.c.latest).label("latest"),
    ).join(ParkingLot, ParkingLot.id == daily.c.lot).where(ParkingLot.is_active.is_(True)).group_by(daily.c.lot, ParkingLot.name).order_by(daily.c.lot)
    rows = (await session.execute(query)).mappings().all()
    return ParkingOutlookResponse(generated_at=now, airport_code=airport.code, arrival_at=arrival_at, history_days=days,
        weekday=local.weekday(), hour=local.hour, items=[ParkingOutlookLot(
            parking_lot_id=row["lot"], parking_lot_name=row["name"], sample_days=row["sample_days"], observations=row["observations"],
            average_available_spaces=round(row["mean"], 1), minimum_available_spaces=row["low"], maximum_available_spaces=row["high"],
            full_days=row["full_days"], full_day_ratio=round(row["full_days"] / row["sample_days"] * 100, 1),
            minimum_capacity=row["min_capacity"], maximum_capacity=row["max_capacity"], latest_observed_at=row["latest"],
        ) for row in rows])
