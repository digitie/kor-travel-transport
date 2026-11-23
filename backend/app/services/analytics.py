from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, median
from typing import NamedTuple
from zoneinfo import ZoneInfo

from app.core.time_utils import align_to_interval, ensure_tz, now_utc
from app.models import Airport, ParkingLot, ParkingSnapshot

WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]


def _snapshot_preference_key(snapshot: ParkingSnapshot) -> tuple[int, float, int]:
    """Prefer live provider observations when HTTP migration overlaps them."""

    is_migration = 1 if snapshot.source.startswith("migration_") else 0
    collected_at = ensure_tz(snapshot.collected_at, "UTC").timestamp()
    return is_migration, -collected_at, -(snapshot.id or 0)


def deduplicate_snapshots(snapshots: list[ParkingSnapshot]) -> list[ParkingSnapshot]:
    """Collapse source-overlapping snapshots to one row per lot and time."""

    selected: dict[tuple[int, datetime], ParkingSnapshot] = {}
    for snapshot in snapshots:
        key = (snapshot.parking_lot_id, ensure_tz(snapshot.observed_at, "UTC"))
        current = selected.get(key)
        if current is None or _snapshot_preference_key(snapshot) < _snapshot_preference_key(current):
            selected[key] = snapshot
    return sorted(
        selected.values(),
        key=lambda snapshot: (
            ensure_tz(snapshot.observed_at, "UTC"),
            snapshot.parking_lot_id,
            snapshot.id or 0,
        ),
    )


def deduplicate_snapshot_rows(
    rows: list[tuple[ParkingSnapshot, ParkingLot, Airport]],
) -> list[tuple[ParkingSnapshot, ParkingLot, Airport]]:
    """Apply the same source preference to joined analytics rows."""

    selected: dict[tuple[int, datetime], tuple[ParkingSnapshot, ParkingLot, Airport]] = {}
    for row in rows:
        snapshot = row[0]
        key = (snapshot.parking_lot_id, ensure_tz(snapshot.observed_at, "UTC"))
        current = selected.get(key)
        if current is None or _snapshot_preference_key(snapshot) < _snapshot_preference_key(current[0]):
            selected[key] = row
    return sorted(
        selected.values(),
        key=lambda row: (
            ensure_tz(row[0].observed_at, "UTC"),
            row[0].parking_lot_id,
            row[0].id or 0,
        ),
    )


def build_global_cohort_summary(rows: list[ParkingSnapshot]) -> tuple[dict[str, int], int]:
    """기존 source 우선순위로 중복 제거한 뒤 전국의 같은 시각 합계를 표본으로 삼는다."""
    selected = deduplicate_snapshots(rows)
    cohorts: dict[datetime, int] = defaultdict(int)
    for row in selected:
        cohorts[ensure_tz(row.observed_at, "UTC")] += row.available_spaces
    if not cohorts:
        raise ValueError("관측 없는 전국 통계를 0 표본으로 발행하지 않습니다.")
    values = list(cohorts.values())
    return {"count": len(values), "sum": sum(values), "min": min(values), "max": max(values)}, len(selected)


def classify_status_level(available_spaces: int, total_spaces: int) -> str:
    if available_spaces <= 0:
        return "full"
    if available_spaces < 10:
        return "critical"
    if available_spaces < 50:
        return "warning"
    if total_spaces and available_spaces / total_spaces < 0.25:
        return "busy"
    return "stable"


def build_hourly_buckets(
    snapshots: list[ParkingSnapshot],
    tz_name: str = "Asia/Seoul",
) -> list[dict[str, int | float]]:
    tz = ZoneInfo(tz_name)
    groups: dict[int, list[int]] = defaultdict(list)
    for snapshot in snapshots:
        hour = ensure_tz(snapshot.observed_at, "UTC").astimezone(tz).hour
        groups[hour].append(snapshot.available_spaces)

    buckets = []
    for hour in sorted(groups):
        values = groups[hour]
        buckets.append(
            {
                "hour": hour,
                "average_available_spaces": round(mean(values), 2),
                "min_available_spaces": min(values),
                "max_available_spaces": max(values),
                "observations": len(values),
            }
        )
    return buckets


def build_weekday_buckets(
    snapshots: list[ParkingSnapshot],
    tz_name: str = "Asia/Seoul",
) -> list[dict[str, int | float | str]]:
    tz = ZoneInfo(tz_name)
    groups: dict[int, list[int]] = defaultdict(list)

    for snapshot in snapshots:
        weekday = ensure_tz(snapshot.observed_at, "UTC").astimezone(tz).weekday()
        groups[weekday].append(snapshot.available_spaces)

    buckets = []
    for weekday in sorted(groups):
        values = groups[weekday]
        buckets.append(
            {
                "weekday": weekday,
                "weekday_name": WEEKDAY_LABELS[weekday],
                "average_available_spaces": round(mean(values), 2),
                "min_available_spaces": min(values),
                "max_available_spaces": max(values),
                "observations": len(values),
            }
        )
    return buckets


def build_weekday_hour_patterns(
    snapshots: list[ParkingSnapshot],
    tz_name: str = "Asia/Seoul",
) -> list[dict[str, int | float | str | None | list[dict[str, int | float | None]]]]:
    tz = ZoneInfo(tz_name)
    weekday_groups: dict[int, list[int]] = defaultdict(list)
    hour_groups: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))

    for snapshot in snapshots:
        local_observed_at = ensure_tz(snapshot.observed_at, "UTC").astimezone(tz)
        weekday = local_observed_at.weekday()
        hour = local_observed_at.hour
        weekday_groups[weekday].append(snapshot.available_spaces)
        hour_groups[weekday][hour].append(snapshot.available_spaces)

    patterns = []
    for weekday in sorted(weekday_groups):
        weekday_values = weekday_groups[weekday]
        hourly_buckets = []

        for hour in range(24):
            hour_values = hour_groups[weekday].get(hour, [])
            hourly_buckets.append(
                {
                    "hour": hour,
                    "average_available_spaces": round(_mean(hour_values), 2) if hour_values else None,
                    "min_available_spaces": min(hour_values) if hour_values else None,
                    "max_available_spaces": max(hour_values) if hour_values else None,
                    "observations": len(hour_values),
                }
            )

        patterns.append(
            {
                "weekday": weekday,
                "weekday_name": WEEKDAY_LABELS[weekday],
                "average_available_spaces": round(_mean(weekday_values), 2),
                "min_available_spaces": min(weekday_values),
                "max_available_spaces": max(weekday_values),
                "observations": len(weekday_values),
                "hourly_buckets": hourly_buckets,
            }
        )

    return patterns


def build_time_series(
    snapshots: list[ParkingSnapshot],
    *,
    now: datetime | None = None,
    days: int = 7,
    interval_minutes: int = 10,
    future_hours: int = 0,
    tz_name: str = "Asia/Seoul",
    anchor_at: datetime | None = None,
) -> list[dict[str, int | datetime]]:
    if not snapshots:
        return []

    snapshots_by_lot: dict[int, list[ParkingSnapshot]] = defaultdict(list)
    for snapshot in sorted(snapshots, key=lambda item: (item.parking_lot_id, item.observed_at)):
        snapshots_by_lot[snapshot.parking_lot_id].append(snapshot)

    latest_snapshots = [lot_snapshots[-1] for lot_snapshots in snapshots_by_lot.values() if lot_snapshots]
    # For a "relative to now" query (anchor_at not given), the window is anchored on
    # whatever was actually observed last - that's the whole point of "recent N days".
    # For an explicit calendar date-range query (anchor_at given), the window must stay
    # pinned to the *requested* end of range regardless of collection gaps - otherwise a
    # trailing gap (scheduler paused for a backup restore, an upstream rate-limit block,
    # a request for "today" made before end of day) silently shifts the whole window
    # backward to whenever data actually stops, while the response's own start_date/
    # end_date fields keep claiming the originally-requested range.
    latest_observed_at = (
        ensure_tz(anchor_at, "UTC")
        if anchor_at is not None
        else max(
            (ensure_tz(snapshot.observed_at, "UTC") for snapshot in latest_snapshots),
            default=ensure_tz(now or now_utc(), "UTC"),
        )
    )

    history_bucket_count = max(1, int((days * 24 * 60) / interval_minutes))
    future_bucket_count = max(0, int((future_hours * 60) / interval_minutes))
    bucket_count = history_bucket_count + future_bucket_count
    aligned_current = align_to_interval(latest_observed_at, interval_minutes, tz_name)
    start = aligned_current - timedelta(minutes=interval_minutes * (history_bucket_count - 1))
    buckets = [start + timedelta(minutes=interval_minutes * index) for index in range(bucket_count)]

    items = [
        {
            "bucket_at": bucket,
            "available_spaces": 0,
            "occupied_spaces": 0,
            "total_spaces": 0,
            "lot_observations": 0,
        }
        for bucket in buckets
    ]

    # bucket은 증가 순서다. 최신 관측 뒤의 bucket(미래 구간)은 끝쪽 연속 구간이라 앞부분만 채운다.
    bucket_times = [ensure_tz(bucket, "UTC") for bucket in buckets]
    filled_bucket_count = bisect_right(bucket_times, latest_observed_at)
    max_carry = timedelta(minutes=interval_minutes)
    available_sums = [0] * bucket_count
    occupied_sums = [0] * bucket_count
    total_sums = [0] * bucket_count
    observation_counts = [0] * bucket_count

    for lot_snapshots in snapshots_by_lot.values():
        observed_times = [ensure_tz(snapshot.observed_at, "UTC") for snapshot in lot_snapshots]
        snapshot_count = len(observed_times)
        if not snapshot_count:
            continue
        # 각 bucket의 값은 그 시각 이전(포함) 마지막 관측이다. 첫 관측 전 bucket에는 값이 없다.
        snapshot_index = 0
        for bucket_index in range(bisect_left(bucket_times, observed_times[0], 0, filled_bucket_count),
                                  filled_bucket_count):
            bucket_at = bucket_times[bucket_index]
            while snapshot_index < snapshot_count and observed_times[snapshot_index] <= bucket_at:
                snapshot_index += 1
            # 관측 공백 뒤의 과거 값을 현재 버킷에 계속 이월하지 않는다.
            if bucket_at - observed_times[snapshot_index - 1] > max_carry:
                continue
            current = lot_snapshots[snapshot_index - 1]
            available_sums[bucket_index] += current.available_spaces
            occupied_sums[bucket_index] += current.occupied_spaces
            total_sums[bucket_index] += current.total_spaces
            observation_counts[bucket_index] += 1

    for item, available, occupied, total, observations in zip(
        items, available_sums, occupied_sums, total_sums, observation_counts,
    ):
        item["available_spaces"] = available
        item["occupied_spaces"] = occupied
        item["total_spaces"] = total
        item["lot_observations"] = observations

    # Stamping the exact latest per-lot reading into the final bucket only makes sense
    # when that bucket genuinely represents "now" (the relative-days path) - for an
    # explicit date-range anchor, the final bucket represents the *requested* end of
    # range, which may be well after the last real observation (a trailing gap). Forcing
    # stale data into that slot would misrepresent it as current-as-of-end-of-range.
    if anchor_at is None and latest_snapshots:
        current_index = history_bucket_count - 1
        fresh_snapshots = [snapshot for snapshot in latest_snapshots
                           if latest_observed_at - ensure_tz(snapshot.observed_at, "UTC")
                           <= timedelta(minutes=interval_minutes)]
        latest_item = {
            "bucket_at": latest_observed_at,
            "available_spaces": sum(snapshot.available_spaces for snapshot in fresh_snapshots),
            "occupied_spaces": sum(snapshot.occupied_spaces for snapshot in fresh_snapshots),
            "total_spaces": sum(snapshot.total_spaces for snapshot in fresh_snapshots),
            "lot_observations": len(fresh_snapshots),
        }
        if items[current_index]["bucket_at"] == latest_observed_at:
            items[current_index] = latest_item
        else:
            # 마지막 정규 bucket은 수집 공백일 수 있다. 그 자리를 덮으면 공백이
            # 사라져 차트가 이전 관측과 최신 관측을 연속선으로 잘못 연결한다.
            items.insert(history_bucket_count, latest_item)

    return items


def build_holiday_patterns(
    snapshots: list[ParkingSnapshot],
    holidays: list[tuple[date, str]],
    tz_name: str = "Asia/Seoul",
) -> list[dict[str, int | float | str | None | list[dict[str, int | float | None]]]]:
    return build_special_day_patterns(
        snapshots,
        [(local_date, name, "holiday") for local_date, name in holidays],
        tz_name=tz_name,
    )


class SpecialDayHourAggregate(NamedTuple):
    """한 특수일·현지 시(hour)의 '같은 관측 시각 합계' 표본 요약.

    `count`는 서로 다른 관측 시각 수, `total`·`minimum`·`maximum`은 그 시각별 합계의
    합·최솟값·최댓값이다. PostgreSQL 집계와 Python 계산이 같은 값을 만든다.
    """

    count: int
    total: int
    minimum: int
    maximum: int


def _integer_mean(total: int, count: int) -> int | float:
    """`statistics.mean`과 같은 값·타입: 정수 표본의 평균이 정수면 int, 아니면 올바르게 반올림한 float.

    `statistics.mean`은 정수 합을 분수로 나눈 뒤 float로 바꾼다. Python의 정수 나눗셈(`/`)도 같은
    유리수를 올바르게 반올림하므로 값이 같고, 분수 연산 비용만 없다.
    """
    return total // count if total % count == 0 else total / count


def _mean(values: list[int]) -> int | float:
    if all(type(value) is int for value in values):
        return _integer_mean(sum(values), len(values))
    return mean(values)


def special_day_hour_aggregates(
    snapshots: list[ParkingSnapshot],
    special_days: list[tuple[date, str, str]],
    tz_name: str = "Asia/Seoul",
) -> dict[tuple[date, int], SpecialDayHourAggregate]:
    tz = ZoneInfo(tz_name)
    special_day_names = {local_date for local_date, _name, _day_type in special_days}
    hourly_totals: dict[tuple[date, int], dict[datetime, int]] = defaultdict(lambda: defaultdict(int))

    for snapshot in snapshots:
        observed_at_utc = ensure_tz(snapshot.observed_at, "UTC")
        local_observed_at = observed_at_utc.astimezone(tz)
        local_date = local_observed_at.date()
        if local_date not in special_day_names:
            continue
        hourly_totals[(local_date, local_observed_at.hour)][observed_at_utc] += snapshot.available_spaces

    return {
        key: SpecialDayHourAggregate(len(totals), sum(totals.values()), min(totals.values()), max(totals.values()))
        for key, totals in hourly_totals.items()
    }


def build_special_day_patterns_from_aggregates(
    aggregates: dict[tuple[date, int], SpecialDayHourAggregate],
    special_days: list[tuple[date, str, str]],
) -> list[dict[str, int | float | str | None | list[dict[str, int | float | None]]]]:
    special_day_types = {local_date: day_type for local_date, _name, day_type in special_days}
    patterns = []
    for local_date, name, day_type in sorted(special_days, key=lambda item: item[0], reverse=True):
        hourly_buckets = []
        date_count = date_total = 0
        date_min: int | None = None
        date_max: int | None = None

        for hour in range(24):
            aggregate = aggregates.get((local_date, hour))
            if aggregate is not None and aggregate.count:
                date_count += aggregate.count
                date_total += aggregate.total
                date_min = aggregate.minimum if date_min is None else min(date_min, aggregate.minimum)
                date_max = aggregate.maximum if date_max is None else max(date_max, aggregate.maximum)
            hourly_buckets.append(
                {
                    "hour": hour,
                    "average_available_spaces": round(_integer_mean(aggregate.total, aggregate.count), 2)
                    if aggregate and aggregate.count else None,
                    "min_available_spaces": aggregate.minimum if aggregate and aggregate.count else None,
                    "max_available_spaces": aggregate.maximum if aggregate and aggregate.count else None,
                    "observations": aggregate.count if aggregate else 0,
                }
            )

        patterns.append(
            {
                "local_date": local_date.isoformat(),
                "name": name,
                "day_type": special_day_types.get(local_date, day_type),
                "weekday": local_date.weekday(),
                "weekday_name": WEEKDAY_LABELS[local_date.weekday()],
                "average_available_spaces": round(_integer_mean(date_total, date_count), 2) if date_count else None,
                "min_available_spaces": date_min,
                "max_available_spaces": date_max,
                "observations": date_count,
                "hourly_buckets": hourly_buckets,
            }
        )

    return patterns


def build_special_day_patterns(
    snapshots: list[ParkingSnapshot],
    special_days: list[tuple[date, str, str]],
    tz_name: str = "Asia/Seoul",
) -> list[dict[str, int | float | str | None | list[dict[str, int | float | None]]]]:
    return build_special_day_patterns_from_aggregates(
        special_day_hour_aggregates(snapshots, special_days, tz_name=tz_name),
        special_days,
    )


def detect_threshold_events(
    snapshot_rows: list[tuple[ParkingSnapshot, ParkingLot, Airport]],
    thresholds: tuple[int, ...] = (10, 50),
    limit: int = 30,
) -> list[dict[str, int | str | datetime]]:
    ordered = sorted(snapshot_rows, key=lambda row: (row[1].id, row[0].observed_at))
    previous_by_lot: dict[int, ParkingSnapshot] = {}
    events: list[dict[str, int | str | datetime]] = []

    for snapshot, lot, airport in ordered:
        previous = previous_by_lot.get(lot.id)
        if previous is None:
            previous_by_lot[lot.id] = snapshot
            continue

        for threshold in thresholds:
            if previous.available_spaces >= threshold > snapshot.available_spaces:
                events.append(
                    {
                        "parking_lot_id": lot.id,
                        "parking_lot_name": lot.name,
                        "airport_code": airport.code,
                        "airport_name": airport.name_ko,
                        "threshold": threshold,
                        "direction": "down",
                        "crossed_at": snapshot.observed_at,
                        "previous_available_spaces": previous.available_spaces,
                        "current_available_spaces": snapshot.available_spaces,
                    }
                )
            if previous.available_spaces < threshold <= snapshot.available_spaces:
                events.append(
                    {
                        "parking_lot_id": lot.id,
                        "parking_lot_name": lot.name,
                        "airport_code": airport.code,
                        "airport_name": airport.name_ko,
                        "threshold": threshold,
                        "direction": "up",
                        "crossed_at": snapshot.observed_at,
                        "previous_available_spaces": previous.available_spaces,
                        "current_available_spaces": snapshot.available_spaces,
                    }
                )

        previous_by_lot[lot.id] = snapshot

    return sorted(events, key=lambda item: item["crossed_at"], reverse=True)[:limit]


def detect_threshold_events_from_time_series(
    points: list[dict[str, int | datetime]],
    thresholds: tuple[int, ...] = (10, 50),
) -> list[dict[str, int | str | datetime]]:
    ordered = sorted(points, key=lambda item: ensure_tz(item["bucket_at"], "UTC"))
    if len(ordered) < 2:
        return []

    events: list[dict[str, int | str | datetime]] = []
    previous = ordered[0]

    for point in ordered[1:]:
        previous_available_spaces = int(previous["available_spaces"])
        current_available_spaces = int(point["available_spaces"])
        crossed_at = ensure_tz(point["bucket_at"], "UTC")

        for threshold in thresholds:
            if previous_available_spaces >= threshold > current_available_spaces:
                events.append(
                    {
                        "threshold": threshold,
                        "direction": "down",
                        "crossed_at": crossed_at,
                        "previous_available_spaces": previous_available_spaces,
                        "current_available_spaces": current_available_spaces,
                    }
                )
            if previous_available_spaces < threshold <= current_available_spaces:
                events.append(
                    {
                        "threshold": threshold,
                        "direction": "up",
                        "crossed_at": crossed_at,
                        "previous_available_spaces": previous_available_spaces,
                        "current_available_spaces": current_available_spaces,
                    }
                )

        previous = point

    return events


def build_threshold_insights(
    points: list[dict[str, int | datetime]],
    thresholds: tuple[int, ...] = (10, 50),
    tz_name: str = "Asia/Seoul",
    history_limit: int = 30,
) -> dict[str, list[dict[str, int | str | datetime | None]]]:
    tz = ZoneInfo(tz_name)
    down_events = [
        event
        for event in detect_threshold_events_from_time_series(points, thresholds=thresholds)
        if event["direction"] == "down"
    ]

    first_crossings_by_date: dict[tuple[int, str], dict[str, int | str | datetime]] = {}
    for event in sorted(down_events, key=lambda item: ensure_tz(item["crossed_at"], "UTC")):
        crossed_at = ensure_tz(event["crossed_at"], "UTC").astimezone(tz)
        local_date = crossed_at.date().isoformat()
        key = (int(event["threshold"]), local_date)
        first_crossings_by_date.setdefault(key, event)

    weekday_groups: dict[tuple[int, int], list[int]] = defaultdict(list)
    history_items: list[dict[str, int | str | datetime]] = []

    for (threshold, local_date), event in first_crossings_by_date.items():
        local_crossed_at = ensure_tz(event["crossed_at"], "UTC").astimezone(tz)
        weekday = local_crossed_at.weekday()
        minutes_of_day = local_crossed_at.hour * 60 + local_crossed_at.minute
        weekday_groups[(threshold, weekday)].append(minutes_of_day)
        history_items.append(
            {
                "threshold": threshold,
                "local_date": local_date,
                "weekday": weekday,
                "weekday_name": WEEKDAY_LABELS[weekday],
                "crossed_at": ensure_tz(event["crossed_at"], "UTC"),
                "minutes_of_day": minutes_of_day,
                "available_spaces": int(event["current_available_spaces"]),
            }
        )

    weekday_items: list[dict[str, int | str | None]] = []
    for threshold in thresholds:
        for weekday, weekday_name in enumerate(WEEKDAY_LABELS):
            values = weekday_groups.get((threshold, weekday), [])
            weekday_items.append(
                {
                    "threshold": threshold,
                    "weekday": weekday,
                    "weekday_name": weekday_name,
                    "typical_minutes_of_day": round(median(values)) if values else None,
                    "sample_count": len(values),
                }
            )

    history_items.sort(key=lambda item: ensure_tz(item["crossed_at"], "UTC"), reverse=True)
    return {
        "weekday_items": weekday_items,
        "history_items": history_items[:history_limit],
    }
