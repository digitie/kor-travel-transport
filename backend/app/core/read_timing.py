"""조회 관측: 본문/질의/매개변수 없이 route template와 비용만 기록한다."""
import logging
from contextvars import ContextVar
from dataclasses import dataclass
from time import perf_counter, process_time

from sqlalchemy import event

logger = logging.getLogger(__name__)


@dataclass
class ReadTiming:
    statements: int = 0
    sql_seconds: float = 0


_current: ContextVar[ReadTiming | None] = ContextVar("transport_read_timing", default=None)


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


class ReadTimingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        timing = ReadTiming()
        token = _current.set(timing)
        started, cpu_started = perf_counter(), process_time()
        status = 500

        async def timed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                value = (f'app;dur={(perf_counter()-started)*1000:.3f}, '
                         f'sql;dur={timing.sql_seconds*1000:.3f}, '
                         f'sql_count;desc="{timing.statements}", '
                         f'cpu;dur={(process_time()-cpu_started)*1000:.3f}')
                message = {**message, "headers": [*message.get("headers", []),
                                                 (b"server-timing", value.encode("ascii"))]}
            await send(message)

        try:
            await self.app(scope, receive, timed_send)
        finally:
            duration = (perf_counter()-started)*1000
            if duration >= 1000:
                route = getattr(scope.get("route"), "path", "unmatched")
                logger.warning("slow_request route=%s status=%s duration_ms=%.3f sql_count=%s sql_ms=%.3f cpu_ms=%.3f",
                            route, status, duration, timing.statements, timing.sql_seconds*1000,
                            (process_time()-cpu_started)*1000)
            _current.reset(token)
