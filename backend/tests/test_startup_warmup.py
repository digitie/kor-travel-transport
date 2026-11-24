"""API 기동 warmup의 순서·상한·관측(감사 RT-06·RT-13·G2-09·G3-10).

풀 채우기 → 철도·여객선 지문 → 주차 이력 캐시 시작. 어느 단계의 실패도 이력 캐시 시작과 서빙을 막지 않는다.
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.services import startup_warmup


class FakeConnection:
    async def execute(self, _statement):
        return None


def _engine(size=5, *, fail=0, delay=0.0, events=None):
    state = {"opened": 0, "failures": fail, "active": 0, "max_active": 0}

    @asynccontextmanager
    async def connect():
        if events is not None:
            events.append("connect")
        if delay:
            await asyncio.sleep(delay)
        if state["failures"]:
            state["failures"] -= 1
            raise OSError("connection refused")
        state["opened"] += 1
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        try:
            yield FakeConnection()
        finally:
            state["active"] -= 1

    return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), pool=SimpleNamespace(size=lambda: size),
                           connect=connect, state=state)


def test_prefill_holds_pool_size_connections_at_once():
    # 하나씩 열고 돌려주면 같은 연결을 재사용해 풀에 하나만 남는다. 모두 동시에 쥔 뒤 함께 돌려줘야 한다(RT-13).
    engine = _engine(5)
    assert asyncio.run(startup_warmup.prefill_pool(engine)) == 5
    assert engine.state["max_active"] == 5 and engine.state["active"] == 0


def test_prefill_opens_pool_size_connections_and_ignores_failures():
    engine = _engine(5, fail=2)
    assert asyncio.run(startup_warmup.prefill_pool(engine)) == 3
    assert engine.state["opened"] == 3 and engine.state["max_active"] == 3 and engine.state["active"] == 0


def test_prefill_fills_a_real_postgresql_pool(test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 시험 DB에서만 실제 풀을 본다")

    async def scenario():
        # 시험 DB 모드의 앱 엔진은 NullPool이라(풀 채우기는 no-op) 운영과 같은 크기의 QueuePool을 직접 만든다.
        engine = create_async_engine(test_settings.database_url, pool_size=5, max_overflow=5, pool_pre_ping=True)
        try:
            opened = await startup_warmup.prefill_pool(engine)
            return opened, engine.pool.size(), engine.pool.checkedin(), engine.pool.checkedout()
        finally:
            await engine.dispose()

    opened, size, idle, busy = asyncio.run(scenario())
    assert (opened, size, idle, busy) == (5, 5, 5, 0)


def test_prefill_is_a_no_op_for_null_pool_engines(test_settings):
    from sqlalchemy.pool import NullPool

    async def scenario():
        engine = create_async_engine(test_settings.database_url, poolclass=NullPool)
        try:
            return await startup_warmup.prefill_pool(engine)
        finally:
            await engine.dispose()

    assert asyncio.run(scenario()) == 0


def test_prefill_is_bounded_and_skips_pools_without_a_size():
    slow = _engine(2, delay=1)
    assert asyncio.run(startup_warmup.prefill_pool(slow, timeout_seconds=0.05)) == 0
    # 일부만 늦으면 이미 연 연결은 상한에서 돌려주고 그 수를 낸다.
    partial = _engine(3)
    original = partial.connect

    @asynccontextmanager
    async def one_hangs():
        if partial.state["opened"] >= 2:
            await asyncio.sleep(60)
        async with original() as connection:
            yield connection

    partial.connect = one_hangs
    assert asyncio.run(startup_warmup.prefill_pool(partial, timeout_seconds=0.05)) == 2
    assert partial.state["active"] == 0
    no_pool = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), pool=SimpleNamespace())
    assert asyncio.run(startup_warmup.prefill_pool(no_pool)) == 0

    async def sqlite():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            return await startup_warmup.prefill_pool(engine)
        finally:
            await engine.dispose()

    assert asyncio.run(sqlite()) == 0


def test_history_cache_starts_only_after_pool_and_reference_warmup(caplog):
    events = []
    engine = _engine(2, events=events)

    async def warm_references():
        events.append("references")
        return [{"kind": "rail-stations-v1", "status": "warmed", "duration_ms": 5},
                {"kind": "ferry-ports-v1", "status": "source_unavailable", "duration_ms": 1}]

    with caplog.at_level(logging.WARNING, logger="app.services.startup_warmup"):
        summary = asyncio.run(startup_warmup.run_startup_warmup(
            engine, warm_references=warm_references, start_history_cache=lambda: events.append("history"),
        ))
    assert events == ["connect", "connect", "references", "history"]
    assert summary["status"] == "finished" and summary["pool_prefilled"] == 2
    logged = [json.loads(record.getMessage()) for record in caplog.records
              if record.getMessage().startswith('{"event": "startup_warmup"')]
    assert len(logged) == 1  # 완료 때 한 줄
    assert [row["kind"] for row in logged[0]["kinds"]] == ["rail-stations-v1", "ferry-ports-v1"]
    assert logged[0]["history_cache_started"] is True and logged[0]["duration_ms"] >= 0


def test_history_cache_starts_at_the_deadline_even_if_warmup_hangs():
    started = []

    async def hang():
        await asyncio.sleep(60)

    summary = asyncio.run(startup_warmup.run_startup_warmup(
        _engine(1), warm_references=hang, start_history_cache=lambda: started.append(True), deadline_seconds=0.05,
    ))
    assert summary["status"] == "deadline" and started == [True]


def test_warmup_failure_still_starts_history_cache():
    started = []

    async def broken():
        raise RuntimeError("fingerprint failed")

    summary = asyncio.run(startup_warmup.run_startup_warmup(
        _engine(1), warm_references=broken, start_history_cache=lambda: started.append(True),
    ))
    assert summary["status"] == "failed" and summary["error_type"] == "RuntimeError" and started == [True]


def test_shutdown_cancellation_does_not_start_history_cache():
    started = []

    async def scenario():
        entered = asyncio.Event()

        async def slow():
            entered.set()
            await asyncio.sleep(60)

        task = asyncio.create_task(startup_warmup.run_startup_warmup(
            _engine(1), warm_references=slow, start_history_cache=lambda: started.append(True),
        ))
        await entered.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return True
        return False

    assert asyncio.run(scenario()) is True
    assert started == []
