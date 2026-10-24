"""브라우저 재호출 없이 완료 스냅샷 저장을 재개하는 경계를 검증한다."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock
from dataclasses import replace

import pytest
from opinet import OpinetServerError
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.core.time_utils import now_utc, serialize_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import CollectionRun, FuelLatestPrice, FuelPriceSnapshot, FuelStation, TransportCollectionState
from app.services.transport_collection import OPINET_SOURCE, TransportCollectionService, _is_transient_database_error
from test_transport_collection import FakeTransportProvider, build_settings


def test_failed_store_resumes_without_provider_requests_or_extending_reservation(tmp_path):
    async def exercise():
        settings = build_settings(tmp_path)
        provider = FakeTransportProvider()
        snapshot = await provider.collect_fuel()
        provider.collect_fuel = AsyncMock(return_value=snapshot)
        provider.pending_fuel_snapshot = AsyncMock(side_effect=[None, snapshot])
        provider.acknowledge_fuel_snapshot = Mock()
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        try:
            service = TransportCollectionService(settings, provider)
            store = service._store_fuel_snapshot
            service._store_fuel_snapshot = AsyncMock(side_effect=RuntimeError("storage unavailable"))
            async with factory() as session:
                assert (await service.collect(session, scope="fuel"))["status"] == "failed"
                state = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == OPINET_SOURCE))
                due = serialize_utc(state.next_due_at)
                assert due > now_utc()
                assert await session.scalar(select(FuelLatestPrice.fuel_station_id).limit(1)) is None
                provider.acknowledge_fuel_snapshot.assert_not_called()
                service._store_fuel_snapshot = store
                result = await service.collect(session, scope="fuel")
                assert result["status"] == "success"
                assert serialize_utc(state.next_due_at) == due
                assert serialize_utc(state.last_success_at) == serialize_utc(snapshot.collected_at)
                assert await session.scalar(select(FuelLatestPrice.fuel_station_id).limit(1)) is not None
            provider.collect_fuel.assert_awaited_once()
            provider.acknowledge_fuel_snapshot.assert_called_once_with(snapshot)
        finally:
            await engine.dispose()
    asyncio.run(exercise())


@pytest.mark.parametrize("source_status", ["fresh", "failed", "missing"])
@pytest.mark.parametrize("scope", ["fuel", "all"])
@pytest.mark.parametrize("busy_phase", ["pending", "collection"])
def test_active_checkpoint_owner_does_not_publish_false_source_failure(test_settings, tmp_path, source_status, scope, busy_phase):
    from opinet.experimental import OpinetBrowserCollector
    from opinet.experimental._browser_checkpoint import BrowserCheckpoint
    from app.services.transport_collection import fuel_read_model_freshness

    async def exercise():
        provider = FakeTransportProvider()
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        await init_database(engine)
        collector = OpinetBrowserCollector(checkpoint_path=tmp_path / "active.sqlite3")
        owner = (BrowserCheckpoint(collector.checkpoint_path, url=collector.url, query_level=collector.query_level,
                                   max_age=collector.checkpoint_max_age) if busy_phase == "pending" else None)
        def values(state):
            if state is None:
                return None
            return tuple(serialize_utc(getattr(state, name)) if getattr(state, name) else None for name in
                         ("last_started_at", "last_success_at", "next_due_at", "updated_at")) + (state.last_error,)
        try:
            async with factory() as session:
                if source_status != "missing":
                    assert (await TransportCollectionService(test_settings, provider).collect(session, scope="fuel"))["status"] == "success"
                    state = await session.scalar(select(TransportCollectionState).where(
                        TransportCollectionState.source == OPINET_SOURCE))
                    state.next_due_at = now_utc() + (timedelta(hours=4) if busy_phase == "pending" else -timedelta(seconds=1))
                    if source_status == "failed":
                        state.last_error = "previous storage failure"
                    await session.commit()
                state = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == OPINET_SOURCE))
                before = values(state)
                stale_before, _ = await fuel_read_model_freshness(session)
            async def acquire_after_pending_check():
                nonlocal owner
                result = await collector.pending_snapshot()
                assert result is None
                owner = BrowserCheckpoint(collector.checkpoint_path, url=collector.url, query_level=collector.query_level,
                                          max_age=collector.checkpoint_max_age)
                return result
            collector._collect_browser = AsyncMock(side_effect=AssertionError("must not open a competing browser"))
            provider.pending_fuel_snapshot = collector.pending_snapshot if busy_phase == "pending" else acquire_after_pending_check
            provider.collect_fuel = AsyncMock(side_effect=collector.collect_once)
            async with factory() as session:
                result = await TransportCollectionService(test_settings, provider).collect(session, scope=scope)
                assert result["status"] == ("skipped" if scope == "fuel" else "success")
                if scope == "fuel":
                    assert result["fuel_ready"] is (source_status == "fresh")
                    assert result["skip_reason"] == "collector_busy"
                state = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == OPINET_SOURCE))
                assert values(state) == before
                stale_after, _ = await fuel_read_model_freshness(session)
                assert stale_after is stale_before
            assert provider.collect_fuel.await_count == (1 if busy_phase == "collection" else 0)
            collector._collect_browser.assert_not_awaited()
        finally:
            if owner is not None:
                owner.close()
            await engine.dispose()
    asyncio.run(exercise())


@pytest.mark.parametrize("interruption", ["cancel", "error"])
def test_fresh_checkpoint_completion_survives_failure_before_result_return(test_settings, tmp_path, interruption):
    from opinet import OpinetCheckpointBusyError
    from opinet.experimental import OpinetBrowserCollector
    from app.services.transport_collection import fuel_read_model_freshness

    async def exercise():
        provider = FakeTransportProvider()
        original = await provider.collect_fuel()
        collector = OpinetBrowserCollector(checkpoint_path=tmp_path / "completed-before-return.sqlite3")
        completed, fail, error_lock, release = [asyncio.Event() for _ in range(4)]
        async def finish_before_cleanup(checkpoint):
            checkpoint.save_regions(list(original.regions))
            for region in original.regions:
                checkpoint.save(checkpoint.key("station", region), original.stations)
                checkpoint.save(checkpoint.key("lpg", region), ())
            checkpoint.complete()
            completed.set()
            await fail.wait()
            raise RuntimeError("browser cleanup failed")
        collector._collect_browser = finish_before_cleanup
        provider.collect_fuel = collector.collect_once
        provider.pending_fuel_snapshot = collector.pending_snapshot
        provider.acknowledge_fuel_snapshot = collector.acknowledge_snapshot
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        await init_database(engine)
        fresh = TransportCollectionService(test_settings, provider)
        original_lock = fresh._acquire_database_lock
        calls = 0
        async def gate(session, group):
            nonlocal calls
            calls += 1
            if calls == 2:
                error_lock.set()
                await release.wait()
            await original_lock(session, group)
        fresh._acquire_database_lock = gate
        async def collect(service):
            async with factory() as session:
                return await service.collect(session, scope="fuel")
        task = asyncio.create_task(collect(fresh))
        try:
            await asyncio.wait_for(completed.wait(), 15)
            with pytest.raises(OpinetCheckpointBusyError):
                await collector.pending_snapshot()
            if interruption == "cancel":
                task.cancel()
            else:
                fail.set()
            await asyncio.wait_for(error_lock.wait(), 15)
            assert (await collect(TransportCollectionService(test_settings, provider)))["status"] == "success"
            release.set()
            if interruption == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                assert (await task)["fuel_ready"] is True
            async with factory() as session:
                state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE))
                assert state.last_error is None
                assert (await fuel_read_model_freshness(session))[0] is False
                latest = await session.scalar(select(FuelLatestPrice))
                assert latest is not None
                assert float(latest.price) == 1700.5
        finally:
            fail.set()
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await engine.dispose()
    asyncio.run(exercise())


def test_busy_claim_rollback_preserves_a_competing_committed_snapshot(test_settings):
    from opinet import OpinetCheckpointBusyError

    async def exercise():
        provider = FakeTransportProvider()
        original = await provider.collect_fuel()
        pending = {"snapshot": None}
        committed = {}
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        await init_database(engine)
        async def read_pending():
            return pending["snapshot"]
        async def competing_success_then_busy():
            pending["snapshot"] = replace(original, collected_at=now_utc(), stations=(
                replace(original.stations[0], prices=(replace(original.stations[0].prices[0], price=1900.5),)),))
            async with factory() as session:
                assert (await TransportCollectionService(test_settings, provider).collect(session, scope="fuel"))["status"] == "success"
                state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE))
                committed.update({name: getattr(state, name) for name in
                                  ("last_started_at", "last_success_at", "next_due_at", "last_error", "updated_at")})
            raise OpinetCheckpointBusyError("another collector owns checkpoint")
        try:
            provider.pending_fuel_snapshot = read_pending
            provider.collect_fuel = competing_success_then_busy
            async with factory() as session:
                result = await TransportCollectionService(test_settings, provider).collect(session, scope="fuel")
                assert result["status"] == "skipped" and result["fuel_ready"] is True
                assert result["skip_reason"] == "collector_busy"
                state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE))
                assert {name: getattr(state, name) for name in committed} == committed
                assert float((await session.scalar(select(FuelLatestPrice))).price) == 1900.5
        finally:
            await engine.dispose()
    asyncio.run(exercise())


@pytest.mark.parametrize("code", ["57014", "55P03", "40001", "40P01", "23505"])
def test_server_timeout_retries_storage_only_by_sqlstate(code):
    class ServerError(Exception):
        sqlstate = code
    assert _is_transient_database_error(DBAPIError("INSERT", {}, ServerError())) is (code != "23505")


def test_empty_provider_result_is_failure_and_unhealthy_skip_stays_visible(tmp_path):
    async def exercise():
        settings = build_settings(tmp_path)
        provider = FakeTransportProvider()
        provider.collect_fuel = AsyncMock(return_value=None)
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        try:
            service = TransportCollectionService(settings, provider)
            async with factory() as session:
                assert (await service.collect(session, scope="fuel"))["status"] == "failed"
                result = await service.collect(session, scope="fuel")
                assert result["status"] == "skipped"
                assert result["fuel_ready"] is False
                assert "no browser snapshot" in result["errors"][0]
        finally:
            await engine.dispose()
    asyncio.run(exercise())


@pytest.mark.parametrize("interruption", ["delayed", "error", "cancel"])
def test_late_resume_cannot_regress_new_source_history_or_latest(test_settings, interruption):
    async def exercise():
        provider = FakeTransportProvider()
        original = await provider.collect_fuel()
        stamp = now_utc()
        old_price = replace(original.stations[0].prices[0], updated_at=stamp - timedelta(hours=8))
        old_station = replace(original.stations[0], name="old", prices=(old_price,))
        old = replace(original, collected_at=stamp - timedelta(hours=8), stations=(old_station,))
        new = replace(old, collected_at=stamp, stations=(replace(old_station, name="new",
            prices=(replace(old_price, price=1800.5),)),))
        pending = {"snapshot": old}
        async def read_pending():
            return pending["snapshot"]
        def acknowledge(snapshot):
            if pending["snapshot"] is snapshot:
                pending["snapshot"] = None
        provider.pending_fuel_snapshot = read_pending
        provider.acknowledge_fuel_snapshot = acknowledge
        provider.collect_fuel = AsyncMock(return_value=new)
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        await init_database(engine)
        a, b, c = [TransportCollectionService(test_settings, provider) for _ in range(3)]
        blocked, release = asyncio.Event(), asyncio.Event()
        original_lock = a._acquire_database_lock
        calls = 0
        async def gate(session, group):
            nonlocal calls
            calls += 1
            if calls == (3 if interruption == "error" else 2):
                blocked.set()
                await release.wait()
            await original_lock(session, group)
        a._acquire_database_lock = gate
        if interruption == "error":
            a._store_fuel_snapshot = AsyncMock(side_effect=RuntimeError("storage failed"))
        async def collect(service):
            async with factory() as session:
                return await service.collect(session, scope="fuel")
        try:
            async with factory() as session:
                session.add(TransportCollectionState(source=OPINET_SOURCE, last_started_at=stamp - timedelta(hours=9),
                    next_due_at=stamp - timedelta(hours=1), updated_at=stamp - timedelta(hours=9)))
                await session.commit()
            task = asyncio.create_task(collect(a))
            await asyncio.wait_for(blocked.wait(), timeout=15)
            assert (await collect(b))["status"] == "success"
            assert (await collect(c))["status"] == "success"
            if interruption == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                release.set()
                result = await task
                assert result["status"] == "skipped" and result["fuel_ready"] is True
            async with factory() as session:
                state = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == OPINET_SOURCE))
                assert serialize_utc(state.last_success_at) == stamp
                assert state.last_error is None
                assert (await session.scalar(select(FuelStation))).name == "new"
                latest = await session.scalar(select(FuelLatestPrice))
                raw = await session.get(FuelPriceSnapshot, latest.snapshot_id)
                assert float(latest.price) == float(raw.price) == 1800.5
            provider.collect_fuel.assert_awaited_once()
        finally:
            release.set()
            await engine.dispose()
    asyncio.run(exercise())


@pytest.mark.parametrize("error", [OSError("checkpoint unreadable"),
                                 OpinetServerError("Opinet checkpoint is already in use")])
def test_pending_file_error_is_durable_and_keeps_existing_request_reservation(tmp_path, error):
    async def exercise():
        settings = build_settings(tmp_path)
        provider = FakeTransportProvider()
        provider.pending_fuel_snapshot = AsyncMock(side_effect=error)
        provider.collect_fuel = AsyncMock()
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        try:
            stamp = now_utc()
            due = stamp + timedelta(hours=4)
            async with factory() as session:
                session.add(TransportCollectionState(source=OPINET_SOURCE, last_started_at=stamp,
                    next_due_at=due, updated_at=stamp))
                await session.commit()
                result = await TransportCollectionService(settings, provider).collect(session, scope="fuel")
                assert result["status"] == "failed"
                state = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == OPINET_SOURCE))
                assert str(error) in state.last_error
                assert serialize_utc(state.next_due_at) == due
                assert (await session.get(CollectionRun, result["collection_run_id"])).status == "failed"
            provider.collect_fuel.assert_not_awaited()
        finally:
            await engine.dispose()
    asyncio.run(exercise())


def test_all_scope_cancel_before_fuel_step_preserves_newer_fuel_success(tmp_path):
    async def exercise():
        settings = build_settings(tmp_path)
        provider = FakeTransportProvider()
        current = await provider.collect_fuel()
        old = replace(current, collected_at=current.collected_at - timedelta(hours=8))
        provider.pending_fuel_snapshot = AsyncMock(side_effect=[None, old])
        entered = asyncio.Event()
        async def highway(**kwargs):
            entered.set()
            await asyncio.Event().wait()
        provider.collect_highway = highway
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        try:
            service = TransportCollectionService(settings, provider)
            async with factory() as session:
                assert (await service.collect(session, scope="fuel"))["status"] == "success"
            async def collect_all():
                async with factory() as session:
                    await TransportCollectionService(settings, provider).collect(session, scope="all")
            task = asyncio.create_task(collect_all())
            await asyncio.wait_for(entered.wait(), timeout=15)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            async with factory() as session:
                state = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == OPINET_SOURCE))
                assert serialize_utc(state.last_success_at) == serialize_utc(current.collected_at)
                assert state.last_error is None
        finally:
            await engine.dispose()
    asyncio.run(exercise())


@pytest.mark.parametrize("scheduler_mode", ["dagster", "in_process"])
def test_pending_store_winning_fresh_collection_keeps_next_tick(tmp_path, scheduler_mode):
    async def exercise():
        from app.services.transport_collection import FUEL_NEXT_DUE_START_SLACK

        settings = build_settings(tmp_path)
        settings.scheduler_mode = scheduler_mode
        provider = FakeTransportProvider()
        provider.next_fuel_interval = lambda: timedelta(hours=8)
        pending = {"snapshot": None}
        async def read_pending():
            return pending["snapshot"]
        original_collect = provider.collect_fuel
        async def collect_fuel():
            pending["snapshot"] = await original_collect()
            return pending["snapshot"]
        provider.pending_fuel_snapshot = read_pending
        provider.collect_fuel = AsyncMock(side_effect=collect_fuel)
        provider.acknowledge_fuel_snapshot = Mock()
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        fresh, resume = [TransportCollectionService(settings, provider) for _ in range(2)]
        entered, release = asyncio.Event(), asyncio.Event()
        original_lock = fresh._acquire_database_lock
        calls = 0
        async def gate(session, group):
            nonlocal calls
            calls += 1
            if calls == 2:
                entered.set()
                await release.wait()
            await original_lock(session, group)
        fresh._acquire_database_lock = gate
        async def collect(service):
            async with factory() as session:
                return await service.collect(session, scope="fuel")
        task = asyncio.create_task(collect(fresh))
        try:
            await asyncio.wait_for(entered.wait(), timeout=15)
            assert (await collect(resume))["status"] == "success"
            release.set()
            assert (await task)["status"] == "skipped"
            async with factory() as session:
                state = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == OPINET_SOURCE))
                start = serialize_utc(state.last_started_at)
                due = start + timedelta(hours=8) - FUEL_NEXT_DUE_START_SLACK
                assert serialize_utc(state.next_due_at) == due
                assert fresh._effective_fuel_due_at(state) == (
                    start + timedelta(hours=8) if scheduler_mode == "in_process" else due)
            provider.collect_fuel.assert_awaited_once()
        finally:
            release.set()
            if not task.done():
                await task
            await engine.dispose()
    asyncio.run(exercise())
