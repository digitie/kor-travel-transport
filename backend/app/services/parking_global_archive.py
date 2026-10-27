"""전국 동시각 통계를 영구 seal한다. reader 전환·원본 삭제는 수행하지 않는다."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import ensure_tz, now_utc
from app.models import ParkingArchiveIssue, ParkingGlobalStatisticsBucket, ParkingSnapshot, ParkingStatisticsBucket
from app.services.parking_archive_state import record_archive_issue, seed_latest_states
from app.services.parking_statistics_archive import (
    BUCKET_INTERVAL, RAW_RETENTION, ParkingArchiveConflict, _bucket_expression, _digest, _previous_by_lot,
    _recent_bucket_rows_exists,
    archive_parking_statistics, bucket_start, raw_digest, verify_bucket,
)
from app.services.analytics import build_global_cohort_summary

GLOBAL_FORMAT_VERSION = 1


def global_bucket_values(
    rows: list[ParkingSnapshot], airport_records: dict[int, ParkingStatisticsBucket],
    previous: dict[int, ParkingSnapshot], *, sealed_at: datetime,
) -> dict[str, Any]:
    """각 공항 raw/통계를 먼저 검산한 뒤 전국 cohort와 검산 membership을 만든다."""
    if not rows:
        raise ParkingArchiveConflict("전국 통계를 검산할 원본이 없습니다.")
    at = bucket_start(rows[0].observed_at)
    if any(bucket_start(row.observed_at) != at for row in rows):
        raise ParkingArchiveConflict("전국 통계는 단일 UTC10분 범위만 허용합니다.")
    grouped: dict[int, list[ParkingSnapshot]] = defaultdict(list)
    for row in rows:
        grouped[row.airport_id].append(row)
    if set(grouped) != set(airport_records):
        raise ParkingArchiveConflict("전국 통계의 공항 membership이 일치하지 않습니다.")
    proofs = {}
    for airport_id, observations in sorted(grouped.items()):
        record = airport_records[airport_id]
        verify_bucket(record, observations, previous)
        proofs[str(airport_id)] = {"raw_count": record.raw_count,
                                   "selected_count": record.selected_count,
                                   "max_snapshot_id": record.max_snapshot_id,
                                   "raw_sha256": record.raw_sha256,
                                   "statistics_sha256": record.statistics_sha256}
    summary, selected_count = build_global_cohort_summary(rows)
    payload = {"cohorts": summary}
    return {"bucket_at": at, "bucket_end": at + BUCKET_INTERVAL,
            "format_version": GLOBAL_FORMAT_VERSION, "raw_count": len(rows),
            "selected_count": selected_count, "max_snapshot_id": max(row.id for row in rows),
            "raw_sha256": raw_digest(rows), "statistics_sha256": _digest(payload),
            "statistics_json": payload, "airport_proofs_json": proofs,
            "sealed_at": ensure_tz(sealed_at, "UTC").astimezone(UTC)}


def verify_global_bucket(
    record: ParkingGlobalStatisticsBucket, rows: list[ParkingSnapshot],
    airport_records: dict[int, ParkingStatisticsBucket], previous: dict[int, ParkingSnapshot],
) -> None:
    """prune 전에 재사용할 검산. 부분 잔존 raw나 새 id 재삽입도 통계를 덮지 않는다."""
    expected = global_bucket_values(rows, airport_records, previous, sealed_at=record.sealed_at)
    for key, value in expected.items():
        actual = getattr(record, key)
        if isinstance(value, datetime):
            actual = ensure_tz(actual, "UTC")
        if actual != value:
            raise ParkingArchiveConflict("전국 통계의 원본 지문·공항 coverage·충분통계가 일치하지 않습니다.")


def _next_global_at_query(dialect: str, complete_before: datetime, collected_before: datetime | None = None):
    expression = _bucket_expression(ParkingSnapshot.observed_at, dialect)
    covered = exists(select(1).select_from(ParkingGlobalStatisticsBucket).where(
        ParkingGlobalStatisticsBucket.bucket_at == expression,
        ParkingGlobalStatisticsBucket.max_snapshot_id >= ParkingSnapshot.id,
    ))
    conditions = [ParkingSnapshot.observed_at < complete_before, ~covered]
    if collected_before is not None:
        sealed = exists(select(1).select_from(ParkingGlobalStatisticsBucket).where(
            ParkingGlobalStatisticsBucket.bucket_at == expression,
        ))
        conditions.append(or_(sealed, ~_recent_bucket_rows_exists(
            expression, dialect, collected_before, by_airport=False,
        )))
    return select(ParkingSnapshot.observed_at).where(*conditions).order_by(ParkingSnapshot.observed_at).limit(1)


async def archive_global_statistics(
    session: AsyncSession, *, checked_at: datetime | None = None, max_buckets: int = 144,
) -> dict[str, Any]:
    """원본 한 날짜 범위만 읽는다. 공항별 완료분만 전국 seal로 발행한다."""
    if not 1 <= max_buckets <= 144:
        raise ValueError("전국 통계의 한 실행 상한은 1~144입니다.")
    if session.bind.dialect.name == "postgresql":
        acquired = await session.scalar(text(
            "SELECT pg_try_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"
        ))
        if not acquired:
            return {"status": "busy", "coverage_status": "not_audited", "global_buckets": 0}
    issue = await session.scalar(select(ParkingArchiveIssue).limit(1))
    if issue is not None:
        return {"status": "blocked", "coverage_status": "conflict", "global_buckets": 0,
                "blocked_reason": issue.reason, "blocked_bucket_at": issue.bucket_at.isoformat()}
    checked = ensure_tz(checked_at or now_utc(), "UTC").astimezone(UTC)
    cutoff = checked - RAW_RETENTION
    complete_before = bucket_start(cutoff)
    pending = await session.scalar(_next_global_at_query(session.bind.dialect.name, complete_before))
    if pending is None:
        return {"status": "no_new_rows", "coverage_status": "not_audited", "global_buckets": 0}
    earliest = await session.scalar(_next_global_at_query(session.bind.dialect.name, complete_before, cutoff))
    if earliest is None:
        return {"status": "deferred", "coverage_status": "partial", "global_buckets": 0,
                "deferred_global_buckets": 1, "deferred_count_scope": "first_pending_bucket",
                "oldest_pending_at": bucket_start(pending).isoformat()}
    start = bucket_start(earliest)
    if start < bucket_start(pending) + timedelta(days=1):
        start = bucket_start(pending)
    rows = list((await session.scalars(select(ParkingSnapshot).where(
        ParkingSnapshot.observed_at >= start,
        ParkingSnapshot.observed_at < min(start + timedelta(days=1), complete_before),
    ).order_by(ParkingSnapshot.observed_at, ParkingSnapshot.id))).all())
    grouped: dict[datetime, list[ParkingSnapshot]] = defaultdict(list)
    for row in rows:
        grouped[bucket_start(row.observed_at)].append(row)
    archived = deferred = 0
    for at, observations in sorted(grouped.items()):
        existing = await session.get(ParkingGlobalStatisticsBucket, at)
        airport_ids = {row.airport_id for row in observations}
        records = {record.airport_id: record for record in (await session.scalars(
            select(ParkingStatisticsBucket).where(ParkingStatisticsBucket.bucket_at == at,
                                                  ParkingStatisticsBucket.airport_id.in_(airport_ids)),
        )).all()}
        previous = await _previous_by_lot(session, at, {row.parking_lot_id for row in observations})
        if existing is not None:
            try:
                verify_global_bucket(existing, observations, records, previous)
            except ParkingArchiveConflict:
                await record_archive_issue(session, scope_key="global", at=at,
                                           reason="sealed_raw_mismatch",
                                           max_snapshot_id=max(row.id for row in observations), checked_at=checked)
                return {"status": "blocked", "coverage_status": "conflict", "global_buckets": archived,
                        "blocked_bucket_at": at.isoformat()}
            continue
        if any(ensure_tz(row.collected_at, "UTC") >= cutoff for row in observations) or set(records) != airport_ids:
            deferred += 1
            continue
        if archived >= max_buckets:
            break
        try:
            values = global_bucket_values(observations, records, previous, sealed_at=checked)
        except ParkingArchiveConflict:
            await record_archive_issue(session, scope_key="global", at=at,
                                       reason="airport_statistics_mismatch",
                                       max_snapshot_id=max(row.id for row in observations), checked_at=checked)
            return {"status": "blocked", "coverage_status": "conflict", "global_buckets": archived,
                    "blocked_bucket_at": at.isoformat()}
        record = ParkingGlobalStatisticsBucket(**values)
        session.add(record)
        await session.flush()
        verify_global_bucket(record, observations, records, previous)
        archived += 1
    return {"status": "batch_complete", "coverage_status": "partial", "global_buckets": archived,
            "deferred_global_buckets": deferred}


async def archive_parking_with_coverage(
    session: AsyncSession, *, checked_at: datetime | None = None,
) -> dict[str, Any]:
    """현재 seed·공항 통계·전국 seal을 같은 lease로 처리한다. 삭제는 항상0이다."""
    if session.bind.dialect.name == "postgresql":
        acquired = await session.scalar(text(
            "SELECT pg_try_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"
        ))
        if not acquired:
            return {"status": "busy", "coverage_status": "not_audited", "pruned_snapshots": 0}
    issue = await session.scalar(select(ParkingArchiveIssue).limit(1))
    if issue is not None:
        return {"status": "blocked", "coverage_status": "conflict", "pruned_snapshots": 0,
                "blocked_reason": issue.reason, "blocked_bucket_at": issue.bucket_at.isoformat()}
    seeded = await seed_latest_states(session)
    try:
        async with session.begin_nested():
            airport_result = await archive_parking_statistics(session, checked_at=checked_at)
    except ParkingArchiveConflict:
        # savepoint만 되돌려 통계 원문은 보존하고, 보류 표시는 외부 transaction에서 commit한다.
        await record_archive_issue(session, scope_key="batch", at=datetime(1970, 1, 1, tzinfo=UTC),
                                   reason="airport_archive_conflict", checked_at=checked_at)
        return {"status": "blocked", "coverage_status": "conflict", "latest_seeded": seeded,
                "pruned_snapshots": 0}
    global_result = await archive_global_statistics(session, checked_at=checked_at)
    return {**airport_result, **global_result, "latest_seeded": seeded, "pruned_snapshots": 0}
