"""성능 개선 전 분석 계산(참조 구현)과 현재 구현의 결과가 값·타입까지 같은지 고정한다.

참조 구현은 2026-11-23 main(d4bb920)의 `app/services/analytics.py`에서 그대로 옮겼다.
`statistics.mean`은 정수 평균이 나누어떨어지면 int를 돌려주므로, JSON 표현(3 vs 3.0)까지 비교한다.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.core.time_utils import align_to_interval, ensure_tz
from app.services.analytics import (
    WEEKDAY_LABELS,
    build_special_day_patterns,
    build_time_series,
    build_weekday_hour_patterns,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 23, 9, 31, 7, tzinfo=UTC)


def _reference_weekday_hour_patterns(snapshots, tz_name="Asia/Seoul"):
    tz = ZoneInfo(tz_name)
    weekday_groups = defaultdict(list)
    hour_groups = defaultdict(lambda: defaultdict(list))
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
            hourly_buckets.append({
                "hour": hour,
                "average_available_spaces": round(mean(hour_values), 2) if hour_values else None,
                "min_available_spaces": min(hour_values) if hour_values else None,
                "max_available_spaces": max(hour_values) if hour_values else None,
                "observations": len(hour_values),
            })
        patterns.append({
            "weekday": weekday,
            "weekday_name": WEEKDAY_LABELS[weekday],
            "average_available_spaces": round(mean(weekday_values), 2),
            "min_available_spaces": min(weekday_values),
            "max_available_spaces": max(weekday_values),
            "observations": len(weekday_values),
            "hourly_buckets": hourly_buckets,
        })
    return patterns


def _reference_time_series(snapshots, *, now=None, days=7, interval_minutes=10, future_hours=0,
                           tz_name="Asia/Seoul", anchor_at=None):
    if not snapshots:
        return []
    snapshots_by_lot = defaultdict(list)
    for snapshot in sorted(snapshots, key=lambda item: (item.parking_lot_id, item.observed_at)):
        snapshots_by_lot[snapshot.parking_lot_id].append(snapshot)
    latest_snapshots = [lot_snapshots[-1] for lot_snapshots in snapshots_by_lot.values() if lot_snapshots]
    latest_observed_at = (
        ensure_tz(anchor_at, "UTC")
        if anchor_at is not None
        else max((ensure_tz(snapshot.observed_at, "UTC") for snapshot in latest_snapshots),
                 default=ensure_tz(now or NOW, "UTC"))
    )
    history_bucket_count = max(1, int((days * 24 * 60) / interval_minutes))
    future_bucket_count = max(0, int((future_hours * 60) / interval_minutes))
    bucket_count = history_bucket_count + future_bucket_count
    aligned_current = align_to_interval(latest_observed_at, interval_minutes, tz_name)
    start = aligned_current - timedelta(minutes=interval_minutes * (history_bucket_count - 1))
    buckets = [start + timedelta(minutes=interval_minutes * index) for index in range(bucket_count)]
    items = [{"bucket_at": bucket, "available_spaces": 0, "occupied_spaces": 0, "total_spaces": 0,
              "lot_observations": 0} for bucket in buckets]
    for lot_snapshots in snapshots_by_lot.values():
        snapshot_index = 0
        current = None
        for item in items:
            bucket_at = item["bucket_at"]
            if ensure_tz(bucket_at, "UTC") > latest_observed_at:
                continue
            while snapshot_index < len(lot_snapshots) and ensure_tz(
                    lot_snapshots[snapshot_index].observed_at, "UTC") <= bucket_at:
                current = lot_snapshots[snapshot_index]
                snapshot_index += 1
            if current is None:
                continue
            if bucket_at - ensure_tz(current.observed_at, "UTC") > timedelta(minutes=interval_minutes):
                continue
            item["available_spaces"] += current.available_spaces
            item["occupied_spaces"] += current.occupied_spaces
            item["total_spaces"] += current.total_spaces
            item["lot_observations"] += 1
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
            items.insert(history_bucket_count, latest_item)
    return items


def _reference_special_day_patterns(snapshots, special_days, tz_name="Asia/Seoul"):
    tz = ZoneInfo(tz_name)
    special_day_names = {local_date: name for local_date, name, _day_type in special_days}
    special_day_types = {local_date: day_type for local_date, _name, day_type in special_days}
    hourly_totals = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
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
        date_values = []
        for hour in range(24):
            hour_values = list(hourly_totals.get(local_date, {}).get(hour, {}).values())
            date_values.extend(hour_values)
            hourly_buckets.append({
                "hour": hour,
                "average_available_spaces": round(mean(hour_values), 2) if hour_values else None,
                "min_available_spaces": min(hour_values) if hour_values else None,
                "max_available_spaces": max(hour_values) if hour_values else None,
                "observations": len(hour_values),
            })
        patterns.append({
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
        })
    return patterns


def _exact(value):
    """값과 int/float 구분까지 비교하는 표현. datetime은 UTC ISO 문자열로 바꾼다."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      default=lambda item: ensure_tz(item, "UTC").astimezone(UTC).isoformat())


def _snapshots(seed: int, *, naive: bool = False, lots: int = 5, days: int = 9):
    rng = random.Random(seed)
    rows = []
    for lot in range(1, lots + 1):
        cadence = rng.choice([5, 7, 8, 10, 13])
        minute = days * 1440 + rng.randint(0, 30)
        last_offset = rng.choice([0, 0, 3, 9, 11, 47])  # lot별 최신 관측이 다르다
        while minute >= last_offset:
            if rng.random() < 0.03:
                minute -= rng.randint(15, 400)  # 수집 공백
                continue
            observed = NOW - timedelta(minutes=minute)
            if rng.random() < 0.2:
                observed = observed.replace(second=0, microsecond=0)  # bucket 경계에 정확히 걸치는 관측
            available = rng.choice([0, 2, 4, 9, 10, 11, 49, 50, 51, rng.randint(0, 900)])
            total = rng.choice([100, 500, 900])
            rows.append(SimpleNamespace(
                id=len(rows) + 1, airport_id=1, parking_lot_id=lot,
                observed_at=observed.replace(tzinfo=None) if naive else observed,
                occupied_spaces=max(0, total - available), total_spaces=total, available_spaces=available,
            ))
            minute -= cadence
    rows.sort(key=lambda row: (ensure_tz(row.observed_at, "UTC"), row.parking_lot_id, row.id))
    return rows


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("naive", [False, True])
def test_weekday_hour_patterns_match_reference(seed, naive):
    snapshots = _snapshots(seed, naive=naive)
    assert _exact(build_weekday_hour_patterns(snapshots)) == _exact(_reference_weekday_hour_patterns(snapshots))


def test_weekday_hour_exact_integer_means_keep_statistics_mean_type():
    rows = [SimpleNamespace(observed_at=NOW, available_spaces=value) for value in (2, 4)]
    rows += [SimpleNamespace(observed_at=NOW + timedelta(hours=1), available_spaces=value) for value in (1, 2)]
    assert _exact(build_weekday_hour_patterns(rows)) == _exact(_reference_weekday_hour_patterns(rows))
    hourly = build_weekday_hour_patterns(rows)[0]["hourly_buckets"]
    assert [type(bucket["average_available_spaces"]) for bucket in hourly if bucket["observations"]] == [int, float]


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("naive", [False, True])
@pytest.mark.parametrize("days,interval_minutes,future_hours", [(7, 10, 0), (3, 10, 6), (2, 30, 0), (1, 60, 12)])
def test_time_series_matches_reference(seed, naive, days, interval_minutes, future_hours):
    snapshots = _snapshots(seed, naive=naive)
    window = [row for row in snapshots
              if ensure_tz(row.observed_at, "UTC") >= NOW - timedelta(days=days, minutes=interval_minutes)]
    kwargs = dict(days=days, interval_minutes=interval_minutes, future_hours=future_hours)
    assert _exact(build_time_series(window, **kwargs)) == _exact(_reference_time_series(window, **kwargs))


@pytest.mark.parametrize("seed", range(6))
def test_time_series_with_explicit_anchor_matches_reference(seed):
    snapshots = _snapshots(seed, days=4)
    anchor = datetime(2026, 11, 24, 0, 0, tzinfo=ZoneInfo("Asia/Seoul")) - timedelta(minutes=10)
    kwargs = dict(days=3, interval_minutes=10, anchor_at=anchor)
    assert _exact(build_time_series(snapshots, **kwargs)) == _exact(_reference_time_series(snapshots, **kwargs))


@pytest.mark.parametrize("seed", range(12))
def test_special_day_patterns_match_reference(seed):
    snapshots = _snapshots(seed, days=12)
    rng = random.Random(seed)
    local_today = NOW.astimezone(ZoneInfo("Asia/Seoul")).date()
    candidates = [local_today - timedelta(days=offset) for offset in range(0, 13)]
    special_days = [(day, f"특수일 {day.day}", rng.choice(["holiday", "saturday", "sunday"]))
                    for day in rng.sample(candidates, 6)]
    special_days.append((date(2020, 1, 1), "자료 없는 날", "holiday"))
    assert _exact(build_special_day_patterns(snapshots, special_days)) == _exact(
        _reference_special_day_patterns(snapshots, special_days))
