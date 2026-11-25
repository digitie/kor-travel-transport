"""30일 주차 이력 갱신 계측과 캐시 미사용 직접 조회의 상한(동시 1건·스트리밍 압축·깨움·떠난 요청)."""

from __future__ import annotations

import asyncio
import gzip
import json
import threading
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import brotli
import pytest
from pydantic_core import to_json
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import TextClause

from app.core.time_utils import serialize_utc
from app.models import Airport, ParkingLot, ParkingSnapshot
from app.services import parking_history_cache as history_cache

NOW = datetime(2026, 11, 24, tzinfo=UTC)


def _rows(count: int) -> list[tuple]:
    zones = (UTC, ZoneInfo("Asia/Seoul"), timezone(timedelta(hours=5, minutes=45)), None)
    rows = []
    for index in range(count):
        observed = NOW - timedelta(days=2) + timedelta(seconds=index // 3)
        zone = zones[index % len(zones)]
        observed = observed.replace(tzinfo=None) if zone is None else observed.astimezone(zone)
        rows.append((
            observed, index % 3 + 1, "GMP" if index % 2 else "CJU",
            None if index % 7 == 0 else index % 90, 100, 100 - index % 90,
        ))
    return rows


def _legacy_body(rows: list[tuple]) -> bytes:
    # 변경 전 직접 조회 경로(main.py serialize_rows)의 전체 문서 직렬화와 같은 식이다.
    return to_json({"items": [
        {"airport_code": code, "parking_lot_id": lot, "observed_at": serialize_utc(observed),
         "occupied_spaces": occupied, "total_spaces": total, "available_spaces": available}
        for observed, lot, code, occupied, total, available in rows
    ], "next_cursor": None})


class _Result:
    def __init__(self, rows, events=None, gate: asyncio.Event | None = None, fail_after: int | None = None):
        self.rows, self.events, self.gate, self.fail_after = rows, events, gate, fail_after
        self.closed = False

    async def partitions(self, size):
        if self.gate is not None:
            await self.gate.wait()
        for number, start in enumerate(range(0, len(self.rows), size)):
            if self.fail_after is not None and number >= self.fail_after:
                raise RuntimeError("fetch failed")
            if self.events is not None:
                self.events.append(("batch", size))
            yield self.rows[start:start + size]

    async def close(self):
        self.closed = True


class _StreamSession:
    """`session.connection().stream()`과 지문 조회를 흉내 내는 PostgreSQL session."""

    def __init__(self, rows=(), *, max_id=1, counters=(0, 0, 0), result_factory=None):
        self.rows, self.max_id, self.counters = list(rows), max_id, counters
        self.result_factory = result_factory
        self.connection_options = []
        self.statements = []
        self.results: list[_Result] = []
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def __call__(self):
        return self

    async def scalar(self, _statement):
        return self.max_id

    async def execute(self, statement):
        if isinstance(statement, TextClause):  # pg_stat 지문
            return SimpleNamespace(one=lambda: self.counters)
        return SimpleNamespace(one=lambda: (self.max_id, len(self.rows)))  # 전체 적재의 max(id)·행 수

    async def connection(self, execution_options=None):
        self.connection_options.append(execution_options)
        return SimpleNamespace(stream=self.stream)

    async def stream(self, statement):
        self.statements.append(statement)
        result = self.result_factory() if self.result_factory else _Result(self.rows)
        self.results.append(result)
        return result


# --- 2. 재생성 계측과 진행 표시 ---------------------------------------------


def test_worker_cpu_meter_reads_thread_time_inside_worker_thread(monkeypatch) -> None:
    main_thread = threading.get_ident()
    seen_threads = []
    clock = iter([10.0, 10.25, 20.0, 20.5])

    def fake_thread_time():
        seen_threads.append(threading.get_ident())
        return next(clock)

    monkeypatch.setattr(history_cache, "thread_time", fake_thread_time)
    meter = history_cache.WorkerCpuMeter()

    async def check():
        token = history_cache._WORKER_CPU.set(meter)
        try:
            assert await history_cache._run_worker(lambda value: value * 2, 21) == 42
            with pytest.raises(ValueError):
                await history_cache._run_worker(lambda: (_ for _ in ()).throw(ValueError("boom")))
        finally:
            history_cache._WORKER_CPU.reset(token)
        # 갱신 밖에서는 계측하지 않는다.
        assert await history_cache._run_worker(lambda: 7) == 7

    asyncio.run(check())
    assert meter.seconds == pytest.approx(0.75)
    assert len(seen_threads) == 4 and main_thread not in seen_threads


def _ticking_thread_time(monkeypatch):
    lock = threading.Lock()
    ticks = {"value": 0.0}
    callers = []

    def fake_thread_time():
        with lock:
            callers.append(threading.get_ident())
            ticks["value"] += 0.0625
            return ticks["value"]

    monkeypatch.setattr(history_cache, "thread_time", fake_thread_time)
    return callers


def _finish_events(caplog) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records
            if r.getMessage().startswith('{"event":"parking_history_rebuild"') and '"phase":"finish"' in r.getMessage()]


def test_full_rebuild_finish_log_counts_conversion_and_gzip_cpu(monkeypatch, caplog) -> None:
    callers = _ticking_thread_time(monkeypatch)
    monkeypatch.setattr(history_cache, "now_utc", lambda: NOW)
    session = _StreamSession(_rows(5), max_id=5, counters=(5, 0, 0))
    cache = history_cache.ParkingHistoryReadCache(session)
    caplog.set_level("WARNING", logger=history_cache.__name__)
    asyncio.run(cache.refresh_once())
    (finish,) = _finish_events(caplog)
    # 전체 적재의 from_rows와 30일 gzip 조립(render_gzip) 두 번의 worker 호출이 thread_time을 두 번씩 읽는다.
    assert finish["outcome"] == "published" and finish["mode"] == "full"
    assert finish["worker_cpu_ms"] == pytest.approx(2 * 62.5)
    assert len(callers) == 4 and threading.get_ident() not in callers
    assert finish["process_cpu_ms"] >= 0
    assert session.connection_options[0] == {"isolation_level": "REPEATABLE READ"}


def test_incremental_refresh_is_metered_through_the_same_context(monkeypatch, caplog) -> None:
    callers = _ticking_thread_time(monkeypatch)
    monkeypatch.setattr(history_cache, "now_utc", lambda: NOW)
    base = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 1, [], 1, NOW)
    cache = history_cache.ParkingHistoryReadCache(None)
    cache.snapshot, cache.last_fingerprint = base, (1, 1, 0, 0)
    fingerprints = iter([(2, 2, 0, 0), (2, 2, 0, 0)])

    async def fingerprint():
        return next(fingerprints)

    async def changes(_factory, snapshot, **_kwargs):
        # 실제 load_changes처럼 조각 반영을 _run_worker로 thread에서 한다.
        updated = await history_cache._run_worker(
            snapshot.with_changes, NOW - timedelta(days=30), 2, 2, frozenset(), [],
        )
        return updated, 0

    monkeypatch.setattr(cache, "source_fingerprint", fingerprint)
    monkeypatch.setattr(history_cache, "load_changes", changes)
    caplog.set_level("WARNING", logger=history_cache.__name__)
    asyncio.run(cache.refresh_once())
    (finish,) = _finish_events(caplog)
    assert finish["mode"] == "incremental" and finish["outcome"] == "published"
    # 증분 반영(with_changes)과 30일 gzip 조립(render_gzip) 두 번이 계측된다.
    assert finish["worker_cpu_ms"] == pytest.approx(2 * 62.5) and len(callers) == 4
    assert history_cache._WORKER_CPU.get() is None


def test_peak_rss_is_reported_in_kib_when_resource_is_available(monkeypatch) -> None:
    usage = SimpleNamespace(ru_maxrss=2048)
    fake_resource = SimpleNamespace(RUSAGE_SELF=0, getrusage=lambda _who: usage)
    monkeypatch.setattr(history_cache, "resource", fake_resource)
    monkeypatch.setattr(history_cache.sys, "platform", "linux")
    assert history_cache.peak_rss_kib() == 2048
    monkeypatch.setattr(history_cache.sys, "platform", "darwin")
    assert history_cache.peak_rss_kib() == 2
    monkeypatch.setattr(history_cache, "resource", None)
    assert history_cache.peak_rss_kib() is None


@pytest.mark.parametrize("fail", [False, True])
def test_rebuild_active_is_true_only_while_rebuilding(monkeypatch, fail) -> None:
    async def check():
        entered, release = asyncio.Event(), asyncio.Event()

        async def load(_factory, **_kwargs):
            entered.set()
            await release.wait()
            if fail:
                raise RuntimeError("load failed")
            return history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 1, [])

        monkeypatch.setattr(history_cache, "load_snapshot", load)
        cache = history_cache.ParkingHistoryReadCache(_StreamSession(max_id=1))
        assert cache.rebuild_active is False
        task = asyncio.create_task(cache.refresh_once())
        await entered.wait()
        assert cache.rebuild_active is True
        assert cache.rebuild_started_at is not None
        release.set()
        if fail:
            with pytest.raises(RuntimeError):
                await task
        else:
            await task
        assert cache.rebuild_active is False and cache.rebuild_started_at is None

    asyncio.run(check())


# --- 4. 직접 조회 fallback: 스트리밍 인코딩과 동시 1건 상한 -----------------


def _decompress(body: bytes, encoding: str) -> bytes:
    return {"br": brotli.decompress, "gzip": gzip.decompress}.get(encoding, lambda value: value)(body)


@pytest.mark.parametrize(("accept_encoding", "encoding"), [("", "identity"), ("gzip", "gzip"), ("gzip, br", "br")])
@pytest.mark.parametrize("count", [0, 1, history_cache.HISTORY_FETCH_ROWS, history_cache.HISTORY_FETCH_ROWS * 2 + 3])
def test_direct_history_streams_batches_and_matches_legacy_and_cache_bytes(count, accept_encoding, encoding) -> None:
    rows = _rows(count)
    events = []
    session = _StreamSession(result_factory=lambda: _Result(rows, events))
    body, headers = asyncio.run(history_cache.render_direct_history(
        session, ParkingSnapshot.observed_at >= NOW - timedelta(days=30), accept_encoding=accept_encoding,
    ))
    assert headers == history_cache.response_headers(encoding)
    assert headers.get("Content-Encoding") == (None if encoding == "identity" else encoding)
    decoded = _decompress(body, encoding)
    assert decoded == _legacy_body(rows)
    snapshot = history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), count, [
        SimpleNamespace(observed_at=o, parking_lot_id=lot, code=c, occupied_spaces=oc, total_spaces=t, available_spaces=a)
        for o, lot, c, oc, t, a in rows
    ])
    assert decoded == snapshot.render(NOW - timedelta(days=30), None, None)
    (statement,) = session.statements
    assert statement.get_execution_options()["yield_per"] == history_cache.HISTORY_FETCH_ROWS
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "DISTINCT ON" in compiled and "left(parking_snapshots.source" in compiled
    assert "history_rows" in compiled and "parking_snapshots.id <=" not in compiled
    assert events == [("batch", history_cache.HISTORY_FETCH_ROWS)] * (-(-count // history_cache.HISTORY_FETCH_ROWS))
    assert session.results[0].closed


@pytest.mark.parametrize("accept_encoding", ["gzip", "br"])
def test_direct_history_compressed_fallback_never_holds_the_identity_body(monkeypatch, accept_encoding) -> None:
    rows = _rows(history_cache.HISTORY_FETCH_ROWS * 3)
    largest_part = {"size": 0}
    original_write = history_cache._StreamingBodyEncoder.write

    def tracking_write(self, data):
        original_write(self, data)
        largest_part["size"] = max(largest_part["size"], sum(len(part) for part in self.parts))

    monkeypatch.setattr(history_cache._StreamingBodyEncoder, "write", tracking_write)
    session = _StreamSession(result_factory=lambda: _Result(rows))
    body, _headers = asyncio.run(history_cache.render_direct_history(
        session, ParkingSnapshot.observed_at >= NOW, accept_encoding=accept_encoding,
    ))
    identity = _legacy_body(rows)
    assert _decompress(body, accept_encoding) == identity
    # 보유한 조각은 압축본뿐이다. 비압축 본문 크기의 일부에 그친다.
    assert largest_part["size"] < len(identity) // 4


def test_direct_history_closes_cursor_when_fetch_fails() -> None:
    session = _StreamSession(result_factory=lambda: _Result(_rows(history_cache.HISTORY_FETCH_ROWS + 1), fail_after=1))
    with pytest.raises(RuntimeError, match="fetch failed"):
        asyncio.run(history_cache.render_direct_history(session, ParkingSnapshot.observed_at >= NOW))
    assert session.results[0].closed


def test_cancelled_direct_history_waits_for_running_encode_thread_and_closes_cursor(monkeypatch) -> None:
    rows = _rows(history_cache.HISTORY_FETCH_ROWS + 1)
    encode_started, release_encode = threading.Event(), threading.Event()
    finished_threads = []
    original = history_cache._encode_history_batch

    def blocking_encode(batch):
        encode_started.set()
        release_encode.wait(5)
        finished_threads.append(threading.get_ident())
        return original(batch)

    class StalledResult(_Result):
        async def partitions(self, size):
            yield self.rows[:size]
            await asyncio.Event().wait()  # 다음 묶음 수신이 멈춘다.
            yield self.rows[size:]

    monkeypatch.setattr(history_cache, "_encode_history_batch", blocking_encode)
    session = _StreamSession(result_factory=lambda: StalledResult(rows))

    async def check():
        task = asyncio.create_task(history_cache.render_direct_history(
            session, ParkingSnapshot.observed_at >= NOW, accept_encoding="gzip",
        ))
        while not encode_started.is_set():
            await asyncio.sleep(0.01)
        task.cancel()
        for _ in range(20):
            await asyncio.sleep(0.01)
        # 변환 thread가 끝나기 전에는 반환하지 않는다(잠금·전송 슬롯을 계속 쥔다).
        assert not task.done() and finished_threads == []
        release_encode.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(finished_threads) == 1 and session.results[0].closed

    asyncio.run(check())


def _history_route(monkeypatch, test_settings, cache):
    from app import main as main_module

    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    monkeypatch.setattr(main_module, "create_engine_and_session_factory", lambda _url: (fake_engine, object()))
    monkeypatch.setattr(main_module, "ParkingHistoryReadCache", lambda _factory: cache)
    app = main_module.create_app(test_settings.model_copy(update={"seed_sample_data": False}))
    included = next(route for route in app.routes if hasattr(route, "original_router"))
    return next(route for route in included.original_router.routes if route.path == "/parking/history")


async def _send(response) -> bytes:
    sent = []

    async def send(message):
        sent.append(message)

    await response({"type": "http", "method": "GET", "asgi": {"spec_version": "2.4"}}, None, send)
    return b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")


class _Request:
    def __init__(self, *, disconnected: bool = False):
        self.headers = {}
        self.disconnected = disconnected
        self.disconnect_checks = 0

    async def is_disconnected(self) -> bool:
        self.disconnect_checks += 1
        return self.disconnected


class _MissCache(history_cache.ParkingHistoryReadCache):
    """직접 조회 차례·깨움은 실제 구현을 쓰고, 캐시를 쓸 수 있는지만 시험이 정한다."""

    def __init__(self):
        super().__init__(None)
        self.validated_at_utc = NOW

    def usable_snapshot(self, _cutoff):
        return self.snapshot

    def publish(self, snapshot) -> None:
        # refresh_once 끝의 게시·재확인과 같은 신호를 낸다.
        self.snapshot = snapshot
        self._notify_state_changed()

    async def response_body(self, snapshot, cutoff, airport_code, parking_lot_id, accept_encoding):
        body = snapshot.render(cutoff, airport_code, parking_lot_id)
        return history_cache.encode_response(body, accept_encoding)


def _published_snapshot():
    return history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=60), 9, [
        SimpleNamespace(observed_at=datetime.now(UTC) - timedelta(hours=1), parking_lot_id=7, code="GMP",
                        occupied_spaces=1, total_spaces=2, available_spaces=1),
    ])


async def _spin(times: int = 20) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


@pytest.mark.parametrize(("parking_lot_id", "days", "heavy"), [
    (None, 30, True), (None, 8, True), (None, 7, False), (None, 3, False), (5, 30, False), (5, 1, False),
])
def test_only_long_airport_or_all_scope_is_serialized(parking_lot_id, days, heavy) -> None:
    assert history_cache.direct_fallback_is_heavy(parking_lot_id, days) is heavy


def test_concurrent_cache_misses_build_direct_history_one_at_a_time(monkeypatch, test_settings) -> None:
    cache = _MissCache()
    route = _history_route(monkeypatch, test_settings, cache)
    rows = _rows(3)

    async def check():
        gate = asyncio.Event()
        active = {"now": 0, "max": 0}

        class TrackedResult(_Result):
            async def partitions(self, size):
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
                try:
                    await gate.wait()
                    async for batch in super().partitions(size):
                        yield batch
                finally:
                    active["now"] -= 1

        sessions = [_StreamSession(result_factory=lambda: TrackedResult(rows)) for _ in range(2)]
        tasks = [asyncio.create_task(route.endpoint(_Request(), None, None, 30, None, None, s))
                 for s in sessions]
        await _spin()
        # 첫 요청이 DB 결과를 받는 동안 두 번째 요청은 직접 조회 차례를 기다린다.
        assert active["now"] == 1
        assert sum(len(s.statements) for s in sessions) == 1
        assert cache.direct_fallback_lock.locked()
        gate.set()
        responses = await asyncio.wait_for(asyncio.gather(*tasks), 5)
        bodies = [await _send(response) for response in responses]
        assert active["max"] == 1
        assert all(body == _legacy_body(rows) for body in bodies)
        assert [r.headers["x-parking-history-cache"] for r in responses] == ["miss", "miss"]
        assert not cache.direct_fallback_lock.locked() and cache.delivery_semaphore._value == 2

    asyncio.run(check())


@pytest.mark.parametrize(("airport_code", "parking_lot_id", "days"), [
    (None, 5, 1), (None, 5, 30), (None, None, 3), ("GMP", None, 7),
])
def test_scoped_or_short_cache_miss_is_not_queued_behind_long_fallback(
    monkeypatch, test_settings, airport_code, parking_lot_id, days,
) -> None:
    # 리뷰 재현(HOL): 주차장 하나·짧은 기간 요청이 30일 전체 직접 조회 뒤에 줄 서지 않는다.
    cache = _MissCache()
    route = _history_route(monkeypatch, test_settings, cache)

    async def check():
        gate = asyncio.Event()
        full = _StreamSession(result_factory=lambda: _Result(_rows(3), gate=gate))
        small = _StreamSession(result_factory=lambda: _Result(_rows(1)))
        full_task = asyncio.create_task(route.endpoint(_Request(), None, None, 30, None, None, full))
        await _spin()
        assert cache.direct_fallback_lock.locked()
        small_request = _Request()
        small_response = await asyncio.wait_for(
            route.endpoint(small_request, airport_code, parking_lot_id, days, None, None, small), 2,
        )
        assert small_response.headers["x-parking-history-cache"] == "miss" and len(small.statements) == 1
        assert small_request.disconnect_checks == 0 and not full_task.done()
        await _send(small_response)
        gate.set()
        await _send(await full_task)
        assert cache.delivery_semaphore._value == 2 and not cache.direct_fallback_lock.locked()

    asyncio.run(check())


def test_waiting_miss_serves_cache_as_soon_as_it_is_published(monkeypatch, test_settings) -> None:
    cache = _MissCache()
    route = _history_route(monkeypatch, test_settings, cache)

    async def check():
        gate = asyncio.Event()
        first_session = _StreamSession(result_factory=lambda: _Result(_rows(2), gate=gate))
        second_session = _StreamSession()
        first = asyncio.create_task(route.endpoint(_Request(), None, None, 30, None, None, first_session))
        await _spin()
        second = asyncio.create_task(route.endpoint(_Request(), None, None, 30, None, None, second_session))
        await _spin()
        assert not second.done()
        cache.publish(_published_snapshot())
        # 앞선 직접 조회가 끝나기를 기다리지 않고 새 캐시로 바로 응답한다.
        second_response = await asyncio.wait_for(second, 0.5)
        assert not first.done()
        assert second_response.headers["x-parking-history-cache"] == "hit"
        assert second_session.statements == []
        assert json.loads(await _send(second_response))["items"][0]["parking_lot_id"] == 7
        gate.set()
        first_response = await first
        assert first_response.headers["x-parking-history-cache"] == "miss"
        await _send(first_response)
        assert cache.delivery_semaphore._value == 2 and not cache.direct_fallback_lock.locked()

    asyncio.run(check())


def test_waiter_that_disconnected_skips_the_direct_fallback(monkeypatch, test_settings) -> None:
    cache = _MissCache()
    route = _history_route(monkeypatch, test_settings, cache)

    async def check():
        gate = asyncio.Event()
        first = asyncio.create_task(route.endpoint(
            _Request(), None, None, 30, None, None, _StreamSession(result_factory=lambda: _Result(_rows(1), gate=gate)),
        ))
        await _spin()
        gone, gone_session = _Request(disconnected=True), _StreamSession()
        waiting = asyncio.create_task(route.endpoint(gone, None, None, 30, None, None, gone_session))
        await _spin()
        assert gone.disconnect_checks == 0
        gate.set()
        await _send(await first)
        response = await asyncio.wait_for(waiting, 2)
        # 차례를 얻은 뒤 연결이 끊긴 것을 보고 DB 조회 없이 끝낸다.
        assert response.status_code == 499 and gone.disconnect_checks == 1 and gone_session.statements == []
        assert cache.delivery_semaphore._value == 2 and not cache.direct_fallback_lock.locked()

    asyncio.run(check())


def test_cancelled_waiting_miss_releases_delivery_slot(monkeypatch, test_settings) -> None:
    cache = _MissCache()
    route = _history_route(monkeypatch, test_settings, cache)

    async def check():
        gate = asyncio.Event()
        first = asyncio.create_task(route.endpoint(
            _Request(), None, None, 30, None, None,
            _StreamSession(result_factory=lambda: _Result(_rows(1), gate=gate)),
        ))
        await _spin(10)
        waiting_session = _StreamSession()
        waiting = asyncio.create_task(route.endpoint(_Request(), None, None, 30, None, None, waiting_session))
        await _spin(10)
        assert cache.delivery_semaphore._value == 0
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert cache.delivery_semaphore._value == 1 and waiting_session.statements == []
        gate.set()
        await _send(await first)
        assert cache.delivery_semaphore._value == 2 and not cache.direct_fallback_lock.locked()

    asyncio.run(check())


def test_refresh_once_wakes_fallback_waiters(monkeypatch) -> None:
    cache = history_cache.ParkingHistoryReadCache(None)

    async def fingerprint():
        return (10, 100, 0, 0)

    async def load(_factory):
        return history_cache.ParkingHistorySnapshot.from_rows(NOW - timedelta(days=30), 10, [], 0, NOW)

    monkeypatch.setattr(cache, "source_fingerprint", fingerprint)
    monkeypatch.setattr(history_cache, "load_snapshot", load)
    monkeypatch.setattr(history_cache, "now_utc", lambda: NOW)
    for _ in range(2):  # 게시(전체 재생성)와 무변경 재확인 모두 깨운다.
        before = cache._state_changed
        asyncio.run(cache.refresh_once())
        assert before.is_set() and cache._state_changed is not before and not cache._state_changed.is_set()


# --- 실제 PostgreSQL: 직접 조회와 캐시 본문이 같은 bytes -------------------


def test_postgres_direct_history_matches_cache_bytes(client) -> None:
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 통합 검증에서만 실행")
    observed_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=30)

    async def seed() -> int:
        async with client.app.state.session_factory() as session:
            airport = await session.scalar(select(Airport).where(Airport.code == "GMP"))
            lot = await session.scalar(select(ParkingLot).where(ParkingLot.airport_id == airport.id))
            session.add_all([
                ParkingSnapshot(
                    airport_id=airport.id, parking_lot_id=lot.id, source="migration_rebuild_cost",
                    observed_at=observed_at, collected_at=observed_at + timedelta(minutes=2),
                    occupied_spaces=90, total_spaces=100, available_spaces=10,
                ),
                ParkingSnapshot(
                    airport_id=airport.id, parking_lot_id=lot.id, source="kac_rebuild_cost",
                    observed_at=observed_at, collected_at=observed_at + timedelta(minutes=1),
                    occupied_spaces=41, total_spaces=100, available_spaces=59,
                ),
            ])
            await session.commit()
            return lot.id

    lot_id = asyncio.run(seed())
    response = client.get("/v1/parking/history", params={"days": 2}, headers={"Accept-Encoding": "identity"})
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    items = json.loads(response.content)["items"]
    # 표본 데이터에도 같은 값(예: 90)이 시각에 따라 생길 수 있으므로 넣은 주차장·관측 시각의 행만 본다.
    seeded = [
        item for item in items
        if item["parking_lot_id"] == lot_id
        and datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00")) == observed_at
    ]
    assert [item["occupied_spaces"] for item in seeded] == [41]
    cache = history_cache.ParkingHistoryReadCache(client.app.state.session_factory)
    asyncio.run(cache.refresh_once())
    first_observed = datetime.fromisoformat(items[0]["observed_at"].replace("Z", "+00:00"))
    assert cache.snapshot.render(first_observed, None, None) == response.content
