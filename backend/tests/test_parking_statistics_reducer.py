"""2A의 DB 미사용 회귀. unittest와 pytest 양쪽에서 실행할 수 있다."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import unittest

from app.services.analytics import build_global_cohort_summary
from app.services.parking_archive_state import is_newer_current, latest_state_values


def observation(identity, lot, minute, available, *, source="kac_parking", airport=1):
    at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
    return SimpleNamespace(id=identity, airport_id=airport, parking_lot_id=lot,
                           observed_at=at, collected_at=at + timedelta(seconds=30), source=source,
                           available_spaces=available, occupied_spaces=100 - available, total_spaces=100,
                           congestion_label=None, congestion_ratio=None)


class ParkingStatisticsReducerTests(unittest.TestCase):
    def test_global_cohorts_preserve_airport_correlation(self):
        rows = [observation(1, 1, 0, 0), observation(2, 1, 5, 100),
                observation(3, 2, 0, 100, airport=2), observation(4, 2, 5, 0, airport=2)]
        summary, selected = build_global_cohort_summary(rows)
        self.assertEqual(summary, {"count": 2, "sum": 200, "min": 100, "max": 100})
        self.assertEqual(selected, 4)

    def test_global_mixed_timestamps_do_not_invent_synchronous_observations(self):
        rows = [observation(1, 1, 0, 5), observation(2, 2, 1, 90, airport=2),
                observation(3, 1, 5, 10), observation(4, 2, 5, 80, airport=2)]
        self.assertEqual(build_global_cohort_summary(rows),
                         ({"count": 3, "sum": 185, "min": 5, "max": 90}, 4))

    def test_global_duplicate_prefers_live_then_collected_then_id(self):
        rows = [observation(1, 1, 0, 20), observation(9, 1, 0, 90, source="migration_http"),
                observation(2, 1, 0, 30), observation(3, 2, 0, 40, airport=2)]
        self.assertEqual(build_global_cohort_summary(rows),
                         ({"count": 1, "sum": 70, "min": 70, "max": 70}, 2))

    def test_empty_global_bucket_is_not_a_valid_zero(self):
        with self.assertRaises(ValueError):
            build_global_cohort_summary([])

    def test_current_preserves_id_priority_instead_of_analysis_source_priority(self):
        live = observation(1, 1, 0, 60)
        migration = observation(9, 1, 0, 9, source="migration_http")
        self.assertTrue(is_newer_current(migration, live))
        self.assertFalse(is_newer_current(live, migration))
        state = SimpleNamespace(**latest_state_values(migration))
        self.assertFalse(is_newer_current(live, state))

    def test_current_does_not_replace_new_observation_with_new_id_of_old_time(self):
        latest = observation(5, 1, 5, 70)
        old = observation(99, 1, 0, 9)
        self.assertFalse(is_newer_current(old, latest))

    def test_current_keeps_original_point_time_and_separate_ingest_watermark(self):
        latest = observation(5, 1, 5, 70)
        received = latest.collected_at + timedelta(days=2)
        values = latest_state_values(latest, latest_ingested_at=received)
        self.assertEqual(values["collected_at"], latest.collected_at)
        self.assertEqual(values["latest_ingested_at"], received)
        self.assertNotIn("raw_item_json", values)
        self.assertNotIn("collection_run_id", values)


if __name__ == "__main__":
    unittest.main()
