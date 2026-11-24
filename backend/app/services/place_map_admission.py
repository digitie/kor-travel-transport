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
  rollback한 뒤 504를 낸다. 리더가 계산을 시작하기도 전에(슬롯 대기 중) 시한이 지나면 합류한 요청은
  리더의 504를 받지 않고 자기 시한으로 다시 판단한다. 서버 쪽 문장 상한은 `limit_statement_time`을 본다.
- 연결 끊김: 브라우저가 이전 조회를 취소하면 관리 BFF·공개 gateway가 upstream 연결을 닫는다. Starlette는
  일반 endpoint를 연결 끊김으로 취소하지 않으므로, `StreamingResponse`처럼 `receive()`로 `http.disconnect`를
  기다리다가 오면 대기열 자리나 계산을 취소한다. 합류한 다른 요청이 결과를 기다리는 리더는 그들을 위해
  계산을 이어 가되, 합류한 요청까지 모두 떠나면 그때 취소한다.
- 호출자별 몫(2026-11-24 후속): 공개 listener(:12301 transport-api, :12307 fuel)와 관리 화면(BFF → :12302)이
  슬롯 하나를 나눠 쓰면 익명 공개 요청이 관리 `/map`을 굶길 수 있다. 그래서 요청을 `admin`·`public` 두 줄로
  나눈다. 공개 요청은 동시 계산 `max_running - admin_reserved`건까지만 쓰고, 대기열도 줄마다 따로 센다
  (`max_waiting`·`admin_max_waiting`). 슬롯이 비면 관리 대기 요청을 먼저 깨운다. 관리 판정은 위조할 수 없는
  신호만 쓴다 — 관리 BFF가 붙이는 32자 이상 관리자 토큰(`x-transport-admin-token`, 상수 시간 비교)이 맞고,
  공개 gateway가 클라이언트 값을 덮어쓰는 `x-transport-listener` header가 **없을** 때만 관리다. 그 밖은 모두
  공개다(토큰을 설정하지 않은 배포는 관리 화면도 공개 몫을 쓴다).
"""
from __future__ import annotations

import asyncio
import logging
import math
import secrets
from collections import deque
from collections.abc import Awaitable, Callable, Hashable, Mapping
from contextlib import suppress
from functools import wraps
from typing import Any, TypeVar

from anyio import CapacityLimiter, to_thread
from fastapi import HTTPException
from sqlalchemy import event
from starlette.responses import Response

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: 도착부터 응답까지의 전체 시한(초) 기본값. 공개 fuel gateway `proxy_read_timeout`과 관리 BFF의 30초보다 짧다.
#: 운영 값은 `PLACES_DEADLINE_SECONDS`(설정 상한 25초)로 바꾼다.
PLACES_DEADLINE_SECONDS = 25.0
#: 동시에 DB 계산을 하는 장소 지도 요청 수 기본값(`PLACES_MAX_RUNNING`). API 풀 10개 중 나머지는
#: export·`/health`·이력 캐시 몫이다.
PLACES_MAX_RUNNING = 4
#: 실행 슬롯을 기다릴 수 있는 요청 수 기본값(`PLACES_MAX_WAITING`). 넘치면 즉시 429다(합류한 동일 요청은 세지 않는다).
PLACES_MAX_WAITING = 8
#: 혼잡(입장 거절) 재시도 안내(초). 지도 화면은 5초 이하이면 같은 조건으로 한 번 자동 재조회한다.
BUSY_RETRY_AFTER_SECONDS = 2
#: 시한 초과 재시도 안내(초). 25초를 쓰고 실패한 계산을 화면이 곧바로 되풀이하지 않게 5초보다 길게 둔다.
TIMEOUT_RETRY_AFTER_SECONDS = 10
#: 연결이 끊긴 요청의 기록용 상태(nginx `client closed request`). 받을 클라이언트는 없다.
CLIENT_CLOSED_STATUS = 499
#: 입장 거절 경고 로그의 최소 간격(초). 혼잡할 때 거절마다 한 줄씩 쓰지 않고 그 사이 건수를 함께 남긴다.
REJECT_LOG_INTERVAL_SECONDS = 10.0
#: 관리 화면 몫으로 남겨 두는 동시 계산 수 기본값(`PLACES_ADMIN_RESERVED_RUNNING`). 공개 요청은 나머지만 쓴다.
PLACES_ADMIN_RESERVED_RUNNING = 1
#: 관리 화면 요청의 대기열 길이 기본값(`PLACES_ADMIN_MAX_WAITING`). 공개 대기열과 따로 센다.
PLACES_ADMIN_MAX_WAITING = 4
#: 시한 초과 뒤 rollback에 쓰는 최대 시간(초). 시한(기본 25초) + 이 값이 BFF·gateway 30초 안에 들어야 한다.
#: 넘기면 rollback을 기다리지 않고 504를 낸다(연결은 session 종료가 마저 정리한다).
TIMEOUT_CLEANUP_GRACE_SECONDS = 2.0
#: 앞단(관리 BFF `fetchNoStore`·공개 gateway `proxy_read_timeout`)의 시한(초). 시한 초과 로그의 여유 계산용.
UPSTREAM_PROXY_TIMEOUT_SECONDS = 30.0

ADMIN = "admin"
PUBLIC = "public"
#: 공개 gateway가 `proxy_set_header`로 덮어쓰는 표지. 값과 관계없이 있으면 공개 요청이다.
LISTENER_HEADER = "x-transport-listener"
ADMIN_TOKEN_HEADER = "x-transport-admin-token"

# 리더가 결과 없이 끝나면(연결 끊김·종료·계산 시작 전 시한 초과) 합류한 요청은 처음부터 다시 판단한다.
_RESTART = object()


def busy_error() -> HTTPException:
    return HTTPException(
        status_code=429, detail="장소 지도 조회가 혼잡합니다. 잠시 후 다시 시도하세요.",
        headers={"Retry-After": str(BUSY_RETRY_AFTER_SECONDS)},
    )


def timeout_error(*, queued: bool = False) -> HTTPException:
    detail = ("장소 지도 조회가 혼잡해 시간 안에 시작하지 못했습니다. 잠시 후 다시 시도하세요." if queued
              else "장소 지도 조회 시간이 초과되었습니다. 지도 범위를 좁히거나 잠시 후 다시 시도하세요.")
    return HTTPException(status_code=504, detail=detail, headers={"Retry-After": str(TIMEOUT_RETRY_AFTER_SECONDS)})


class _Flight:
    """슬롯을 기다리는(또는 기다렸던) 리더 하나의 결과와, 그 결과를 함께 기다리는 요청 수."""

    __slots__ = ("future", "followers", "task", "started", "abandoned")

    def __init__(self, future: asyncio.Future, task: asyncio.Task | None) -> None:
        self.future = future
        self.followers = 0
        self.task = task
        # 슬롯을 얻어 계산을 시작했는지. 시작 전에 시한이 지나면 합류한 요청은 다시 판단한다.
        self.started = False
        # 리더 자신의 클라이언트가 떠났는지. 합류한 요청이 모두 떠나면 계산을 취소한다.
        self.abandoned = False


class PlaceMapGate:
    """event loop 하나(앱 lifespan)에 속한 입장 제한기. 모든 상태 변경은 같은 loop에서 await 없이 일어난다."""

    def __init__(self, *, max_running: int = PLACES_MAX_RUNNING, max_waiting: int = PLACES_MAX_WAITING,
                 deadline_seconds: float = PLACES_DEADLINE_SECONDS, admin_reserved: int = 0,
                 admin_max_waiting: int = PLACES_ADMIN_MAX_WAITING, admin_token: str | None = None) -> None:
        if (max_running < 1 or max_waiting < 0 or admin_max_waiting < 0 or not 0 <= admin_reserved < max_running
                or not deadline_seconds > 0 or not math.isfinite(deadline_seconds)):
            raise ValueError("장소 지도 입장 제한 값이 올바르지 않습니다.")
        self.max_running = max_running
        self.max_waiting = max_waiting
        self.deadline_seconds = deadline_seconds
        self.admin_max_waiting = admin_max_waiting
        # 관리 판정용 토큰. 32자 미만이면 관리 줄을 쓰지 않는다(관리 경로 guard와 같은 조건).
        token = (admin_token or "").encode("utf-8")
        self._admin_token = token if len(token) >= 32 else None
        # 관리 요청을 알아볼 수 없으면 남겨 둔 몫은 아무도 쓰지 못한다. 그때는 공개 요청에 모두 준다.
        self.admin_reserved = admin_reserved if self._admin_token is not None else 0
        self._lane_running = {ADMIN: 0, PUBLIC: 0}
        self._lane_waiting = {ADMIN: 0, PUBLIC: 0}
        # 슬롯을 기다리는 (줄, future). 슬롯이 비면 관리 줄을 먼저, 줄 안에서는 도착 순으로 깨운다.
        self._queue: deque[tuple[str, asyncio.Future]] = deque()
        # 아직 슬롯을 기다리는 리더의 결과. 실행을 시작하면 바로 뺀다(새 합류 차단).
        self.pending: dict[Hashable, _Flight] = {}
        # 대기열에 줄을 섰던 리더 task → 그 결과를 기다리는 요청 수(연결 끊김 취소 판단용).
        self._leading: dict[asyncio.Task, _Flight] = {}
        # 운영 판단용 누계(프로세스 단위). 거절·시한·끊김은 로그도 남긴다.
        self.stats = {"coalesced": 0, "rejected": 0, "timed_out": 0, "abandoned": 0}
        self._last_reject_log: dict[str, float] = {}
        self._rejects_since_log = {ADMIN: 0, PUBLIC: 0}

    @property
    def running(self) -> int:
        return self._lane_running[ADMIN] + self._lane_running[PUBLIC]

    @property
    def waiting(self) -> int:
        return self._lane_waiting[ADMIN] + self._lane_waiting[PUBLIC]

    def lane_running(self, lane: str) -> int:
        return self._lane_running[lane]

    def lane_waiting(self, lane: str) -> int:
        return self._lane_waiting[lane]

    def lane_for(self, headers: Mapping[str, str] | None) -> str:
        """요청 header로 줄을 고른다. 공개 gateway 표지가 있거나 관리자 토큰이 맞지 않으면 공개다."""
        if headers is None or self._admin_token is None or headers.get(LISTENER_HEADER) is not None:
            return PUBLIC
        provided = headers.get(ADMIN_TOKEN_HEADER, "").encode("utf-8")
        return ADMIN if secrets.compare_digest(self._admin_token, provided) else PUBLIC

    def _has_room(self, lane: str) -> bool:
        if self.running >= self.max_running:
            return False
        return lane == ADMIN or self._lane_running[PUBLIC] < self.max_running - self.admin_reserved

    async def _acquire(self, lane: str) -> None:
        if self._has_room(lane):
            self._lane_running[lane] += 1
            return
        entry = (lane, asyncio.get_running_loop().create_future())
        self._queue.append(entry)
        try:
            await entry[1]
        except BaseException:
            if entry[1].done() and not entry[1].cancelled():
                # 슬롯을 받은 직후 취소됐다. 받은 슬롯을 돌려준다.
                self._release(lane)
            else:
                with suppress(ValueError):
                    self._queue.remove(entry)
            raise

    def _release(self, lane: str) -> None:
        self._lane_running[lane] -= 1
        # 빈 슬롯은 관리 대기 요청에 먼저 준다. 줄 안에서는 도착 순서다.
        for wanted in (ADMIN, PUBLIC):
            for entry in list(self._queue):
                lane_of, future = entry
                if lane_of != wanted:
                    continue
                if future.done():
                    self._queue.remove(entry)
                    continue
                if not self._has_room(lane_of):
                    break
                self._queue.remove(entry)
                self._lane_running[lane_of] += 1
                future.set_result(None)

    def abandon(self, task: asyncio.Task) -> bool:
        """리더 `task`의 클라이언트가 떠났다. 지금 취소해도 되면 True.

        합류한 요청이 결과를 기다리면 False를 돌려주고 표시만 한다. 그 요청들이 모두 떠나면(받거나 끊기거나
        시한이 지나면) 마지막으로 떠나는 요청이 리더 계산을 취소한다.
        """
        flight = self._leading.get(task)
        if flight is None or flight.followers == 0:
            return True
        flight.abandoned = True
        return False

    async def run(self, key: Hashable | None, compute: Callable[[], Awaitable[Any]], *,
                  deadline: float | None = None,
                  on_timeout: Callable[[], Awaitable[None]] | None = None, lane: str = PUBLIC) -> Any:
        if lane not in (ADMIN, PUBLIC):
            raise ValueError(f"알 수 없는 장소 지도 줄: {lane}")
        loop = asyncio.get_running_loop()
        if deadline is None:
            deadline = loop.time() + self.deadline_seconds
        arrived = deadline - self.deadline_seconds
        # 줄이 다르면 합치지 않는다. 공개 리더에 합류한 관리 요청이 공개 대기열 순서를 기다리지 않게 한다.
        if key is not None and lane == ADMIN:
            key = (ADMIN, key)
        while key is not None and (joined := self.pending.get(key)) is not None:
            self.stats["coalesced"] += 1
            joined.followers += 1
            try:
                async with asyncio.timeout_at(deadline):
                    shared = await asyncio.shield(joined.future)
            except TimeoutError as exc:
                self._timed_out("follower", lane, loop.time() - arrived)
                raise timeout_error(queued=not joined.started) from exc
            finally:
                joined.followers -= 1
                if joined.followers == 0 and joined.abandoned and joined.task is not None and not joined.task.done():
                    # 리더의 클라이언트도, 합류한 요청도 모두 떠났다. 받을 곳 없는 계산을 멈춘다.
                    joined.task.cancel()
            if shared is _RESTART:
                continue
            ok, value = shared
            if not ok:
                raise value
            return _copy(value)

        waiting_limit = self.admin_max_waiting if lane == ADMIN else self.max_waiting
        if not self._has_room(lane) and self._lane_waiting[lane] >= waiting_limit:
            self._rejected(loop, lane)
            raise busy_error()

        task = asyncio.current_task()
        flight: _Flight | None = None
        outcome: Any = _RESTART
        scope = asyncio.timeout_at(deadline)
        try:
            async with scope:
                if not self._has_room(lane):
                    flight = _Flight(loop.create_future(), task)
                    if task is not None:
                        self._leading[task] = flight
                    if key is not None:
                        self.pending[key] = flight
                    self._lane_waiting[lane] += 1
                    try:
                        await self._acquire(lane)
                    finally:
                        self._lane_waiting[lane] -= 1
                        # 읽기를 시작한 계산에는 새 요청을 합류시키지 않는다(모듈 설명 참고).
                        if key is not None and self.pending.get(key) is flight:
                            del self.pending[key]
                    flight.started = True
                else:
                    await self._acquire(lane)
                try:
                    result = await compute()
                finally:
                    self._release(lane)
        except TimeoutError as exc:
            if not scope.expired():
                # 계산 자체가 낸 TimeoutError(우리 시한이 아님)는 일반 오류로 전한다.
                outcome = (False, exc)
                raise
            started = flight is None or flight.started
            if on_timeout is not None:
                try:
                    # rollback이 멈춰도(서버 무응답 등) 504가 앞단 30초 안에 나가도록 기다림에 상한을 둔다.
                    async with asyncio.timeout(TIMEOUT_CLEANUP_GRACE_SECONDS):
                        await on_timeout()
                except TimeoutError:
                    logger.warning("places_timeout_cleanup_slow grace_s=%s", TIMEOUT_CLEANUP_GRACE_SECONDS)
                except Exception:  # 응답은 504로 정한다. 연결 정리는 session 종료가 마저 한다.
                    logger.warning("places_timeout_cleanup_failed", exc_info=True)
            self._timed_out("leader" if started else "queued", lane, loop.time() - arrived)
            error = timeout_error(queued=not started)
            if started:
                # 계산이 시한을 넘겼다. 같은 계산을 기다린 요청에게도 같은 결과다.
                outcome = (False, error)
            # 슬롯을 기다리다 시한이 지났으면 합류한 요청은 늦게 왔으므로 자기 시한으로 다시 판단한다(_RESTART).
            raise error from exc
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
                if task is not None:
                    self._leading.pop(task, None)
                if not flight.future.done():
                    flight.future.set_result(outcome)

    def _rejected(self, loop: asyncio.AbstractEventLoop, lane: str) -> None:
        self.stats["rejected"] += 1
        self._rejects_since_log[lane] += 1
        now = loop.time()
        last = self._last_reject_log.get(lane)
        if last is None or now - last >= REJECT_LOG_INTERVAL_SECONDS:
            # 간격은 줄마다 잰다. 공개 거절이 쏟아져도 관리 거절 한 줄은 바로 남는다.
            logger.warning("places_admission_rejected lane=%s running=%s waiting=%s lane_running=%s "
                           "lane_waiting=%s rejected_since_last_log=%s total=%s", lane, self.running, self.waiting,
                           self._lane_running[lane], self._lane_waiting[lane], self._rejects_since_log[lane],
                           self.stats["rejected"])
            self._last_reject_log[lane] = now
            self._rejects_since_log[lane] = 0

    def _timed_out(self, role: str, lane: str, elapsed: float) -> None:
        """시한 초과 기록. `elapsed_ms`는 도착부터 504를 정한 순간(rollback 뒤)까지이고, `proxy_margin_ms`는
        앞단 30초 시한까지 남은 여유다. 운영에서 이 값이 줄면 시한·rollback 상한을 다시 본다."""
        self.stats["timed_out"] += 1
        elapsed_ms = elapsed * 1000
        logger.warning("places_deadline_exceeded role=%s lane=%s running=%s waiting=%s deadline_s=%s "
                       "elapsed_ms=%.0f proxy_margin_ms=%.0f", role, lane, self.running, self.waiting,
                       self.deadline_seconds, elapsed_ms, UPSTREAM_PROXY_TIMEOUT_SECONDS * 1000 - elapsed_ms)


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


def limit_statement_time(session, deadline: float, loop: asyncio.AbstractEventLoop) -> None:
    """이 요청 session이 여는 PostgreSQL transaction마다 `SET LOCAL statement_timeout`을 둔다.

    값은 그 transaction을 시작하는 순간 남은 전체 시한(ms, 최소 1)이다. PostgreSQL은 이 상한을 transaction이
    아니라 **문장마다** 그 문장의 시작부터 잰다. 그래서 transaction의 첫 문장은 전체 시한에 끝나고, 같은
    transaction의 뒤 문장은 transaction 시작 뒤 흐른 시간만큼 시한을 넘길 수 있다. 전체 시한 자체는
    `PlaceMapGate`의 asyncio 시한이 문장을 클라이언트 쪽에서 취소해 지킨다. 서버 상한은 그 취소가 서버에 닿지
    않을 때(연결 유실 등)의 안전판이며, 다른 경로의 엔진 기본 상한(120초)은 바꾸지 않는다.

    transaction 시작 직후에 실행하므로 page cache 증명이 고르는 격리 수준(REPEATABLE READ)과 첫 snapshot을
    바꾸지 않는다. `SET`은 snapshot을 잡거나 xid를 할당하지 않는다.
    """
    if session is None or session.get_bind().dialect.name != "postgresql":
        return

    def apply(_session, _transaction, connection) -> None:
        remaining_ms = max(1, math.ceil((deadline - loop.time()) * 1000))
        connection.exec_driver_sql(f"SET LOCAL statement_timeout = '{remaining_ms}ms'")

    event.listen(session.sync_session, "after_begin", apply)


async def run_in_thread_holding(limiter: CapacityLimiter, function: Callable[..., T], *args: Any) -> T:
    """`limiter` 토큰을 얻어 `function`을 thread에서 실행한다.

    호출자가 취소돼도(연결 끊김·시한) thread는 멈출 수 없다. 그래서 토큰은 호출자가 아니라 thread 실행에 묶어
    thread가 끝날 때 반납한다. 끊김이 잦아도 동시에 도는 검증 thread 수가 limiter 안에 머문다. 취소된 호출의
    결과는 버린다. 토큰을 얻기 전의 대기는 그대로 취소되므로 아직 시작하지 않은 검증은 돌리지 않는다.
    """
    borrower = object()
    await limiter.acquire_on_behalf_of(borrower)
    try:
        work = asyncio.ensure_future(to_thread.run_sync(function, *args))
    except BaseException:
        limiter.release_on_behalf_of(borrower)
        raise

    def finished(done: asyncio.Future) -> None:
        limiter.release_on_behalf_of(borrower)
        if not done.cancelled():
            done.exception()  # 호출자가 떠난 뒤의 실패도 소비해 "never retrieved" 경고를 남기지 않는다.

    work.add_done_callback(finished)
    return await asyncio.shield(work)


async def client_disconnected(receive: Callable[[], Awaitable[dict]]) -> None:
    """`http.disconnect`가 올 때까지 기다린다(Starlette `StreamingResponse.listen_for_disconnect`와 같은 방식).

    GET 본문(빈 `http.request`)은 FastAPI가 endpoint 전에 읽지 않으므로 여기서 소비해도 된다. 응답 전에
    `http.disconnect`가 오는 경우는 클라이언트(BFF·gateway)가 연결을 닫은 경우뿐이다.
    """
    while (await receive())["type"] != "http.disconnect":
        pass


async def _settle(task: asyncio.Task) -> None:
    """`task`가 끝날 때까지 기다리고 그 결과·예외를 소비한다. 이 coroutine 자신의 취소(종료)는 그대로 전한다."""
    await asyncio.wait({task})
    if not task.cancelled():
        task.exception()


def _gate(state) -> PlaceMapGate:
    gate = getattr(state, "place_map_gate", None)
    if gate is None:
        gate = state.place_map_gate = PlaceMapGate()
    return gate


def place_map_admission(handler):
    """route handler를 `PlaceMapGate`로 감싼다. FastAPI는 `__wrapped__`의 signature로 인자를 푼다."""

    @wraps(handler)
    async def wrapped(**arguments: Any):
        request = arguments["request"]
        session = arguments.get("session")
        gate = _gate(request.app.state)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + gate.deadline_seconds
        # task를 만들기 전에 필요한 값을 모두 읽는다. 둘째 task 생성이 실패해 첫 task가 남는 일이 없게 한다.
        receive, key = request.receive, request_key(arguments)
        lane = gate.lane_for(getattr(request, "headers", None))

        async def compute():
            limit_statement_time(session, deadline, loop)
            return await handler(**arguments)

        async def rollback() -> None:
            if session is not None:
                await session.rollback()

        async def abandoned() -> Response:
            gate.stats["abandoned"] += 1
            logger.info("places_client_disconnected lane=%s running=%s waiting=%s", lane, gate.running, gate.waiting)
            with suppress(Exception):
                await rollback()
            return Response(status_code=CLIENT_CLOSED_STATUS)

        work = asyncio.ensure_future(gate.run(key, compute, deadline=deadline, on_timeout=rollback, lane=lane))
        gone = asyncio.ensure_future(client_disconnected(receive))
        try:
            await asyncio.wait((work, gone), return_when=asyncio.FIRST_COMPLETED)
            # receive 자체가 실패하면(서버 구현 차이) 끊김으로 보지 않고 계산을 그대로 기다린다.
            if not work.done() and gone.exception() is None:
                if gate.abandon(work):
                    # 받을 곳이 없는 계산·대기열 자리를 놓는다.
                    work.cancel()
                    await _settle(work)
                    return await abandoned()
                # 합류한 요청이 결과를 기다린다. 그들이 모두 떠나면 마지막 요청이 이 계산을 취소한다.
                await _settle(work)
                if work.cancelled():
                    return await abandoned()
            return await work
        finally:
            for task in (gone, work):
                if not task.done():
                    task.cancel()
                    await _settle(task)

    return wrapped
