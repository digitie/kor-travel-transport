"""API 기동 직후(lifespan yield 뒤)의 best-effort warmup.

배포·재시작 직후에는 커넥션 풀, 입력 지문 memo, 주차 이력 캐시가 모두 비어 있다. 이력 캐시 첫 구성(수십 초 CPU)이
먼저 돌면 같은 프로세스의 첫 export 요청이 함께 느려진다(G3-10). 그래서 순서를 둔다:

1. 풀 채우기 — pool_size만큼 동시에 checkout해 `SELECT 1`(모두 쥔 뒤 함께 반환, 3초 상한, 실패 무시).
2. 입력 지문 memo — Map이 읽는 종류(철도역 → 여객선 터미널)를 하나씩(종류별 10초 상한).
3. 위 둘이 끝나거나 30초가 지나면 주차 이력 캐시 구성을 시작한다.

어느 단계도 readiness나 요청을 막지 않는다. 끝나면 결과를 한 줄 로그로 남긴다(G2-09).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from time import monotonic

from sqlalchemy import text

logger = logging.getLogger(__name__)

POOL_PREFILL_TIMEOUT_SECONDS = 3
#: 이력 캐시 구성은 warmup이 끝나거나 이 시간이 지나면 시작한다(warmup은 이 시간에 끊는다).
HISTORY_CACHE_START_DEADLINE_SECONDS = 30


async def prefill_pool(engine, *, timeout_seconds: float = POOL_PREFILL_TIMEOUT_SECONDS) -> int:
    """풀의 기본 연결 수(pool_size)만큼 **동시에** checkout해 연결을 열어 둔다. 연 연결 수를 돌려준다.

    연결마다 `SELECT 1` 뒤 나머지가 모두 checkout(또는 실패)할 때까지 쥐고 있다가 함께 돌려준다. 하나씩 열고 바로
    돌려주면 다음 checkout이 방금 돌아온 연결을 재사용해 풀에 연결 하나만 남는다. 상한(기본 3초)을 넘기거나 일부가
    실패해도 기동·서빙에는 영향이 없다(실패는 세지 않고 무시한다). 풀이 없거나 PostgreSQL이 아니면 0이다.
    """
    size = getattr(engine.pool, "size", None)
    if engine.dialect.name != "postgresql" or not callable(size):
        return 0
    count = int(size())
    if count <= 0:
        return 0
    all_arrived = asyncio.Event()
    arrived = opened = 0

    def arrive() -> None:
        nonlocal arrived
        arrived += 1
        if arrived >= count:
            all_arrived.set()

    async def hold_one() -> None:
        nonlocal opened
        counted = False
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                opened += 1
                counted = True
                arrive()
                await all_arrived.wait()
        except Exception:  # noqa: BLE001 - 풀 채우기는 best-effort다. 실패한 checkout도 도착으로 센다.
            if not counted:
                arrive()

    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(timeout_seconds):
            await asyncio.gather(*(hold_one() for _ in range(count)))
    return opened


async def run_startup_warmup(
    engine,
    *,
    warm_references: Callable[[], Awaitable[list[dict]]] | None,
    start_history_cache: Callable[[], None] | None,
    deadline_seconds: float = HISTORY_CACHE_START_DEADLINE_SECONDS,
) -> dict:
    started = monotonic()
    summary: dict = {"event": "startup_warmup"}
    try:
        async with asyncio.timeout(deadline_seconds):
            summary["pool_prefilled"] = await prefill_pool(engine)
            if warm_references is not None:
                summary["kinds"] = await warm_references()
        summary["status"] = "finished"
    except TimeoutError:
        summary["status"] = "deadline"
    except Exception as exc:  # noqa: BLE001 - warmup 실패가 이력 캐시 시작과 서빙을 막지 않는다.
        summary.update(status="failed", error_type=type(exc).__name__)
    summary["duration_ms"] = round((monotonic() - started) * 1000)
    if start_history_cache is not None:
        start_history_cache()
        summary["history_cache_started"] = True
    logger.warning(json.dumps(summary, ensure_ascii=False))
    return summary
