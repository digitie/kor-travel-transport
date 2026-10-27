"""실제 archive builder 결과를 기존 원본 pattern과 비교한다. DB·수집 실행은 없다."""
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from app.models import ParkingStatisticsBucket
from app.services.analytics import (
    build_hourly_buckets, build_weekday_buckets, build_weekday_hour_patterns, deduplicate_snapshots,
)
from app.services.parking_archive_reader import ParkingArchivePrecisionUnavailable, read_pattern_statistics
from app.services.parking_statistics_archive import (
    BUCKET_INTERVAL, ParkingArchiveConflict, _digest, bucket_start, build_bucket, raw_digest,
)

AT = datetime(2026, 1, 1, tzinfo=UTC)


def sample(identity, at, available, *, lot=1, airport=1, source="kac_parking"):
    return SimpleNamespace(id=identity, airport_id=airport, parking_lot_id=lot,
                           observed_at=at, collected_at=at + timedelta(seconds=10), source=source,
                           available_spaces=available, occupied_spaces=100 - available, total_spaces=100,
                           congestion_label=None, congestion_ratio=None, raw_item_json={"available": available})


def archive(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.airport_id, bucket_start(row.observed_at)].append(row)
    result, previous = [], {}
    for (airport, at), members in sorted(grouped.items(), key=lambda pair: (pair[0][1], pair[0][0])):
        payload, count = build_bucket(members, previous)
        result.append(ParkingStatisticsBucket(
            airport_id=airport, bucket_at=at, bucket_end=at + BUCKET_INTERVAL, format_version=1,
            raw_count=len(members), selected_count=count, max_snapshot_id=max(row.id for row in members),
            raw_sha256=raw_digest(members), statistics_sha256=_digest(payload), statistics_json=payload,
            created_at=AT + timedelta(days=100),
        ))
    return result


class ParkingArchiveReaderTests(unittest.TestCase):
    def assert_matches_raw(self, records, raw, original, start, end, **scope):
        result = read_pattern_statistics(records, raw, start=start, end=end, **scope)
        selected = deduplicate_snapshots([row for row in original if start <= row.observed_at < end
            and (scope.get("airport_id") is None or row.airport_id == scope["airport_id"])
            and (scope.get("parking_lot_id") is None or row.parking_lot_id == scope["parking_lot_id"])])
        tz = scope.get("tz_name", "Asia/Seoul")
        self.assertEqual(result.by_hour, build_hourly_buckets(selected, tz))
        self.assertEqual(result.by_weekday, build_weekday_buckets(selected, tz))
        self.assertEqual(result.by_weekday_hour, build_weekday_hour_patterns(selected, tz))
        self.assertEqual(result.metadata["archive_observations"] + result.metadata["raw_observations"], len(selected))
        self.assertEqual(result.metadata["coverage"], "unknown")
        return result

    def test_long_windows_archive_only_and_mixed_match_all_three_patterns(self):
        for days in (7, 14, 21, 28, 90):
            rows = []
            for day in range(days):
                for airport, lot in ((1, 1), (1, 2), (2, 3)):
                    # KST 자정 앞뒤, 두 시간과 두 source가 섞인 실제 관측 단위다.
                    for offset in (14 * 60 + 59, 15 * 60, 15 * 60 + 5):
                        rows.append(sample(len(rows) + 1, AT + timedelta(days=day, minutes=offset),
                                           (day * 3 + lot + offset) % 100, lot=lot, airport=airport))
            sealed = [row for row in rows if row.observed_at < AT + timedelta(days=days - 2)]
            recent = [row for row in rows if row not in sealed]
            for scope in ({}, {"airport_id": 1}, {"parking_lot_id": 3}):
                with self.subTest(days=days, scope=scope, kind="archive_only"):
                    self.assert_matches_raw(archive(rows), [], rows, AT, AT + timedelta(days=days), **scope)
                with self.subTest(days=days, scope=scope, kind="mixed_with_overlap"):
                    self.assert_matches_raw(archive(sealed), rows, rows, AT, AT + timedelta(days=days), **scope)
                with self.subTest(days=days, scope=scope, kind="mixed_without_overlap"):
                    self.assert_matches_raw(archive(sealed), recent, rows, AT, AT + timedelta(days=days), **scope)

    def test_sufficient_sums_preserve_sample_weights_not_mean_of_means(self):
        rows = [sample(1, AT, 0)] + [sample(i + 2, AT + timedelta(minutes=10, seconds=i), 100) for i in range(9)]
        result = self.assert_matches_raw(archive(rows), [], rows, AT, AT + timedelta(hours=1))
        self.assertEqual(result.by_hour[0]["average_available_spaces"], 90)
        self.assertEqual(result.by_hour[0]["observations"], 10)

    def test_live_priority_dedup_and_archive_raw_overlap_are_not_double_counted(self):
        rows = [sample(1, AT, 10, source="migration_http"), sample(2, AT, 90),
                sample(3, AT + timedelta(minutes=5), 50)]
        self.assert_matches_raw(archive(rows), rows, rows, AT, AT + timedelta(hours=1))
        self.assert_matches_raw(archive(rows), rows[:1], rows, AT, AT + timedelta(hours=1))

    def test_unaligned_boundary_uses_only_complete_fingerprint_verified_raw(self):
        rows = [sample(1, AT + timedelta(minutes=1), 0), sample(2, AT + timedelta(minutes=8), 100)]
        records = archive(rows)
        result = self.assert_matches_raw(records, rows, rows, AT + timedelta(minutes=5), AT + timedelta(minutes=9))
        self.assertEqual(result.metadata["raw_observations"], 1)
        for retained in ([], rows[:1], rows[1:]):
            with self.subTest(retained=len(retained)), self.assertRaises(ParkingArchivePrecisionUnavailable) as caught:
                read_pattern_statistics(records, retained, start=AT + timedelta(minutes=5), end=AT + timedelta(minutes=9))
            self.assertEqual(caught.exception.metadata["reason"], "query_boundary_inside_bucket")
            self.assertEqual(caught.exception.metadata["archive_resolution_minutes"], 10)

    def test_exact_first_last_bounds_and_half_open_query_do_not_require_raw(self):
        rows = [sample(1, AT + timedelta(minutes=1), 0), sample(2, AT + timedelta(minutes=8), 100)]
        self.assert_matches_raw(archive(rows), [], rows, AT + timedelta(minutes=1), AT + timedelta(minutes=9))
        for start, end in [(AT - timedelta(minutes=1), AT + timedelta(minutes=1)),
                           (AT + timedelta(minutes=9), AT + timedelta(minutes=10))]:
            self.assert_matches_raw(archive(rows), [], rows, start, end)

    def test_kathmandu_hour_cut_does_not_assign_all_observations_to_first_hour(self):
        rows = [sample(1, AT + timedelta(minutes=12), 0), sample(2, AT + timedelta(minutes=18), 100)]
        with self.assertRaises(ParkingArchivePrecisionUnavailable) as caught:
            read_pattern_statistics(archive(rows), [], start=AT, end=AT + timedelta(hours=1), tz_name="Asia/Kathmandu")
        self.assertEqual(caught.exception.metadata["reason"], "local_hour_boundary_inside_bucket")
        self.assert_matches_raw(archive(rows), rows, rows, AT, AT + timedelta(hours=1), tz_name="Asia/Kathmandu")

    def test_empty_inputs_have_unknown_coverage_and_no_fake_zero_observations(self):
        result = self.assert_matches_raw([], [], [], AT, AT + timedelta(days=90))
        self.assertEqual(result.by_hour, [])
        self.assertEqual(result.by_weekday_hour, [])

    def test_missing_lot_is_empty_but_new_lot_replay_in_sealed_bucket_is_conflict(self):
        rows = [sample(1, AT, 30)]
        self.assert_matches_raw(archive(rows), [], rows, AT, AT + timedelta(hours=1), parking_lot_id=2)
        with self.assertRaises(ParkingArchiveConflict):
            read_pattern_statistics(archive(rows), [sample(2, AT, 40, lot=2)], start=AT,
                                    end=AT + timedelta(hours=1), parking_lot_id=2)

    def test_deleted_raw_replay_neither_overwrites_nor_appends_old_statistics(self):
        rows = [sample(1, AT, 0), sample(2, AT + timedelta(minutes=5), 100)]
        records = archive(rows)
        before = deepcopy(records[0].statistics_json)
        self.assert_matches_raw(records, [], rows, AT, AT + timedelta(hours=1))
        replay = sample(3, AT, 0)
        replay.collected_at = AT + timedelta(days=3)
        with self.assertRaises(ParkingArchiveConflict):
            read_pattern_statistics(records, [replay], start=AT, end=AT + timedelta(hours=1))
        self.assertEqual(records[0].statistics_json, before)

    def test_stat_corruption_duplicate_archive_and_complete_raw_mutation_refuse(self):
        rows = [sample(1, AT, 10), sample(2, AT + timedelta(minutes=5), 20)]
        records = archive(rows)
        with self.assertRaises(ParkingArchiveConflict):
            read_pattern_statistics(records * 2, [], start=AT, end=AT + timedelta(hours=1))
        mutated = deepcopy(rows)
        mutated[0].raw_item_json = {"changed": True}
        with self.assertRaises(ParkingArchiveConflict):
            read_pattern_statistics(records, mutated, start=AT, end=AT + timedelta(hours=1))
        records[0].statistics_json["lots"][0]["available"]["sum"] = 999
        with self.assertRaises(ParkingArchiveConflict):
            read_pattern_statistics(records, [], start=AT, end=AT + timedelta(hours=1))

    def test_invalid_window_refuses_instead_of_returning_empty_success(self):
        for end in (AT, AT - timedelta(seconds=1)):
            with self.assertRaises(ValueError):
                read_pattern_statistics([], [], start=AT, end=end)
