"""수집 행의 Dagster 소유권·게시 fencing과 중단 기록 회수. 도메인 SQL은 앱이 소유한다."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from kortravelcommon.deadline import call_with_deadline
from kortravelcommon.stall import StallClock
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.time_utils import now_utc, serialize_utc
from app.models import CollectionRun
from app.services.transport_collection import TRANSPORT_TRIGGER_PREFIX

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
    실행이 4시간 상한까지 매달려 coalescing이 새 실행을 막는 경우도 정체로 잡힌다.
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
) -> int:
    """회수 sensor 한 tick.

    수집 신선도를 먼저 본다(회수가 예산을 다 써도 정체 판단은 매 tick 한다). 이어서 회수를 예산 안에서
    이어 하고, 정체면 `CollectionStalled`로 정체 시계에 알린다.
    """
    stale = await stale_five_minute_triggers(session_factory)
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
