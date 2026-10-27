"""48시간 원본 정책의 선행 단계: 검산 가능한 영구 통계의 멱등 backfill.

아직 원본에 의존하는 읽기 경로를 전환하기 전에는 삭제를 허용하지 않는다.
캐시 TTL과 독립적이며 provider 호출·수집 실행 생성·원본 변경을 하지 않는다.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, Interval, Integer, String, case, cast, exists, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.time_utils import ensure_tz, now_utc
from app.models import ParkingSnapshot, ParkingStatisticsBucket
from app.services.analytics import deduplicate_snapshots

RAW_RETENTION = timedelta(hours=48)
BUCKET_INTERVAL = timedelta(minutes=10)
FORMAT_VERSION = 1
THRESHOLDS = (10, 50)


class ParkingArchiveConflict(RuntimeError):
    """기존 영구 통계와 달라진 원본을 자동으로 덮어쓰지 않는다."""


def bucket_start(value: datetime) -> datetime:
    value = ensure_tz(value, "UTC").astimezone(UTC)
    return value.replace(minute=value.minute // 10 * 10, second=0, microsecond=0)


def _iso(value: datetime) -> str:
    return ensure_tz(value, "UTC").astimezone(UTC).isoformat()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def raw_digest(rows: list[ParkingSnapshot]) -> str:
    # 개별 JSON은 checksum 계산에만 쓰며 통계 JSON에 복사하지 않는다.
    return _digest([{
        "id": row.id, "airport": row.airport_id, "lot": row.parking_lot_id,
        "source": row.source, "observed": _iso(row.observed_at), "collected": _iso(row.collected_at),
        "available": row.available_spaces, "occupied": row.occupied_spaces, "total": row.total_spaces,
        "congestion_label": row.congestion_label, "congestion_ratio": row.congestion_ratio,
        "raw_item": row.raw_item_json,
    } for row in sorted(rows, key=lambda item: item.id)])


def _summary(values: list[int]) -> dict[str, int]:
    return {"count": len(values), "sum": sum(values), "min": min(values), "max": max(values)}


def _point(row: ParkingSnapshot) -> dict[str, Any]:
    # 최신/정각 경계 값은 추이 재표본화용이다. 모든 원관측을 보존하지 않는다.
    return {"observed_at": _iso(row.observed_at), "available": row.available_spaces,
            "occupied": row.occupied_spaces, "total": row.total_spaces}


def build_bucket(
    rows: list[ParkingSnapshot], previous: dict[int, ParkingSnapshot],
) -> tuple[dict[str, Any], int]:
    """동일 시각 중복을 live→최근 적재→id 순으로 정리한 충분통계/이벤트."""
    selected = deduplicate_snapshots(rows)
    if not selected:
        raise ValueError("빈 원본 버킷은 통계로 발행하지 않습니다.")
    start = bucket_start(selected[0].observed_at)
    airport_id = selected[0].airport_id
    if any(row.airport_id != airport_id or bucket_start(row.observed_at) != start for row in rows):
        raise ValueError("한 공항의 단일 10분 버킷만 허용합니다.")
    lots: dict[int, list[ParkingSnapshot]] = defaultdict(list)
    cohorts: dict[datetime, int] = defaultdict(int)
    events = []
    for row in selected:
        lots[row.parking_lot_id].append(row)
        cohorts[ensure_tz(row.observed_at, "UTC")] += row.available_spaces
        prior = previous.get(row.parking_lot_id)
        if prior is not None:
            for threshold in THRESHOLDS:
                down = prior.available_spaces >= threshold > row.available_spaces
                up = prior.available_spaces < threshold <= row.available_spaces
                if down or up:
                    events.append({"parking_lot_id": row.parking_lot_id, "threshold": threshold,
                                   "direction": "down" if down else "up",
                                   "previous_at": _iso(prior.observed_at), "crossed_at": _iso(row.observed_at),
                                   "previous_available_spaces": prior.available_spaces,
                                   "current_available_spaces": row.available_spaces})
        previous[row.parking_lot_id] = row
    payload_lots = []
    for lot_id, observations in sorted(lots.items()):
        capacity_positive = [row for row in observations if row.total_spaces > 0]
        positive = None
        if capacity_positive:
            positive = {**_summary([row.available_spaces for row in capacity_positive]),
                        "capacity_min": min(row.total_spaces for row in capacity_positive),
                        "capacity_max": max(row.total_spaces for row in capacity_positive),
                        "latest_observed_at": _iso(capacity_positive[-1].observed_at)}
        payload_lots.append({"parking_lot_id": lot_id,
                             "available": _summary([row.available_spaces for row in observations]),
                             "positive_capacity": positive,
                             "first": _point(observations[0]),
                             "last": {**_point(observations[-1]),
                                      "collected_at": _iso(observations[-1].collected_at),
                                      "congestion_label": observations[-1].congestion_label,
                                      "congestion_ratio": observations[-1].congestion_ratio}})
    return {"lots": payload_lots, "airport_cohorts": _summary(list(cohorts.values())),
            "events": events}, len(selected)


def verify_bucket(
    record: ParkingStatisticsBucket, rows: list[ParkingSnapshot], previous: dict[int, ParkingSnapshot],
) -> None:
    """삭제 전에도 재사용하는 fail-closed 검산. 잘못된 버전/유실/변조는 예외다."""
    if not rows:
        raise ParkingArchiveConflict("집계한 구간의 원본이 없어 지문을 검산할 수 없습니다.")
    expected, selected_count = build_bucket(rows, dict(previous))
    if (record.format_version != FORMAT_VERSION or record.raw_count != len(rows)
            or record.raw_sha256 != raw_digest(rows)
            or record.statistics_sha256 != _digest(record.statistics_json)
            or record.statistics_sha256 != _digest(expected)
            or record.airport_id != rows[0].airport_id
            or ensure_tz(record.bucket_at, "UTC") != bucket_start(rows[0].observed_at)
            or record.selected_count != selected_count
            or record.max_snapshot_id != max(row.id for row in rows)
            or record.selected_count != sum(lot["available"]["count"] for lot in record.statistics_json["lots"])
            or ensure_tz(record.bucket_end, "UTC") != ensure_tz(record.bucket_at, "UTC") + BUCKET_INTERVAL):
        raise ParkingArchiveConflict("주차 원본 수량·지문 또는 영구 통계 검산이 일치하지 않습니다.")


async def _previous_by_lot(
    session: AsyncSession, start: datetime, lot_ids: set[int],
) -> dict[int, ParkingSnapshot]:
    # 아직 삭제가 비활성이므로 원본에서 정확한 직전 상태를 얻을 수 있다.
    # 후속 읽기/삭제 전환은 archive last와 함께 이 경계도 전환해야 한다.
    result = {}
    for lot_id in sorted(lot_ids):
        # 기존 lot/time 인덱스의 역방향 최신 한 행 탐색으로 전체 과거 정렬을 피한다.
        row = await session.scalar(select(ParkingSnapshot).where(
            ParkingSnapshot.parking_lot_id == lot_id, ParkingSnapshot.observed_at < start,
        ).order_by(
            ParkingSnapshot.observed_at.desc(),
            case((func.substr(ParkingSnapshot.source, 1, 10) == "migration_", 1), else_=0),
            ParkingSnapshot.collected_at.desc(), ParkingSnapshot.id.desc(),
        ).limit(1))
        if row is not None:
            result[lot_id] = row
    return result


def _bucket_expression(column: Any, dialect: str):
    if dialect == "postgresql":
        return func.date_bin(literal(BUCKET_INTERVAL, type_=Interval()), column,
                             literal(datetime(1970, 1, 1, tzinfo=UTC), type_=DateTime(timezone=True)))
    minute = cast(func.strftime("%M", column), Integer)
    return (func.strftime("%Y-%m-%d %H:", column, type_=String)
            + func.printf("%02d", minute.op("/")(10) * 10, type_=String) + ":00.000000")


def _recent_bucket_rows_exists(at_expression: Any, dialect: str, cutoff: datetime, *, by_airport: bool):
    recent = aliased(ParkingSnapshot)
    end = (at_expression + literal(BUCKET_INTERVAL, type_=Interval()) if dialect == "postgresql"
           else func.datetime(at_expression, "+10 minutes"))
    conditions = [recent.observed_at >= at_expression, recent.observed_at < end,
                  recent.collected_at >= cutoff]
    if by_airport:
        conditions.append(recent.airport_id == ParkingSnapshot.airport_id)
    return exists(select(1).select_from(recent).where(*conditions))


def _next_unarchived_at_query(dialect: str, complete_before: datetime, collected_before: datetime | None = None):
    at_expression = _bucket_expression(ParkingSnapshot.observed_at, dialect)
    covered = exists().where(
        ParkingStatisticsBucket.airport_id == ParkingSnapshot.airport_id,
        ParkingStatisticsBucket.bucket_at == at_expression,
        ParkingStatisticsBucket.max_snapshot_id >= ParkingSnapshot.id,
    )
    conditions = [ParkingSnapshot.observed_at < complete_before, ~covered]
    if collected_before is not None:
        sealed = exists().where(ParkingStatisticsBucket.airport_id == ParkingSnapshot.airport_id,
                                 ParkingStatisticsBucket.bucket_at == at_expression)
        # 새 bucket 전체가 완결돼야 한다. 기존 seal의 새 id는 fresh여도 충돌 검산을 피하지 않는다.
        conditions.append(or_(sealed, ~_recent_bucket_rows_exists(
            at_expression, dialect, collected_before, by_airport=True,
        )))
    return select(ParkingSnapshot.observed_at).where(*conditions).order_by(ParkingSnapshot.observed_at).limit(1)


async def archive_parking_statistics(
    session: AsyncSession, *, checked_at: datetime | None = None, max_buckets: int = 144,
) -> dict[str, int | str | None]:
    """완결된 과거 버킷을 최대 1일 범위에서 처리한다. commit은 호출자가 소유한다.

    원천 collector와 같은 advisory lock을 사용한다. 경합은 즉시 반환하고 원본을 변경하지 않는다.
    동일 공항/시간 버킷에 늦게 추가된 원본은 이미 발행한 통계를 덮지 않고 검산 실패로 보류한다.
    """
    if not 1 <= max_buckets <= 2016:
        raise ValueError("한 실행의 버킷 상한은 1~2016입니다.")
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        acquired = await session.scalar(text(
            "SELECT pg_try_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"
        ))
        if not acquired:
            return {**_run_metadata(ensure_tz(checked_at or now_utc(), "UTC").astimezone(UTC), max_buckets),
                    "status": "busy", "coverage_status": "not_audited", "archived_buckets": 0, "pruned_snapshots": 0}
    checked = ensure_tz(checked_at or now_utc(), "UTC").astimezone(UTC)
    cutoff = checked - RAW_RETENTION
    complete_before = bucket_start(cutoff)
    metadata = _run_metadata(checked, max_buckets)
    pending = await session.scalar(_next_unarchived_at_query(session.bind.dialect.name, complete_before))
    if pending is None:
        # max_id는 append-only 수집의 새 행 탐색용이다. 같은 id 변조·삭제 검산을 뜻하지 않는다.
        # 전체 coverage 완료나 삭제 가능 상태로 반환하지 않는다. 삭제 직전에는 verify_bucket 필수다.
        return {**metadata, "status": "no_new_rows", "coverage_status": "not_audited", "archived_buckets": 0,
                "pruned_snapshots": 0}
    earliest = await session.scalar(_next_unarchived_at_query(session.bind.dialect.name, complete_before, cutoff))
    if earliest is None:
        return {**metadata, "status": "deferred", "coverage_status": "partial", "archived_buckets": 0,
                "deferred_buckets": 1, "deferred_count_scope": "first_pending_bucket",
                "oldest_pending_at": _iso(bucket_start(pending)), "pruned_snapshots": 0}
    start = bucket_start(earliest)
    if start < bucket_start(pending) + timedelta(days=1):
        start = bucket_start(pending)
    end = min(start + timedelta(days=1), complete_before)
    rows = list((await session.scalars(select(ParkingSnapshot).where(
        ParkingSnapshot.observed_at >= start, ParkingSnapshot.observed_at < end,
    ).order_by(ParkingSnapshot.observed_at, ParkingSnapshot.id))).all())
    grouped: dict[tuple[datetime, int], list[ParkingSnapshot]] = defaultdict(list)
    for row in rows:
        grouped[(bucket_start(row.observed_at), row.airport_id)].append(row)
    metadata.update({"selection_start_at": _iso(start), "selection_end_exclusive": _iso(end),
                     "selected_snapshots": len(rows), "selected_buckets": len(grouped)})
    if rows:
        metadata.update({"selected_observed_min_at": _iso(rows[0].observed_at),
                         "selected_observed_max_at": _iso(rows[-1].observed_at)})
    previous = await _previous_by_lot(session, start, {row.parking_lot_id for row in rows})
    archived = 0
    deferred = 0
    verified_ats: list[datetime] = []
    archived_ats: list[datetime] = []
    for (at, airport_id), observations in sorted(grouped.items()):
        existing = await session.get(ParkingStatisticsBucket, (airport_id, at))
        if existing is not None:
            verify_bucket(existing, observations, previous)
            verified_ats.append(at)
            # 다음 threshold 경계에도 기존 구간의 직전 관측을 반영한다.
            build_bucket(observations, previous)
            continue
        if any(ensure_tz(row.collected_at, "UTC") >= cutoff for row in observations):
            deferred += 1
            build_bucket(observations, previous)
            continue
        if archived >= max_buckets:
            break
        prior_for_verification = dict(previous)
        payload, selected_count = build_bucket(observations, previous)
        record = ParkingStatisticsBucket(
            airport_id=airport_id, bucket_at=at, bucket_end=at + BUCKET_INTERVAL,
            format_version=FORMAT_VERSION, raw_count=len(observations), selected_count=selected_count,
            max_snapshot_id=max(row.id for row in observations), raw_sha256=raw_digest(observations),
            statistics_sha256=_digest(payload), statistics_json=payload,
            created_at=ensure_tz(checked_at or now_utc(), "UTC").astimezone(UTC),
        )
        session.add(record)
        await session.flush()
        verify_bucket(record, observations, prior_for_verification)
        verified_ats.append(at)
        archived_ats.append(at)
        archived += 1
    if verified_ats:
        metadata.update({"verification_scope": "selected_bucket_subset", "verified_buckets": len(verified_ats),
                         "verified_min_bucket_at": _iso(min(verified_ats)),
                         "verified_max_bucket_at": _iso(max(verified_ats))})
    if archived_ats:
        metadata.update({"archived_min_bucket_at": _iso(min(archived_ats)),
                         "archived_max_bucket_at": _iso(max(archived_ats))})
    return {**metadata, "status": "batch_complete", "coverage_status": "partial", "archived_buckets": archived,
            "deferred_buckets": deferred, "oldest_pending_at": _iso(bucket_start(pending)), "pruned_snapshots": 0}


def _run_metadata(checked_at: datetime, max_buckets: int) -> dict[str, int | str | None]:
    """실제 선택 창과 검산/발행 extrema를 구분하며 전체 coverage를 추정하지 않는다."""
    cutoff = checked_at - RAW_RETENTION
    return {"checked_at": _iso(checked_at), "raw_cutoff_at": _iso(cutoff),
            "complete_before": _iso(bucket_start(cutoff)), "max_buckets": max_buckets,
            "selection_start_at": None, "selection_end_exclusive": None,
            "selected_observed_min_at": None, "selected_observed_max_at": None,
            "selected_snapshots": 0, "selected_buckets": 0, "deferred_buckets": 0,
            "verified_buckets": 0, "verified_min_bucket_at": None, "verified_max_bucket_at": None,
            "archived_min_bucket_at": None, "archived_max_bucket_at": None,
            "verification_scope": "none"}


async def prune_parking_raw(*_args: Any, **_kwargs: Any) -> None:
    # 설정 하나로 원본을 지워 7/14/21일 화면을 손상시키는 진입을 막는다.
    raise RuntimeError("영구 통계 읽기 전환·수용 검증 전에는 주차 원본 삭제를 허용하지 않습니다.")
