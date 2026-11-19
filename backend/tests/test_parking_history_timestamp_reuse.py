"""이력 인덱스와 JSON이 동일한 UTC 시각을 재사용하고 응답 계약을 유지한다."""

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic_core import to_json

from app.services import parking_history_cache as history


@pytest.mark.parametrize("observed", [
    datetime(2026, 11, 19, 3, 0, tzinfo=UTC),
    datetime(2026, 11, 19, 3, 0),
    datetime(2026, 11, 19, 12, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    datetime(2026, 11, 19, 8, 45, tzinfo=timezone(timedelta(hours=5, minutes=45))),
    datetime(2026, 11, 1, 1, 30, tzinfo=ZoneInfo("America/New_York"), fold=1),
])
def test_history_converts_each_row_once_and_preserves_index_and_json(monkeypatch, observed):
    convert = history.serialize_utc
    expected = convert(observed)
    calls = []

    def measured(value):
        calls.append(value)
        return convert(value)

    monkeypatch.setattr(history, "serialize_utc", measured)
    rows = [SimpleNamespace(observed_at=observed, code=code, parking_lot_id=lot,
                            occupied_spaces=None, total_spaces=100, available_spaces=0)
            for code, lot in [("GMP", 1), ("CJU", 2), ("GMP", 3)]]
    snapshot = history.ParkingHistorySnapshot.from_rows(expected - timedelta(days=30), 42, rows)
    expected_items = [{"airport_code": row.code, "parking_lot_id": row.parking_lot_id,
                       "observed_at": expected, "occupied_spaces": None,
                       "total_spaces": 100, "available_spaces": 0} for row in rows]
    assert snapshot.render(expected, None, None) == to_json({
        "items": expected_items, "next_cursor": None,
    })
    assert snapshot.render(expected, "GMP", None) == to_json({
        "items": [expected_items[0], expected_items[2]], "next_cursor": None,
    })
    assert snapshot.render(expected, "GMP", 2) == to_json({
        "items": [expected_items[1]], "next_cursor": None,
    })
    assert snapshot.render(expected + timedelta(microseconds=1), None, None) == to_json({
        "items": [], "next_cursor": None,
    })
    assert snapshot.times == (expected,) * 3
    assert all(item.observed_at is timestamp for item, timestamp in zip(snapshot.items, snapshot.times))
    assert len(calls) == len(rows)
