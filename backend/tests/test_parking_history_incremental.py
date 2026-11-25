"""30일 주차 이력 캐시의 증분 갱신(PARKING-HISTORY-INCREMENTAL-20261124).

증분 결과는 같은 읽기 시점의 전체 재생성과 bytes·순서·범위 색인이 같아야 한다(누락·중복·순서).
"""

from __future__ import annotations

import asyncio
import gc
import gzip
import json
import random
import weakref
import zlib
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text

from app.models import Airport, ParkingLot, ParkingSnapshot
from app.services import parking_history_cache as history_cache

NOW = datetime(2026, 11, 24, 3, 0, tzinfo=UTC)
LOTS = {1: "GMP", 2: "GMP", 3: "CJU", 4: "ICN", 5: "ICN"}


@dataclass(frozen=True)
class SourceRow:
    id: int
    observed_at: datetime
    parking_lot_id: int
    source: str
    collected_at: datetime
    occupied_spaces: int
    airport_override: str | None = None  # 같은 주차장이 다른 공항 코드로 들어온 행(이관·원천 오류)

    @property
    def code(self) -> str:
        return self.airport_override or LOTS[self.parking_lot_id]

    total_spaces = 100

    @property
    def available_spaces(self) -> int:
        return 100 - self.occupied_spaces


def _winners(rows: list[SourceRow], max_id: int, earliest: datetime, keys=None) -> list[SourceRow]:
    """`history_rows_statement`의 DISTINCT ON 규칙을 Python으로 옮긴 기준 구현."""
    best: dict[tuple[datetime, int], SourceRow] = {}
    for row in rows:
        key = (row.observed_at, row.parking_lot_id)
        if row.id > max_id or row.observed_at < earliest or (keys is not None and key not in keys):
            continue
        rank = (row.source.startswith("migration_"), -row.collected_at.timestamp(), -row.id)
        current = best.get(key)
        if current is None or rank < (current.source.startswith("migration_"),
                                      -current.collected_at.timestamp(), -current.id):
            best[key] = row
    return [best[key] for key in sorted(best)]


def _assert_same(left: history_cache.ParkingHistorySnapshot, right: history_cache.ParkingHistorySnapshot) -> None:
    assert left.max_snapshot_id == right.max_snapshot_id
    assert left.source_row_count == right.source_row_count
    assert [item.encoded for item in left.items] == [item.encoded for item in right.items]
    assert left.times == right.times
    for name in ("airport_indexes", "lot_indexes"):
        mine, theirs = getattr(left, name), getattr(right, name)
        assert set(mine) == set(theirs)
        for key in mine:
            assert [item.encoded for item in mine[key].items] == [item.encoded for item in theirs[key].items]
            assert mine[key].times == theirs[key].times
    earliest = max(left.earliest_observed_at, right.earliest_observed_at)
    # start_index 전수 대조(조각 경계·자정 포함).
    for cutoff in sorted({*left.times[::97], *(t + timedelta(microseconds=1) for t in left.times[::131])}):
        assert left.start_index(cutoff, None, None) == sum(1 for t in left.times if t < cutoff)
    for cutoff in (earliest, NOW - timedelta(days=1), NOW - timedelta(hours=3), NOW):
        for airport, lot in ((None, None), ("GMP", None), ("ICN", None), ("CJU", None), ("PUS", None), (None, 4), ("ICN", 1)):
            body = right.render(cutoff, airport, lot)
            assert left.render(cutoff, airport, lot) == body
            # 날짜 조각 gzip(증분 snapshot은 이전 조각 압축을 물려받는다)도 같은 본문으로 풀린다.
            assert gzip.decompress(left.render_gzip(cutoff, airport, lot)) == body


@pytest.mark.parametrize("seed", range(12))
def test_incremental_chain_equals_full_rebuild(seed: int) -> None:
    """무작위 수집 흐름(새 관측·같은 관측의 다른 source·이관 행·늦은 옛 관측·기간 경계)에서 증분 = 전체."""
    rng = random.Random(seed)
    rows: list[SourceRow] = []
    next_id = 1

    def add(observed: datetime, lot: int, source: str, collected: datetime, airport: str | None = None) -> None:
        nonlocal next_id
        rows.append(SourceRow(next_id, observed, lot, source, collected, rng.randrange(0, 100), airport))
        next_id += 1

    clock = NOW - timedelta(days=31)
    while clock < NOW - timedelta(days=29, hours=20):
        for lot in LOTS:
            add(clock, lot, "live", clock + timedelta(seconds=30))
        clock += timedelta(minutes=5)
    earliest = NOW - timedelta(days=30, hours=1)
    snapshot = history_cache.ParkingHistorySnapshot.from_rows(
        earliest, next_id - 1, _winners(rows, next_id - 1, earliest), len(rows), NOW,
    )
    for step in range(40):
        watermark = next_id - 1
        for _ in range(rng.randrange(0, 12)):
            kind = rng.random()
            lot = rng.choice(list(LOTS))
            if kind < 0.55:
                add(clock, lot, "live", clock + timedelta(seconds=40))
            elif kind < 0.7:
                # 같은 관측 키의 다른 source(나중 수집이 이긴다).
                old = rng.choice(rows)
                add(old.observed_at, old.parking_lot_id, "kac_dup", old.collected_at + timedelta(minutes=rng.randrange(-5, 5)))
            elif kind < 0.8:
                # 나중에 들어온 이관 행은 live를 이기지 못한다.
                old = rng.choice(rows)
                add(old.observed_at, old.parking_lot_id, "migration_backfill", NOW + timedelta(days=1))
            elif kind < 0.85:
                # 늦게 들어온 옛 관측(기간 밖 포함).
                add(clock - timedelta(hours=rng.randrange(1, 800)), lot, "late", clock)
            elif kind < 0.9:
                # UTC 자정 정각·µs 경계 관측, 다른 공항 코드로 들어온 같은 주차장 행.
                midnight = clock.replace(hour=0, minute=0, second=0, microsecond=0)
                add(midnight - timedelta(microseconds=rng.choice((0, 1))), lot, "edge", clock,
                    rng.choice((None, "PUS")))
            else:
                add(clock + timedelta(minutes=rng.randrange(1, 4)), lot, "live", clock)
        clock += timedelta(minutes=5)
        # 수집마다 기간이 앞으로 간다(가끔 크게 건너뛴다).
        earliest = earliest + timedelta(minutes=rng.choice((0, 5, 5, 90)))
        max_id = next_id - 1
        touched = {(row.observed_at, row.parking_lot_id) for row in rows
                   if watermark < row.id <= max_id and row.observed_at >= earliest}
        snapshot = snapshot.with_changes(
            earliest, max_id, len(rows), frozenset(touched), _winners(rows, max_id, earliest, touched),
        )
        full = history_cache.ParkingHistorySnapshot.from_rows(
            snapshot.earliest_observed_at, max_id, _winners(rows, max_id, snapshot.earliest_observed_at),
            len(rows), NOW,
        )
        _assert_same(snapshot, full)


def test_incremental_reuses_unchanged_encoded_objects_and_drops_window_prefix() -> None:
    base_rows = [SourceRow(index + 1, NOW - timedelta(minutes=10 * (5 - index)), 1 + index % 2, "live",
                           NOW, 10 * index) for index in range(5)]
    snapshot = history_cache.ParkingHistorySnapshot.from_rows(
        NOW - timedelta(days=1), 5, base_rows, 5, NOW,
    )
    new = SourceRow(6, NOW, 3, "live", NOW, 1)
    updated = snapshot.with_changes(
        NOW - timedelta(minutes=35), 6, 6, frozenset({(new.observed_at, 3)}), [new],
    )
    # 앞 2행(50·40분 전)은 기간 밖으로 빠지고, 남은 항목은 같은 객체를 재사용한다.
    assert [item.parking_lot_id for item in updated.items] == [1, 2, 1, 3]
    assert updated.items[0] is snapshot.items[2]
    assert updated.lot_indexes[2].items[0] is snapshot.items[3]
    assert set(updated.airport_indexes) == {"GMP", "CJU"}
    assert updated.full_built_at == NOW and updated.source_row_count == 6
    # 기간이 앞으로만 간다.
    assert updated.with_changes(NOW - timedelta(days=2), 6, 6, frozenset(), []).earliest_observed_at == \
        NOW - timedelta(minutes=35)
    # 한 주차장이 기간 밖으로 모두 빠지면 그 범위 색인을 지운다.
    emptied = updated.with_changes(NOW - timedelta(minutes=5), 6, 6, frozenset(), [])
    assert set(emptied.lot_indexes) == {3} and set(emptied.airport_indexes) == {"CJU"}


def _cache_with(snapshot, fingerprint):
    cache = history_cache.ParkingHistoryReadCache(None)
    cache.snapshot = snapshot
    cache.last_fingerprint = fingerprint
    return cache


def test_refresh_mode_falls_back_to_full_only_when_insert_only_breaks(monkeypatch) -> None:
    snapshot = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 10, [], 10, NOW)
    monkeypatch.setattr(history_cache, "now_utc", lambda: NOW + timedelta(hours=1))
    assert history_cache.ParkingHistoryReadCache(None).refresh_mode((10, 1, 0, 0)) == ("full", "cold")
    cache = _cache_with(snapshot, (10, 10, 0, 0))
    assert cache.refresh_mode((11, 11, 0, 0)) == ("incremental", "new_rows")
    assert cache.refresh_mode((11, 11, 1, 0)) == ("full", "update_or_delete")
    assert cache.refresh_mode((11, 11, 0, 1)) == ("full", "update_or_delete")
    assert cache.refresh_mode((9, 11, 0, 0)) == ("full", "max_id_decreased")
    no_count = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 10, [])
    assert _cache_with(no_count, (10, 10, 0, 0)).refresh_mode((11, 11, 0, 0)) == ("full", "no_row_count")
    # 안전망: 마지막 전체 재생성이 20시간을 넘었고 KST 새벽(03~04시)일 때만 전체 재생성한다.
    old = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 10, [], 10, NOW - timedelta(hours=21))
    monkeypatch.setattr(history_cache, "now_utc", lambda: datetime(2026, 11, 24, 18, 30, tzinfo=UTC))  # 03:30 KST
    assert _cache_with(old, (10, 10, 0, 0)).refresh_mode((11, 11, 0, 0)) == ("full", "periodic")
    monkeypatch.setattr(history_cache, "now_utc", lambda: datetime(2026, 11, 24, 3, 30, tzinfo=UTC))  # 12:30 KST
    assert _cache_with(old, (10, 10, 0, 0)).refresh_mode((11, 11, 0, 0)) == ("incremental", "new_rows")


def test_incremental_refresh_publishes_without_full_load_and_prepares_matching_bodies(monkeypatch) -> None:
    rows = [SourceRow(index + 1, NOW - timedelta(minutes=5 * (10 - index)), 1 + index % 5, "live", NOW, index)
            for index in range(10)]
    base = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 10, rows, 10, NOW)
    cache = _cache_with(base, (10, 10, 0, 0))
    new = SourceRow(11, NOW, 4, "live", NOW, 77)
    loaded = []

    async def fingerprint():
        return (11, 11, 0, 0)

    async def no_full(_factory):
        raise AssertionError("새 행만 들어왔으면 전체 재생성하지 않는다")

    async def changes(_factory, snapshot, **_kwargs):
        loaded.append(snapshot.max_snapshot_id)
        return snapshot.with_changes(NOW - timedelta(days=30), 11, 11, frozenset({(NOW, 4)}), [new]), 1

    monkeypatch.setattr(cache, "source_fingerprint", fingerprint)
    monkeypatch.setattr(history_cache, "now_utc", lambda: NOW + timedelta(minutes=1))
    monkeypatch.setattr(history_cache, "load_snapshot", no_full)
    monkeypatch.setattr(history_cache, "load_changes", changes)
    asyncio.run(cache.refresh_once())
    assert loaded == [10]
    assert cache.snapshot.max_snapshot_id == 11 and cache.last_fingerprint == (11, 11, 0, 0)
    # 사전 압축 본문(#270 전체 이력 경로)이 새 snapshot과 같다.
    cutoff = history_cache.now_utc() - timedelta(days=30)
    body = cache.snapshot.render(cutoff, None, None)
    by_encoding = {key[-1]: value for key, value in cache.prepared_responses.items()}
    assert set(by_encoding) == {"gzip"}
    assert gzip.decompress(by_encoding["gzip"]) == body
    assert json.loads(body)["items"][-1] == {
        "airport_code": "ICN", "parking_lot_id": 4, "observed_at": "2026-11-24T03:00:00Z",
        "occupied_spaces": 77, "total_spaces": 100, "available_spaces": 23,
    }


@pytest.mark.parametrize(("failure", "reason"), [
    (history_cache.IncrementalUnavailable("late_commit_or_delete"), "late_commit_or_delete"),
    # 증분 코드·DB 오류도 전체 재생성으로 회복한다(캐시가 다음 새벽까지 꺼지지 않게).
    (RuntimeError("boom"), "incremental_error:RuntimeError"),
])
def test_incremental_unavailable_falls_back_to_full_rebuild(monkeypatch, caplog, failure, reason) -> None:
    base = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 10, [], 10, NOW)
    cache = _cache_with(base, (10, 10, 0, 0))
    full = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 12, [], 12, NOW)

    async def fingerprint():
        return (12, 12, 0, 0)

    async def changes(_factory, _snapshot, **_kwargs):
        raise failure

    async def load(_factory):
        return full

    monkeypatch.setattr(cache, "source_fingerprint", fingerprint)
    monkeypatch.setattr(history_cache, "load_changes", changes)
    monkeypatch.setattr(history_cache, "load_snapshot", load)
    asyncio.run(cache.refresh_once())
    assert cache.snapshot is full
    finish = [json.loads(record.getMessage()) for record in caplog.records
              if '"phase":"finish"' in record.getMessage()][-1]
    assert (finish["mode"], finish["reason"], finish["outcome"]) == ("full", reason, "published")
    assert "full_load_ms" in finish["phases_ms"] and "gzip_ms" in finish["phases_ms"]
    assert finish["incremental_errors"] == (1 if isinstance(failure, RuntimeError) else 0)
    # 증분 고장은 traceback을 남긴다(전체 재생성으로 회복해도 원인을 찾을 수 있게). 기존 갱신 실패 로그와 같은 수준이다.
    assert ("parking history incremental refresh failed" in caplog.text) == isinstance(failure, RuntimeError)


# ---------------------------------------------------------------------------
# 실제 PostgreSQL: 증분 = 같은 시점의 전체 재생성, 늦은 commit 감지
# ---------------------------------------------------------------------------


def _at(items: list[dict], when: datetime) -> dict:
    stamp = when.isoformat().replace("+00:00", "Z")
    return next(item for item in items if item["observed_at"] == stamp)


def _pg_only(client) -> None:
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 통합 검증에서만 실행")


async def _full_now(factory, earliest):
    return await history_cache.load_snapshot(factory, earliest_observed_at=earliest)


def test_postgres_incremental_matches_full_rebuild(client) -> None:
    _pg_only(client)
    factory = client.app.state.session_factory
    base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=6)

    async def check():
        async with factory() as session:
            airports = (await session.scalars(select(Airport).order_by(Airport.code))).all()
            lots = (await session.scalars(select(ParkingLot).order_by(ParkingLot.id))).all()
            lot_airport = {lot.id: lot.airport_id for lot in lots}
            assert len(airports) >= 2 and len(lots) >= 3
            for step in range(12):
                for lot in lots:
                    session.add(ParkingSnapshot(
                        airport_id=lot.airport_id, parking_lot_id=lot.id, source="inc_live",
                        observed_at=base_time + timedelta(minutes=5 * step),
                        collected_at=base_time + timedelta(minutes=5 * step, seconds=20),
                        occupied_spaces=step, total_spaces=100, available_spaces=100 - step,
                    ))
            await session.commit()
        earliest = base_time - timedelta(hours=1)
        base = await history_cache.load_snapshot(factory, earliest_observed_at=earliest)
        assert base.source_row_count is not None

        lot_ids = list(lot_airport)
        async with factory() as session:
            first, second = lot_ids[0], lot_ids[1]
            session.add_all([
                # 새 관측
                *(ParkingSnapshot(airport_id=lot_airport[lot], parking_lot_id=lot, source="inc_live",
                                  observed_at=base_time + timedelta(minutes=60), collected_at=datetime.now(UTC),
                                  occupied_spaces=61, total_spaces=100, available_spaces=39) for lot in lot_ids),
                # 같은 관측의 다른 source, 나중 수집 → 바뀐다
                ParkingSnapshot(airport_id=lot_airport[first], parking_lot_id=first, source="inc_other",
                                observed_at=base_time + timedelta(minutes=15), collected_at=datetime.now(UTC),
                                occupied_spaces=88, total_spaces=100, available_spaces=12),
                # 이관 행은 나중 수집이어도 live를 이기지 못한다 → 그대로
                ParkingSnapshot(airport_id=lot_airport[second], parking_lot_id=second, source="migration_inc",
                                observed_at=base_time + timedelta(minutes=20), collected_at=datetime.now(UTC),
                                occupied_spaces=99, total_spaces=100, available_spaces=1),
                # 늦게 들어온 옛 관측(기존 시각 사이)
                ParkingSnapshot(airport_id=lot_airport[second], parking_lot_id=second, source="inc_live",
                                observed_at=base_time + timedelta(minutes=7), collected_at=datetime.now(UTC),
                                occupied_spaces=7, total_spaces=100, available_spaces=93),
                # 기간 밖의 늦은 관측은 들어오지 않는다
                ParkingSnapshot(airport_id=lot_airport[second], parking_lot_id=second, source="inc_live",
                                observed_at=earliest - timedelta(minutes=1), collected_at=datetime.now(UTC),
                                occupied_spaces=1, total_spaces=100, available_spaces=99),
            ])
            await session.commit()
        moved = earliest + timedelta(minutes=12)
        incremental, changed = await history_cache.load_changes(factory, base, earliest_observed_at=moved)
        assert changed == len(lot_ids) + 3
        _assert_same(incremental, await _full_now(factory, moved))
        rendered = json.loads(incremental.render(moved, None, first))["items"]
        assert _at(rendered, base_time + timedelta(minutes=15))["occupied_spaces"] == 88
        second_items = json.loads(incremental.render(moved, None, second))["items"]
        assert _at(second_items, base_time + timedelta(minutes=20))["occupied_spaces"] == 4
        assert _at(second_items, base_time + timedelta(minutes=7))["occupied_spaces"] == 7
        # 변화가 없으면 같은 항목 그대로(기간만 자른다).
        again, changed = await history_cache.load_changes(factory, incremental, earliest_observed_at=moved)
        assert changed == 0 and again.items == incremental.items

    asyncio.run(check())


def test_postgres_late_lower_id_commit_forces_full_rebuild(client) -> None:
    """시퀀스는 commit 순서가 아니다. 직전 읽기 때 진행 중이던 낮은 id가 늦게 commit하면 놓치지 않는다."""
    _pg_only(client)
    factory = client.app.state.session_factory
    base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)

    async def check():
        async with factory() as session:
            lot = await session.scalar(select(ParkingLot).order_by(ParkingLot.id))
            airport_id, lot_id = lot.airport_id, lot.id
        earliest = base_time - timedelta(hours=1)
        cache = history_cache.ParkingHistoryReadCache(factory)
        await cache.refresh_once()
        assert cache.snapshot is not None

        slow = factory()
        await slow.__aenter__()
        try:
            slow.add(ParkingSnapshot(airport_id=airport_id, parking_lot_id=lot_id, source="slow_tx",
                                     observed_at=base_time, collected_at=datetime.now(UTC),
                                     occupied_spaces=11, total_spaces=100, available_spaces=89))
            await slow.flush()  # 낮은 id를 먼저 받는다
            async with factory() as fast:
                fast.add(ParkingSnapshot(airport_id=airport_id, parking_lot_id=lot_id, source="fast_tx",
                                         observed_at=base_time + timedelta(minutes=5), collected_at=datetime.now(UTC),
                                         occupied_spaces=22, total_spaces=100, available_spaces=78))
                await fast.commit()
            await cache.refresh_once()  # fast만 보인다(증분)
            seen = json.loads(cache.snapshot.render(earliest, None, lot_id))["items"]
            assert _at(seen, base_time + timedelta(minutes=5))["occupied_spaces"] == 22
            assert all(item["observed_at"] != base_time.isoformat().replace("+00:00", "Z") for item in seen)
            await slow.commit()
        finally:
            await slow.__aexit__(None, None, None)
        with pytest.raises(history_cache.IncrementalUnavailable, match="late_commit_or_delete"):
            await history_cache.load_changes(factory, cache.snapshot)
        # 늦은 commit은 최대 id를 바꾸지 않는다. pg_stat 삽입 수 반영(수 초 지연)을 흉내 내 지문만 바꾼다.
        cache.last_fingerprint = (cache.last_fingerprint[0], -1, *cache.last_fingerprint[2:])
        await cache.refresh_once()  # 증분 시도 → 늦은 commit 감지 → 전체 재생성
        items = json.loads(cache.snapshot.render(earliest, None, lot_id))["items"]
        assert _at(items, base_time)["occupied_spaces"] == 11
        assert _at(items, base_time + timedelta(minutes=5))["occupied_spaces"] == 22
        _assert_same(cache.snapshot, await _full_now(factory, cache.snapshot.earliest_observed_at))

    asyncio.run(check())


def test_crc32_combine_matches_zlib() -> None:
    rng = random.Random(7)
    for _ in range(40):
        left = rng.randbytes(rng.randrange(0, 3000))
        right = rng.randbytes(rng.randrange(0, 200_000))
        assert history_cache.crc32_combine(zlib.crc32(left), zlib.crc32(right), len(right)) == zlib.crc32(left + right)


def test_gzip_segments_are_reused_and_only_changed_days_recompressed(monkeypatch) -> None:
    """갱신 뒤 gzip은 바뀐 날짜·첫 날짜(부분)만 새로 압축한다. 나머지 날짜 조각 압축은 그대로 쓴다."""
    rows = [SourceRow(index + 1, NOW - timedelta(hours=6 * (16 - index)), 1 + index % 5, "live", NOW, index)
            for index in range(16)]  # 4일에 걸친 관측
    snapshot = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 16, rows, 16, NOW)
    cutoff = NOW - timedelta(days=5)
    deflated = []
    original = history_cache.deflate_segment
    monkeypatch.setattr(history_cache, "deflate_segment",
                        lambda raw, *level: deflated.append(len(raw)) or original(raw, *level))
    first = snapshot.render_gzip(cutoff, None, None)
    days = len(snapshot.everything.chunks)
    assert days >= 4 and len(deflated) == days + 1  # 첫 날짜(머리말 포함) + 나머지 날짜 + 꼬리
    assert gzip.decompress(first) == snapshot.render(cutoff, None, None)
    deflated.clear()
    snapshot.render_gzip(cutoff, None, None)
    assert len(deflated) == 2  # 첫 날짜·꼬리만(나머지는 보관한 조각)
    when = NOW - timedelta(hours=5)  # 마지막 날짜 조각 안
    new = SourceRow(17, when, 3, "live", NOW, 99)
    updated = snapshot.with_changes(NOW - timedelta(days=30), 17, 17, frozenset({(when, 3)}), [new])
    assert len(updated.everything.chunks) == len(snapshot.everything.chunks)
    # 바뀐 날짜 앞의 조각 객체(압축 포함)는 그대로 넘어간다.
    assert all(a is b for a, b in zip(updated.everything.chunks[:-1], snapshot.everything.chunks[:-1], strict=True))
    deflated.clear()
    body = updated.render_gzip(cutoff, None, None)
    assert len(deflated) == 3  # 첫 날짜·바뀐 마지막 날짜·꼬리
    assert gzip.decompress(body) == updated.render(cutoff, None, None)
    # 범위 밖·빈 범위도 정상 gzip이다.
    assert gzip.decompress(updated.render_gzip(NOW + timedelta(days=1), None, None)) == b'{"items":[],"next_cursor":null}'
    assert gzip.decompress(updated.render_gzip(cutoff, "missing", None)) == b'{"items":[],"next_cursor":null}'


def test_cached_responses_prefer_gzip_segments_and_keep_br_for_br_only_clients() -> None:
    assert history_cache.cached_response_encoding("br, gzip") == "gzip"
    assert history_cache.cached_response_encoding("gzip, deflate, br, zstd") == "gzip"
    assert history_cache.cached_response_encoding("br") == "br"
    assert history_cache.cached_response_encoding("br, gzip;q=0") == "br"
    assert history_cache.cached_response_encoding("") == "identity"


def test_late_old_observation_rebuilds_only_its_own_day() -> None:
    """늦게 들어온 옛 관측 하나는 그 날짜 조각만 다시 만든다(그 뒤 날짜의 압축 조각은 그대로)."""
    rows = [SourceRow(index + 1, NOW - timedelta(hours=6 * (24 - index)), 1 + index % 5, "live", NOW, index)
            for index in range(24)]  # 6일
    snapshot = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 24, rows, 24, NOW)
    old = rows[2]
    late = SourceRow(25, old.observed_at + timedelta(minutes=1), 2, "live", NOW, 5)
    updated = snapshot.with_changes(NOW - timedelta(days=30), 25, 25,
                                    frozenset({(late.observed_at, 2)}), [late])
    changed_day = history_cache._day_of(late.observed_at)
    before, after = snapshot.everything.chunks, updated.everything.chunks
    assert [chunk.day for chunk in after] == [chunk.day for chunk in before]
    for old_chunk, new_chunk in zip(before, after, strict=True):
        assert (old_chunk is new_chunk) == (old_chunk.day != changed_day)


def test_cache_window_keeps_a_margin_for_requests_waiting_for_a_slot(monkeypatch) -> None:
    """갱신 직전에 시각을 정한 30일 요청이 갱신 뒤에도 캐시를 쓴다(앞부분을 30일에 딱 맞춰 자르지 않는다)."""
    monkeypatch.setattr(history_cache, "now_utc", lambda: NOW)
    base = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=31), 1, [], 1, NOW)

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def connection(self, **_kwargs):
            return None

        async def execute(self, _statement):
            return SimpleNamespace(one=lambda: (1, 1, 1))

    snapshot, _ = asyncio.run(history_cache.load_changes(Session, base))
    request_cutoff = NOW - timedelta(minutes=10) - timedelta(days=30)  # 10분 전에 시각을 정한 요청
    assert snapshot.earliest_observed_at <= request_cutoff
    assert snapshot.earliest_observed_at == NOW - history_cache.HISTORY_WINDOW - history_cache.HISTORY_WINDOW_MARGIN


# ---------------------------------------------------------------------------
# 전체 재생성 중 원본 변화: 결과를 증분 기준으로 채택하고 따라잡는다(#284·#281 후속)
# ---------------------------------------------------------------------------


def _finish_events(caplog) -> list[dict]:
    return [json.loads(record.getMessage()) for record in caplog.records
            if record.getMessage().startswith('{"event":"parking_history_rebuild","phase":"finish"')]


def _fake_adoption_cache(monkeypatch, fingerprints, changes):
    """fake 원본: `fingerprints`를 차례로 내고(마지막 값은 반복), 전체 적재는 max id 10, 증분은 `changes(base)`."""
    cache = history_cache.ParkingHistoryReadCache(None)
    rows = [SourceRow(index + 1, NOW - timedelta(minutes=5 * (10 - index)), 1 + index % 5, "live", NOW, index)
            for index in range(10)]
    full = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 10, rows, 10, NOW)
    loads: list[str] = []
    queue = list(fingerprints)

    async def fingerprint():
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def load(_factory):
        loads.append("full")
        return full

    async def incremental(_factory, base, **_kwargs):
        loads.append(f"inc@{base.max_snapshot_id}")
        return changes(base)

    monkeypatch.setattr(cache, "source_fingerprint", fingerprint)
    monkeypatch.setattr(history_cache, "load_snapshot", load)
    monkeypatch.setattr(history_cache, "load_changes", incremental)
    monkeypatch.setattr(history_cache, "now_utc", lambda: NOW + timedelta(minutes=1))
    return cache, full, loads


def _add_row(base, row_id):
    new = SourceRow(row_id, NOW - timedelta(seconds=row_id), 4, "live", NOW, row_id)
    keys = frozenset({(new.observed_at, new.parking_lot_id)})
    return base.with_changes(NOW - timedelta(days=30), row_id, row_id, keys, [new]), 1


def test_full_rebuild_changed_during_load_is_adopted_and_caught_up(monkeypatch, caplog) -> None:
    # 시작 전(10) → 적재 뒤(11): 채택 → 따라잡기 증분 → 그 뒤 지문 그대로(11) → 게시.
    cache, _full, loads = _fake_adoption_cache(
        monkeypatch, [(10, 10, 0, 0), (11, 11, 0, 0), (11, 11, 0, 0)], lambda base: _add_row(base, 11))
    asyncio.run(cache.refresh_once())
    assert loads == ["full", "inc@10"]
    assert cache.snapshot.max_snapshot_id == 11 and cache.last_fingerprint == (11, 11, 0, 0)
    assert cache.pending_base is None and cache.usable_snapshot(NOW - timedelta(days=1)) is cache.snapshot
    # 사전 압축 본문은 따라잡은 snapshot의 것이다.
    ((_key, body),) = cache.prepared_responses.items()
    assert gzip.decompress(body) == cache.snapshot.render(NOW + timedelta(minutes=1) - timedelta(days=30), None, None)
    finish = _finish_events(caplog)[-1]
    assert (finish["mode"], finish["reason"], finish["outcome"]) == ("full", "cold", "published")
    assert (finish["adoption"], finish["catchups"], finish["row_count"]) == ("published", 1, 11)
    assert "catchup_ms" in finish["phases_ms"]


def test_adoption_keeps_unvalidated_base_while_source_keeps_changing(monkeypatch, caplog) -> None:
    # 따라잡는 사이에도 수집이 계속 끼면 검증 없이 기준만 둔다(요청에는 안 쓴다). 다음 확인이 그 기준에서 증분한다.
    fingerprints = [(10, 10, 0, 0), *((row_id, row_id, 0, 0) for row_id in range(11, 16))]
    cache, _full, loads = _fake_adoption_cache(
        monkeypatch, fingerprints, lambda base: _add_row(base, base.max_snapshot_id + 1))
    asyncio.run(cache.refresh_once())
    assert loads == ["full", "inc@10", "inc@11", "inc@12"]
    assert cache.snapshot is None and cache.validated_at == 0
    pending, pending_fingerprint = cache.pending_base
    assert pending.max_snapshot_id == 13 and pending_fingerprint == (13, 13, 0, 0)
    assert cache.usable_snapshot(NOW - timedelta(days=1)) is None
    assert _finish_events(caplog)[-1]["outcome"] == "adopted_pending"
    # 다음 확인: 전체 재생성 없이 기준에서 증분하고 게시한다.
    asyncio.run(cache.refresh_once())
    assert loads[4:] == ["inc@13"]
    assert cache.snapshot.max_snapshot_id == 14 and cache.pending_base is None
    finish = _finish_events(caplog)[-1]
    assert (finish["mode"], finish["reason"], finish["outcome"]) == ("incremental", "adopted_pending", "published")


@pytest.mark.parametrize(("after", "failure", "adoption"), [
    # 적재 사이 update·delete 통계 변화: 행 수 검사가 못 보는 update가 있을 수 있어 버린다.
    ((11, 11, 1, 0), None, "update_or_delete"),
    ((11, 11, 0, 1), None, "update_or_delete"),
    ((9, 11, 0, 0), None, "max_id_decreased"),
    # 따라잡기 증분이 늦은 낮은 id commit·삭제를 찾으면 버린다.
    ((11, 11, 0, 0), history_cache.IncrementalUnavailable("late_commit_or_delete"), "late_commit_or_delete"),
    ((11, 11, 0, 0), RuntimeError("boom"), "catchup_error:RuntimeError"),
])
def test_adoption_falls_back_to_discard_when_an_invariant_may_break(monkeypatch, caplog, after, failure, adoption) -> None:
    def changes(base):
        if failure is not None:
            raise failure
        return _add_row(base, 11)
    cache, _full, loads = _fake_adoption_cache(monkeypatch, [(10, 10, 0, 0), after, after], changes)
    asyncio.run(cache.refresh_once())
    assert cache.snapshot is None and cache.pending_base is None and cache.validated_at == 0
    finish = _finish_events(caplog)[-1]
    assert (finish["outcome"], finish["adoption"]) == ("source_changed", adoption)
    assert loads[0] == "full" and len(loads) == (1 if failure is None else 2)


def test_update_seen_only_after_adoption_still_forces_full_rebuild(monkeypatch, caplog) -> None:
    """pg_stat 반영이 늦어 채택 뒤에야 update가 보여도, 다음 확인이 채택 지문과 비교해 전체 재생성한다."""
    cache, _full, loads = _fake_adoption_cache(
        monkeypatch, [(10, 10, 0, 0), (11, 11, 0, 0), (11, 11, 0, 0), (11, 11, 1, 0)],
        lambda base: _add_row(base, 11))
    asyncio.run(cache.refresh_once())
    assert cache.last_fingerprint == (11, 11, 0, 0)
    asyncio.run(cache.refresh_once())
    assert loads == ["full", "inc@10", "full"]
    assert _finish_events(caplog)[-1]["reason"] == "update_or_delete"


def test_incremental_source_change_is_still_discarded(monkeypatch, caplog) -> None:
    """채택은 전체 재생성만 한다. 증분 결과는 예전처럼 버리고 다음 확인이 같은 기준에서 다시 증분한다."""
    base = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 10, [], 10, NOW)
    cache, _full, loads = _fake_adoption_cache(
        monkeypatch, [(11, 11, 0, 0), (12, 12, 0, 0)], lambda snapshot: _add_row(snapshot, 11))
    cache.snapshot, cache.last_fingerprint = base, (10, 10, 0, 0)
    asyncio.run(cache.refresh_once())
    assert loads == ["inc@10"] and cache.snapshot is base and cache.pending_base is None
    finish = _finish_events(caplog)[-1]
    assert (finish["outcome"], finish["adoption"], finish["catchups"]) == ("source_changed", None, 0)


def test_refresh_mode_uses_pending_base_and_its_fingerprint(monkeypatch) -> None:
    published = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 10, [], 10, NOW)
    pending = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 20, [], 20, NOW)
    monkeypatch.setattr(history_cache, "now_utc", lambda: NOW + timedelta(hours=1))
    cache = _cache_with(published, (10, 10, 0, 0))
    cache.pending_base = (pending, (20, 20, 0, 0))
    assert cache.refresh_mode((21, 21, 0, 0)) == ("incremental", "adopted_pending")
    assert cache.refresh_mode((21, 21, 1, 0)) == ("full", "update_or_delete")
    assert cache.refresh_mode((15, 21, 0, 0)) == ("full", "max_id_decreased")
    cold = history_cache.ParkingHistoryReadCache(None)
    cold.pending_base = (pending, (20, 20, 0, 0))
    assert cold.refresh_mode((20, 20, 0, 0)) == ("incremental", "adopted_pending")


_STATS_SQL = "SELECT {column} FROM pg_stat_user_tables WHERE relid = 'parking_snapshots'::regclass"


async def _stat(factory, column: str) -> int:
    async with factory() as session:
        return int(await session.scalar(text(_STATS_SQL.format(column=column))))


async def _wait_for_stats(factory, column: str, previous: int) -> None:
    """pg_stat 반영(backend별 최대 약 1초 지연)을 기다린다. 채택 판정이 update·delete 통계를 보게 한다."""
    for _ in range(100):
        if await _stat(factory, column) > previous:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"pg_stat {column} did not advance")


async def _first_lot(factory):
    async with factory() as session:
        lot = await session.scalar(select(ParkingLot).order_by(ParkingLot.id))
        return lot.airport_id, lot.id


def _snapshot_row(airport_id, lot_id, observed_at, occupied, source="adopt_live"):
    return ParkingSnapshot(airport_id=airport_id, parking_lot_id=lot_id, source=source,
                           observed_at=observed_at, collected_at=datetime.now(UTC),
                           occupied_spaces=occupied, total_spaces=100, available_spaces=100 - occupied)


async def _refresh_until_usable(cache, attempts: int = 30) -> None:
    # pg_stat 삽입 수 반영 지연으로 지문이 한두 번 더 바뀔 수 있다. 그때도 전체 재생성 없이 증분으로 맞춘다.
    for _ in range(attempts):
        await cache.refresh_once()
        if (cache.snapshot is not None and cache.pending_base is None
                and cache.usable_snapshot(cache.snapshot.earliest_observed_at) is not None
                and await cache.source_fingerprint() == cache.last_fingerprint):
            return
        await asyncio.sleep(0.2)
    raise AssertionError("cache did not become usable")


def _base_time_items(items: list[dict], when: datetime) -> list[dict]:
    stamp = when.isoformat().replace("+00:00", "Z")
    return [item for item in items if item["observed_at"] == stamp]


def test_postgres_full_rebuild_with_concurrent_inserts_is_adopted_without_second_full_load(
    client, monkeypatch, caplog,
) -> None:
    """전체 적재의 읽기 시점 뒤 새 행 commit·rollback이 있어도 두 번째 전체 재생성 없이 직접 조회와 같아진다."""
    _pg_only(client)
    factory = client.app.state.session_factory
    base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
    original = history_cache.load_snapshot
    full_loads = 0

    async def load_then_collect(session_factory, **kwargs):
        nonlocal full_loads
        full_loads += 1
        snapshot = await original(session_factory, **kwargs)
        if full_loads == 1:
            airport_id, lot_id = await _first_lot(factory)
            async with factory() as rolled_back:  # id만 쓰고 rollback — 어디에도 보이면 안 된다
                rolled_back.add(_snapshot_row(airport_id, lot_id, base_time + timedelta(minutes=30), 66, "rolled_back"))
                await rolled_back.flush()
                await rolled_back.rollback()
            async with factory() as session:
                session.add_all([
                    _snapshot_row(airport_id, lot_id, base_time + timedelta(minutes=10), 10),
                    # 이미 있는 관측의 다른 source(나중 수집) → 바뀐다
                    _snapshot_row(airport_id, lot_id, base_time, 55, "adopt_other"),
                ])
                await session.commit()
        return snapshot

    async def check():
        airport_id, lot_id = await _first_lot(factory)
        async with factory() as session:
            session.add(_snapshot_row(airport_id, lot_id, base_time, 1))
            await session.commit()
        monkeypatch.setattr(history_cache, "load_snapshot", load_then_collect)
        cache = history_cache.ParkingHistoryReadCache(factory)
        await _refresh_until_usable(cache)
        events = _finish_events(caplog)
        # 첫 전체 재생성 결과를 채택했다(버리지 않았다).
        assert events[0]["mode"] == "full" and events[0]["adoption"] in {"published", "adopted_pending"}
        # 그 뒤 전체 재생성은 시험 밖 쓰기가 update·delete를 일으킨 경우뿐이다(삽입만으로는 생기지 않는다).
        assert all(event["mode"] == "incremental" or event["reason"] in {"update_or_delete", "max_id_decreased"}
                   for event in events[1:])
        assert full_loads == 1 + sum(event["mode"] == "full" for event in events[1:])
        items = json.loads(cache.snapshot.render(base_time - timedelta(minutes=1), None, lot_id))["items"]
        assert [item["occupied_spaces"] for item in _base_time_items(items, base_time)] == [55]
        assert _at(items, base_time + timedelta(minutes=10))["occupied_spaces"] == 10
        assert all(item["occupied_spaces"] != 66 for item in items)
        _assert_same(cache.snapshot, await _full_now(factory, cache.snapshot.earliest_observed_at))

    asyncio.run(check())


def test_postgres_late_lower_id_commit_during_full_rebuild_is_not_adopted(client, monkeypatch, caplog) -> None:
    """적재 시점에 진행 중이던 낮은 id가 적재 뒤 commit하면 채택하지 않는다(예전처럼 버리고 전체 재생성)."""
    _pg_only(client)
    factory = client.app.state.session_factory
    base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)
    original = history_cache.load_snapshot
    full_loads = 0

    async def load_with_late_commit(session_factory, **kwargs):
        nonlocal full_loads
        full_loads += 1
        if full_loads > 1:
            return await original(session_factory, **kwargs)
        airport_id, lot_id = await _first_lot(factory)
        slow = factory()
        await slow.__aenter__()
        try:
            slow.add(_snapshot_row(airport_id, lot_id, base_time, 11, "slow_tx"))
            await slow.flush()  # 낮은 id를 먼저 받는다
            async with factory() as fast:
                fast.add(_snapshot_row(airport_id, lot_id, base_time + timedelta(minutes=5), 22, "fast_tx"))
                await fast.commit()
            snapshot = await original(session_factory, **kwargs)  # fast만 보인다
            await slow.commit()
        finally:
            await slow.__aexit__(None, None, None)
        return snapshot

    async def check():
        _airport_id, lot_id = await _first_lot(factory)
        monkeypatch.setattr(history_cache, "load_snapshot", load_with_late_commit)
        cache = history_cache.ParkingHistoryReadCache(factory)
        await cache.refresh_once()
        assert cache.snapshot is None and cache.pending_base is None
        finish = _finish_events(caplog)[-1]
        assert (finish["outcome"], finish["adoption"]) == ("source_changed", "late_commit_or_delete")
        await _refresh_until_usable(cache)
        assert full_loads == 2
        items = json.loads(cache.snapshot.render(base_time - timedelta(minutes=1), None, lot_id))["items"]
        assert _at(items, base_time)["occupied_spaces"] == 11
        assert _at(items, base_time + timedelta(minutes=5))["occupied_spaces"] == 22
        _assert_same(cache.snapshot, await _full_now(factory, cache.snapshot.earliest_observed_at))

    asyncio.run(check())


@pytest.mark.parametrize("change", ["update", "delete"])
def test_postgres_update_or_delete_during_full_rebuild_is_not_adopted(client, monkeypatch, caplog, change) -> None:
    """적재 뒤 update·delete가 통계에 보이면 채택하지 않는다(update는 행 수 검사가 못 본다)."""
    _pg_only(client)
    factory = client.app.state.session_factory
    base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)
    original = history_cache.load_snapshot
    full_loads = 0
    column = "n_tup_upd" if change == "update" else "n_tup_del"
    statement = ("UPDATE parking_snapshots SET occupied_spaces = 77, available_spaces = 23 "
                 "WHERE source = 'adopt_rewrite' AND observed_at = :at" if change == "update" else
                 "DELETE FROM parking_snapshots WHERE source = 'adopt_rewrite' AND observed_at = :at")

    async def load_then_rewrite(session_factory, **kwargs):
        nonlocal full_loads
        full_loads += 1
        snapshot = await original(session_factory, **kwargs)
        if full_loads == 1:
            previous = await _stat(factory, column)
            airport_id, lot_id = await _first_lot(factory)
            async with factory() as session:
                await session.execute(text(statement), {"at": base_time})
                # 새 행도 넣어 최대 id를 바꾼다(통계 반영 전이어도 지문이 달라져 채택 경로를 탄다).
                session.add(_snapshot_row(airport_id, lot_id, base_time + timedelta(minutes=20), 20))
                await session.commit()
                if (await session.scalar(text("SHOW server_version_num"))) >= "150000":
                    await session.execute(text("SELECT pg_stat_force_next_flush()"))
                    await session.commit()
            await _wait_for_stats(factory, column, previous)
        return snapshot

    async def check():
        airport_id, lot_id = await _first_lot(factory)
        async with factory() as session:
            session.add(_snapshot_row(airport_id, lot_id, base_time, 5, "adopt_rewrite"))
            await session.commit()
        monkeypatch.setattr(history_cache, "load_snapshot", load_then_rewrite)
        cache = history_cache.ParkingHistoryReadCache(factory)
        await cache.refresh_once()
        assert cache.snapshot is None and cache.pending_base is None
        finish = _finish_events(caplog)[-1]
        assert (finish["outcome"], finish["adoption"]) == ("source_changed", "update_or_delete")
        await _refresh_until_usable(cache)
        assert full_loads == 2
        items = json.loads(cache.snapshot.render(base_time - timedelta(minutes=1), None, lot_id))["items"]
        expected = [77] if change == "update" else []
        assert [item["occupied_spaces"] for item in _base_time_items(items, base_time)] == expected
        _assert_same(cache.snapshot, await _full_now(factory, cache.snapshot.earliest_observed_at))

    asyncio.run(check())


class _TrackedSnapshot(history_cache.ParkingHistorySnapshot):
    """약한 참조로 해제 여부를 볼 수 있는 snapshot(시험 전용)."""

    __slots__ = ("__weakref__",)


def _tracked(snapshot):
    return _TrackedSnapshot(**{field.name: getattr(snapshot, field.name) for field in dataclass_fields(snapshot)})


def _pending_cache(monkeypatch, fingerprints, changes, full_check=None):
    cache, full, loads = _fake_adoption_cache(monkeypatch, fingerprints, changes)
    pending = _tracked(_add_row(full, 11)[0])
    cache.pending_base = (pending, (11, 11, 0, 0))
    if full_check is not None:
        async def load(_factory):
            loads.append("full")
            full_check()
            return full
        monkeypatch.setattr(history_cache, "load_snapshot", load)
    return cache, full, loads, weakref.ref(pending)


def test_pending_base_is_released_before_fallback_full_load(monkeypatch, caplog) -> None:
    """검증 전 기준에서 증분이 안 되면(늦은 commit 등) 전체 적재 전에 그 기준을 놓는다(snapshot 3개 동시 상주 방지)."""
    released = []

    def changes(_base):
        raise history_cache.IncrementalUnavailable("late_commit_or_delete")

    def check():
        gc.collect()
        released.append(cache.pending_base is None and pending_ref() is None)

    cache, full, loads, pending_ref = _pending_cache(monkeypatch, [(12, 12, 0, 0)], changes, check)
    asyncio.run(cache.refresh_once())
    assert loads == ["inc@11", "full"] and released == [True]
    assert cache.snapshot is full and cache.pending_base is None
    finish = _finish_events(caplog)[-1]
    assert (finish["mode"], finish["reason"], finish["outcome"]) == ("full", "late_commit_or_delete", "published")


def test_pending_base_advances_when_source_changes_during_its_incremental(monkeypatch, caplog) -> None:
    """검증 전 기준의 증분 결과는 지문이 또 바뀌어도 버리지 않고 새 기준(읽기 직전 지문과 함께)으로 올린다."""
    cache, _full, loads, _ref = _pending_cache(
        monkeypatch, [(12, 12, 0, 0), (13, 13, 0, 0), (13, 13, 0, 0)],
        lambda base: _add_row(base, base.max_snapshot_id + 1))
    asyncio.run(cache.refresh_once())
    assert loads == ["inc@11"] and cache.snapshot is None
    advanced, advanced_fingerprint = cache.pending_base
    assert advanced.max_snapshot_id == 12 and advanced_fingerprint == (12, 12, 0, 0)
    finish = _finish_events(caplog)[-1]
    assert (finish["reason"], finish["outcome"], finish["adoption"]) == (
        "adopted_pending", "adopted_pending", "adopted_pending")
    asyncio.run(cache.refresh_once())  # 지문 (13): 새 기준(12)에서 차이만 읽고 게시
    assert loads == ["inc@11", "inc@12"]
    assert cache.snapshot.max_snapshot_id == 13 and cache.pending_base is None


@pytest.mark.parametrize("counters", [(1, 0), (0, 1)])
def test_pending_base_then_update_or_delete_next_poll_rebuilds_in_full(monkeypatch, caplog, counters) -> None:
    """채택 결과를 검증 전 기준으로 둔 뒤 다음 확인에서 update·delete 통계가 보이면 그 기준을 버리고 전체 재생성한다."""
    fingerprints = [(10, 10, 0, 0), *((row_id, row_id, 0, 0) for row_id in range(11, 15)), (15, 15, *counters)]
    cache, full, loads = _fake_adoption_cache(
        monkeypatch, fingerprints, lambda base: _add_row(base, base.max_snapshot_id + 1))
    asyncio.run(cache.refresh_once())
    assert cache.pending_base is not None and _finish_events(caplog)[-1]["outcome"] == "adopted_pending"
    asyncio.run(cache.refresh_once())
    assert loads[-1] == "full" and cache.pending_base is None and cache.snapshot is full
    finish = _finish_events(caplog)[-1]
    assert (finish["mode"], finish["reason"], finish["outcome"]) == ("full", "update_or_delete", "published")


@pytest.mark.parametrize("failing", ["prepare", "fingerprint"])
def test_adoption_prepare_or_fingerprint_failure_is_a_catchup_error(monkeypatch, caplog, failing) -> None:
    """따라잡기의 사전 압축·지문 확인 실패도 `catchup_error:*`로 버린다(로그와 문서가 같은 말을 한다)."""
    calls = {"fingerprint": 0}
    cache, _full, loads = _fake_adoption_cache(
        monkeypatch, [(10, 10, 0, 0), (11, 11, 0, 0)], lambda base: _add_row(base, 11))
    original_prepare, original_fingerprint = cache.prepare_full_window, cache.source_fingerprint

    async def prepare(snapshot):
        if failing == "prepare" and snapshot.max_snapshot_id == 11:
            raise OSError("disk")
        return await original_prepare(snapshot)

    async def fingerprint():
        calls["fingerprint"] += 1
        if failing == "fingerprint" and calls["fingerprint"] == 3:
            raise ConnectionError("db")
        return await original_fingerprint()

    monkeypatch.setattr(cache, "prepare_full_window", prepare)
    monkeypatch.setattr(cache, "source_fingerprint", fingerprint)
    asyncio.run(cache.refresh_once())
    expected = "catchup_error:OSError" if failing == "prepare" else "catchup_error:ConnectionError"
    finish = _finish_events(caplog)[-1]
    assert (finish["outcome"], finish["adoption"], finish["catchups"]) == ("source_changed", expected, 0)
    assert "catchup_ms" in finish["phases_ms"] and cache.snapshot is None and loads == ["full", "inc@10"]
