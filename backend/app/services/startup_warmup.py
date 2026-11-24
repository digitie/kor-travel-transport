"""API 기동 직후(lifespan yield 뒤)의 best-effort warmup.

배포·재시작 직후에는 커넥션 풀, 입력 지문 memo, 주차 이력 캐시가 모두 비어 있다. 이력 캐시 첫 구성(수십 초 CPU)이
먼저 돌면 같은 프로세스의 첫 export 요청이 함께 느려진다(G3-10). 그래서 순서를 둔다:

1. 풀 채우기 — pool_size 중 빈 만큼 동시에 checkout해 `SELECT 1`(모두 쥔 뒤 함께 반환, 3초 상한, 실패 무시).
   이미 요청이 연결을 쓰고 있으면 건너뛴다.
2. 입력 지문 memo — Map이 읽는 종류(철도역 → 여객선 터미널)를 하나씩(종류별 10초 상한).
3. 위 둘이 끝나거나(보통 수 초, 최대 약 23초 = 풀 3초 + 지문 10초×2) 안전 상한 30초가 지나면 주차 이력 캐시
   구성을 시작한다. 그 전의 `/parking/history`는 캐시 없이 직접 SQL(무거운 대체 경로)로 응답한다.

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
    """풀의 기본 연결 수(pool_size) 중 비어 있는 만큼 **동시에** checkout해 연결을 열어 둔다. 연 연결 수를 돌려준다.

    이미 checkout된 연결이 있으면(기동 직후 요청이 들어왔으면) 아무것도 하지 않는다 — 채우기가 연결을 쥔 3초 동안
    요청이 풀을 기다리지 않게 한다. 이미 풀에 있는 연결(checkedin)만큼은 덜 연다.

    연결마다 `SELECT 1` 뒤 나머지가 모두 checkout(또는 실패)할 때까지 쥐고 있다가 함께 돌려준다. 하나씩 열고 바로
    돌려주면 다음 checkout이 방금 돌아온 연결을 재사용해 풀에 연결 하나만 남는다. 상한(기본 3초)을 넘기거나 일부가
    실패해도 기동·서빙에는 영향이 없다(실패는 세지 않고 무시한다). 풀이 없거나 PostgreSQL이 아니면 0이다.
    """
    pool = engine.pool
    size = getattr(pool, "size", None)
    if engine.dialect.name != "postgresql" or not callable(size):
        return 0
    checked_out = getattr(pool, "checkedout", None)
    if callable(checked_out) and checked_out() > 0:
        # 이미 요청이 연결을 쓰고 있다(기동 직후 burst). 채우기가 남은 슬롯을 붙잡아 요청을 기다리게 하지 않는다.
        return 0
    checked_in = getattr(pool, "checkedin", None)
    count = int(size()) - (int(checked_in()) if callable(checked_in) else 0)
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
    # 성공도 WARNING이다: API는 app logger에 handler·level을 두지 않아(uvicorn은 자기 logger만 설정) Python 기본
    # lastResort가 WARNING 이상만 낸다. INFO로 두면 운영 로그에 남지 않아 'warm 전 도착'과 'warm 실패'를 못 가른다(G2-09).
    logger.warning(json.dumps(summary, ensure_ascii=False))
    return summary
