"""앱 DB 연결은 PostgreSQL JIT를 끈다(2026-11-28 운영 시군구 유가 통계 3.5~5.7초, `app/db/session.py` SERVER_JIT)."""
import asyncio
import os

import pytest
from sqlalchemy import text

from app.db.session import create_engine_and_session_factory

DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")


@pytest.mark.skipif(not DATABASE_URL.startswith("postgres"), reason="PostgreSQL TEST_DATABASE_URL 필요")
@pytest.mark.parametrize("collector", [False, True])
def test_engine_connections_run_without_jit(collector: bool) -> None:
    async def check() -> tuple[str, str]:
        engine, session_factory = create_engine_and_session_factory(DATABASE_URL, collector=collector)
        try:
            async with session_factory() as session:
                jit = await session.scalar(text("SHOW jit"))
                # 비용 기준을 0으로 낮춰도 이 연결에서는 JIT가 붙지 않는다(EXPLAIN에 JIT 절이 없다).
                await session.execute(text("SET LOCAL jit_above_cost = 0"))
                plan = "\n".join((await session.execute(text(
                    "EXPLAIN (ANALYZE, COSTS OFF) SELECT sum(g) FROM generate_series(1, 1000) g"))).scalars())
                return jit, plan
        finally:
            await engine.dispose()

    jit, plan = asyncio.run(check())
    assert jit == "off"
    assert "JIT:" not in plan
