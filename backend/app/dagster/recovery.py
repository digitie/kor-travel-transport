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
from app.service_exports import REFERENCE_STALE_AFTER
from app.services.rest_area_collection import REST_AREA_FUEL_SOURCE
from app.services.transport_collection import OPINET_SOURCE, TRANSPORT_TRIGGER_PREFIX, _fuel_last_attempt_failed

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

#: Dagster 유가 op가 저장하는 `CollectionRun.trigger`(`definitions._collect_transport_in_one_loop`의 `dagster_{scope}`에
#: 서비스가 접두를 붙인다). 회수 sensor의 유가 시도 소실 판정이 이 값으로 claim의 주인 실행을 찾는다.
FUEL_TRIGGER = f"{TRANSPORT_TRIGGER_PREFIX}dagster_fuel"
#: 결과(성공·실패)를 남기지 못하고 끝난 유가 시도에 회수 sensor가 남기는 `last_error`(G1-F5). 실행이 op 밖에서 죽으면
#: (code-server 재기동·worker 소실·SIGKILL) `_mark_fuel_failure`가 불리지 않아 직전 성공의 `last_error=None`이 남고,
#: 그러면 관리자 "재시도"도 "직전 시도 성공"으로 보고 호출 유예로 건너뛰었다. 실패 1회와 같게 보이게 한다.
LOST_FUEL_ATTEMPT_ERROR = "실행 소실: 유가 수집 실행이 결과를 기록하지 못하고 끝났습니다(회수 sensor 기록)."
#: 유가 신선도 점검 한 번(상태 읽기·소실 기록·판정)의 상한(초). 느린 DB에서 회수 예산을 다 쓰지 않게 끊고 회수로 넘어간다.
FUEL_CHECK_TIMEOUT_SECONDS = 2 * RECOVERY_STATEMENT_TIMEOUT_SECONDS
#: 유가 신선도 event 이름 접두(로그 검색·런북 기준). 형식은 `FuelFreshnessAlerts`가 정본이다.
FUEL_FRESHNESS_EVENT = "transport_fuel_freshness"
#: 정기 수집 주기. 경고 기준(2주기)에 쓴다. `definitions`의 유가 `0 */8 * * *`·휴게소 유가 `25 */4 * * *`와 같아야 한다
#: (`test_fuel_freshness_cycles_follow_the_schedules`).
FUEL_FRESHNESS_CYCLES = {OPINET_SOURCE: timedelta(hours=8), REST_AREA_FUEL_SOURCE: timedelta(hours=4)}
#: 경고: 마지막 성공 나이 > 이만큼의 주기이고 마지막 시도가 실패. 유가는 16시간 = 연속 2회 실패로, 다음 실패가 곧
#: export 503(`REFERENCE_STALE_AFTER`)이 되는 선행 신호다.
FUEL_FRESHNESS_WARNING_CYCLES = 2
#: 위험: 마지막 성공 나이 > export stale 기준(`REFERENCE_STALE_AFTER`)의 이 비율. 실패 여부와 무관하다(수집이 멈춰도 잡는다).
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
# 본다). 유가 신선도는 이 sensor tick에서 같이 본다 — 새 run이나 schedule을 만들지 않고, 오피넷을 더 부르지도 않는다.


@dataclass(frozen=True)
class LostFuelAttempt:
    """회수 sensor가 `LOST_FUEL_ATTEMPT_ERROR`를 남긴 유가 시도. 로그 한 줄에 싣는 고정 필드만 둔다."""

    collection_run_id: int
    last_started_at: datetime


@dataclass(frozen=True)
class FuelFreshness:
    """한 유가 원천의 신선도 단계. `level`은 `ok`·`warning`·`critical`이다."""

    source: str
    level: str
    age_seconds: int
    last_success_at: datetime
    last_attempt_failed: bool
    warning_after: timedelta
    critical_after: timedelta


@dataclass
class FuelFreshnessReport:
    """한 tick의 유가 점검 결과. `failure`는 점검 실패의 서명(형식 이름[:SQLSTATE])이다. 회수·정체 판정은 계속한다.

    `checked`는 단계 판정을 끝까지 했는가다. 점검 자체를 하지 못한 tick(예산 부족, 앞 단계의 DB 장애로 tick이 먼저
    끝남)은 `levels`가 비어도 "판단 대상 없음"이 아니다 — 경보 기억을 지우거나 회복으로 보지 않는다.
    """

    lost_attempt: LostFuelAttempt | None = None
    levels: list[FuelFreshness] = field(default_factory=list)
    failure: str | None = None
    checked: bool = False


#: claim(`last_started_at`)이 그 실행의 시작(`CollectionRun.started_at`)보다 늦을 수 있는 최대 폭. 둘은 같은 transaction에서
#: 유가 advisory lock을 쥔 채 몇 초 안에 정해진다(체크포인트 확인·예약 조회). 이보다 먼 Dagster 유가 실행은 그 claim의
#: 주인이 아니다(in-process·수동 실행의 claim) — 판단하지 않는다.
FUEL_CLAIM_MAX_DELAY = timedelta(minutes=15)


def fuel_freshness_thresholds(source: str) -> tuple[timedelta, timedelta]:
    """(경고 기준 나이, 위험 기준 나이). 위험 기준은 export stale 기준(`REFERENCE_STALE_AFTER`)을 따라 바뀐다."""
    return (
        FUEL_FRESHNESS_WARNING_CYCLES * FUEL_FRESHNESS_CYCLES[source],
        FUEL_FRESHNESS_CRITICAL_RATIO * REFERENCE_STALE_AFTER[source],
    )


def evaluate_fuel_freshness(source: str, state: TransportCollectionState | None, *, now: datetime) -> FuelFreshness | None:
    """마지막 성공 나이로 단계를 정한다. 성공 이력이 없으면(새 DB·쓰지 않는 원천) 판단하지 않는다 — export가 이미 503이다.

    - 위험: 나이 > export stale 기준의 80%(유가 19.2시간·휴게소 유가 9.6시간). 실패 여부와 무관하다 — 수집이 멈춰도 잡는다.
    - 경고: 나이 > 2주기(유가 16시간·휴게소 유가 8시간)이고 마지막 시도가 실패(`_fuel_last_attempt_failed`: 오류가 남아 있고
      마지막 성공이 마지막 시작보다 앞섬. 휴게소 유가 상태 행도 같은 규칙으로 쓴다).
    """
    if state is None or state.last_success_at is None:
        return None
    warning_after, critical_after = fuel_freshness_thresholds(source)
    last_success = serialize_utc(state.last_success_at)
    age = now - last_success
    failed = _fuel_last_attempt_failed(state)
    level = "critical" if age > critical_after else "warning" if age > warning_after and failed else "ok"
    return FuelFreshness(
        source=source, level=level, age_seconds=max(0, int(age.total_seconds())), last_success_at=last_success,
        last_attempt_failed=failed, warning_after=warning_after, critical_after=critical_after,
    )


async def record_lost_fuel_attempt(session_factory, *, now: datetime | None = None) -> LostFuelAttempt | None:
    """결과 없이 끝난 오피넷 유가 시도에 `LOST_FUEL_ATTEMPT_ERROR`를 남긴다. `last_success_at`·`next_due_at`은 그대로다.

    claim(`_mark_source_started`)은 `last_started_at`만 바꾸고, 시도는 끝날 때 성공(`last_success_at` + `last_error=None`)이나
    실패(`last_error`)를 남긴다. 둘 다 없는 claim의 주인 — claim 시각 직전(`FUEL_CLAIM_MAX_DELAY` 안)에 시작한 마지막 Dagster
    유가 실행 — 이 failed로 끝났고 그 뒤에 시작한 유가 실행(체크포인트 저장 재개 포함)도 모두 끝났으면, 그 시도는 결과를
    잃었다. 유가 claim은 실행 행 INSERT와 같은 transaction에서 유가 advisory lock을 쥔 채 하므로 주인이 하나로 정해진다.
    정상 종료한 실행은 결과를 상태 행에 먼저 남기므로 주인이 failed가 아니면 판단하지 않는다. 잡는 경우:

    - op 밖에서 죽어(code-server 재기동·worker 소실·SIGKILL) 회수(`reconcile_collection_runs`)가 failed로 닫은 실행
    - 실패 기록 commit 자체가 실패한 실행(실행 행은 failed인데 상태 행에는 오류가 없다)

    갱신은 읽은 claim 그대로일 때만 한다(CAS). 그 사이 새 claim·성공·실패가 들어오면 0행이고, 실패 처리가 늦게 도착하면
    원래 오류 문장이 이 값을 덮는다. 실행 중인 유가 실행이 있으면 건드리지 않는다. 운영 Dagster 유가 실행만 대상이다.
    """
    now = now or now_utc()
    async with session_factory() as session:
        state = await session.scalar(
            select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE)
        )
        if (
            state is None
            or state.last_started_at is None
            or state.last_error is not None
            or (state.last_success_at is not None
                and serialize_utc(state.last_success_at) >= serialize_utc(state.last_started_at))
        ):
            return None
        claimed_at = state.last_started_at  # DB 값 그대로 비교한다(SQLite는 tz 없는 값을 돌려준다).
        owner = (await session.execute(
            select(CollectionRun.id, CollectionRun.status)
            .where(
                CollectionRun.trigger == FUEL_TRIGGER,
                CollectionRun.started_at <= claimed_at,
                CollectionRun.started_at >= claimed_at - FUEL_CLAIM_MAX_DELAY,
            )
            .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
            .limit(1)
        )).first()
        # 주인이 failed(회수가 닫았거나 실패 기록 전에 끝남)일 때만이다. 정상 종료(success·skipped·partial_success)한
        # 실행은 결과를 상태 행에 먼저 commit하므로, 성공 시각이 claim보다 이른 경우(시계·고정 시각 대역)를 소실로 오인하지 않는다.
        if owner is None or owner.status != "failed":
            return None
        running = await session.scalar(
            select(CollectionRun.id)
            .where(CollectionRun.trigger == FUEL_TRIGGER, CollectionRun.id >= owner.id, CollectionRun.status == "running")
            .limit(1)
        )
        if running is not None:
            return None
        if session.bind.dialect.name == "postgresql":
            # 상태 행을 쥔 수집 transaction 뒤에서 오래 기다리지 않는다(실패하면 다음 tick이 다시 본다).
            await session.execute(text("SET LOCAL lock_timeout = '1s'"))
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
            )
            .values(last_error=LOST_FUEL_ATTEMPT_ERROR, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    if result.rowcount != 1:
        return None
    return LostFuelAttempt(collection_run_id=owner.id, last_started_at=serialize_utc(claimed_at))


async def fuel_freshness_levels(session_factory, *, now: datetime | None = None) -> list[FuelFreshness]:
    """오피넷·휴게소 유가 상태 행을 한 번에 읽어 원천별 단계를 돌려준다(`ok` 포함 — 회복 줄에 쓴다)."""
    now = now or now_utc()
    async with session_factory() as session:
        rows = (await session.scalars(
            select(TransportCollectionState).where(TransportCollectionState.source.in_(tuple(FUEL_FRESHNESS_CYCLES)))
        )).all()
    states = {row.source: row for row in rows}
    levels = []
    for source in FUEL_FRESHNESS_CYCLES:
        level = evaluate_fuel_freshness(source, states.get(source), now=now)
        if level is not None:
            levels.append(level)
    return levels


def _failure_signature(exc: BaseException) -> str:
    """예외 원문 없이 형식 이름과 SQLSTATE만(정체 시계의 `last_failure`와 같은 모양)."""
    from kortravelcommon.pg_errors import pg_error_info

    info = pg_error_info(exc)
    return f"{type(exc).__name__}:{info.sqlstate}" if info is not None else type(exc).__name__


async def check_fuel_freshness(
    session_factory, report: FuelFreshnessReport, *, now: datetime | None = None,
) -> None:
    """유가 시도 소실 기록 → 신선도 판정. 부가 점검이라 실패해도 올리지 않고 `report.failure`에 서명만 남긴다.

    `FUEL_CHECK_TIMEOUT_SECONDS`에서 끊어 회수 예산을 지킨다. tick 전체의 취소(`CancelledError`)는 그대로 올린다.
    """
    try:
        async with asyncio.timeout(FUEL_CHECK_TIMEOUT_SECONDS):
            report.lost_attempt = await record_lost_fuel_attempt(session_factory, now=now)
            report.levels = await fuel_freshness_levels(session_factory, now=now)
            report.checked = True
    except Exception as exc:  # noqa: BLE001 — 회수·정체 판정을 막지 않는다.
        report.failure = _failure_signature(exc)


class FuelFreshnessAlerts:
    """유가 신선도 경보 줄(고정 event 이름 한 줄, `format_stall_alert`와 같은 관례).

    단계가 바뀌면 바로, 같은 단계는 `FUEL_FRESHNESS_REALERT_SECONDS`마다 다시 남긴다. 경고·위험에서 `ok`로 돌아오면 회복 줄을
    한 번 남긴다. sensor cursor는 정체 시계가 소유하므로 마지막 경보는 code-server 프로세스 안에 둔다(재시작하면 현재 단계를
    한 번 더 남길 뿐이다). 줄은 실제로 남길 tick에서만 만든다 — 만든 뒤에는 남긴 것으로 기억한다.
    """

    _CHECK_FAILED = "check_failed"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[str, tuple[str, float]] = {}

    def lines(self, report: FuelFreshnessReport, *, now: float) -> list[tuple[int, str]]:
        """(logging 수준, 한 줄) 목록."""
        out: list[tuple[int, str]] = []
        if report.lost_attempt is not None:
            lost = report.lost_attempt
            out.append((logging.WARNING, (
                f"{FUEL_FRESHNESS_EVENT}.lost_attempt source={OPINET_SOURCE} "
                f"collection_run_id={lost.collection_run_id} last_started_at={lost.last_started_at.isoformat()}"
            )))
        with self._lock:
            if report.failure is not None:
                # 판정하지 못한 tick은 원천별 단계 기억을 바꾸지 않는다.
                if self._due(self._CHECK_FAILED, "failed", now):
                    out.append((logging.WARNING, f"{FUEL_FRESHNESS_EVENT}.check_failed error={report.failure}"))
                return out
            if not report.checked:
                # 점검을 시작하지 못한 tick(예산 부족·앞 단계 장애)도 기억을 바꾸지 않는다. 빈 `levels`를 "모두 판단 대상 아님"으로
                # 읽어 경보 기억을 지우면, 다음 tick이 같은 단계를 즉시 다시 남기고 그 사이 회복 줄을 놓친다.
                return out
            self._last.pop(self._CHECK_FAILED, None)
            seen = set()
            for item in report.levels:
                seen.add(item.source)
                previous = self._last.get(item.source)
                if item.level == "ok":
                    if previous is not None:
                        del self._last[item.source]
                        out.append((logging.WARNING, (
                            f"{FUEL_FRESHNESS_EVENT}.recovered source={item.source} age_seconds={item.age_seconds} "
                            f"last_success_at={item.last_success_at.isoformat()} previous={previous[0]}"
                        )))
                    continue
                if self._due(item.source, item.level, now):
                    out.append((logging.ERROR if item.level == "critical" else logging.WARNING, format_fuel_freshness(item)))
            for source in [key for key in self._last if key not in seen]:
                del self._last[source]  # 상태 행·성공 이력이 사라진 원천(판단 대상 아님)
        return out

    def _due(self, key: str, level: str, now: float) -> bool:
        previous = self._last.get(key)
        if previous is not None and previous[0] == level and now - previous[1] < FUEL_FRESHNESS_REALERT_SECONDS:
            return False
        self._last[key] = (level, now)
        return True


def format_fuel_freshness(item: FuelFreshness) -> str:
    """경고·위험 한 줄. 상태 행의 고정 필드만 싣는다(오류 원문 없음)."""
    return (
        f"{FUEL_FRESHNESS_EVENT}.{item.level} source={item.source} age_seconds={item.age_seconds} "
        f"last_success_at={item.last_success_at.isoformat()} "
        f"last_attempt_failed={'true' if item.last_attempt_failed else 'false'} "
        f"warning_after_seconds={int(item.warning_after.total_seconds())} "
        f"critical_after_seconds={int(item.critical_after.total_seconds())}"
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
) -> int:
    """회수 sensor 한 tick.

    수집 신선도를 먼저 본다(회수가 예산을 다 써도 정체 판단은 매 tick 한다). 이어서 회수를 예산 안에서
    이어 하고, 정체면 `CollectionStalled`로 정체 시계에 알린다.

    `collection_scheduled(trigger)`가 False인 trigger(예: 점검으로 schedule을 STOPPED)는 수집이 멈춘 것이
    의도이므로 정체로 세지 않고 `paused`에 담는다. 판정은 오래된 trigger가 있을 때만 부른다.

    `fuel_report`를 주면 회수 전에 유가 시도 소실 기록과 신선도 판정(`check_fuel_freshness`)을 해 담는다. 유가 신선도는
    정체가 아니다 — 정체 시계에 알리지 않고 경보 줄만 남긴다(`definitions._report_fuel_freshness`).
    """
    stale = await stale_five_minute_triggers(session_factory)
    if stale and collection_scheduled is not None:
        scheduled = [(trigger, minutes) for trigger, minutes in stale if collection_scheduled(trigger)]
        if paused is not None:
            paused.extend(trigger for trigger, minutes in stale if (trigger, minutes) not in scheduled)
        stale = scheduled
    if fuel_report is not None and _has_budget(remaining):
        await check_fuel_freshness(session_factory, fuel_report)
    recovered = await reconcile_collection_runs(
        session_factory, instance, position=position, remaining=remaining
    )
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
