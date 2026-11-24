"""조회 관측: 본문/질의/매개변수 없이 route template와 비용만 기록한다.

로그 한 줄(`slow_request`·`export_request`)과 Server-Timing 필드의 뜻·읽는 법은
docs/runbooks/request-timing-logs.md를 따른다.
"""
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter, process_time, thread_time

from sqlalchemy import event

logger = logging.getLogger(__name__)

#: 느린 요청 로그의 기본 임계(ms). 운영 값은 Settings `slow_request_threshold_ms`
#: (env `SLOW_REQUEST_THRESHOLD_MS`)로 바꾼다.
DEFAULT_SLOW_REQUEST_THRESHOLD_MS = 1000
#: 지연과 무관하게 모든 요청을 한 줄씩 남기는 경로 접두어. Map 소비자 export(ADR-013)는 하루 수백 건
#: 규모라 1초 미만 요청까지 남겨야 서버 쪽 지연 분포(p50/p95)와 cold/warm 구분을 만들 수 있다.
ALWAYS_LOGGED_PATH_PREFIXES = ("/v1/service/exports/",)


@dataclass
class ReadTiming:
    statements: int = 0
    sql_seconds: float = 0
    page_builds: int = 0
    fingerprint_calculations: int = 0
    # 풀에서 연결을 받기까지 걸린 시간 합(대기열 대기 + 새 연결 수립 + pre-ping). SQL 시간 밖 구간이다.
    pool_wait_seconds: float = 0
    pool_checkouts: int = 0
    # 이 요청 중 새로 만든 DB 연결 수(풀이 비었거나 NullPool). 0이 아니면 연결 수립 비용이 섞인다.
    pool_connects: int = 0
    # 연결을 받은 직후 풀의 사용 중 연결 수 최댓값(자기 연결 포함). QueuePool 계열만 값이 있다.
    pool_checkedout: int | None = None


_current: ContextVar[ReadTiming | None] = ContextVar("transport_read_timing", default=None)
# 단일 프로세스의 이벤트 루프 thread에서만 바뀌므로 잠금 없이 센다.
_inflight = 0


def observe_page_build():
    timing = _current.get()
    if timing is not None:
        timing.page_builds += 1


def observe_fingerprint():
    timing = _current.get()
    if timing is not None:
        timing.fingerprint_calculations += 1



@contextmanager
def observe_native_statement():
    """SQLAlchemy cursor hook 밖의 native COPY도 같은 요청 계수에 포함한다."""
    timing = _current.get()
    started = perf_counter()
    if timing is not None:
        timing.statements += 1
    yield
    # 기존 after_cursor_execute와 같이 성공한 문장의 왕복만 누적한다.
    if timing is not None:
        timing.sql_seconds += perf_counter() - started


def _observe_pool_wait(pool):
    """`Pool.connect()` 한 번의 소요 시간을 요청 계수에 더한다.

    SQLAlchemy pool 이벤트(`checkout`)는 연결을 받은 뒤에만 불려 대기 시작 시각을 알 수 없다.
    Engine은 모든 연결을 `pool.connect()`로 받으므로 이 호출을 감싸 대기열 대기·새 연결·pre-ping을
    함께 잰다. 풀 고갈 `TimeoutError`(기본 30초)로 끝나도 기다린 시간을 남긴다.
    """
    if getattr(pool, "_transport_read_timing", False):
        return
    connect = pool.connect

    def timed_connect():
        timing = _current.get()
        if timing is None:
            return connect()
        started = perf_counter()
        try:
            return connect()
        finally:
            timing.pool_wait_seconds += perf_counter() - started
            timing.pool_checkouts += 1
            checkedout = getattr(pool, "checkedout", None)
            if checkedout is not None:
                timing.pool_checkedout = max(checkedout(), timing.pool_checkedout or 0)

    pool.connect = timed_connect
    pool._transport_read_timing = True


def observe_engine(engine):
    # 엔진 옵션만 검증하는 기존 test double에는 실제 동기 엔진이 없다.
    sync_engine = engine.sync_engine
    if sync_engine is None:
        return

    @event.listens_for(sync_engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, executemany):
        timing = _current.get()
        if timing is not None:
            timing.statements += 1
            context._transport_timing = (timing, perf_counter())

    @event.listens_for(sync_engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, executemany):
        measurement = getattr(context, "_transport_timing", None)
        if measurement is not None:
            timing, started = measurement
            timing.sql_seconds += perf_counter() - started

    # pool 이벤트 listener는 dispose 뒤 새 pool로 이어진다. connect 감싸기는 새 pool에 다시 적용한다.
    @event.listens_for(sync_engine, "connect")
    def connect(dbapi_connection, connection_record):
        timing = _current.get()
        if timing is not None:
            timing.pool_connects += 1

    @event.listens_for(sync_engine, "engine_disposed")
    def disposed(disposed_engine):
        _observe_pool_wait(disposed_engine.pool)

    _observe_pool_wait(sync_engine.pool)


def _utc_millis(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ReadTimingMiddleware:
    def __init__(self, app, slow_threshold_ms: float = DEFAULT_SLOW_REQUEST_THRESHOLD_MS):
        if slow_threshold_ms < 0:
            raise ValueError("slow_threshold_ms는 0 이상이어야 합니다.")
        self.app = app
        self.slow_threshold_ms = slow_threshold_ms

    async def __call__(self, scope, receive, send):
        global _inflight
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        timing = ReadTiming()
        token = _current.set(timing)
        _inflight += 1
        inflight_start = _inflight
        started_at = datetime.now(UTC)
        # cpu는 프로세스 전체(모든 thread) CPU라 이력 재구성 thread·동시 요청 비용이 섞인다(연속성 때문에 유지).
        # loop_cpu는 이 요청을 처리한 이벤트 루프 thread의 CPU만 센다. 같은 루프에서 번갈아 돈 다른
        # coroutine의 CPU는 포함하고, asyncio.to_thread·threadpool에서 돈 작업의 CPU는 빠진다.
        started, cpu_started, loop_cpu_started = perf_counter(), process_time(), thread_time()
        # http.response.start 없이 끝나면(취소·연결 끊김) none으로 남긴다.
        status: int | str = "none"

        async def timed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                # 기존 필드의 이름·순서는 그대로 두고 새 필드는 뒤에만 붙인다.
                value = (f'app;dur={(perf_counter()-started)*1000:.3f}, '
                         f'sql;dur={timing.sql_seconds*1000:.3f}, '
                         f'sql_count;desc="{timing.statements}", '
                         f'cpu;dur={(process_time()-cpu_started)*1000:.3f}, '
                         f'page_builds;desc="{timing.page_builds}", '
                         f'fingerprint_calculations;desc="{timing.fingerprint_calculations}", '
                         f'pool;dur={timing.pool_wait_seconds*1000:.3f}, '
                         f'loop_cpu;dur={(thread_time()-loop_cpu_started)*1000:.3f}')
                message = {**message, "headers": [*message.get("headers", []),
                                                 (b"server-timing", value.encode("ascii"))]}
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        except Exception:
            # 응답 시작 전 예외는 바깥 ServerErrorMiddleware가 500으로 응답한다.
            if status == "none":
                status = 500
            raise
        finally:
            _inflight -= 1
            duration = (perf_counter()-started)*1000
            slow = duration >= self.slow_threshold_ms
            if slow or scope.get("path", "").startswith(ALWAYS_LOGGED_PATH_PREFIXES):
                route = getattr(scope.get("route"), "path", "unmatched")
                # 운영 uvicorn은 app logger에 handler를 두지 않아 WARNING 미만은 버려지고(logging.lastResort),
                # 시각도 붙지 않는다. 주차 이력 재구성 로그와 같이 WARNING으로 남기고 시작 시각을 start에 싣는다.
                logger.warning(
                    "%s route=%s method=%s status=%s start=%s duration_ms=%.3f sql_count=%s sql_ms=%.3f "
                    "cpu_ms=%.3f loop_cpu_ms=%.3f page_builds=%s fingerprint_calculations=%s pool_ms=%.3f "
                    "pool_checkouts=%s pool_connects=%s pool_checkedout=%s inflight_start=%s inflight_end=%s",
                    "slow_request" if slow else "export_request", route, scope.get("method", "-"), status,
                    _utc_millis(started_at), duration, timing.statements, timing.sql_seconds*1000,
                    (process_time()-cpu_started)*1000, (thread_time()-loop_cpu_started)*1000,
                    timing.page_builds, timing.fingerprint_calculations, timing.pool_wait_seconds*1000,
                    timing.pool_checkouts, timing.pool_connects,
                    "none" if timing.pool_checkedout is None else timing.pool_checkedout,
                    inflight_start, _inflight,
                )
            _current.reset(token)
