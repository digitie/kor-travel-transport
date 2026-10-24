"""일반철도 정상 응답 저장. provider 요청·파싱은 datagokr 라이브러리가 소유한다."""
from datetime import timedelta

from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc
from app.models import GeneralRailQuerySnapshot


async def save_general_rail(session: AsyncSession, operation: str, key: str, response: BaseModel) -> None:
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(GeneralRailQuerySnapshot).values(operation=operation, request_key=key,
        fetched_at=response.fetched_at, response_json=response.model_dump(mode="json"))
    statement = statement.on_conflict_do_update(index_elements=["operation", "request_key"],
        set_={"fetched_at": statement.excluded.fetched_at, "response_json": statement.excluded.response_json},
        where=statement.excluded.fetched_at >= GeneralRailQuerySnapshot.fetched_at)
    await session.execute(statement)
    await session.execute(delete(GeneralRailQuerySnapshot).where(GeneralRailQuerySnapshot.fetched_at < now_utc() - timedelta(days=32)))
    await session.commit()
