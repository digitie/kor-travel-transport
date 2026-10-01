from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import Airport, ParkingLot, ParkingSnapshot
from app.services.analytics import (
    build_threshold_insights,
    build_hourly_buckets,
    build_time_series,
    build_weekday_buckets,
    build_weekday_hour_patterns,
    classify_status_level,
    deduplicate_snapshots,
    detect_threshold_events,
)


def test_classify_status_level() -> None:
    assert classify_status_level(0, 100) == "full"
    assert classify_status_level(8, 100) == "critical"
    assert classify_status_level(30, 100) == "warning"
    assert classify_status_level(90, 100) == "stable"


def test_detect_threshold_events() -> None:
    airport = Airport(
        id=1,
        code="GMP",
        name_ko="김포국제공항",
        name_en=None,
        source="kac",
        created_at=datetime.now(tz=ZoneInfo("UTC")),
        updated_at=datetime.now(tz=ZoneInfo("UTC")),
    )
    lot = ParkingLot(
        id=1,
        airport_id=1,
        source_lot_id="gmp-lot",
        name="국내선 제1주차장",
        terminal=None,
        category=None,
        total_spaces_hint=100,
        is_active=True,
        created_at=datetime.now(tz=ZoneInfo("UTC")),
        updated_at=datetime.now(tz=ZoneInfo("UTC")),
    )
    start = datetime.now(tz=ZoneInfo("UTC")) - timedelta(hours=1)
    snapshots = [
        ParkingSnapshot(id=1, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=start, collected_at=start, occupied_spaces=40, total_spaces=100, available_spaces=60, congestion_label=None, congestion_ratio=None, raw_item_json=None),
        ParkingSnapshot(id=2, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=start + timedelta(minutes=10), collected_at=start, occupied_spaces=52, total_spaces=100, available_spaces=48, congestion_label=None, congestion_ratio=None, raw_item_json=None),
        ParkingSnapshot(id=3, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=start + timedelta(minutes=20), collected_at=start, occupied_spaces=90, total_spaces=100, available_spaces=10, congestion_label=None, congestion_ratio=None, raw_item_json=None),
        ParkingSnapshot(id=4, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=start + timedelta(minutes=30), collected_at=start, occupied_spaces=95, total_spaces=100, available_spaces=5, congestion_label=None, congestion_ratio=None, raw_item_json=None),
        ParkingSnapshot(id=5, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=start + timedelta(minutes=40), collected_at=start, occupied_spaces=89, total_spaces=100, available_spaces=11, congestion_label=None, congestion_ratio=None, raw_item_json=None),
    ]

    events = detect_threshold_events([(snapshot, lot, airport) for snapshot in snapshots], limit=10)
    assert len(events) >= 3
    assert any(event["threshold"] == 50 and event["direction"] == "down" for event in events)
    assert any(event["threshold"] == 10 and event["direction"] == "down" for event in events)
    assert any(event["threshold"] == 10 and event["direction"] == "up" for event in events)


def test_build_aggregations() -> None:
    base = datetime(2026, 4, 21, 0, 0, tzinfo=ZoneInfo("UTC"))
    snapshots = [
        ParkingSnapshot(id=index, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=base + timedelta(hours=index * 6), collected_at=base, occupied_spaces=50, total_spaces=100, available_spaces=50 + index, congestion_label=None, congestion_ratio=None, raw_item_json=None)
        for index in range(4)
    ]

    hourly = build_hourly_buckets(snapshots)
    weekday = build_weekday_buckets(snapshots)
    assert hourly
    assert weekday
    assert weekday[0]["weekday_name"] == "화"


def test_deduplicate_snapshots_prefers_live_source_over_http_migration() -> None:
    observed_at = datetime(2026, 4, 21, 0, 0, tzinfo=ZoneInfo("UTC"))
    snapshots = [
        ParkingSnapshot(
            id=1,
            collection_run_id=None,
            airport_id=1,
            parking_lot_id=1,
            source="migration_http",
            observed_at=observed_at,
            collected_at=observed_at,
            occupied_spaces=90,
            total_spaces=100,
            available_spaces=10,
            congestion_label=None,
            congestion_ratio=None,
            raw_item_json=None,
        ),
        ParkingSnapshot(
            id=2,
            collection_run_id=2,
            airport_id=1,
            parking_lot_id=1,
            source="kac_parking",
            observed_at=observed_at,
            collected_at=observed_at + timedelta(minutes=1),
            occupied_spaces=70,
            total_spaces=100,
            available_spaces=30,
            congestion_label=None,
            congestion_ratio=None,
            raw_item_json=None,
        ),
    ]

    selected = deduplicate_snapshots(snapshots)

    assert len(selected) == 1
    assert selected[0].source == "kac_parking"
    assert selected[0].available_spaces == 30


def test_build_time_series_aggregates_latest_state_per_half_hour() -> None:
    base = datetime(2026, 4, 21, 0, 0, tzinfo=ZoneInfo("UTC"))
    snapshots = [
        ParkingSnapshot(id=1, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=base + timedelta(minutes=5), collected_at=base, occupied_spaces=40, total_spaces=100, available_spaces=60, congestion_label=None, congestion_ratio=None, raw_item_json=None),
        ParkingSnapshot(id=2, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=base + timedelta(minutes=25), collected_at=base, occupied_spaces=50, total_spaces=100, available_spaces=50, congestion_label=None, congestion_ratio=None, raw_item_json=None),
        ParkingSnapshot(id=3, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=base + timedelta(minutes=35), collected_at=base, occupied_spaces=55, total_spaces=100, available_spaces=45, congestion_label=None, congestion_ratio=None, raw_item_json=None),
        ParkingSnapshot(id=4, collection_run_id=None, airport_id=1, parking_lot_id=2, source="seed", observed_at=base + timedelta(minutes=10), collected_at=base, occupied_spaces=30, total_spaces=80, available_spaces=50, congestion_label=None, congestion_ratio=None, raw_item_json=None),
        ParkingSnapshot(id=5, collection_run_id=None, airport_id=1, parking_lot_id=2, source="seed", observed_at=base + timedelta(minutes=40), collected_at=base, occupied_spaces=40, total_spaces=80, available_spaces=40, congestion_label=None, congestion_ratio=None, raw_item_json=None),
    ]

    buckets = build_time_series(snapshots, now=base + timedelta(hours=1), days=1, interval_minutes=30, tz_name="UTC")

    assert len(buckets) == 48
    assert buckets[-2]["available_spaces"] == 0
    assert buckets[-2]["total_spaces"] == 0
    assert buckets[-1]["available_spaces"] == 85
    assert buckets[-1]["lot_observations"] == 2
    assert buckets[-1]["bucket_at"] == base + timedelta(minutes=40)


def test_relative_time_series_final_point_excludes_stale_parking_lot() -> None:
    current = datetime(2026, 4, 21, 12, 0, tzinfo=ZoneInfo("UTC"))
    snapshots = [
        ParkingSnapshot(id=index, collection_run_id=None, airport_id=1, parking_lot_id=index,
                        source="seed", observed_at=observed_at, collected_at=observed_at,
                        occupied_spaces=100 - available, total_spaces=100,
                        available_spaces=available, congestion_label=None, congestion_ratio=None,
                        raw_item_json=None)
        for index, observed_at, available in (
            (1, current, 80), (2, current - timedelta(hours=2), 30),
        )
    ]

    items = build_time_series(snapshots, days=1, interval_minutes=10, tz_name="UTC")
    assert (items[-1]["lot_observations"], items[-1]["available_spaces"]) == (1, 80)
    assert all(item["lot_observations"] == 0 for item in items[-10:-1])


def test_build_time_series_adds_future_axis_without_carrying_parking_values() -> None:
    base = datetime(2026, 4, 21, 0, 0, tzinfo=ZoneInfo("UTC"))
    snapshots = [
        ParkingSnapshot(id=1, collection_run_id=None, airport_id=1, parking_lot_id=1, source="seed", observed_at=base + timedelta(minutes=40), collected_at=base, occupied_spaces=40, total_spaces=100, available_spaces=60, congestion_label=None, congestion_ratio=None, raw_item_json=None),
    ]

    buckets = build_time_series(
        snapshots,
        now=base + timedelta(hours=1),
        days=1,
        interval_minutes=30,
        future_hours=1,
        tz_name="UTC",
    )

    assert len(buckets) == 50
    assert buckets[-3]["bucket_at"] == base + timedelta(minutes=40)
    assert buckets[-3]["available_spaces"] == 60
    assert buckets[-2]["lot_observations"] == 0
    assert buckets[-2]["available_spaces"] == 0
    assert buckets[-1]["lot_observations"] == 0


def test_build_weekday_hour_patterns_returns_hourly_breakdown_per_weekday() -> None:
    base = datetime(2026, 4, 20, 0, 0, tzinfo=ZoneInfo("UTC"))
    snapshots = [
        ParkingSnapshot(
            id=1,
            collection_run_id=None,
            airport_id=1,
            parking_lot_id=1,
            source="seed",
            observed_at=base + timedelta(hours=1),
            collected_at=base,
            occupied_spaces=40,
            total_spaces=100,
            available_spaces=60,
            congestion_label=None,
            congestion_ratio=None,
            raw_item_json=None,
        ),
        ParkingSnapshot(
            id=2,
            collection_run_id=None,
            airport_id=1,
            parking_lot_id=1,
            source="seed",
            observed_at=base + timedelta(hours=1, days=7),
            collected_at=base,
            occupied_spaces=55,
            total_spaces=100,
            available_spaces=45,
            congestion_label=None,
            congestion_ratio=None,
            raw_item_json=None,
        ),
        ParkingSnapshot(
            id=3,
            collection_run_id=None,
            airport_id=1,
            parking_lot_id=1,
            source="seed",
            observed_at=base + timedelta(hours=14, days=1),
            collected_at=base,
            occupied_spaces=25,
            total_spaces=100,
            available_spaces=75,
            congestion_label=None,
            congestion_ratio=None,
            raw_item_json=None,
        ),
    ]

    patterns = build_weekday_hour_patterns(snapshots, tz_name="UTC")

    assert len(patterns) == 2
    monday = patterns[0]
    assert monday["weekday"] == 0
    assert monday["weekday_name"] == "월"
    assert monday["hourly_buckets"][1]["average_available_spaces"] == 52.5
    assert monday["hourly_buckets"][1]["observations"] == 2
    assert monday["hourly_buckets"][2]["average_available_spaces"] is None

    tuesday = patterns[1]
    assert tuesday["weekday"] == 1
    assert tuesday["hourly_buckets"][14]["average_available_spaces"] == 75


def test_build_threshold_insights_returns_weekday_and_history_views() -> None:
    base = datetime(2026, 4, 20, 0, 0, tzinfo=ZoneInfo("UTC"))
    points = [
        {"bucket_at": base, "available_spaces": 80, "occupied_spaces": 20, "total_spaces": 100, "lot_observations": 1},
        {"bucket_at": base + timedelta(hours=4), "available_spaces": 45, "occupied_spaces": 55, "total_spaces": 100, "lot_observations": 1},
        {"bucket_at": base + timedelta(hours=6), "available_spaces": 8, "occupied_spaces": 92, "total_spaces": 100, "lot_observations": 1},
        {"bucket_at": base + timedelta(hours=10), "available_spaces": 30, "occupied_spaces": 70, "total_spaces": 100, "lot_observations": 1},
        {"bucket_at": base + timedelta(days=1), "available_spaces": 75, "occupied_spaces": 25, "total_spaces": 100, "lot_observations": 1},
        {"bucket_at": base + timedelta(days=1, hours=5), "available_spaces": 49, "occupied_spaces": 51, "total_spaces": 100, "lot_observations": 1},
        {"bucket_at": base + timedelta(days=1, hours=8), "available_spaces": 9, "occupied_spaces": 91, "total_spaces": 100, "lot_observations": 1},
    ]

    insights = build_threshold_insights(points, tz_name="UTC", history_limit=10)

    monday_fifty = next(
        item for item in insights["weekday_items"] if item["threshold"] == 50 and item["weekday"] == 0
    )
    monday_ten = next(
        item for item in insights["weekday_items"] if item["threshold"] == 10 and item["weekday"] == 0
    )

    assert monday_fifty["typical_minutes_of_day"] == 240
    assert monday_fifty["sample_count"] == 1
    assert monday_ten["typical_minutes_of_day"] == 360
    assert insights["history_items"][0]["threshold"] == 10
    assert insights["history_items"][0]["local_date"] == "2026-04-21"
