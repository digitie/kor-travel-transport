from __future__ import annotations

import os
import socket
import ssl
from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
from app.core.problems import DatabaseConnectError, DatabaseConnectTimeout
from app.core.read_timing import observe_engine

ALEMBIC_HEAD = "0051_rest_area_food"

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
#: API 엔진의 asyncpg **새 접속** 상한(초). asyncpg 기본 60초는 Map read timeout(30초)보다 길어 PG가 응답하지 않는
#: 동안 요청이 소비자보다 늦게 실패했다(감사 T1-07·RT-04). 넘으면 export 경로는 503 TRANSIENT_DB, 그 밖은 예전처럼 500이다.
#: 이미 pool에 있는 연결의 pre-ping·멈춘 문장은 이 상한이 덮지 않는다 — API 엔진에는 클라이언트 command_timeout이
#: 없다. export는 handler 전체 상한(T2/T3/T4 25초 `app/core/export_guard.py`, T1은 T1 export 작업)이 끊는다.
API_CONNECT_TIMEOUT_SECONDS = 10
#: API 엔진 pool checkout 대기 상한(초). SQLAlchemy 기본 30초는 Map read timeout과 같아 소비자가 먼저 끊었다
#: (감사 RT-02). 넘으면 `sqlalchemy.exc.TimeoutError`로 export 경로는 503 TRANSIENT_DB다. **엔진 전체 설정이라
#: 공개·관리 경로도 바뀐다**: 예전에 10~30초 기다려 성공하던 요청이 이제 10초에 500으로 끝난다. 장소 지도 입장
#: 제한(MUI-02, #273)이 장소 지도 몰림을 줄이지만, 함께 배포되지 않은 이미지에서는 장소 지도 몰림이 pool을 채워 이 500이
#: 늘 수 있다(ADR-013 개정 2026-11-24).
API_POOL_TIMEOUT_SECONDS = 10
#: `pg_stat_activity`·`pg_locks`에서 어느 프로세스의 연결인지 가른다(감사 WLH-09). 수집 엔진은 Dagster op·
#: 기준정보 준비가 쓴다. API 엔진의 in_process 수집(개발 기본)은 API 이름으로 보인다.
API_APPLICATION_NAME = "kor-travel-transport-api"
COLLECTOR_APPLICATION_NAME = "kor-travel-transport-collector"
#: 두 엔진 모두 PostgreSQL JIT를 끈다(2026-11-28). 이 앱의 문장은 짧은 OLTP 읽기·쓰기라 JIT로 얻는 실행 이득이 없는데,
#: 계획 비용 추정이 `jit_above_cost`(기본 100000)를 넘으면 LLVM inlining·optimization 컴파일이 실행마다 붙는다.
#: 운영(odroid ARM) 공개 유가 시군구 통계가 shared hit 351·인덱스 스캔 수 ms인데 3.5~5.7초였고(SQL 92~96%),
#: 시간이 상위 노드(Sort→Unique)에 붙어 있었다. 같은 문장을 로컬 x86 PG18에서 JIT 강제로 돌리면 2.3ms→318ms(JIT 201ms)다.
#: 연결 단위 설정이라 DB 전체(`postgresql.conf`)나 다른 서비스 연결은 바꾸지 않는다.
SERVER_JIT = "off"
# API 엔진에 서버 `lock_timeout`을 두지 않는다(감사 T1-07·WLH-09 검토, 2026-11-24). 관리자 KRIC 매핑 저장
# (`save_rail_station_mappings`)은 기준 역 수집과 같은 `pg_advisory_xact_lock`을 의도적으로 기다리고, 관리자 좌표
# 보정은 수집이 잡은 행 잠금(`FOR UPDATE`)을 기다리며, in_process 수집(개발 기본)도 같은 API 엔진으로 수집 잠금을
# 기다린다. 엔진 전체 상한은 이 대기를 55P03 실패로 바꾼다. 짧은 대기가 맞는 경로는 이미 트랜잭션 안에서
# `SET LOCAL lock_timeout`을 둔다(T2/T3 export 2초, 자동 역 매핑 2초). `idle_in_transaction_session_timeout`·
# `transaction_timeout`은 어느 엔진에도 두지 않는다 — 공항(`collection.py` 공항 수집 lease)·버스 기준정보
# (`bus_collection.py`)·일반철도(`general_rail_collection.py`)·KRIC 시간표(`kric_collection.py`)의 세션 advisory
# lease 연결은 `pg_try_advisory_lock` 뒤 commit하지 않아 SQLAlchemy autobegin으로 run 내내(공항 최대 1,800초)
# idle in transaction이다. 서버가 끊으면 unlock이 실패해 run이 RuntimeError로 끝나고 실행 중 lease를 잃는다
# (감사 WLH-09 검증 정정). 먼저 lease 획득 직후 commit을 넣어야 한다.


def _classify_connect_failures(engine: AsyncEngine) -> None:
    """접속 단계의 OSError·timeout을 `DatabaseConnectError`로 표시해 export 경로에서 503 TRANSIENT_DB로 가르게 한다.

    asyncpg의 PostgreSQL 오류(57P03·53300 등)는 SQLAlchemy가 SQLSTATE 있는 DBAPIError로 바꾸지만, 접속 거부·
    접속 timeout은 원래 예외(OSError·TimeoutError)로 그대로 올라와 route 코드의 다른 OSError와 구분되지 않는다.
    새 예외는 각각 `ConnectionError`·`TimeoutError`를 상속해 기존 except 처리는 같다.

    DNS 해석 실패(`socket.gaierror`)와 TLS 오류(`ssl.SSLError`, 인증서 검증 포함)는 표시하지 않는다 — 주소·인증서
    설정 문제라 기다려도 풀리지 않는데, "잠시 뒤 다시"(TRANSIENT_DB)로 내면 소비자가 끝없이 재시도한다. 예전처럼
    500과 오류 로그로 남는다.
    """

    if engine.sync_engine is None:  # 엔진 옵션만 검증하는 test double
        return

    @event.listens_for(engine.sync_engine, "do_connect")
    def connect(dialect, _connection_record, cargs, cparams):
        try:
            return dialect.connect(*cargs, **cparams)
        except (DatabaseConnectError, socket.gaierror, ssl.SSLError):
            raise
        except TimeoutError as exc:
            raise DatabaseConnectTimeout("데이터베이스 접속 시간이 초과됐습니다.") from exc
        except OSError as exc:
            raise DatabaseConnectError("데이터베이스에 접속하지 못했습니다.") from exc


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
                "server_settings": {"lock_timeout": "5s", "statement_timeout": f"{statement_timeout}s",
                                    "application_name": COLLECTOR_APPLICATION_NAME, "jit": SERVER_JIT},
            }
        else:
            engine_options["connect_args"] = {
                "timeout": API_CONNECT_TIMEOUT_SECONDS,
                "server_settings": {"statement_timeout": f"{statement_timeout}s",
                                    "application_name": API_APPLICATION_NAME, "jit": SERVER_JIT},
            }
        if os.getenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE") == "1":
            engine_options["poolclass"] = NullPool
        else:
            # 한 connection은 session advisory lease, 나머지는 게시 transaction이 사용한다.
            engine_options.update({"pool_size": 2 if collector else 5, "max_overflow": 0 if collector else 5})
            if not collector:
                engine_options["pool_timeout"] = API_POOL_TIMEOUT_SECONDS
    engine = create_async_engine(database_url, **engine_options)
    observe_engine(engine)
    if database_url.startswith("postgresql") and not collector:
        _classify_connect_failures(engine)

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
