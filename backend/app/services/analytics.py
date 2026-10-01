from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, median
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
                    "average_available_spaces": round(mean(hour_values), 2) if hour_values else None,
                    "min_available_spaces": min(hour_values) if hour_values else None,
                    "max_available_spaces": max(hour_values) if hour_values else None,
                    "observations": len(hour_values),
                }
            )

        patterns.append(
            {
                "weekday": weekday,
                "weekday_name": WEEKDAY_LABELS[weekday],
                "average_available_spaces": round(mean(weekday_values), 2),
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

    for lot_snapshots in snapshots_by_lot.values():
        snapshot_index = 0
        current: ParkingSnapshot | None = None
        for item in items:
            bucket_at = item["bucket_at"]
            if ensure_tz(bucket_at, "UTC") > latest_observed_at:
                continue
            while snapshot_index < len(lot_snapshots) and ensure_tz(lot_snapshots[snapshot_index].observed_at, "UTC") <= bucket_at:
                current = lot_snapshots[snapshot_index]
                snapshot_index += 1

            if current is None:
                continue
            # 관측 공백 뒤의 과거 값을 현재 버킷에 계속 이월하지 않는다.
            if bucket_at - ensure_tz(current.observed_at, "UTC") > timedelta(minutes=interval_minutes):
                continue

            item["available_spaces"] += current.available_spaces
            item["occupied_spaces"] += current.occupied_spaces
            item["total_spaces"] += current.total_spaces
            item["lot_observations"] += 1

    # Stamping the exact latest per-lot reading into the final bucket only makes sense
    # when that bucket genuinely represents "now" (the relative-days path) - for an
    # explicit date-range anchor, the final bucket represents the *requested* end of
    # range, which may be well after the last real observation (a trailing gap). Forcing
    # stale data into that slot would misrepresent it as current-as-of-end-of-range.
    if anchor_at is None and latest_snapshots:
        current_index = history_bucket_count - 1
        items[current_index] = {
            "bucket_at": latest_observed_at,
            "available_spaces": sum(snapshot.available_spaces for snapshot in latest_snapshots),
            "occupied_spaces": sum(snapshot.occupied_spaces for snapshot in latest_snapshots),
            "total_spaces": sum(snapshot.total_spaces for snapshot in latest_snapshots),
            "lot_observations": len(latest_snapshots),
        }

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


def build_special_day_patterns(
    snapshots: list[ParkingSnapshot],
    special_days: list[tuple[date, str, str]],
    tz_name: str = "Asia/Seoul",
) -> list[dict[str, int | float | str | None | list[dict[str, int | float | None]]]]:
    tz = ZoneInfo(tz_name)
    special_day_names = {local_date: name for local_date, name, _day_type in special_days}
    special_day_types = {local_date: day_type for local_date, _name, day_type in special_days}
    hourly_totals: dict[date, dict[int, dict[datetime, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

    for snapshot in snapshots:
        observed_at_utc = ensure_tz(snapshot.observed_at, "UTC")
        local_observed_at = observed_at_utc.astimezone(tz)
        local_date = local_observed_at.date()
        if local_date not in special_day_names:
            continue
        hourly_totals[local_date][local_observed_at.hour][observed_at_utc] += snapshot.available_spaces

    patterns = []
    for local_date, name, day_type in sorted(special_days, key=lambda item: item[0], reverse=True):
        hourly_buckets = []
        date_values: list[int] = []

        for hour in range(24):
            hour_values = list(hourly_totals.get(local_date, {}).get(hour, {}).values())
            date_values.extend(hour_values)
            hourly_buckets.append(
                {
                    "hour": hour,
                    "average_available_spaces": round(mean(hour_values), 2) if hour_values else None,
                    "min_available_spaces": min(hour_values) if hour_values else None,
                    "max_available_spaces": max(hour_values) if hour_values else None,
                    "observations": len(hour_values),
                }
            )

        patterns.append(
            {
                "local_date": local_date.isoformat(),
                "name": name,
                "day_type": special_day_types.get(local_date, day_type),
                "weekday": local_date.weekday(),
                "weekday_name": WEEKDAY_LABELS[local_date.weekday()],
                "average_available_spaces": round(mean(date_values), 2) if date_values else None,
                "min_available_spaces": min(date_values) if date_values else None,
                "max_available_spaces": max(date_values) if date_values else None,
                "observations": len(date_values),
                "hourly_buckets": hourly_buckets,
            }
        )

    return patterns


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
