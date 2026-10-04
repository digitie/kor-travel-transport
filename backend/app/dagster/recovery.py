"""수집 행의 Dagster 소유권·게시 fencing과 중단 기록 회수. 도메인 SQL은 앱이 소유한다."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from kortravelcommon.deadline import call_with_deadline
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from app.core.time_utils import now_utc, serialize_utc
from app.models import CollectionRun

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


async def reconcile_collection_runs(
    session_factory, instance, *, page_size: int = PAGE_SIZE
) -> int:
    """첫 생존 page 뒤의 terminal 행도 읽는다. metadata 장애는 사망으로 간주하지 않는다."""
    cursor = 0
    recovered = 0
    while True:
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
            return recovered
        for row in rows:
            try:
                run = call_with_deadline(
                    lambda owner=row.orchestrator_run_id: instance.get_run_by_id(owner),
                    timeout_seconds=10,
                )
            except Exception:  # noqa: BLE001 — metadata 장애에서는 소유권을 회수하지 않는다.
                # metadata 장애 때 전체 tick을 멈춘다. per-row 반복 timeout도 만들지 않는다.
                return recovered
            now = now_utc()
            heartbeat = serialize_utc(row.heartbeat_at or row.started_at)
            missing_expired = run is None and heartbeat <= now - MISSING_RUN_GRACE
            if not missing_expired and (run is None or not run.is_finished):
                continue
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
        cursor = rows[-1].id
