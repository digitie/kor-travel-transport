"""대량 이력 구성 중의 협력 지점과 출력·범위 불변성을 검증한다."""

import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic_core import to_json
from sqlalchemy.engine.row import Row

from app.core.time_utils import serialize_utc
from app.services import parking_history_cache as history


def rows(count):
    names = ("observed_at", "parking_lot_id", "code", "occupied_spaces", "total_spaces", "available_spaces")
    keymap = {name: i for i, name in enumerate(names)}
    start = datetime(2026, 11, 19, tzinfo=UTC)
    return [
        Row(None, None, keymap, (
            (start + timedelta(seconds=i // 3)).astimezone(ZoneInfo("Asia/Seoul") if i % 2 else UTC),
            i % 3 + 1, "GMP" if i % 2 else "CJU", None if i % 7 == 0 else i % 90, 100, 100 - i % 90,
        ))
        for i in range(count)
    ]


def expected_body(values):
    return to_json({"items": [{
        "airport_code": row.code, "parking_lot_id": row.parking_lot_id,
        "observed_at": serialize_utc(row.observed_at), "occupied_spaces": row.occupied_spaces,
        "total_spaces": row.total_spaces, "available_spaces": row.available_spaces,
    } for row in values], "next_cursor": None})


def test_large_conversion_exposes_checkpoint_before_completion_without_changing_body(monkeypatch):
    class ObservedRows(list):
        consumed = 0

        def __iter__(self):
            for row in super().__iter__():
                self.consumed += 1
                yield row

    values = ObservedRows(rows(805))
    permit, progressed, completed = threading.Event(), threading.Event(), threading.Event()
    peer_observed_completion = []
    checkpoints = []

    def peer():
        assert permit.wait(5)
        peer_observed_completion.append(completed.is_set())
        progressed.set()

    def checkpoint(seconds):
        assert seconds == 0
        checkpoints.append(values.consumed)
        permit.set()
        assert progressed.wait(5)

    # 대기 중인 다른 작업이 구성 완료 전에 실행 기회를 받는지 결정적으로 확인한다.
    monkeypatch.setattr(history, "sleep", checkpoint, raising=False)
    worker = threading.Thread(target=peer)
    worker.start()
    try:
        snapshot = history.ParkingHistorySnapshot.from_rows(values[0].observed_at, 805, values)
        completed.set()
        assert progressed.is_set(), "대량 구성 완료 전 협력 지점이 없었습니다"
        assert peer_observed_completion == [False]
        assert checkpoints == [400, 800]
        assert snapshot.render(serialize_utc(values[0].observed_at), None, None) == expected_body(values)
        assert snapshot.times == tuple(serialize_utc(row.observed_at) for row in values)
        for lot in (1, 2, 3):
            assert tuple(x.encoded for x in snapshot.lot_indexes[lot].items) == tuple(
                item.encoded for item in snapshot.items if item.parking_lot_id == lot
            )
    finally:
        completed.set()
        permit.set()
        worker.join(5)
        assert not worker.is_alive()


@pytest.mark.parametrize("count", [0, 399, 400, 401, 800])
def test_checkpoint_boundaries_preserve_all_rows_times_and_filtered_bytes(monkeypatch, count):
    values = rows(count)
    calls = []
    monkeypatch.setattr(history, "sleep", lambda seconds: calls.append(seconds), raising=False)
    start = datetime(2026, 11, 19, tzinfo=UTC)
    snapshot = history.ParkingHistorySnapshot.from_rows(start - timedelta(days=30), count, values)
    assert calls == [0] * (count // 400)
    assert snapshot.render(start, None, None) == expected_body(values)
    assert snapshot.max_snapshot_id == count
    assert snapshot.render(start, "GMP", None) == expected_body([r for r in values if r.code == "GMP"])
    # lot 필터의 우선순위와 같은 시각의 원래 행 순서도 경계 전후에 유지된다.
    assert snapshot.render(start, "CJU", 2) == expected_body([r for r in values if r.parking_lot_id == 2])
