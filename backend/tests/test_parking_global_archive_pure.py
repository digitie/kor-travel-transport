"""실제 DB를 사용하지 않는 전국 seal 지문·범위·재삽입 회귀."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from app.models import ParkingGlobalStatisticsBucket, ParkingStatisticsBucket
from app.services.parking_global_archive import global_bucket_values, verify_global_bucket
from app.services.parking_statistics_archive import (
    BUCKET_INTERVAL, ParkingArchiveConflict, _digest, bucket_start, build_bucket, raw_digest,
)


def row(identity, lot, minute, available, airport=1):
    at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    return SimpleNamespace(id=identity, airport_id=airport, parking_lot_id=lot,
                           observed_at=at, collected_at=at + timedelta(seconds=10), source="kac_parking",
                           available_spaces=available, occupied_spaces=100 - available, total_spaces=100,
                           congestion_label=None, congestion_ratio=None, raw_item_json={"parking": available})


def airport_records(rows):
    result = {}
    for airport in {item.airport_id for item in rows}:
        members = [item for item in rows if item.airport_id == airport]
        payload, selected = build_bucket(members, {})
        at = bucket_start(members[0].observed_at)
        result[airport] = ParkingStatisticsBucket(
            airport_id=airport, bucket_at=at, bucket_end=at + BUCKET_INTERVAL, format_version=1,
            raw_count=len(members), selected_count=selected, max_snapshot_id=max(item.id for item in members),
            raw_sha256=raw_digest(members), statistics_sha256=_digest(payload), statistics_json=payload,
            created_at=datetime(2026, 1, 4, tzinfo=UTC),
        )
    return result


class ParkingGlobalArchivePureTests(unittest.TestCase):
    def setUp(self):
        self.rows = [row(1, 1, 0, 0), row(2, 1, 5, 100),
                     row(3, 2, 0, 100, airport=2), row(4, 2, 5, 0, airport=2)]
        self.airports = airport_records(self.rows)
        self.values = global_bucket_values(self.rows, self.airports, {}, sealed_at=datetime(2026, 1, 4, tzinfo=UTC))
        self.record = ParkingGlobalStatisticsBucket(**self.values)

    def test_global_coverage_verifies_every_airport_and_exact_cohort(self):
        verify_global_bucket(self.record, self.rows, self.airports, {})
        self.assertEqual(self.record.statistics_json, {"cohorts": {"count": 2, "sum": 200, "min": 100, "max": 100}})
        self.assertEqual(set(self.record.airport_proofs_json), {"1", "2"})
        self.assertNotIn("observations", self.record.statistics_json)

    def test_missing_airport_is_not_complete_coverage(self):
        with self.assertRaises(ParkingArchiveConflict):
            verify_global_bucket(self.record, self.rows, {1: self.airports[1]}, {})

    def test_same_id_value_or_raw_json_mutation_is_rejected(self):
        for field, value in (("available_spaces", 9), ("raw_item_json", {"changed": True})):
            changed = deepcopy(self.rows)
            setattr(changed[0], field, value)
            with self.subTest(field=field), self.assertRaises(ParkingArchiveConflict):
                verify_global_bucket(self.record, changed, self.airports, {})

    def test_raw_deleted_then_old_observation_reinserted_is_not_append_or_replace(self):
        before = deepcopy(self.record.statistics_json)
        replay = deepcopy(self.rows[0])
        replay.id = 99
        replay.collected_at += timedelta(days=20)
        with self.assertRaises(ParkingArchiveConflict):
            verify_global_bucket(self.record, [replay], self.airports, {})
        self.assertEqual(self.record.statistics_json, before)

    def test_empty_or_partial_raw_cannot_validate_sealed_statistics(self):
        for rows in ([], self.rows[:-1]):
            with self.subTest(count=len(rows)), self.assertRaises(ParkingArchiveConflict):
                verify_global_bucket(self.record, rows, self.airports, {})

    def test_global_proof_or_statistics_mutation_is_rejected(self):
        for field in ("airport_proofs_json", "statistics_json"):
            record = ParkingGlobalStatisticsBucket(**{**self.values, field: {"tampered": True}})
            with self.subTest(field=field), self.assertRaises(ParkingArchiveConflict):
                verify_global_bucket(record, self.rows, self.airports, {})

    def test_bucket_floor_uses_utc_before_rounding_non_ten_minute_offsets(self):
        local = datetime(2026, 10, 27, 0, 7, tzinfo=timezone(timedelta(hours=5, minutes=45)))
        self.assertEqual(bucket_start(local), datetime(2026, 10, 26, 18, 20, tzinfo=UTC))
        self.assertEqual(bucket_start(local).utcoffset(), timedelta(0))
        for minutes in (0, 345, -225, 525):
            same_instant = local.astimezone(timezone(timedelta(minutes=minutes)))
            self.assertEqual(bucket_start(same_instant), bucket_start(local.astimezone(UTC)))

    def test_raw_digest_and_statistical_point_are_canonical_utc(self):
        shifted = deepcopy(self.rows)
        zone = timezone(timedelta(hours=5, minutes=45))
        for item in shifted:
            item.observed_at = item.observed_at.astimezone(zone)
            item.collected_at = item.collected_at.astimezone(zone)
        self.assertEqual(raw_digest(shifted), raw_digest(self.rows))
        self.assertEqual(build_bucket(shifted[:2], {})[0], build_bucket(self.rows[:2], {})[0])


if __name__ == "__main__":
    unittest.main()
