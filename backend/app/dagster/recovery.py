"""수집 행의 Dagster 소유권·게시 fencing과 중단 기록 회수. 도메인 SQL은 앱이 소유한다."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from kortravelcommon.deadline import call_with_deadline
from kortravelcommon.stall import StallClock
from sqlalchemy import event, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.time_utils import now_utc, serialize_utc
from app.models import CollectionRun, TransportCollectionState
from app.services.rest_area_collection import REST_AREA_FUEL_SOURCE, REST_AREA_FUEL_TRIGGER
from app.services.transport_collection import (
    DAGSTER_FUEL_TRIGGER,
    FUEL_IN_FLIGHT_WINDOW,
    LOST_FUEL_ATTEMPT_ERROR,
    OPINET_SOURCE,
    TRANSPORT_COLLECTION_ADVISORY_LOCK_KEY,
    TRANSPORT_TRIGGER_PREFIX,
    _fuel_last_attempt_failed,
    fuel_claim_owner,
    fuel_runs_in_flight,
    lost_fuel_claim_owner,
)

OWNER: ContextVar[str | None] = ContextVar("transport_dagster_owner", default=None)


@dataclass
class OwnerLease:
    """동일 op의 새 session과 asyncio context에도 회수 사실을 유지한다."""

    run_id: str
    instance: Any = None
    revoked: bool = False


OWNER_LEASE: ContextVar[OwnerLease | None] = ContextVar("transport_dagster_lease", default=None)
MISSING_RUN_GRACE = timedelta(hours=5)  # 기존 4시간 실행 상한보다 길게 둔다.
PAGE_SIZE = 100

#: 회수 sensor 한 tick의 예산(초). Dagster sensor 평가 상한(기본 60초) 안에 경보 기록까지 끝나게 둔다.
RECOVERY_BUDGET_SECONDS = 45
#: 회수 sensor 전용 엔진의 문장 상한(초)이자 접속 상한. 예산이 끊은 뒤에도 남는 thread의 DB 문장이
#: 오래 돌지 않게 예산보다 짧게 둔다. 조회는 running 행 keyset 100행, 갱신은 PK 한 행이다.
RECOVERY_STATEMENT_TIMEOUT_SECONDS = 5
#: Dagster metadata(`get_run_by_id`) 한 건의 대기 상한(초). 기존 값과 같다.
METADATA_TIMEOUT_SECONDS = 10
#: 다음 단계를 시작하는 데 필요한 남은 예산(초). 가장 긴 단계는 한 행의 metadata 확인 + 새 session
#: 접속 + UPDATE + COMMIT이다(10 + 5 + 5 + 5). 이보다 적으면 위치를 저장하고 tick을 정상 종료한다
#: (다음 tick이 이어서 본다). 그래서 예산 초과(`DeadlineExceeded`)는 각 상한이 모두 걸릴 만큼 느린 경우에만 남는다.
STEP_RESERVE_SECONDS = METADATA_TIMEOUT_SECONDS + 3 * RECOVERY_STATEMENT_TIMEOUT_SECONDS
#: 예산 끝에 남겨 두는 정리 시간(초). 작업 전체(첫 접속의 dialect 초기화 문장, 빈 page 확인 포함)는
#: `asyncio.timeout`으로 `예산 - 이 값`에서 끊고, 엔진 dispose는 이 안에서 끝나게 상한을 둔다
#: (`app.dagster.definitions._reconcile_workers`). 그래서 콜백 thread는 느린 DB에서도 예산 안에 돌아온다.
CLEANUP_RESERVE_SECONDS = 5
#: 5분 주기 수집 op가 서비스에 넘기는 trigger. definitions.py가 이 상수를 그대로 쓴다.
AIRPORT_TRIGGER = "dagster_airport"
HIGHWAY_TRIGGER = "dagster_highway"
#: 저장되는 `CollectionRun.trigger`. 교통 서비스는 접두를 붙여 저장한다(`TransportCollectionService.collect`).
#: 실행이 시작되면 행이 생긴다(건너뜀 포함). 예외: 공항 수집의 advisory lease 경합은 행 없이 돌아오지만
#: 그 경합이 20분 넘게 이어지면 그 자체로 정체다.
FIVE_MINUTE_TRIGGERS = (AIRPORT_TRIGGER, f"{TRANSPORT_TRIGGER_PREFIX}{HIGHWAY_TRIGGER}")
#: 마지막 시작이 이보다 오래되면 5분 수집 정체로 본다(4주기 누락). 정체 시계가 이어서
#: `stall_after_seconds`(900초)를 더 기다린 뒤 경보하므로 마지막 시작 뒤 약 35분에 첫 경보가 난다.
COLLECTION_STALE_AFTER = timedelta(minutes=20)
#: 정체 경보의 안정적인 event 이름(로그 검색·런북 기준). 형식은 `format_stall_alert`가 정본이다.
STALL_EVENT = "transport_worker_recovery.stalled"

#: Dagster 유가 op가 저장하는 `CollectionRun.trigger`. 정본은 서비스(`DAGSTER_FUEL_TRIGGER`)다.
FUEL_TRIGGER = DAGSTER_FUEL_TRIGGER
#: 원천별 정기 수집 실행의 trigger. "진행 중인 실행" 판정에 쓴다.
FUEL_SOURCE_TRIGGERS = {OPINET_SOURCE: DAGSTER_FUEL_TRIGGER, REST_AREA_FUEL_SOURCE: REST_AREA_FUEL_TRIGGER}
#: 유가 시도 소실 기록 단계의 상한(초). 잠금 시도·상태·주인·진행 중 확인·갱신·commit(문장마다 5초 상한)을 이 안에서 끊는다.
FUEL_LOST_STEP_SECONDS = 2 * RECOVERY_STATEMENT_TIMEOUT_SECONDS
#: 유가 신선도 판정 단계의 상한(초). 상태 행·진행 중 실행·소실 주인 조회를 이 안에서 끊는다. 두 단계는 따로 끊고 따로
#: 실패한다 — 소실 기록이 실패해도 신선도(특히 위험·만료) 판정은 한다. 판정 단계의 예산을 먼저 남긴다(`check_fuel_freshness`).
FUEL_LEVEL_STEP_SECONDS = 2 * RECOVERY_STATEMENT_TIMEOUT_SECONDS
#: 유가 신선도 event 이름 접두(로그 검색·런북 기준). 형식은 `FuelFreshnessAlerts`·`format_fuel_freshness`가 정본이다.
FUEL_FRESHNESS_EVENT = "transport_fuel_freshness"
#: 정기 수집 주기. 경고 기준(2주기)에 쓴다. `definitions`의 유가 `0 */8 * * *`·휴게소 유가 `25 */4 * * *`와 같아야 한다
#: (`test_fuel_freshness_cycles_follow_the_schedules`).
FUEL_FRESHNESS_CYCLES = {OPINET_SOURCE: timedelta(hours=8), REST_AREA_FUEL_SOURCE: timedelta(hours=4)}
#: 경고: 마지막 성공 나이 > 이만큼의 주기이고 마지막으로 **끝난** 시도가 실패(진행 중인 실행이 있으면 실패로 세지 않는다).
#: 유가는 16시간 = 연속 2회 실패로, 다음 실패가 곧 export 503(`REFERENCE_STALE_AFTER`)이 되는 선행 신호다.
FUEL_FRESHNESS_WARNING_CYCLES = 2
#: 위험: 마지막 성공 나이 > export stale 기준(`REFERENCE_STALE_AFTER`)의 이 비율. 실패 여부와 무관하다(수집이 멈춰도 잡는다).
#: 기준 자체를 넘으면 `expired`(export가 지금 503)다.
FUEL_FRESHNESS_CRITICAL_RATIO = 0.8
#: 같은 단계를 다시 남기는 간격(초). 정체 경보의 재경보 간격(common `realert_after_seconds`)과 같다.
FUEL_FRESHNESS_REALERT_SECONDS = 3600


class CollectionLeaseLost(RuntimeError):
    """회수된 worker의 늦은 ORM/bulk 게시·완료 상태 덮어쓰기를 거절한다."""


@contextmanager
def collection_owner(run_id: str, instance=None):
    token = OWNER.set(run_id)
    lease = OWNER_LEASE.get()
    if lease is None or lease.run_id != run_id:
        lease = OwnerLease(run_id, instance)
    elif instance is not None:
        lease.instance = instance
    lease_token = OWNER_LEASE.set(lease)
    try:
        yield
    finally:
        OWNER_LEASE.reset(lease_token)
        OWNER.reset(token)


def ensure_collection_owner_active() -> None:
    """새 session/후속 op는 terminal owner를 다시 쓰지 않는다. 조회 장애는 예외로 전달한다."""
    lease = OWNER_LEASE.get()
    if lease is None:
        return
    if lease.revoked:
        raise CollectionLeaseLost("회수된 실행은 새 수집을 시작할 수 없습니다.")
    if lease.instance is not None:
        run = call_with_deadline(
            lambda: lease.instance.get_run_by_id(lease.run_id), timeout_seconds=10
        )
        if run is None or run.is_finished:
            lease.revoked = True
            raise CollectionLeaseLost("종료된 Dagster 실행은 새 수집을 시작할 수 없습니다.")


class CollectorSyncSession(Session):
    pass


class CollectorSession(AsyncSession):
    sync_session_class = CollectorSyncSession


def owned_session_factory(engine, owner: str):
    lease = OWNER_LEASE.get()
    if lease is None or lease.run_id != owner:
        lease = OwnerLease(owner)
    return async_sessionmaker(
        engine,
        class_=CollectorSession,
        expire_on_commit=False,
        info={"collector_owner": owner, "collector_owner_lease": lease},
    )


def _fence(session: CollectorSyncSession) -> None:
    lease = session.info["collector_owner_lease"]
    if lease.revoked:
        raise CollectionLeaseLost("회수된 실행의 게시를 거절합니다.")
    # SQLAlchemy bulk execute는 ORM flush를 우회한다. before_commit에서도 같은 잠금을 잡는다.
    fenced = session.info.setdefault("collector_fenced", set())
    for run_id in session.info.get("collector_runs", {}):
        if run_id in fenced:
            continue
        connection = session.connection()
        row = connection.execute(
            select(CollectionRun.status, CollectionRun.orchestrator_run_id)
            .where(CollectionRun.id == run_id)
            .with_for_update()
        ).first()
        if (
            row is None
            or row.status != "running"
            or row.orchestrator_run_id != session.info["collector_owner"]
        ):
            lease.revoked = True
            raise CollectionLeaseLost("수집 실행 소유권이 종료되어 게시를 거절합니다.")
        connection.execute(
            update(CollectionRun).where(CollectionRun.id == run_id).values(heartbeat_at=now_utc())
        )
        fenced.add(run_id)


@event.listens_for(CollectorSyncSession, "before_flush")
def _before_flush(session, _flush_context, _instances):
    pending = session.info.setdefault("collector_pending", [])
    for row in session.new:
        if isinstance(row, CollectionRun) and row not in pending:
            row.orchestrator_run_id = session.info["collector_owner"]
            row.heartbeat_at = now_utc()
            pending.append(row)
    _fence(session)


@event.listens_for(CollectorSyncSession, "after_flush_postexec")
def _capture_runs(session, _flush_context):
    for row in session.info.pop("collector_pending", []):
        if row.status == "running":
            session.info.setdefault("collector_runs", {})[row.id] = row
            # 신규 INSERT는 이 transaction이 소유하며 아직 다른 worker가 회수할 수 없다.
            session.info.setdefault("collector_fenced", set()).add(row.id)
            session.info.setdefault("collector_new_ids", set()).add(row.id)


@event.listens_for(CollectorSyncSession, "before_commit")
def _before_commit(session):
    _fence(session)


@event.listens_for(CollectorSyncSession, "after_commit")
def _after_commit(session):
    session.info["collector_runs"] = {
        key: row
        for key, row in session.info.get("collector_runs", {}).items()
        # rollback/expire로 상태를 모르면 DB fence를 유지한다. None은 종료의 증거가 아니다.
        if row.__dict__.get("status") in (None, "running")
    }
    session.info.pop("collector_fenced", None)
    session.info.pop("collector_new_ids", None)


@event.listens_for(CollectorSyncSession, "after_rollback")
def _after_rollback(session):
    for key in session.info.pop("collector_new_ids", set()):
        session.info.get("collector_runs", {}).pop(key, None)
    session.info.pop("collector_fenced", None)
    session.info.pop("collector_pending", None)


class RecoveryMetadataUnavailable(RuntimeError):
    """Dagster metadata 조회 장애. 소유권은 회수하지 않고 정체 시계에만 남긴다."""


class CollectionStalled(RuntimeError):
    """5분 주기 수집이 오래 시작되지 않았다. 메시지에는 trigger 이름과 경과 분만 담는다."""


class ScanPosition:
    """회수 keyset 위치. code-server 프로세스 안에서 tick 사이에 유지한다.

    sensor cursor는 common `reconciliation_sensor`의 정체 시계가 소유하므로 쓰지 않는다. 위치를 잃으면
    (재시작) 처음부터 다시 볼 뿐 행을 건너뛰지 않는다. 끝까지 보면 0으로 돌아가 앞쪽 행을 다시 본다.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = 0

    def get(self) -> int:
        with self._lock:
            return self._value

    def set(self, value: int) -> None:
        with self._lock:
            self._value = value


def _has_budget(remaining: Callable[[], float] | None) -> bool:
    return remaining is None or remaining() > STEP_RESERVE_SECONDS


async def stale_five_minute_triggers(
    session_factory, *, now: datetime | None = None
) -> list[tuple[str, int]]:
    """마지막 시작이 `COLLECTION_STALE_AFTER`보다 오래된 5분 수집 trigger와 경과 분.

    행이 하나도 없는 trigger(새 DB)는 판단하지 않는다. 실행 중·실패·건너뜀도 '시작'으로 센다.
    실행이 상한까지 매달려 coalescing이 새 실행을 막는 경우도 정체로 잡힌다. 다만 5분 job의 상한이 20~30분이 된 뒤에는
    매번 상한에서 끊기는 run이 정체 경보(마지막 시작 20분 + 연속 900초)까지 가지 않을 수 있다 — 그 경우는 run FAILURE
    (max_runtime 초과)로 보인다.
    """
    now = now or now_utc()
    stale: list[tuple[str, int]] = []
    async with session_factory() as session:
        for trigger in FIVE_MINUTE_TRIGGERS:
            latest = await session.scalar(
                select(CollectionRun.started_at)
                .where(CollectionRun.trigger == trigger)
                .order_by(CollectionRun.started_at.desc())
                .limit(1)
            )
            if latest is None:
                continue
            age = now - serialize_utc(latest)
            if age > COLLECTION_STALE_AFTER:
                stale.append((trigger, int(age.total_seconds() // 60)))
    return stale


# ---------------------------------------------------------------------------
# 유가 시도 소실 기록과 신선도 단계 (2026-11-24 감사 G1-F5·G1-F6)
#
# 2026-11-23 08:17Z~11-24 00:17Z T1 주유소 export가 16.6시간 503이었는데 아무 경보도 없었다(정체 경보는 5분 수집만
# 본다). 유가 신선도는 이 sensor tick에서 회수 뒤에 같이 본다 — 새 run이나 schedule을 만들지 않고, 오피넷을 더 부르지도 않는다.


@dataclass(frozen=True)
class LostFuelAttempt:
    """결과를 잃은 오피넷 유가 시도(claim). 로그 한 줄에 싣는 고정 필드만 둔다."""

    collection_run_id: int | None
    orchestrator_run_id: str | None
    last_started_at: datetime


@dataclass(frozen=True)
class FuelFreshness:
    """한 유가 원천의 신선도 단계. `level`은 `ok`·`warning`·`critical`·`expired`다.

    `cause`는 마지막 시도의 사정이다: `running`(진행 중인 실행이 있음), `lost`(결과 없이 끝남 — `LOST_FUEL_ATTEMPT_ERROR`),
    `failed`(실패 기록), `none`(실패 기록도 진행 중인 실행도 없음 — 수집이 돌지 않거나 아직 예정 전).
    """

    source: str
    level: str
    age_seconds: int
    last_success_at: datetime
    last_attempt_failed: bool
    cause: str
    warning_after: timedelta
    critical_after: timedelta
    expired_after: timedelta


@dataclass
class FuelFreshnessReport:
    """한 tick의 유가 점검 결과. 회수·정체 판정은 이 점검의 성패와 무관하게 계속한다.

    - `recorded`: 이번 tick에 `LOST_FUEL_ATTEMPT_ERROR`를 기록한 시도. `lost_attempt`: 상태 행 기준으로 지금 결과를 잃은
      시도(기록이 앞 tick이었어도 — 경보 줄을 놓치지 않게 상태에서 다시 만든다).
    - `lost_failure`·`failure`: 소실 기록 단계·판정 단계의 실패 서명(형식 이름[:SQLSTATE]).
    - `checked`: 판정 단계를 끝까지 했는가. 점검을 하지 못한 tick(예산 부족·앞 단계 장애)은 `levels`가 비어도 "판단 대상
      없음"이 아니다 — 경보 기억을 지우거나 회복으로 보지 않는다.
    - `paused`: provider가 꺼졌거나 schedule이 STOPPED라 경보에서 뺀 원천(정체 판정의 `paused`와 같은 뜻).
    """

    recorded: LostFuelAttempt | None = None
    lost_attempt: LostFuelAttempt | None = None
    levels: list[FuelFreshness] = field(default_factory=list)
    paused: list[str] = field(default_factory=list)
    lost_failure: str | None = None
    failure: str | None = None
    checked: bool = False


def fuel_freshness_thresholds(source: str) -> tuple[timedelta, timedelta, timedelta]:
    """(경고 기준 나이, 위험 기준 나이, 만료 = export stale 기준). 위험·만료는 `REFERENCE_STALE_AFTER`를 따라 바뀐다.

    export 모듈(FastAPI router 정의)을 Dagster 프로세스가 import하지 않게 여기서만 늦게 읽는다.
    """
    from app.service_exports import REFERENCE_STALE_AFTER

    expired_after = REFERENCE_STALE_AFTER[source]
    return (
        FUEL_FRESHNESS_WARNING_CYCLES * FUEL_FRESHNESS_CYCLES[source],
        FUEL_FRESHNESS_CRITICAL_RATIO * expired_after,
        expired_after,
    )


def evaluate_fuel_freshness(
    source: str, state: TransportCollectionState | None, *, now: datetime, in_flight: bool = False,
) -> FuelFreshness | None:
    """마지막 성공 나이로 단계를 정한다. 성공 이력이 없으면(새 DB·쓰지 않는 원천) 판단하지 않는다 — export가 이미 503이다.

    - 만료: 나이 > export stale 기준(`REFERENCE_STALE_AFTER`). export가 지금 503이다.
    - 위험: 나이 > 그 기준의 80%. 실패 여부와 무관하다 — 수집이 멈춰도 잡는다.
    - 경고: 나이 > 2주기(유가 16시간·휴게소 유가 8시간)이고 마지막으로 **끝난** 시도가 실패(`_fuel_last_attempt_failed`).
      claim은 이전 오류를 지우지 않으므로, 진행 중인 실행(`in_flight`)이 있으면 실패로 세지 않는다 — 실패 1회 뒤 다음
      정기 실행이 수집 중인 동안 경고하지 않는다.
    """
    if state is None or state.last_success_at is None:
        return None
    warning_after, critical_after, expired_after = fuel_freshness_thresholds(source)
    last_success = serialize_utc(state.last_success_at)
    age = now - last_success
    failed = _fuel_last_attempt_failed(state) and not in_flight
    cause = ("running" if in_flight else "lost" if failed and state.last_error == LOST_FUEL_ATTEMPT_ERROR
             else "failed" if failed else "none")
    level = ("expired" if age > expired_after else "critical" if age > critical_after
             else "warning" if age > warning_after and failed else "ok")
    return FuelFreshness(
        source=source, level=level, age_seconds=max(0, int(age.total_seconds())), last_success_at=last_success,
        last_attempt_failed=failed, cause=cause, warning_after=warning_after, critical_after=critical_after,
        expired_after=expired_after,
    )


async def record_lost_fuel_attempt(session_factory, *, now: datetime | None = None) -> LostFuelAttempt | None:
    """결과 없이 끝난 오피넷 유가 시도에 `LOST_FUEL_ATTEMPT_ERROR`를 남긴다. `last_success_at`·`next_due_at`은 그대로다.

    판정은 서비스의 `lost_fuel_claim_owner`(관리자 재시도와 같은 규칙)다: claim에 결과가 없고, 그 주인 Dagster 유가 실행이
    failed로 끝났으며, 진행 중인 Dagster 유가 실행이 없다. 잡는 경우:

    - op 밖에서 죽어(code-server·run worker 재시작, SIGKILL, `--no-drain` 배포) 회수(`reconcile_collection_runs`)가 failed로
      닫은 실행 — 같은 tick의 회수 직후에 기록한다
    - 실패 기록 commit 자체가 실패한 실행(실행 행은 failed인데 상태 행에는 오류가 없다)

    경합: PostgreSQL에서는 유가 수집기가 claim·저장에 쓰는 advisory lock(`TRANSPORT_COLLECTION_ADVISORY_LOCK_KEY + 1`)을
    try로 먼저 잡는다. 못 잡으면 수집기가 claim·저장 중이므로 이번 tick은 건너뛴다(기다리지 않는다). 갱신은 읽은 claim
    그대로이고 결과가 여전히 없으며 진행 중인 유가 실행이 없을 때만 한다(CAS + NOT EXISTS) — 그 사이의 새 claim·성공·실패를
    덮지 않는다. 늦게 도착한 실패 처리는 원래 오류 문장으로 이 값을 덮는다.
    """
    now = now or now_utc()
    async with session_factory() as session:
        if session.get_bind().dialect.name == "postgresql":
            locked = await session.scalar(
                text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                {"lock_key": TRANSPORT_COLLECTION_ADVISORY_LOCK_KEY + 1},
            )
            if not locked:
                return None
            # 상태 행을 쥔 다른 transaction 뒤에서 오래 기다리지 않는다(실패하면 다음 tick이 다시 본다).
            await session.execute(text("SET LOCAL lock_timeout = '1s'"))
        state = await session.scalar(
            select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE)
        )
        owner = await lost_fuel_claim_owner(session, state)
        if owner is None:
            return None
        claimed_at = state.last_started_at  # DB 값 그대로 비교한다(SQLite는 tz 없는 값을 돌려준다).
        result = await session.execute(
            update(TransportCollectionState)
            .where(
                TransportCollectionState.source == OPINET_SOURCE,
                TransportCollectionState.last_started_at == claimed_at,
                TransportCollectionState.last_error.is_(None),
                or_(
                    TransportCollectionState.last_success_at.is_(None),
                    TransportCollectionState.last_success_at < TransportCollectionState.last_started_at,
                ),
                ~select(CollectionRun.id).where(fuel_runs_in_flight(DAGSTER_FUEL_TRIGGER, now=now)).exists(),
            )
            .values(last_error=LOST_FUEL_ATTEMPT_ERROR, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    if result.rowcount != 1:
        return None
    return LostFuelAttempt(
        collection_run_id=owner.id, orchestrator_run_id=owner.orchestrator_run_id,
        last_started_at=serialize_utc(claimed_at),
    )


async def fuel_freshness_snapshot(
    session_factory, *, now: datetime | None = None,
) -> tuple[list[FuelFreshness], LostFuelAttempt | None]:
    """오피넷·휴게소 유가 상태 행과 진행 중인 실행을 읽어 원천별 단계(`ok` 포함 — 회복 줄에 쓴다)를 돌려준다.

    오피넷 claim이 지금 `실행 소실` 상태면(상태 문장이 `LOST_FUEL_ATTEMPT_ERROR`, 주인 실행 failed, 진행 중인 유가 실행
    없음) 그 시도도 돌려준다. 소실 줄을 이번 tick의 기록 여부가 아니라 상태에서 만들므로 예산 부족으로 놓친 줄도 남긴다.
    """
    now = now or now_utc()
    async with session_factory() as session:
        rows = (await session.scalars(
            select(TransportCollectionState).where(TransportCollectionState.source.in_(tuple(FUEL_FRESHNESS_CYCLES)))
        )).all()
        in_flight = set((await session.scalars(
            select(CollectionRun.trigger).where(
                CollectionRun.trigger.in_(tuple(FUEL_SOURCE_TRIGGERS.values())),
                CollectionRun.status == "running",
                CollectionRun.started_at >= now - FUEL_IN_FLIGHT_WINDOW,
            ).distinct()
        )).all())
        states = {row.source: row for row in rows}
        opinet = states.get(OPINET_SOURCE)
        lost = None
        if (opinet is not None and opinet.last_error == LOST_FUEL_ATTEMPT_ERROR and opinet.last_started_at is not None
                and DAGSTER_FUEL_TRIGGER not in in_flight):
            owner = await fuel_claim_owner(session, opinet.last_started_at)
            if owner is not None and owner.status == "failed":
                lost = LostFuelAttempt(collection_run_id=owner.id, orchestrator_run_id=owner.orchestrator_run_id,
                                       last_started_at=serialize_utc(opinet.last_started_at))
    levels = []
    for source, trigger in FUEL_SOURCE_TRIGGERS.items():
        level = evaluate_fuel_freshness(source, states.get(source), now=now, in_flight=trigger in in_flight)
        if level is not None:
            levels.append(level)
    return levels, lost


async def fuel_freshness_levels(session_factory, *, now: datetime | None = None) -> list[FuelFreshness]:
    """원천별 단계만(`fuel_freshness_snapshot`의 앞 값)."""
    return (await fuel_freshness_snapshot(session_factory, now=now))[0]


def _failure_signature(exc: BaseException) -> str:
    """예외 원문 없이 형식 이름과 SQLSTATE만(정체 시계의 `last_failure`와 같은 모양)."""
    from kortravelcommon.pg_errors import pg_error_info

    info = pg_error_info(exc)
    return f"{type(exc).__name__}:{info.sqlstate}" if info is not None else type(exc).__name__


async def check_fuel_freshness(
    session_factory,
    report: FuelFreshnessReport,
    *,
    now: datetime | None = None,
    remaining: Callable[[], float] | None = None,
    monitored: Callable[[str], bool] | None = None,
) -> None:
    """유가 시도 소실 기록 → 신선도 판정. 부가 점검이라 실패해도 올리지 않고 단계별 실패 서명만 `report`에 남긴다.

    두 단계는 각자의 상한(`FUEL_LOST_STEP_SECONDS`·`FUEL_LEVEL_STEP_SECONDS`)으로 따로 끊고 따로 실패한다. 남은 예산
    (`remaining`)이 두 단계를 다 담지 못하면 소실 기록을 건너뛰고 판정만 한다(위험·만료 경보가 우선). 판정 단계도 담지
    못하면 아무것도 하지 않는다(`checked=False`). tick 전체의 취소(`CancelledError`)는 그대로 올린다.

    `monitored(source)`는 경고 이상인 원천에만 부른다. False면(provider 꺼짐·schedule STOPPED) `paused`로 옮긴다. 확인
    자체가 실패하면 경보 쪽(감시 중)으로 본다.
    """

    def has(seconds: float) -> bool:
        return remaining is None or remaining() > seconds

    if has(FUEL_LOST_STEP_SECONDS + FUEL_LEVEL_STEP_SECONDS):
        try:
            async with asyncio.timeout(FUEL_LOST_STEP_SECONDS):
                report.recorded = await record_lost_fuel_attempt(session_factory, now=now)
        except Exception as exc:  # noqa: BLE001 — 판정·회수·정체 판정을 막지 않는다.
            report.lost_failure = _failure_signature(exc)
    if not has(FUEL_LEVEL_STEP_SECONDS):
        return
    try:
        async with asyncio.timeout(FUEL_LEVEL_STEP_SECONDS):
            report.levels, report.lost_attempt = await fuel_freshness_snapshot(session_factory, now=now)
    except Exception as exc:  # noqa: BLE001
        report.failure = _failure_signature(exc)
        return
    report.checked = True
    if monitored is None:
        return
    kept = []
    for item in report.levels:
        watched = True
        if item.level != "ok":
            try:
                watched = bool(monitored(item.source))
            except Exception:  # noqa: BLE001 — 애매하면 경보 쪽
                watched = True
        if watched:
            kept.append(item)
        else:
            report.paused.append(item.source)
    report.levels = kept


@dataclass(frozen=True)
class FuelAlertLine:
    """남길 경보 한 줄과, 남긴 **뒤에** 경보 기억에 반영할 값(`remember=None`이면 그 key를 지운다)."""

    level: int
    text: str
    key: str
    remember: tuple[str, float] | None


class FuelFreshnessAlerts:
    """유가 신선도 경보 줄(고정 event 이름 한 줄, `format_stall_alert`와 같은 관례).

    단계가 바뀌면 바로, 같은 단계는 `FUEL_FRESHNESS_REALERT_SECONDS`마다 다시 남긴다. 경고 이상에서 `ok`로 돌아오면 회복
    줄을 한 번 남긴다. 소실 줄은 claim마다 한 번이다. sensor cursor는 정체 시계가 소유하므로 마지막 경보는 code-server 프로세스
    안에 둔다. 재시작하면 기억이 비어 현재 비정상 단계·소실을 한 번 더 남기고, 재시작 사이에 회복했으면 회복 줄은 없다
    (그 원천의 경보 줄이 `FUEL_FRESHNESS_REALERT_SECONDS`보다 오래 없으면 정상이다).

    `lines()`는 줄과 기억할 값만 만든다. 기억은 호출자가 줄을 실제로 남긴 뒤 `commit()`으로 반영한다 — 로그 기록이 실패한
    줄은 다음 tick에 다시 만든다.
    """

    _CHECK_FAILED = "check_failed:"
    _LOST = "lost:"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[str, tuple[str, float]] = {}

    def lines(self, report: FuelFreshnessReport, *, now: float) -> list[FuelAlertLine]:
        out: list[FuelAlertLine] = []
        with self._lock:
            for step, failure, ran in (("lost_attempt", report.lost_failure, report.lost_failure is not None
                                        or report.recorded is not None or report.checked),
                                       ("levels", report.failure, report.checked)):
                key = self._CHECK_FAILED + step
                if failure is not None:
                    if self._due(key, failure, now):
                        out.append(FuelAlertLine(
                            logging.WARNING, f"{FUEL_FRESHNESS_EVENT}.check_failed step={step} error={failure}",
                            key, (failure, now)))
                elif ran:
                    self._last.pop(key, None)
            if not report.checked:
                # 판정하지 못한 tick(실패·예산 부족·앞 단계 장애)은 원천별 단계와 소실 기억을 바꾸지 않는다. 빈 `levels`를
                # "모두 판단 대상 아님"으로 읽어 기억을 지우면 다음 tick이 같은 단계를 즉시 다시 남기고 회복 줄을 놓친다.
                return out
            lost_key = self._LOST + OPINET_SOURCE
            if report.lost_attempt is None:
                self._last.pop(lost_key, None)
            else:
                lost = report.lost_attempt
                claim = lost.last_started_at.isoformat()
                if self._last.get(lost_key, ("", 0.0))[0] != claim:
                    run_id = lost.collection_run_id if lost.collection_run_id is not None else "none"
                    out.append(FuelAlertLine(logging.WARNING, (
                        f"{FUEL_FRESHNESS_EVENT}.lost_attempt source={OPINET_SOURCE} collection_run_id={run_id} "
                        f"orchestrator_run_id={lost.orchestrator_run_id or 'none'} last_started_at={claim}"
                    ), lost_key, (claim, now)))
            seen = set()
            for item in report.levels:
                seen.add(item.source)
                previous = self._last.get(item.source)
                if item.level == "ok":
                    if previous is not None:
                        out.append(FuelAlertLine(logging.WARNING, (
                            f"{FUEL_FRESHNESS_EVENT}.recovered source={item.source} age_seconds={item.age_seconds} "
                            f"last_success_at={item.last_success_at.isoformat()} previous={previous[0]}"
                        ), item.source, None))
                    continue
                if self._due(item.source, item.level, now):
                    severity = logging.WARNING if item.level == "warning" else logging.ERROR
                    out.append(FuelAlertLine(severity, format_fuel_freshness(item), item.source, (item.level, now)))
            for source in FUEL_FRESHNESS_CYCLES:
                if source not in seen:
                    # 상태 행·성공 이력이 없거나 경보에서 뺀(provider 꺼짐·STOPPED) 원천 — 판단 대상이 아니다.
                    self._last.pop(source, None)
        return out

    def commit(self, line: FuelAlertLine) -> None:
        """줄을 실제로 남긴 뒤 기억에 반영한다."""
        with self._lock:
            if line.remember is None:
                self._last.pop(line.key, None)
            else:
                self._last[line.key] = line.remember

    def _due(self, key: str, level: str, now: float) -> bool:
        previous = self._last.get(key)
        return previous is None or previous[0] != level or now - previous[1] >= FUEL_FRESHNESS_REALERT_SECONDS


def format_fuel_freshness(item: FuelFreshness) -> str:
    """경고·위험·만료 한 줄. 상태 행의 고정 필드만 싣는다(오류 원문 없음)."""
    return (
        f"{FUEL_FRESHNESS_EVENT}.{item.level} source={item.source} age_seconds={item.age_seconds} "
        f"last_success_at={item.last_success_at.isoformat()} cause={item.cause} "
        f"last_attempt_failed={'true' if item.last_attempt_failed else 'false'} "
        f"warning_after_seconds={int(item.warning_after.total_seconds())} "
        f"critical_after_seconds={int(item.critical_after.total_seconds())} "
        f"expired_after_seconds={int(item.expired_after.total_seconds())}"
    )


async def reconcile_collection_runs(
    session_factory,
    instance,
    *,
    page_size: int = PAGE_SIZE,
    position: ScanPosition | None = None,
    remaining: Callable[[], float] | None = None,
) -> int:
    """첫 생존 page 뒤의 terminal 행도 읽는다. metadata 장애는 사망으로 간주하지 않는다.

    `position`이 있으면 그 위치부터 보고, 예산(`remaining`)이 모자라면 마지막으로 끝낸 행 ID를 저장한
    채 정상 반환한다. 끝까지 보면 위치를 0으로 돌린다. metadata 장애는 회수하지 않고 그 행 직전 위치를
    저장한 뒤 `RecoveryMetadataUnavailable`로 알린다(정체 시계가 센다).
    """
    cursor = position.get() if position is not None else 0

    def save(value: int) -> None:
        if position is not None:
            position.set(value)

    recovered = 0
    while True:
        if not _has_budget(remaining):
            save(cursor)
            return recovered
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        CollectionRun.id,
                        CollectionRun.orchestrator_run_id,
                        CollectionRun.heartbeat_at,
                        CollectionRun.started_at,
                    )
                    .where(
                        CollectionRun.id > cursor,
                        CollectionRun.status == "running",
                        CollectionRun.orchestrator_run_id.is_not(None),
                    )
                    .order_by(CollectionRun.id)
                    .limit(page_size)
                )
            ).all()
        if not rows:
            save(0)
            return recovered
        for row in rows:
            # 예산이 끊은 뒤 남은 thread는 metadata를 더 부르지 않는다(common 계약).
            if not _has_budget(remaining):
                save(cursor)
                return recovered
            try:
                run = call_with_deadline(
                    lambda owner=row.orchestrator_run_id: instance.get_run_by_id(owner),
                    timeout_seconds=METADATA_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # metadata 장애에서는 소유권을 회수하지 않는다.
                # 전체 tick을 멈춘다. per-row 반복 timeout도 만들지 않는다. 이 행부터 다시 본다.
                save(cursor)
                raise RecoveryMetadataUnavailable(
                    "Dagster metadata를 확인하지 못해 회수를 멈췄습니다."
                ) from exc
            now = now_utc()
            heartbeat = serialize_utc(row.heartbeat_at or row.started_at)
            missing_expired = run is None and heartbeat <= now - MISSING_RUN_GRACE
            if missing_expired or (run is not None and run.is_finished):
                async with session_factory() as session:
                    statement = update(CollectionRun).where(
                        CollectionRun.id == row.id,
                        CollectionRun.status == "running",
                        CollectionRun.orchestrator_run_id == row.orchestrator_run_id,
                    )
                    if missing_expired:
                        statement = statement.where(CollectionRun.heartbeat_at == row.heartbeat_at)
                    result = await session.execute(
                        statement.values(
                            status="failed",
                            finished_at=now,
                            error_message=(
                                "Dagster 실행 종료 또는 소유권 유실을 확인하여 "
                                "수집 기록을 회수했습니다."
                            ),
                        )
                    )
                    await session.commit()
                    recovered += result.rowcount
            cursor = row.id
        save(cursor)


async def run_recovery_tick(
    session_factory,
    instance,
    *,
    position: ScanPosition,
    remaining: Callable[[], float] | None = None,
    collection_scheduled: Callable[[str], bool] | None = None,
    paused: list[str] | None = None,
    fuel_report: FuelFreshnessReport | None = None,
    fuel_monitored: Callable[[str], bool] | None = None,
) -> int:
    """회수 sensor 한 tick.

    수집 신선도를 먼저 본다(회수가 예산을 다 써도 정체 판단은 매 tick 한다). 이어서 회수를 예산 안에서
    이어 하고, 정체면 `CollectionStalled`로 정체 시계에 알린다.

    `collection_scheduled(trigger)`가 False인 trigger(예: 점검으로 schedule을 STOPPED)는 수집이 멈춘 것이
    의도이므로 정체로 세지 않고 `paused`에 담는다. 판정은 오래된 trigger가 있을 때만 부른다.

    `fuel_report`를 주면 회수 **뒤에** 유가 시도 소실 기록과 신선도 판정(`check_fuel_freshness`)을 해 담는다. 회수가
    예산을 먼저 쓰므로 회수는 굶지 않고, 이번 tick에 회수가 닫은 유가 실행의 소실도 같은 tick에 기록한다. 회수가 metadata
    장애 등으로 실패해도 유가 점검은 하고 그 예외를 다시 올린다. 유가 신선도는 정체가 아니다 — 정체 시계에 알리지 않고
    경보 줄만 남긴다(`definitions._report_fuel_freshness`). `fuel_monitored`는 `check_fuel_freshness(monitored=)`다.
    """
    stale = await stale_five_minute_triggers(session_factory)
    if stale and collection_scheduled is not None:
        scheduled = [(trigger, minutes) for trigger, minutes in stale if collection_scheduled(trigger)]
        if paused is not None:
            paused.extend(trigger for trigger, minutes in stale if (trigger, minutes) not in scheduled)
        stale = scheduled
    reconcile_error: Exception | None = None
    try:
        recovered = await reconcile_collection_runs(
            session_factory, instance, position=position, remaining=remaining
        )
    except Exception as exc:  # 유가 점검은 하고 다시 올린다(정체 시계가 센다).
        reconcile_error, recovered = exc, 0
    if fuel_report is not None:
        await check_fuel_freshness(session_factory, fuel_report, remaining=remaining, monitored=fuel_monitored)
    if reconcile_error is not None:
        raise reconcile_error
    if stale:
        detail = ", ".join(f"{trigger}={minutes}분" for trigger, minutes in stale)
        raise CollectionStalled(f"5분 수집의 마지막 시작이 오래됐습니다: {detail}")
    return recovered


def format_stall_alert(clock: StallClock, *, now: float) -> str:
    """정체 경보 한 줄. 원문 예외 message 없이 시계의 고정 필드(형식 이름·SQLSTATE)만 싣는다."""
    first = datetime.fromtimestamp(clock.first_failed_at, UTC).isoformat()
    return (
        f"{STALL_EVENT} key={clock.key} first_failed_at={first} "
        f"stalled_seconds={max(0, int(now - clock.first_failed_at))} "
        f"last_failure={clock.last_failure}"
    )
