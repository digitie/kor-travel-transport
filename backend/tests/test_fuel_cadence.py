"""유가 성공 tick 여유와 실패/기동 예약을 실제 진입·대기 경계에서 구분한다."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import create_engine_and_session_factory, init_database
from app.models import TransportCollectionState
from app.services import transport_collection
from app.services.transport_collection import OPINET_SOURCE, TransportCollectionService
from test_transport_collection import FakeTransportProvider, build_settings
from unittest.mock import AsyncMock


@pytest.mark.parametrize("status,skip_reason,next_delay,expected", [
    ("failed", None, 1, 300), ("partial_success", None, 1, 300), ("failed", None, 7200, 7200),
    ("success", None, 1, 1), ("skipped", "collector_busy", 1, 300),
    ("skipped", "collector_busy", 7200, 7200), ("skipped", None, 1, 1),
])
def test_pending_store_failure_has_scheduler_backoff(tmp_path, monkeypatch, status, skip_reason, next_delay, expected):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from app.main import _run_transport_scheduler

    @asynccontextmanager
    async def session_factory():
        yield SimpleNamespace(rollback=AsyncMock())

    settings = build_settings(tmp_path)
    service = SimpleNamespace(
        collect=AsyncMock(return_value={
            "collection_run_id": 1, "status": status, "client_mode": "live",
            "skip_reason": skip_reason,
            "traffic_snapshot_count": 0, "incident_snapshot_count": 0,
            "fuel_station_count": 0, "fuel_price_count": 0,
        }),
        next_collection_delay=AsyncMock(return_value=next_delay),
    )
    app = SimpleNamespace(state=SimpleNamespace(
        session_factory=session_factory, settings=settings, transport_collection_service=service))
    sleep = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr("app.main.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run_transport_scheduler(app, "fuel"))
    sleep.assert_awaited_once_with(expected)


@pytest.mark.parametrize("mode", ["in_process", "dagster"])
@pytest.mark.parametrize("reservation", ["success", "replayed_success", "failure", "claim", "legacy_success"])
def test_fuel_entry_and_sleep_share_the_effective_due(tmp_path, monkeypatch, mode, reservation):
    start = datetime(2026, 10, 23, tzinfo=timezone.utc)
    clock = {"now": start + timedelta(hours=7, minutes=50)}
    monkeypatch.setattr(transport_collection, "now_utc", lambda: clock["now"])
    settings = build_settings(tmp_path)
    settings.scheduler_mode = mode
    provider = FakeTransportProvider()
    provider.next_fuel_interval = lambda: timedelta(hours=8)
    success = start + timedelta(hours=1)
    due = start + timedelta(hours=7, minutes=45)
    error = None
    expected = start + timedelta(hours=8) if mode == "in_process" else due
    if reservation == "replayed_success":
        success = start - timedelta(hours=1)  # 검증한 원천 수집 시각은 이번 재생 시작보다 이를 수 있다.
    elif reservation == "failure":
        success = start - timedelta(days=1)
        due = start + timedelta(hours=10)  # 02시 실패 + 8시간
        error = "TimeoutError"
        clock["now"] = start + timedelta(hours=2)
        expected = due
    elif reservation == "claim":
        success = start - timedelta(days=1)
        due = start + timedelta(hours=12)
        expected = due
    elif reservation == "legacy_success":
        due = success + timedelta(hours=8)
        expected = due

    async def exercise():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        try:
            async with factory() as session:
                session.add(TransportCollectionState(
                    source=OPINET_SOURCE, last_started_at=start, last_success_at=success,
                    next_due_at=due, last_error=error, updated_at=start,
                ))
                await session.commit()
                # 재기동으로 sleep을 거치지 않고 수집부터 시작해도 같은 경계를 지킨다.
                assert await service._fuel_is_due(session) is (clock["now"] >= expected)
                assert await service.next_collection_delay(session, "fuel") == max(
                    1.0, (expected - clock["now"]).total_seconds())
                clock["now"] = expected - timedelta(microseconds=1)
                assert not await service._fuel_is_due(session)
                clock["now"] = expected
                assert await service._fuel_is_due(session)
        finally:
            await service.close()
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["dagster", "in_process"])
def test_failure_allows_earlier_next_dagster_tick_but_in_process_waits_full_interval(tmp_path, monkeypatch, mode):
    start = datetime(2026, 10, 24, 8, 2, tzinfo=timezone.utc)
    clock = {"now": start}
    monkeypatch.setattr(transport_collection, "now_utc", lambda: clock["now"])
    provider = FakeTransportProvider()
    provider.next_fuel_interval = lambda: timedelta(hours=8)
    provider.collect_fuel = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    settings = build_settings(tmp_path)
    settings.scheduler_mode = mode
    async def exercise():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        try:
            service = TransportCollectionService(settings, provider)
            async with factory() as session:
                assert (await service.collect(session, scope="fuel"))["status"] == "failed"
                clock["now"] = start + timedelta(hours=8, minutes=-1)
                assert await service._fuel_is_due(session) is (mode == "dagster")
                clock["now"] = start + timedelta(hours=8)
                assert await service._fuel_is_due(session)
        finally:
            await engine.dispose()
    asyncio.run(exercise())
