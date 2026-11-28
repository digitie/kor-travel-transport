"""앱 DB 연결은 PostgreSQL JIT를 끈다(2026-11-28 운영 시군구 유가 통계 3.5~5.7초 가설, `app/db/session.py` SERVER_JIT)."""
import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db.session import create_engine_and_session_factory

DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
# 세 비용 기준을 모두 0으로 내려 JIT가 켜진 연결이면 반드시 컴파일하게 한다.
FORCE_JIT = ("SET LOCAL jit_above_cost = 0", "SET LOCAL jit_inline_above_cost = 0", "SET LOCAL jit_optimize_above_cost = 0")
# COSTS OFF면 JIT가 돌아도 `JIT:` 절이 찍히지 않는다(PG16·18 확인) — 기본 형식으로 본다.
PROBE = "EXPLAIN (ANALYZE) SELECT sum(g) FROM generate_series(1, 1000) g"


async def _plan(connection) -> str:
    for statement in FORCE_JIT:
        await connection.execute(text(statement))
    return "\n".join((await connection.execute(text(PROBE))).scalars())


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="PostgreSQL TEST_DATABASE_URL 필요")
@pytest.mark.parametrize("collector", [False, True], ids=["api", "collector"])
def test_engine_connections_run_without_jit(collector: bool) -> None:
    async def check() -> tuple[bool, str, str, str]:
        # 대조군: 앱 설정 없는 연결은 서버 기본(jit=on)으로 같은 문장에서 JIT 절을 낸다.
        plain = create_async_engine(DATABASE_URL, poolclass=NullPool)
        try:
            async with plain.connect() as connection:
                available = bool(await connection.scalar(text("SELECT pg_jit_available()")))
                control = await _plan(connection)
        finally:
            await plain.dispose()
        engine, session_factory = create_engine_and_session_factory(DATABASE_URL, collector=collector)
        try:
            async with session_factory() as session:
                jit = await session.scalar(text("SHOW jit"))
                plan = await _plan(await session.connection())
        finally:
            await engine.dispose()
        return available, control, jit, plan

    available, control, jit, plan = asyncio.run(check())
    assert jit == "off"
    if not available:
        pytest.skip("이 PostgreSQL에는 JIT provider가 없어 EXPLAIN 대조를 할 수 없다(SHOW jit=off만 확인)")
    assert "JIT:" in control
    assert "JIT:" not in plan
