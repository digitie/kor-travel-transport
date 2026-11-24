"""30일 주차 이력 캐시의 증분 갱신(PARKING-HISTORY-INCREMENTAL-20261124).

증분 결과는 같은 읽기 시점의 전체 재생성과 bytes·순서·범위 색인이 같아야 한다(누락·중복·순서).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import random
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

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
