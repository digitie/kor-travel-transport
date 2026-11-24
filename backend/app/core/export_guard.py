"""`/v1/service/exports/*`의 실패 경계: 일시 DB 불가 503과 T2/T3/T4 handler 전체 상한(ADR-013 개정 2026-11-24).

- `ExportTransientDbMiddleware`: export 경로에서만, 응답 시작 전에 올라온 일시 DB 오류(`is_transient_db_error`)를
  503 `TRANSIENT_DB` problem으로 바꾼다. 다른 경로는 이 미들웨어를 그냥 통과한다 — 앱 전체 exception handler를
  DB 예외 클래스에 등록하면 Starlette가 이미 시작된 stream(예: `/` 아래 MCP)에서 원래 예외 대신
  `RuntimeError("Caught handled exception, but response already started.")`를 올리므로 등록하지 않는다.
- `ExportDeadlineRoute`: T2(교통 current)·T3(기준정보)·T4(가격 이력) handler를 25초 안에 끝낸다. Map read
  timeout(30초)보다 먼저 code 있는 503을 돌려주려는 것이다. pool checkout의 pre-ping·멈춘 PG 문장처럼 connect·
  pool 상한이 덮지 못하는 대기도 여기서 끊는다. T1 handler의 상한은 T1 export 작업(#279)이 따로 둔다.
- 일시 DB 불가는 처음 한 번과 그 뒤 60초마다 ERROR로, 그 사이는 WARNING으로 남긴다(원인 종류·errno·SQLSTATE만).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass
from http import HTTPStatus
from time import monotonic
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.core.problems import (
    RETRY_AFTER_SECONDS,
    SERVICE_EXPORT_PATH_PREFIX,
    TRANSIENT_DB_DETAIL,
    ProblemCode,
    database_sqlstate,
    is_transient_db_error,
    problem_body,
    transient_cause,
    unavailable,
)

logger = logging.getLogger(__name__)

#: T2/T3/T4 export handler 전체 상한(초). Map read timeout(30초)보다 작아야 Map이 timeout 대신 code 있는 503을 본다.
#: 본문 구성 예산(15초) + admission lock_timeout(2초) + 페이지 읽기를 넉넉히 덮는다.
EXPORT_HANDLER_DEADLINE_SECONDS = 25.0
DEADLINE_DETAIL = "export 응답 준비 시간 상한을 초과했습니다. 잠시 후 다시 요청하세요."
#: 일시 DB 불가 ERROR 로그 사이 간격(초). 그 사이 같은 사건은 WARNING이다.
OUTAGE_LOG_WINDOW_SECONDS = 60.0


@dataclass
class _Phase:
    building: bool = False


_phase: ContextVar[_Phase | None] = ContextVar("transport_export_phase", default=None)


def mark_building() -> None:
    """요청이 지금 본문(snapshot·artifact)을 구성하는 중임을 표시한다. 상한 초과의 code를 가른다."""
    phase = _phase.get()
    if phase is not None:
        phase.building = True


class _OutageLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window_started: float | None = None
        self._repeated = 0

    def record(self, message: str, *args: Any) -> None:
        now = monotonic()
        with self._lock:
            if self._window_started is None or now - self._window_started >= OUTAGE_LOG_WINDOW_SECONDS:
                repeated, self._repeated, self._window_started = self._repeated, 0, now
                level = logging.ERROR
            else:
                self._repeated += 1
                repeated, level = 0, logging.WARNING
        logger.log(level, message + " repeated_in_previous_window=%d", *args, repeated)


_outage_log = _OutageLog()


def transient_db_response(path: str, exc: BaseException) -> JSONResponse:
    # 원문(SQL·DSN·드라이버 문장)은 응답·로그 어디에도 싣지 않는다. 종류·원인·SQLSTATE만 남긴다.
    _outage_log.record("export database unavailable mapped to 503 TRANSIENT_DB type=%s cause=%s sqlstate=%s path=%s",
                       type(exc).__qualname__, transient_cause(exc), database_sqlstate(exc), path)
    status = HTTPStatus.SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=status,
        content=problem_body(status=int(status), title=status.phrase, detail=TRANSIENT_DB_DETAIL, instance=path,
                             code=ProblemCode.TRANSIENT_DB),
        headers={"Retry-After": str(RETRY_AFTER_SECONDS[ProblemCode.TRANSIENT_DB])},
        media_type="application/problem+json",
    )


class ExportTransientDbMiddleware:
    """export 경로에서만 응답 시작 전 일시 DB 오류를 503 `TRANSIENT_DB`로 바꾼다. 가장 안쪽 미들웨어로 둔다."""

    def __init__(self, app: Callable[..., Coroutine[Any, Any, None]]) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        path = str(scope.get("path", ""))
        if scope.get("type") != "http" or not path.startswith(SERVICE_EXPORT_PATH_PREFIX):
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message) -> None:
            nonlocal started
            if message.get("type") == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if started or not is_transient_db_error(exc):
                raise
            await transient_db_response(path, exc)(scope, receive, send)


class ExportDeadlineRoute(APIRoute):
    """handler(의존성 해석 포함)를 `EXPORT_HANDLER_DEADLINE_SECONDS` 안에 끝내고, 넘으면 code 있는 503을 낸다.

    본문 구성 중(`mark_building`)이면 `EXPORT_PREPARE_TIMEOUT`, 그 밖(pool·접속·멈춘 문장)이면 `TRANSIENT_DB`다.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            phase = _Phase()
            token = _phase.set(phase)
            deadline = asyncio.timeout(EXPORT_HANDLER_DEADLINE_SECONDS)
            try:
                async with deadline:
                    return await original(request)
            except TimeoutError as exc:
                if not deadline.expired():
                    raise  # 안쪽에서 난 TimeoutError(예: DB 접속 timeout)는 그대로 분류한다.
                code = ProblemCode.EXPORT_PREPARE_TIMEOUT if phase.building else ProblemCode.TRANSIENT_DB
                _outage_log.record("export handler deadline exceeded code=%s seconds=%s path=%s",
                                   code.value, EXPORT_HANDLER_DEADLINE_SECONDS, request.url.path)
                raise unavailable(code, DEADLINE_DETAIL) from exc
            finally:
                _phase.reset(token)

        return handler
