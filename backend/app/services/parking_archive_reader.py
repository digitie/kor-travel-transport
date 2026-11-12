"""영구 충분통계와 원본을 배타적으로 병합하는 내부 pattern reader.

기존 API는 아직 이 함수를 호출하지 않는다. 원본 없는 10분 내부 경계를
임의 관측으로 복원하지 않으며, 입력의 기간 전체 coverage도 추정하지 않는다.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from app.core.time_utils import ensure_tz
from app.models import ParkingSnapshot, ParkingStatisticsBucket
from app.services.analytics import WEEKDAY_LABELS, deduplicate_snapshots
from app.services.parking_statistics_archive import (
    BUCKET_INTERVAL, FORMAT_VERSION, ParkingArchiveConflict, _digest, bucket_start, raw_digest,
)


def _utc(value: datetime) -> datetime:
    return ensure_tz(value, "UTC").astimezone(UTC)


class ParkingArchivePrecisionUnavailable(ValueError):
    """요약만으로 요청 경계의 정확한 값을 계산할 수 없는 경우다."""

    def __init__(self, reason: str, *, start: datetime, end: datetime, at: datetime):
        super().__init__("10분 영구 통계만으로 요청한 구간을 정확히 나눌 수 없습니다.")
        self.metadata = {"reason": reason, "requested_start": start.isoformat(),
                         "requested_end": end.isoformat(), "bucket_at": at.isoformat(),
                         "archive_resolution_minutes": 10, "coverage": "unknown"}


@dataclass(frozen=True)
class ParkingPatternStatistics:
    by_hour: list[dict[str, Any]]
    by_weekday: list[dict[str, Any]]
    by_weekday_hour: list[dict[str, Any]]
    metadata: dict[str, Any]


@dataclass
class _Summary:
    count: int = 0
    total: int = 0
    minimum: int | None = None
    maximum: int | None = None

    def merge(self, count: int, total: int, minimum: int, maximum: int) -> None:
        self.count += count
        self.total += total
        self.minimum = minimum if self.minimum is None else min(self.minimum, minimum)
        self.maximum = maximum if self.maximum is None else max(self.maximum, maximum)

    def fields(self) -> dict[str, int | float | None]:
        return {"average_available_spaces": round(self.total / self.count, 2) if self.count else None,
                "min_available_spaces": self.minimum, "max_available_spaces": self.maximum,
                "observations": self.count}


def _validate_record(record: ParkingStatisticsBucket) -> list[dict[str, Any]]:
    try:
        at = _utc(record.bucket_at)
        lots = record.statistics_json["lots"]
        valid = (record.format_version == FORMAT_VERSION and at == bucket_start(at)
                 and _utc(record.bucket_end) == at + BUCKET_INTERVAL
                 and 0 < record.selected_count <= record.raw_count
                 and record.max_snapshot_id > 0
                 and record.statistics_sha256 == _digest(record.statistics_json)
                 and record.selected_count == sum(lot["available"]["count"] for lot in lots)
                 and len({lot["parking_lot_id"] for lot in lots}) == len(lots))
        for lot in lots:
            value = lot["available"]
            first = _utc(datetime.fromisoformat(lot["first"]["observed_at"]))
            last = _utc(datetime.fromisoformat(lot["last"]["observed_at"]))
            valid = valid and (all(type(value[name]) is int for name in ("count", "sum", "min", "max"))
                               and value["count"] > 0 and value["min"] <= value["max"]
                               and value["count"] * value["min"] <= value["sum"] <= value["count"] * value["max"]
                               and at <= first <= last < _utc(record.bucket_end))
        if not valid:
            raise ParkingArchiveConflict("주차 영구 통계의 버전·지문·표본·범위가 일치하지 않습니다.")
        return lots
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise ParkingArchiveConflict("주차 영구 통계의 형식을 읽을 수 없습니다.") from error


def read_pattern_statistics(
    records: Sequence[ParkingStatisticsBucket], raw_rows: Sequence[ParkingSnapshot], *,
    start: datetime, end: datetime, airport_id: int | None = None,
    parking_lot_id: int | None = None, tz_name: str = "Asia/Seoul",
) -> ParkingPatternStatistics:
    """반열린 기간의 관측 가중 pattern을 계산한다. DB/API·캐시·삭제를 변경하지 않는다.

    경계 복구에는 해당 공항/버킷의 필터 전 원본 전체가 필요하다. 전체 count/hash를
    검산하지 못하면 archive를 정본으로 사용하며, 분리 불가능한 경계는 명시적 예외다.
    전달되지 않은 과거 버킷이 무관측인지 유실인지 이 함수만으로 판단할 수 없다.
    """
    start, end = _utc(start), _utc(end)
    if start >= end:
        raise ValueError("통계 시작은 종료보다 앞서야 합니다.")
    tz = ZoneInfo(tz_name)
    rows_by_bucket: dict[tuple[int, datetime], list[ParkingSnapshot]] = defaultdict(list)
    for row in raw_rows:
        if airport_id is None or row.airport_id == airport_id:
            rows_by_bucket[row.airport_id, bucket_start(row.observed_at)].append(row)
    hours: dict[int, _Summary] = defaultdict(_Summary)
    weekdays: dict[int, _Summary] = defaultdict(_Summary)
    weekday_hours: dict[tuple[int, int], _Summary] = defaultdict(_Summary)
    canonical = set()
    archive_count = raw_count = 0

    def add(at: datetime, value: dict[str, int]) -> None:
        local = at.astimezone(tz)
        for summary in (hours[local.hour], weekdays[local.weekday()], weekday_hours[local.weekday(), local.hour]):
            summary.merge(value["count"], value["sum"], value["min"], value["max"])

    def add_raw(rows: Sequence[ParkingSnapshot]) -> int:
        selected = deduplicate_snapshots([row for row in rows if start <= _utc(row.observed_at) < end
                                          and (parking_lot_id is None or row.parking_lot_id == parking_lot_id)])
        for row in selected:
            value = row.available_spaces
            add(_utc(row.observed_at), {"count": 1, "sum": value, "min": value, "max": value})
        return len(selected)

    for record in records:
        at = _utc(record.bucket_at)
        if ((airport_id is not None and record.airport_id != airport_id)
                or at >= end or _utc(record.bucket_end) <= start):
            continue
        key = record.airport_id, at
        if key in canonical:
            raise ParkingArchiveConflict("같은 공항/버킷의 영구 통계를 두 번 병합할 수 없습니다.")
        canonical.add(key)
        lots = _validate_record(record)
        available_raw = rows_by_bucket.get(key, [])
        if any(row.id > record.max_snapshot_id for row in available_raw):
            raise ParkingArchiveConflict("봉인한 구간에 새로 적재한 원본이 있어 추가 검산이 필요합니다.")
        complete_raw = len(available_raw) == record.raw_count
        if complete_raw and raw_digest(available_raw) != record.raw_sha256:
            raise ParkingArchiveConflict("영구 통계의 전체 원본 지문이 달라졌습니다.")
        selected_lots = [lot for lot in lots if parking_lot_id is None or lot["parking_lot_id"] == parking_lot_id]
        included = []
        reason = None
        for lot in selected_lots:
            first = _utc(datetime.fromisoformat(lot["first"]["observed_at"]))
            last = _utc(datetime.fromisoformat(lot["last"]["observed_at"]))
            if last < start or first >= end:
                continue
            if first < start or last >= end:
                reason = "query_boundary_inside_bucket"
                break
            if (first.astimezone(tz).weekday(), first.astimezone(tz).hour) != (
                    last.astimezone(tz).weekday(), last.astimezone(tz).hour):
                reason = "local_hour_boundary_inside_bucket"
                break
            included.append((first, lot["available"]))
        if reason is not None:
            if not complete_raw:
                raise ParkingArchivePrecisionUnavailable(reason, start=start, end=end, at=at)
            raw_count += add_raw(available_raw)
        else:
            for first, value in included:
                add(first, value)
                archive_count += value["count"]

    for key, rows in rows_by_bucket.items():
        if key not in canonical:
            raw_count += add_raw(rows)
    by_hour = [{"hour": hour, **summary.fields()} for hour, summary in sorted(hours.items())]
    by_weekday = [{"weekday": day, "weekday_name": WEEKDAY_LABELS[day], **summary.fields()}
                  for day, summary in sorted(weekdays.items())]
    by_weekday_hour = [{**row, "hourly_buckets": [
        {"hour": hour, **weekday_hours.get((row["weekday"], hour), _Summary()).fields()}
        for hour in range(24)]} for row in by_weekday]
    return ParkingPatternStatistics(by_hour, by_weekday, by_weekday_hour, {
        "requested_start": start.isoformat(), "requested_end": end.isoformat(),
        "value_precision": "exact_for_included_observations", "coverage": "unknown",
        "archive_resolution_minutes": 10, "archive_observations": archive_count,
        "raw_observations": raw_count, "raw_fingerprint_validation": "complete_buckets_only",
    })
