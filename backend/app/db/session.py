from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base

ALEMBIC_HEAD = "0037_parking_archive_coverage"

#: 수집 엔진의 문장 상한(초). 이미 쓰던 asyncpg `command_timeout`(클라이언트 측)과 같은 값을 서버
#: `statement_timeout`에도 둔다. 서버 측 실행 시간은 클라이언트 왕복보다 길 수 없으므로 지금 통과하는
#: 문장을 새로 끊지 않는다. 클라이언트가 멈추거나 끊긴 뒤에도 서버가 문장을 끝까지 돌리지 않게 하는
#: 것이 목적이다(유가 bulk 묶음 크기도 이 60초에 맞춰 정했다 — `transport_collection.py`).
COLLECTOR_STATEMENT_TIMEOUT_SECONDS = 60
#: API 엔진의 서버 측 문장 상한(초). 지금까지는 상한이 없었다. 요청 경로는 앱 deadline(통계 25초)과
#: 관리 프록시(30초) 안에 끝나고, 가장 긴 실측 읽기는 n150 30일 전체 주차 이력 약 52만 행 DB 읽기
#: 2.0~2.8초다(journal 2026-10-01). in_process 수집(개발 기본값)의 유가 bulk 묶음은 수집 엔진의 60초에
#: 맞춰 있다. 120초는 이들보다 넉넉한 backstop이며 취소된 요청의 문장이 서버에 남는 것만 막는다.
API_STATEMENT_TIMEOUT_SECONDS = 120


def create_engine_and_session_factory(
    database_url: str, *, collector: bool = False, statement_timeout_seconds: int | None = None,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """PostgreSQL 엔진은 서버 측 `statement_timeout`을 갖는다.

    `statement_timeout_seconds`는 기본 상한(수집 60초, API 120초)을 줄일 때만 쓴다. 회수 sensor처럼
    tick 예산보다 짧은 상한이 필요한 호출자가 쓴다. 수집 엔진은 같은 값을 `command_timeout`에도 두고,
    접속 timeout(기본 10초)도 그 값을 넘지 않게 줄인다.
    """
    if statement_timeout_seconds is not None and (
        isinstance(statement_timeout_seconds, bool)
        or not isinstance(statement_timeout_seconds, int)
        or statement_timeout_seconds <= 0
    ):
        raise ValueError("statement_timeout_seconds는 양의 정수여야 합니다.")
    if database_url.startswith("postgres://"):
        database_url = "postgresql+asyncpg://" + database_url.removeprefix("postgres://")
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+asyncpg://" + database_url.removeprefix("postgresql://")

    if database_url.startswith("sqlite"):
        sqlite_url = make_url(database_url)
        database_path = sqlite_url.database
        if database_path and database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    engine_options: dict[str, object] = {
        "future": True,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }
    if database_url.startswith("postgresql"):
        default_timeout = COLLECTOR_STATEMENT_TIMEOUT_SECONDS if collector else API_STATEMENT_TIMEOUT_SECONDS
        statement_timeout = statement_timeout_seconds or default_timeout
        if collector:
            engine_options["connect_args"] = {
                "timeout": min(10, statement_timeout), "command_timeout": statement_timeout,
                "server_settings": {"lock_timeout": "5s", "statement_timeout": f"{statement_timeout}s"},
            }
        else:
            engine_options["connect_args"] = {
                "server_settings": {"statement_timeout": f"{statement_timeout}s"},
            }
        if os.getenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE") == "1":
            engine_options["poolclass"] = NullPool
        else:
            # 한 connection은 session advisory lease, 나머지는 게시 transaction이 사용한다.
            engine_options.update({"pool_size": 2 if collector else 5, "max_overflow": 0 if collector else 5})
    engine = create_async_engine(database_url, **engine_options)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA cache_size=-20000")
            cursor.execute("PRAGMA mmap_size=268435456")
            cursor.close()

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


async def init_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            version = await connection.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
            if version != ALEMBIC_HEAD:
                raise RuntimeError(
                    f"PostgreSQL schema is not at Alembic head {ALEMBIC_HEAD!r} (found {version!r})"
                )
            return

        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_parking_snapshots_airport_observed "
                "ON parking_snapshots (airport_id, observed_at)"
            )
        )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_parking_snapshots_lot_observed "
                "ON parking_snapshots (parking_lot_id, observed_at)"
            )
        )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_parking_snapshots_airport_lot_observed "
                "ON parking_snapshots (airport_id, parking_lot_id, observed_at)"
            )
        )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_parking_snapshots_airport_lot_observed_desc "
                "ON parking_snapshots (airport_id, parking_lot_id, observed_at DESC, id DESC)"
            )
        )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_parking_snapshots_collected_at "
                "ON parking_snapshots (collected_at)"
            )
        )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_parking_snapshots_collection_run_id "
                "ON parking_snapshots (collection_run_id)"
            )
        )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_raw_api_responses_collection_run_id "
                "ON raw_api_responses (collection_run_id)"
            )
        )
        if connection.dialect.name == "sqlite":
            await connection.execute(text("PRAGMA analysis_limit=1000"))
            await connection.execute(text("PRAGMA optimize"))


async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
