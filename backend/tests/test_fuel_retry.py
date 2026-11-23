"""유가 수집 실패의 재시도(FUEL-RETRY-20261123).

운영(odroid, 2026-11-11~23) 유가 정기 run 36건 중 15건이 실패했다. 실패한 시도를 같은 run 안의 Dagster
step 재시도나 관리자 "재시도"로 다시 할 때, 서비스는 (1) 직전 시도가 실패였을 때만 정기 예약을 앞당기고
(2) 정기 예약 자체(다음 8시간 tick)는 옮기지 않아야 한다. 고속도로 저장은 상태 행 갱신을 commit 직전에 둬서
places revision 행 잠금으로 다른 수집기의 상태 claim을 막지 않아야 한다.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app.core.time_utils import now_utc, serialize_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import HighwayIncidentSnapshot, TransportCollectionState
from app.services.transport_collection import (
    FUEL_NEXT_DUE_START_SLACK,
    INCIDENT_SOURCE,
    OPINET_SOURCE,
    TRAFFIC_SOURCE,
    TransportCollectionService,
    _fuel_last_attempt_failed,
)
from test_transport_collection import FakeTransportProvider, build_settings


def _run_twice(tmp_path: Path, provider, *, first_fails: bool, retry: bool, second_fails: bool = False):
    settings = build_settings(tmp_path)
    real_collect = provider.collect_fuel
    calls = {"count": 0}

    async def collect_fuel():
        calls["count"] += 1
        if (calls["count"] == 1 and first_fails) or (calls["count"] == 2 and second_fails):
            raise RuntimeError("Opinet browser resource policy failed command=Fetch.failRequest cause=Error")
        return await real_collect()

    provider.collect_fuel = collect_fuel

    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with factory() as session:
            first = await service.collect(session, trigger="test", scope="fuel")
            before = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE).execution_options(populate_existing=True))
            snapshot = {name: getattr(before, name) for name in (
                "last_started_at", "last_success_at", "next_due_at", "last_error")}
            second = await service.collect(session, trigger="test", scope="fuel", retry_failed_fuel=retry)
            after = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE).execution_options(populate_existing=True))
        await service.close()
        await engine.dispose()
        return first, snapshot, second, after

    result = asyncio.run(run())
    return (*result, calls["count"])


def test_retry_after_a_failed_attempt_runs_without_moving_the_regular_reservation(tmp_path: Path) -> None:
    first, before, second, after, calls = _run_twice(
        tmp_path, FakeTransportProvider(), first_fails=True, retry=True)
    assert first["status"] == "failed"
    assert before["last_error"] is not None
    assert second["status"] == "success"
    assert calls == 2
    assert after.last_error is None
    # 재시도는 실패한 시도의 예약(시작 + 주기 - 여유 = 다음 정기 tick)을 그대로 둔다.
    assert serialize_utc(after.next_due_at) == serialize_utc(before["next_due_at"])
    assert serialize_utc(after.last_started_at) > serialize_utc(before["last_started_at"])
    assert second["fuel_ready"] is True


def test_failed_retry_still_keeps_the_regular_reservation(tmp_path: Path) -> None:
    first, before, second, after, calls = _run_twice(
        tmp_path, FakeTransportProvider(), first_fails=True, retry=True, second_fails=True)
    assert (first["status"], second["status"], calls) == ("failed", "failed", 2)
    assert serialize_utc(after.next_due_at) == serialize_utc(before["next_due_at"])
    assert after.last_error is not None


def test_retry_does_not_bypass_the_reservation_after_a_success(tmp_path: Path) -> None:
    first, before, second, after, calls = _run_twice(
        tmp_path, FakeTransportProvider(), first_fails=False, retry=True)
    assert first["status"] == "success"
    assert second["status"] == "skipped"
    assert calls == 1  # 성공 뒤의 재시도 요청은 오피넷을 다시 부르지 않는다.
    assert serialize_utc(after.next_due_at) == serialize_utc(before["next_due_at"])


def test_regular_run_does_not_bypass_the_reservation_after_a_failure(tmp_path: Path) -> None:
    provider = FakeTransportProvider()
    first, before, second, after, calls = _run_twice(tmp_path, provider, first_fails=True, retry=False)
    assert (first["status"], second["status"], calls) == ("failed", "skipped", 1)
    due = serialize_utc(after.next_due_at)
    assert due == serialize_utc(before["last_started_at"]) + provider.next_fuel_interval() - FUEL_NEXT_DUE_START_SLACK


def test_last_attempt_failed_needs_an_error_newer_than_the_last_success() -> None:
    now = now_utc()
    state = TransportCollectionState(source=OPINET_SOURCE, last_started_at=now, last_success_at=now - timedelta(hours=8),
                                     last_error="x")
    assert _fuel_last_attempt_failed(state)
    assert not _fuel_last_attempt_failed(None)
    assert not _fuel_last_attempt_failed(TransportCollectionState(source=OPINET_SOURCE, last_started_at=now))
    # 성공 뒤 같은 시작의 오류(통계 등)는 "마지막 시도 실패"가 아니다.
    assert not _fuel_last_attempt_failed(TransportCollectionState(
        source=OPINET_SOURCE, last_started_at=now, last_success_at=now + timedelta(minutes=30), last_error="x"))


def test_highway_marks_source_success_only_after_storing(tmp_path: Path) -> None:
    """상태 행 UPDATE는 places revision 행(문장 trigger)을 commit까지 잠근다. 2026-11-23 odroid 표본에서 소통
    저장 transaction이 그 잠금을 175초 이상 쥐어 다른 수집기의 상태 claim이 lock_timeout(5초)으로 실패했다.
    성공 표시는 저장·통계 갱신을 모두 마친 뒤여야 한다."""
    settings = build_settings(tmp_path)
    provider = FakeTransportProvider()
    order: list[str] = []

    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        store_traffic, store_incidents = service._store_traffic, service._store_incidents
        refresh, mark = service._refresh_recent_traffic_statistics, service._mark_source_success

        async def traffic(*args, **kwargs):
            order.append("store:traffic")
            return await store_traffic(*args, **kwargs)

        async def incidents(*args, **kwargs):
            order.append("store:incident")
            return await store_incidents(*args, **kwargs)

        async def statistics(*args, **kwargs):
            order.append("statistics")
            return await refresh(*args, **kwargs)

        async def marked(session, source, completed_at, **kwargs):
            order.append(f"mark:{source}")
            return await mark(session, source, completed_at, **kwargs)

        service._store_traffic, service._store_incidents = traffic, incidents
        service._refresh_recent_traffic_statistics, service._mark_source_success = statistics, marked
        async with factory() as session:
            result = await service.collect(session, trigger="test", scope="highway")
            incident_state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == INCIDENT_SOURCE))
            collected = await session.scalar(select(func.max(HighwayIncidentSnapshot.collected_at)))
            traffic_state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == TRAFFIC_SOURCE))
        await service.close()
        await engine.dispose()
        return result, incident_state, collected, traffic_state

    result, incident_state, collected, traffic_state = asyncio.run(run())
    assert result["status"] == "success"
    assert order == ["store:traffic", "statistics", f"mark:{TRAFFIC_SOURCE}",
                     "store:incident", f"mark:{INCIDENT_SOURCE}"]
    # 돌발 상태의 성공 시각은 저장 단계가 맞춘 관측 collected_at이다(ADR-013 현재 집합 경계).
    assert serialize_utc(incident_state.last_success_at) == serialize_utc(collected)
    assert incident_state.last_error is None and traffic_state.last_error is None
    assert traffic_state.next_due_at is not None


def test_highway_store_failure_still_records_the_source_failure(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, FakeTransportProvider())
        service._store_traffic = AsyncMock(side_effect=RuntimeError("database flush failed"))
        async with factory() as session:
            await service.collect(session, trigger="test", scope="highway")
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == TRAFFIC_SOURCE))
        await service.close()
        await engine.dispose()
        return state

    state = asyncio.run(run())
    assert state.last_success_at is None
    assert state.last_error and "database flush failed" in state.last_error
