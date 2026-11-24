"""장소 지도(`/v1/transport/features/places`)의 입장 제한·대기 중 동일 요청 합치기·전체 시한·연결 끊김 취소.

2026-11-24 감사 MUI-02: places에는 시한·입장 제한·single-flight가 없었다. 공개 gateway와 관리 BFF가
30초에 504를 낸 뒤에도 문장이 API 엔진 상한(120초)까지 돌았고(운영 11-23 분포 34초·범위 통계 104초),
요청이 몰리면 풀(5+5)을 Map export·`/health`·이력 캐시와 다투다 checkout 대기(30초) 뒤 500이 났다.

- 입장 제한: DB 계산은 동시에 `max_running`건만 한다. 슬롯을 기다리는 요청은 아직 첫 SQL 전이라
  풀 연결을 쥐지 않는다. 대기열이 `max_waiting`건으로 차면 기다리게 하지 않고 즉시 429 + Retry-After를 낸다
  (교통 통계 `cached_transport_statistics`의 입장 거절과 같은 상태 코드).
- 동일 요청 합치기: 같은 정규화 요청이 **아직 DB 읽기를 시작하지 않은(슬롯 대기 중)** 요청을 만나면
  그 결과를 함께 받는다. 리더의 읽기는 합류한 모든 요청이 도착한 뒤에 시작하므로 각자 단독으로 실행한
  것과 같거나 더 새로운 상태를 본다(저장 직후 재조회가 저장 전 결과를 받지 않는다). 이미 실행 중인 계산에는
  합류하지 않는다. 그래서 대기 항목은 대기 리더 수(≤ `max_waiting`)를 넘지 않는다.
- 전체 시한: 도착부터 `deadline_seconds`(기본 25초) 안에 끝내지 못하면 계산을 취소하고 session을
  rollback한 뒤 504를 낸다. 서버 쪽에도 같은 `SET LOCAL statement_timeout`을 둬 클라이언트 취소가
  닿지 않아도 문장이 gateway 시한 뒤까지 남지 않게 한다.
- 연결 끊김: 브라우저가 이전 조회를 취소하면 관리 BFF·공개 gateway가 upstream 연결을 닫는다. Starlette는
  일반 endpoint를 연결 끊김으로 취소하지 않으므로, `StreamingResponse`처럼 `receive()`로 `http.disconnect`를
  기다리다가 오면 대기열 자리나 계산을 취소한다. 단 합류한 다른 요청이 결과를 기다리는 리더는 끝까지 계산한다.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Hashable
from contextlib import suppress
from functools import wraps
from typing import Any

from fastapi import HTTPException
from sqlalchemy import event
from starlette.responses import Response

logger = logging.getLogger(__name__)

#: 도착부터 응답까지의 전체 시한(초). 공개 fuel gateway `proxy_read_timeout`과 관리 BFF의 30초보다 짧다.
PLACES_DEADLINE_SECONDS = 25.0
#: 동시에 DB 계산을 하는 장소 지도 요청 수. API 풀 10개 중 나머지는 export·`/health`·이력 캐시 몫이다.
PLACES_MAX_RUNNING = 4
#: 실행 슬롯을 기다릴 수 있는 요청 수. 넘치면 즉시 429다(합류한 동일 요청은 세지 않는다).
PLACES_MAX_WAITING = 8
#: 서버 측 문장 상한. 전체 시한과 같은 값이라 한 문장이 gateway 시한을 넘겨 남지 않는다.
PLACES_STATEMENT_TIMEOUT_MS = int(PLACES_DEADLINE_SECONDS * 1000)
#: 혼잡(입장 거절) 재시도 안내(초). 지도 화면은 5초 이하이면 같은 조건으로 한 번 자동 재조회한다.
BUSY_RETRY_AFTER_SECONDS = 2
#: 시한 초과 재시도 안내(초). 25초를 쓰고 실패한 계산을 화면이 곧바로 되풀이하지 않게 5초보다 길게 둔다.
TIMEOUT_RETRY_AFTER_SECONDS = 10
#: 연결이 끊긴 요청의 기록용 상태(nginx `client closed request`). 받을 클라이언트는 없다.
CLIENT_CLOSED_STATUS = 499

_SET_STATEMENT_TIMEOUT = f"SET LOCAL statement_timeout = '{PLACES_STATEMENT_TIMEOUT_MS}ms'"
# 리더가 결과 없이 취소되면(연결 끊김·종료) 합류한 요청은 처음부터 다시 판단한다.
_RESTART = object()


def busy_error() -> HTTPException:
    return HTTPException(
        status_code=429, detail="장소 지도 조회가 혼잡합니다. 잠시 후 다시 시도하세요.",
        headers={"Retry-After": str(BUSY_RETRY_AFTER_SECONDS)},
    )


def timeout_error() -> HTTPException:
    return HTTPException(
        status_code=504, detail="장소 지도 조회 시간이 초과되었습니다. 지도 범위를 좁히거나 잠시 후 다시 시도하세요.",
        headers={"Retry-After": str(TIMEOUT_RETRY_AFTER_SECONDS)},
    )


class _Flight:
    """슬롯을 기다리는 리더 하나의 결과와, 그 결과를 함께 기다리는 요청 수."""

    __slots__ = ("future", "followers")

    def __init__(self, future: asyncio.Future) -> None:
        self.future = future
        self.followers = 0


class PlaceMapGate:
    """event loop 하나(앱 lifespan)에 속한 입장 제한기. 모든 상태 변경은 같은 loop에서 await 없이 일어난다."""

    def __init__(self, *, max_running: int = PLACES_MAX_RUNNING, max_waiting: int = PLACES_MAX_WAITING,
                 deadline_seconds: float = PLACES_DEADLINE_SECONDS) -> None:
        if max_running < 1 or max_waiting < 0 or deadline_seconds <= 0:
            raise ValueError("장소 지도 입장 제한 값이 올바르지 않습니다.")
        self.max_running = max_running
        self.max_waiting = max_waiting
        self.deadline_seconds = deadline_seconds
        self._slots = asyncio.Semaphore(max_running)
        self.running = 0
        self.waiting = 0
        # 아직 슬롯을 기다리는 리더의 결과. 실행을 시작하면 바로 뺀다(새 합류 차단).
        self.pending: dict[Hashable, _Flight] = {}
        # 대기열에 줄을 섰던 리더 task → 그 결과를 기다리는 요청 수(연결 끊김 취소 판단용).
        self._leading: dict[asyncio.Task, _Flight] = {}
        # 운영 판단용 누계(프로세스 단위). 거절·시한·끊김은 로그도 남긴다.
        self.stats = {"coalesced": 0, "rejected": 0, "timed_out": 0, "abandoned": 0}

    def shared(self, task: asyncio.Task) -> bool:
        """`task`가 리더이고 합류한 다른 요청이 그 결과를 기다리는지."""
        flight = self._leading.get(task)
        return flight is not None and flight.followers > 0

    async def run(self, key: Hashable | None, compute: Callable[[], Awaitable[Any]], *,
                  on_timeout: Callable[[], Awaitable[None]] | None = None) -> Any:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.deadline_seconds
        while key is not None and (joined := self.pending.get(key)) is not None:
            self.stats["coalesced"] += 1
            joined.followers += 1
            try:
                async with asyncio.timeout_at(deadline):
                    shared = await asyncio.shield(joined.future)
            except TimeoutError as exc:
                self._timed_out("follower")
                raise timeout_error() from exc
            finally:
                joined.followers -= 1
            if shared is _RESTART:
                continue
            ok, value = shared
            if not ok:
                raise value
            return _copy(value)

        if self._slots.locked() and self.waiting >= self.max_waiting:
            self.stats["rejected"] += 1
            logger.warning("places_admission_rejected running=%s waiting=%s", self.running, self.waiting)
            raise busy_error()

        task = asyncio.current_task()
        flight: _Flight | None = None
        outcome: Any = _RESTART
        try:
            try:
                async with asyncio.timeout_at(deadline):
                    if self._slots.locked():
                        flight = _Flight(loop.create_future())
                        self._leading[task] = flight
                        if key is not None:
                            self.pending[key] = flight
                        self.waiting += 1
                        try:
                            await self._slots.acquire()
                        finally:
                            self.waiting -= 1
                            # 읽기를 시작한 계산에는 새 요청을 합류시키지 않는다(모듈 설명 참고).
                            if key is not None and self.pending.get(key) is flight:
                                del self.pending[key]
                    else:
                        await self._slots.acquire()
                    self.running += 1
                    try:
                        result = await compute()
                    finally:
                        self.running -= 1
                        self._slots.release()
            except TimeoutError as exc:
                if on_timeout is not None:
                    try:
                        await on_timeout()
                    except Exception:  # 응답은 504로 정한다. 연결 정리는 session 종료가 마저 한다.
                        logger.warning("places_timeout_cleanup_failed", exc_info=True)
                self._timed_out("leader")
                raise timeout_error() from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            outcome = (False, exc)
            raise
        else:
            outcome = (True, result)
            return result
        finally:
            if flight is not None:
                self._leading.pop(task, None)
                if not flight.future.done():
                    flight.future.set_result(outcome)

    def _timed_out(self, role: str) -> None:
        self.stats["timed_out"] += 1
        logger.warning("places_deadline_exceeded role=%s running=%s waiting=%s deadline_s=%s",
                       role, self.running, self.waiting, self.deadline_seconds)


def _copy(value: Any) -> Any:
    # FastAPI가 반환된 Response에 요청별 background를 붙이므로 같은 객체를 여러 요청에 돌려주지 않는다.
    if isinstance(value, Response):
        copy = Response(content=value.body, status_code=value.status_code)
        copy.raw_headers = list(value.raw_headers)
        return copy
    return value


def request_key(arguments: dict[str, Any]) -> tuple | None:
    """FastAPI가 해석한 query 값으로 만든 키. 해시할 수 없는 값이 있으면 합치지 않는다."""
    key = tuple(sorted((name, value) for name, value in arguments.items() if name not in ("request", "session")))
    try:
        hash(key)
    except TypeError:
        return None
    return key


def limit_statement_time(session) -> None:
    """이 요청 session이 여는 PostgreSQL transaction마다 `SET LOCAL statement_timeout`을 둔다.

    transaction 시작 직후에 실행하므로 page cache 증명이 고르는 격리 수준(REPEATABLE READ)과 첫 snapshot을
    바꾸지 않는다. `SET`은 snapshot을 잡거나 xid를 할당하지 않는다.
    """
    if session is None or session.get_bind().dialect.name != "postgresql":
        return

    def apply(_session, _transaction, connection) -> None:
        connection.exec_driver_sql(_SET_STATEMENT_TIMEOUT)

    event.listen(session.sync_session, "after_begin", apply)


async def client_disconnected(receive: Callable[[], Awaitable[dict]]) -> None:
    """`http.disconnect`가 올 때까지 기다린다(Starlette `StreamingResponse.listen_for_disconnect`와 같은 방식).

    GET 본문(빈 `http.request`)은 FastAPI가 endpoint 전에 읽지 않으므로 여기서 소비해도 된다. 응답 전에
    `http.disconnect`가 오는 경우는 클라이언트(BFF·gateway)가 연결을 닫은 경우뿐이다.
    """
    while (await receive())["type"] != "http.disconnect":
        pass


async def _settle(task: asyncio.Task) -> None:
    with suppress(asyncio.CancelledError, Exception):
        await task


def place_map_admission(handler):
    """route handler를 `PlaceMapGate`로 감싼다. FastAPI는 `__wrapped__`의 signature로 인자를 푼다."""

    @wraps(handler)
    async def wrapped(**arguments: Any):
        request = arguments["request"]
        session = arguments.get("session")
        state = request.app.state
        gate = getattr(state, "place_map_gate", None)
        if gate is None:
            gate = state.place_map_gate = PlaceMapGate()

        async def compute():
            limit_statement_time(session)
            return await handler(**arguments)

        async def rollback() -> None:
            if session is not None:
                await session.rollback()

        # task를 만들기 전에 필요한 값을 모두 읽는다. 둘째 task 생성이 실패해 첫 task가 남는 일이 없게 한다.
        receive, key = request.receive, request_key(arguments)
        work = asyncio.ensure_future(gate.run(key, compute, on_timeout=rollback))
        gone = asyncio.ensure_future(client_disconnected(receive))
        try:
            await asyncio.wait((work, gone), return_when=asyncio.FIRST_COMPLETED)
            # receive 자체가 실패하면(서버 구현 차이) 끊김으로 보지 않고 계산을 그대로 기다린다.
            if not work.done() and gone.exception() is None and not gate.shared(work):
                # 받을 곳이 없는 계산·대기열 자리를 놓는다. 합류한 요청이 있으면 그들을 위해 끝까지 계산한다.
                work.cancel()
                await _settle(work)
                gate.stats["abandoned"] += 1
                logger.info("places_client_disconnected running=%s waiting=%s", gate.running, gate.waiting)
                with suppress(Exception):
                    await rollback()
                return Response(status_code=CLIENT_CLOSED_STATUS)
            return await work
        finally:
            for task in (gone, work):
                if not task.done():
                    task.cancel()
                    await _settle(task)

    return wrapped
