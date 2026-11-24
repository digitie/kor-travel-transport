"""RFC 7807 problem의 기계 판독 사유 `code`와 `Retry-After` (ADR-013 개정 2026-11-24).

오류 본문은 지금처럼 `type/title/status/detail/instance` problem+json이고 한국어 `detail` 문장도 그대로다.
여기에 가산 확장 멤버 `code`(UPPER_SNAKE 문자열)와 HTTP `Retry-After: <정수 초>` 헤더를 더한다. `code`가 없는
응답은 지금까지와 정확히 같은 뜻이다 — 소비자(kor-travel-map)는 `code`가 없거나 모르는 값이면 기존 동작으로
돌아간다. 계약 전문은 `docs/map-service-exports-handoff.md`의 "503 사유 code와 Retry-After" 절이다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from fastapi import HTTPException
from kortravelcommon.pg_errors import pg_error_info
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core.time_utils import serialize_utc


class ProblemCode(StrEnum):
    #: T1 참조 집합(주유소·휴게소·휴게소 유가·공공 주차장)의 근거 수집 마지막 성공이 stale 기준을 넘었다.
    #: 다음 정기 수집이 성공하기 전에는 풀리지 않는다.
    EXPORT_SOURCE_NOT_CURRENT = "EXPORT_SOURCE_NOT_CURRENT"
    #: 근거 수집이 한 번도 성공하지 않았다(T2/T3는 설정에 활성인 scope의 승인 head가 아직 없다).
    EXPORT_NO_HISTORY = "EXPORT_NO_HISTORY"
    #: 고속도로 돌발 활성 집합이 "지금"이 아니다(마지막 시도 실패·30분 초과). #265 뒤 0건 수집도 실패(last_error)로
    #: 남으므로 0건은 대부분 이 code로 나온다.
    EXPORT_INCIDENTS_NOT_CURRENT = "EXPORT_INCIDENTS_NOT_CURRENT"
    #: 상태는 현재인데 낼 집합이 0건이라 삭제로 읽히지 않게 내지 않는다. 돌발은 INCIDENT-EMPTY-SET 안전망(옛 "0건
    #: 성공" 상태 등), T3 기준정보는 완결 증거가 있는 head의 membership이 0건인 경우다.
    EXPORT_EMPTY_SET = "EXPORT_EMPTY_SET"
    #: snapshot admission 경합(55P03·40P01 재시도 뒤, 반복 40001·SnapshotRace, 경합 뒤 재시도가 예산을 다 씀).
    #: 수 초 안에 풀린다.
    EXPORT_BUSY = "EXPORT_BUSY"
    #: 요청 경로 본문 구성 예산(15초) 초과, snapshot 작업 안의 statement timeout(57014), 또는 본문 구성 중
    #: export handler 전체 상한(25초) 초과.
    EXPORT_PREPARE_TIMEOUT = "EXPORT_PREPARE_TIMEOUT"
    #: T4 가격 이력 transaction의 문장 상한(`fuel_price_history_statement_timeout_ms`, 기본 3초)에 걸린 57014.
    #: 같은 조회를 곧바로 반복하지 않도록 짧게(5초) 기다린 뒤 다시 묻는다.
    EXPORT_QUERY_TIMEOUT = "EXPORT_QUERY_TIMEOUT"
    #: T2/T3 export가 설정(`TRANSPORT_MAP_CURRENT_ENABLED=false`)으로 꺼져 있거나, 그 기준정보의 source가 하나도
    #: 설정되지 않았다(예: 주차장 source 없음). 운영 설정을 바꿔야 풀린다.
    EXPORT_DISABLED = "EXPORT_DISABLED"
    #: 승인 head·membership·본문·handle이 서로 맞지 않거나 필수 이름·코드가 비었다. 다음 수집·준비가 고친다.
    EXPORT_SOURCE_INCONSISTENT = "EXPORT_SOURCE_INCONSISTENT"
    #: 고정 집합이 export 행 수·바이트 상한을 넘었다. 데이터·상한이 바뀌기 전에는 결정적으로 같다.
    EXPORT_TOO_LARGE = "EXPORT_TOO_LARGE"
    #: `/v1/service/exports/*`에서 pool checkout timeout·DB 접속 실패·PG 기동 중(57P03)·접속 수 초과(53300)·끊긴
    #: 연결 같은 일시 DB 불가, 또는 본문 구성 밖에서 export handler 전체 상한(25초) 초과. 다른 경로는 예전처럼 500이다.
    TRANSIENT_DB = "TRANSIENT_DB"


#: code별 기본 `Retry-After`(초). **힌트다** — 소비자가 정기 polling을 멈출 근거가 아니고, 값은 계약이 아니라 운영
#: 중에 바뀔 수 있다(계약은 code의 뜻이다). EXPORT_SOURCE_NOT_CURRENT는 수집 상태로 `source_retry_after_seconds`를
#: 계산하고, EXPORT_NO_HISTORY는 5분 주기 집합이면 `FAST_SOURCE_RETRY_AFTER_SECONDS`를 쓴다.
RETRY_AFTER_SECONDS: dict[ProblemCode, int] = {
    ProblemCode.EXPORT_SOURCE_NOT_CURRENT: 1800,
    ProblemCode.EXPORT_NO_HISTORY: 3600,
    ProblemCode.EXPORT_INCIDENTS_NOT_CURRENT: 300,
    ProblemCode.EXPORT_EMPTY_SET: 300,
    ProblemCode.EXPORT_BUSY: 10,
    ProblemCode.EXPORT_PREPARE_TIMEOUT: 60,
    ProblemCode.EXPORT_QUERY_TIMEOUT: 5,
    ProblemCode.EXPORT_DISABLED: 3600,
    ProblemCode.EXPORT_SOURCE_INCONSISTENT: 300,
    ProblemCode.EXPORT_TOO_LARGE: 3600,
    ProblemCode.TRANSIENT_DB: 15,
}
#: TRANSIENT_DB 503과 snapshot 57014 503을 적용하는 경로 접두어. 공개·관리 경로는 일시 DB 오류도 예전처럼
#: 500이다 — 관리 유가 화면은 가격 이력 경로의 어떤 503이든 "수집 이력 없음"으로 보여 준다
#: (`packages/kor-travel-transport-admin/frontend/components/fuel-station-history.tsx`).
SERVICE_EXPORT_PATH_PREFIX = "/v1/service/exports/"
#: EXPORT_SOURCE_NOT_CURRENT 계산값의 하한·상한(초). 상한은 1시간이다 — 다음 정기 수집이 7시간 뒤여도 그 사이
#: 수동·복구 수집이 성공할 수 있고, 힌트를 넘겨 짚어 늦게 다시 묻는 쪽(최신 집합을 놓침)이 몇 번 더 묻는 쪽(싼 503)보다 나쁘다.
SOURCE_RETRY_AFTER_MIN_SECONDS = 60
SOURCE_RETRY_AFTER_MAX_SECONDS = 3600
#: 진행 중인 수집이 예상 수행 시간을 넘겼을 때 다시 볼 간격(초).
SOURCE_RUN_OVERRUN_RETRY_SECONDS = 300
#: 진행 중 판정에서 실패 기록(`updated_at`)과 시작 기록(`last_started_at`)의 시계 차이 허용(같은 claim의 두 now_utc()).
_START_RECORD_TOLERANCE = timedelta(seconds=5)
#: 5분 주기 집합(교통 current·주차장 current·고속도로 돌발)의 이력 없음 Retry-After(초).
FAST_SOURCE_RETRY_AFTER_SECONDS = 300

TRANSIENT_DB_DETAIL = "데이터베이스에 잠시 연결할 수 없습니다. 잠시 후 다시 요청하세요."
#: 일시 DB 불가로 보는 SQLSTATE. 57P01/57P02(관리자·충돌 종료)는 PG 재시작 창, 57P03은 기동 중,
#: 53300은 접속 수 초과다. class 08(connection exception)은 접두어로 따로 보되 08P01(protocol_violation)은 뺀다 —
#: driver·서버 버전 불일치 같은 결정적 문제라 다시 불러도 같다.
TRANSIENT_SQLSTATES = frozenset({"57P01", "57P02", "57P03", "53300"})
NON_TRANSIENT_CONNECTION_SQLSTATES = frozenset({"08P01"})


class CodedHTTPException(HTTPException):
    """`code`와 `Retry-After`를 싣는 HTTPException. problem handler가 본문에 `code`를 더한다."""

    def __init__(
        self, status_code: int, detail: Any, *, code: ProblemCode, retry_after: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        seconds = RETRY_AFTER_SECONDS[code] if retry_after is None else retry_after
        seconds = max(1, int(seconds))
        super().__init__(status_code=status_code, detail=detail,
                         headers={**(headers or {}), "Retry-After": str(seconds)})
        self.code = code
        self.retry_after = seconds


def unavailable(code: ProblemCode, detail: str, *, retry_after: int | None = None) -> CodedHTTPException:
    """503 + `code` + `Retry-After`. 호출자는 `raise unavailable(...)`로 쓴다."""
    return CodedHTTPException(503, detail, code=code, retry_after=retry_after)


def _clamp_source_seconds(seconds: float) -> int:
    return min(max(int(seconds), SOURCE_RETRY_AFTER_MIN_SECONDS), SOURCE_RETRY_AFTER_MAX_SECONDS)


def _aware(value: datetime | None) -> datetime | None:
    return serialize_utc(value) if value is not None else None


def source_retry_after_seconds(state: Any, expected_run: timedelta, *, now: datetime) -> int:
    """stale T1 집합의 `Retry-After` 힌트(초). 새 성공이 보일 것으로 기대되는 때까지, [60, 3600]으로 자른다.

    `state`는 `TransportCollectionState`(또는 같은 이름의 속성을 가진 객체)다.

    - **수집이 진행 중**(마지막 시작이 마지막 성공보다 뒤이고 그 뒤 실패 기록이 없으며, 시작한 지 예상 수행 시간의
      3배가 지나지 않음): `시작 + 예상 수행 시간 − now`. 예상을 넘겼으면 300초. 유가는 claim이 `next_due_at`을
      시작 + 7시간 45분으로 옮기므로, 진행 중에 예정 시각으로 계산하면 이미 도는 복구 run을 몇 시간 넘겨 짚는다.
    - **다음 예정이 미래**: `next_due_at − now + 예상 수행 시간`.
    - **예정이 없거나 지났음**(휴게소 계열은 성공 때 `next_due_at`을 비운다, 수집기가 멈춰 예정이 과거에 머묾): 1800.

    힌트일 뿐이다. 소비자는 이 값 때문에 정기 polling을 멈추지 않는다.
    """
    default = RETRY_AFTER_SECONDS[ProblemCode.EXPORT_SOURCE_NOT_CURRENT]
    if state is None:
        return default
    started, success = _aware(state.last_started_at), _aware(state.last_success_at)
    updated = _aware(getattr(state, "updated_at", None))
    failed_after_start = (state.last_error is not None and updated is not None and started is not None
                          and updated > started + _START_RECORD_TOLERANCE)
    if (started is not None and (success is None or started > success) and not failed_after_start
            and now - started < 3 * expected_run):
        remaining = (started + expected_run - now).total_seconds()
        return _clamp_source_seconds(remaining if remaining > 0 else SOURCE_RUN_OVERRUN_RETRY_SECONDS)
    due = _aware(state.next_due_at)
    if due is None or due <= now:
        return default
    return _clamp_source_seconds((due - now + expected_run).total_seconds())


def problem_body(*, status: int, title: str, detail: Any, instance: str, code: str | None = None) -> dict[str, Any]:
    """RFC 7807 본문. `code`는 있을 때만 싣는다(없으면 기존 본문과 바이트까지 같다)."""
    body: dict[str, Any] = {"type": "about:blank", "title": title, "status": status, "detail": detail,
                            "instance": instance}
    if code is not None:
        body["code"] = str(code)
    return body


class DatabaseConnectError(ConnectionError):
    """API 엔진의 DB 접속 단계 실패(거부·주소·네트워크). 원래 예외는 `__cause__`에 남는다.

    `ConnectionError`(OSError)를 그대로 상속하므로 기존 `except OSError` 처리는 같게 동작한다.
    """


class DatabaseConnectTimeout(DatabaseConnectError, TimeoutError):
    """asyncpg 접속 timeout. `except TimeoutError` 처리도 그대로 잡는다."""


def database_sqlstate(exc: BaseException) -> str | None:
    """SQLAlchemy DBAPIError(또는 asyncpg 원래 예외를 감싼 것)의 SQLSTATE. 공용 분류기를 쓴다."""
    info = pg_error_info(exc)
    return info.sqlstate if info is not None else None


def is_transient_db_error(exc: BaseException) -> bool:
    """잠시 뒤 다시 부르면 풀릴 DB 불가인가. 원인 불명 DB 오류·문장 오류는 False(계속 500)."""
    if isinstance(exc, (PoolTimeoutError, DatabaseConnectError)):
        return True
    if isinstance(exc, DBAPIError):
        code = database_sqlstate(exc)
        if code in NON_TRANSIENT_CONNECTION_SQLSTATES:
            return False
        if exc.connection_invalidated:
            return True
        return code is not None and (code in TRANSIENT_SQLSTATES or code.startswith("08"))
    return False


def transient_cause(exc: BaseException) -> str:
    """로그용 원인 요약: 연쇄에서 처음 만난 driver·OS 예외의 종류와 errno. 원문(SQL·DSN·주소)은 싣지 않는다."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and not isinstance(current, DatabaseConnectError):
            return f"{type(current).__qualname__}(errno={current.errno})"
        orig = getattr(current, "orig", None)
        if orig is not None and orig is not current:
            # SQLAlchemy asyncpg adapter의 오류(`AsyncAdapt_asyncpg_dbapi.Error`)는 원래 asyncpg 예외를 __cause__에 둔다.
            driver = orig
            while driver.__cause__ is not None and id(driver.__cause__) not in seen:
                seen.add(id(driver))
                driver = driver.__cause__
            return type(driver).__qualname__
        current = current.__cause__ or current.__context__
    return type(exc).__qualname__
