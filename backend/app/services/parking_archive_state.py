"""수집과 같은 transaction/lease에서 유지하는 작은 파생 상태와 보류 표시."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc, serialize_utc
from app.models import (ParkingArchiveIssue, ParkingGlobalStatisticsBucket, ParkingLatestState,
                        ParkingLot, ParkingSnapshot)
from app.services.parking_statistics_archive import RAW_RETENTION, bucket_start

_CURRENT_FIELDS = (ParkingSnapshot.id, ParkingSnapshot.airport_id, ParkingSnapshot.parking_lot_id,
                   ParkingSnapshot.source, ParkingSnapshot.observed_at, ParkingSnapshot.collected_at,
                   ParkingSnapshot.available_spaces, ParkingSnapshot.occupied_spaces, ParkingSnapshot.total_spaces,
                   ParkingSnapshot.congestion_label, ParkingSnapshot.congestion_ratio)


def is_newer_current(candidate: Any, current: Any) -> bool:
    """archive 분석의 live 우선 규칙과 public current의 id 우선 규칙은 다르다."""
    order = getattr(current, "snapshot_order", getattr(current, "id", 0))
    return (serialize_utc(candidate.observed_at), candidate.id) > (
        serialize_utc(current.observed_at), order,
    )


def latest_state_values(row: Any, *, latest_ingested_at: datetime | None = None) -> dict[str, Any]:
    """원문 없이 현재 응답에 필요한 값과 순서·수신 watermark만 남긴다."""
    return {"parking_lot_id": row.parking_lot_id, "airport_id": row.airport_id,
            "snapshot_order": row.id, "source": row.source,
            "observed_at": serialize_utc(row.observed_at),
            "collected_at": serialize_utc(row.collected_at),
            "latest_ingested_at": max(serialize_utc(row.collected_at),
                                       serialize_utc(latest_ingested_at or row.collected_at)),
            "available_spaces": row.available_spaces, "occupied_spaces": row.occupied_spaces,
            "total_spaces": row.total_spaces, "congestion_label": row.congestion_label,
            "congestion_ratio": row.congestion_ratio}


async def record_archive_issue(
    session: AsyncSession, *, scope_key: str, at: datetime, reason: str,
    max_snapshot_id: int = 0, checked_at: datetime | None = None,
) -> None:
    """동일 원본 재발견을 관측수로 가산하지 않고 마지막 발견 watermark만 갱신한다."""
    timestamp = serialize_utc(checked_at or now_utc())
    record = await session.get(ParkingArchiveIssue, (scope_key, at))
    if record is None:
        record = ParkingArchiveIssue(scope_key=scope_key, bucket_at=at, reason=reason,
                                     max_seen_snapshot_id=max_snapshot_id,
                                     first_seen_at=timestamp, last_seen_at=timestamp)
        session.add(record)
    else:
        record.reason = reason
        record.max_seen_snapshot_id = max(record.max_seen_snapshot_id, max_snapshot_id)
        record.last_seen_at = timestamp
    await session.flush()


async def capture_latest_snapshot(session: AsyncSession, snapshot: ParkingSnapshot) -> None:
    """public current와 같은 observed/id 선택. 오래된 지연 관측의 수신시각은 별도 유지한다."""
    current = await session.get(ParkingLatestState, snapshot.parking_lot_id)
    if current is None:
        # seed가 아직 도달하지 않은 lot의 첫 수집이 지연 관측일 수 있다.
        # 들어온 한 행 대신 기존 public current와 같은 전체 raw의 observed/id 승자를 읽는다.
        await session.flush()
        latest = (await session.execute(select(*_CURRENT_FIELDS).where(
            ParkingSnapshot.airport_id == snapshot.airport_id,
            ParkingSnapshot.parking_lot_id == snapshot.parking_lot_id,
        ).order_by(ParkingSnapshot.observed_at.desc(), ParkingSnapshot.id.desc()).limit(1))).first()
        if latest is None:
            raise RuntimeError("현재 요약을 초기화할 저장 원본이 없습니다.")
        ingested = await session.scalar(select(func.max(ParkingSnapshot.collected_at)).where(
            ParkingSnapshot.airport_id == snapshot.airport_id,
            ParkingSnapshot.parking_lot_id == snapshot.parking_lot_id,
        ))
        session.add(ParkingLatestState(**latest_state_values(
            SimpleNamespace(**latest._mapping), latest_ingested_at=ingested,
        )))
    else:
        latest_ingested = max(serialize_utc(current.latest_ingested_at), serialize_utc(snapshot.collected_at))
        if is_newer_current(snapshot, current):
            for key, value in latest_state_values(snapshot, latest_ingested_at=latest_ingested).items():
                setattr(current, key, value)
        else:
            current.latest_ingested_at = latest_ingested
    # 2A는 이력 INSERT를 막거나 통계를 수정하지 않는다. sealed 재삽입은 보류로 드러낸다.
    at = bucket_start(snapshot.observed_at)
    if at < bucket_start(now_utc() - RAW_RETENTION):
        sealed = await session.get(ParkingGlobalStatisticsBucket, at)
        if sealed is not None and snapshot.id > sealed.max_snapshot_id:
            await record_archive_issue(session, scope_key=f"airport:{snapshot.airport_id}", at=at,
                                       reason="late_source_rows", max_snapshot_id=snapshot.id)
    await session.flush()


async def seed_latest_states(session: AsyncSession, *, max_lots: int = 512) -> int:
    """기존 raw를 지우지 않고 현재 요약이 없는 lot만 bounded seed한다."""
    if not 1 <= max_lots <= 2048:
        raise ValueError("현재 요약의 한 실행 lot 상한은 1~2048입니다.")
    lots = (await session.execute(select(ParkingLot.id, ParkingLot.airport_id).outerjoin(
        ParkingLatestState, ParkingLatestState.parking_lot_id == ParkingLot.id,
    ).where(ParkingLatestState.parking_lot_id.is_(None), exists(select(1).where(
        ParkingSnapshot.parking_lot_id == ParkingLot.id,
    ))).order_by(ParkingLot.id).limit(max_lots))).all()
    if not lots:
        return 0
    ingested = dict((await session.execute(select(
        ParkingSnapshot.parking_lot_id, func.max(ParkingSnapshot.collected_at),
    ).where(ParkingSnapshot.parking_lot_id.in_([lot.id for lot in lots])).group_by(
        ParkingSnapshot.parking_lot_id,
    ))).all())
    seeded = 0
    for lot in lots:
        row = (await session.execute(select(*_CURRENT_FIELDS).where(
            ParkingSnapshot.airport_id == lot.airport_id, ParkingSnapshot.parking_lot_id == lot.id,
        ).order_by(ParkingSnapshot.observed_at.desc(), ParkingSnapshot.id.desc()).limit(1))).first()
        if row is not None:
            session.add(ParkingLatestState(**latest_state_values(
                SimpleNamespace(**row._mapping), latest_ingested_at=ingested.get(lot.id),
            )))
            seeded += 1
    await session.flush()
    return seeded
