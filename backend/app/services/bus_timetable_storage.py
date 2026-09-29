"""TAGO 성공 응답 영속화. provider 호출이나 보호 상태를 변경하지 않는다."""
from datetime import date

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusTimetableSnapshot
from app.schemas import BusTimetableResponse


async def stored_bus_timetable(session: AsyncSession, key: tuple[str, str, str, date, str | None]) -> BusTimetableResponse | None:
    row = await session.get(BusTimetableSnapshot, (*key[:4], key[4] or ""))
    return BusTimetableResponse.model_validate(row.response_json) if row else None


async def save_bus_timetable(session: AsyncSession, response: BusTimetableResponse, grade: str | None) -> None:
    values = dict(service_type=response.service_type, departure_terminal_id=response.departure_terminal_id,
        arrival_terminal_id=response.arrival_terminal_id, service_date=response.service_date,
        bus_grade_id=grade or "", fetched_at=response.fetched_at, response_json=response.model_dump(mode="json"))
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(BusTimetableSnapshot).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=["service_type", "departure_terminal_id", "arrival_terminal_id", "service_date", "bus_grade_id"],
        set_={"fetched_at": statement.excluded.fetched_at, "response_json": statement.excluded.response_json},
        where=statement.excluded.fetched_at >= BusTimetableSnapshot.fetched_at,
    )
    await session.execute(statement)
    await session.commit()
