"""job 실행 상한의 주기 비례, `dagster/priority`, 고속도로 next_due의 tick 기준 (DAGSTER-RUNTIME-PRIORITY-20261124).

2026-11-23 수집 감사(Map `docs/reports/2026-11-23-collection-failure-audit.md` §2.5 P1 #9·#11, §2.6 #9, §4 #12·#13):
5분 job에 4시간 상한이 붙어 걸린 run 하나가 coalescing으로 최대 48 tick을 막고, 큐 우선순위가 없었고, 고속도로
next_due가 run 시작 기준이라 기동 지연의 흔들림으로 14일 498 run이 떠서 `skipped`로 끝났다.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.time_utils import now_utc, serialize_utc
from app.dagster import definitions as defs
from app.dagster.recovery import OWNER_LEASE, OwnerLease
from app.db.session import create_engine_and_session_factory, init_database
from app.models import TransportCollectionState
from app.services.transport_collection import (
    HIGHWAY_FETCH_TIMEOUT_SECONDS, HIGHWAY_TICK_SLACK, INCIDENT_SOURCE, TRAFFIC_SOURCE, TransportCollectionService,
)
from test_transport_collection import FakeTransportProvider, build_settings

FIVE_MINUTES = 300


def _tags(name: str) -> dict[str, str]:
    return defs.definitions.get_job_def(name).tags


@pytest.mark.parametrize("name", ["airport_collection_job", "highway_collection_job"])
def test_five_minute_jobs_have_a_runtime_proportional_to_their_period(name: str) -> None:
    runtime = int(_tags(name)["dagster/max_runtime"])
    # 걸린 run이 막는 tick은 몇 개뿐이어야 한다(옛 14,400초 = 48 tick).
    assert FIVE_MINUTES * 4 <= runtime <= FIVE_MINUTES * 6
    assert runtime == defs.job_max_runtime_seconds(name)


def test_highway_runtime_covers_its_worst_normal_path() -> None:
    """최초 조회·재확인(각 2x120초)과 claim 예약(2x120+900초)보다 상한이 길어야 정상 run을 끊지 않는다."""
    runtime = defs.job_max_runtime_seconds("highway_collection_job")
    assert runtime - defs.RUN_DEADLINE_MARGIN_SECONDS >= 2 * HIGHWAY_FETCH_TIMEOUT_SECONDS + 900


def test_long_period_jobs_keep_the_four_hour_cap() -> None:
    assert _tags("fuel_collection_job")["dagster/max_runtime"] == str(defs.MAX_RUNTIME_SECONDS)
    assert _tags("reference_export_prepare_job")["dagster/max_runtime"] == "180"


def test_priorities_put_realtime_first_and_never_push_transport_behind_other_tenants() -> None:
    priorities = {}
    for job in defs.definitions.jobs:
        if job.name.startswith("address_refresh"):
            continue
        priorities[job.name] = int(job.tags["dagster/priority"])
    top = max(priorities.values())
    assert {name for name, value in priorities.items() if value == top} == {
        "airport_collection_job", "highway_collection_job",
    }
    assert priorities["fuel_collection_job"] > priorities["bus_reference_collection_job"] == 0
    # 공용 큐에서 다른 테넌트(기본 0)보다 뒤로 미는 음수는 두지 않는다.
    assert min(priorities.values()) == 0


def test_infrastructure_retry_runs_get_the_same_runtime_as_the_job() -> None:
    """common 재시도 sensor는 새 run의 태그를 정책으로 덮는다(정책이 4시간이면 재시도 run만 다시 4시간이 된다)."""
    retry_sensors = [sensor for sensor in defs.definitions.sensors if sensor.name.startswith("transport_infra_retry_")]
    assert {sensor.name.removeprefix("transport_infra_retry_") for sensor in retry_sensors} == set(defs.IDEMPOTENT_JOBS)
    for name in defs.IDEMPOTENT_JOBS:
        assert defs._recovery_policy(name).max_runtime_seconds == defs.job_max_runtime_seconds(name)


class _Instance:
    def __init__(self, started: float, runtime: str | None) -> None:
        self.started, self.runtime = started, runtime

    def get_run_record_by_id(self, run_id):
        tags = {"dagster/max_runtime": self.runtime} if self.runtime else {}
        return SimpleNamespace(start_time=self.started, dagster_run=SimpleNamespace(tags=tags))


def _deadline(instance, max_runtime: int) -> float:
    token = OWNER_LEASE.set(OwnerLease("run-1", instance))
    try:
        return defs._run_deadline_seconds(max_runtime)
    finally:
        OWNER_LEASE.reset(token)


def test_deadline_counts_from_the_run_start_not_the_step_start() -> None:
    """공항 run은 수집 → 본문 준비 두 step이 한 상한을 나눈다. 두 번째 step은 run 시작부터 남은 시간만 쓴다."""
    remaining = _deadline(_Instance(time.time() - 1_500, "1800"), defs.MAX_RUNTIME_SECONDS)
    assert 1800 - 1500 - 60 - 5 <= remaining <= 1800 - 1500 - 60
    # 기동이 늦은 첫 step도 run monitoring보다 먼저 끝난다.
    assert _deadline(_Instance(time.time() - 120, "1200"), 1200) <= 1200 - 120 - 60
    # 이미 거의 다 쓴 run도 정리할 최소 시간은 준다.
    assert _deadline(_Instance(time.time() - 5_000, "1800"), 1800) == defs.MIN_RUN_DEADLINE_SECONDS


def test_deadline_falls_back_to_the_step_budget_without_run_metadata() -> None:
    assert defs._run_deadline_seconds(900) == 900 - defs.RUN_DEADLINE_MARGIN_SECONDS  # Dagster 밖

    class Broken:
        def get_run_record_by_id(self, run_id):
            raise RuntimeError("metadata down")

    assert _deadline(Broken(), 1200) == 1200 - defs.RUN_DEADLINE_MARGIN_SECONDS


def test_run_with_session_uses_the_run_deadline(tmp_path: Path, monkeypatch) -> None:
    settings = build_settings(tmp_path)
    seen: list[float] = []
    original = asyncio.timeout

    def spy(delay):
        seen.append(delay)
        return original(delay)

    monkeypatch.setattr(defs.asyncio, "timeout", spy)

    async def action(session):
        return {"status": "success"}

    asyncio.run(defs._run_with_session(settings, action, max_runtime_seconds=900))
    assert seen == [900 - defs.RUN_DEADLINE_MARGIN_SECONDS]


def test_scheduled_execution_time_tag_is_read_only_for_tick_runs() -> None:
    tick = "2026-11-24T09:03:00+09:00"
    context = SimpleNamespace(run=SimpleNamespace(tags={"dagster/scheduled_execution_time": tick}))
    assert defs._scheduled_execution_time(context) == datetime.fromisoformat(tick)
    assert defs._scheduled_execution_time(SimpleNamespace(run=SimpleNamespace(tags={}))) is None
    assert defs._scheduled_execution_time(SimpleNamespace()) is None


def _collect(settings, provider, **kwargs):
    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with factory() as session:
            await service.collect(session, trigger="test", scope="highway", **kwargs)
            states = {row.source: row for row in await session.scalars(select(TransportCollectionState))}
        await service.close()
        await engine.dispose()
        return states

    return asyncio.run(run())


def test_tick_run_success_is_due_again_at_the_next_tick_whatever_the_launch_delay(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    tick = now_utc().replace(microsecond=0) - timedelta(seconds=45)  # 45초 늦게 시작한 run
    states = _collect(settings, FakeTransportProvider(), scheduled_at=tick)
    for source in (TRAFFIC_SOURCE, INCIDENT_SOURCE):
        due = serialize_utc(states[source].next_due_at)
        assert due == tick + timedelta(seconds=FIVE_MINUTES) - HIGHWAY_TICK_SLACK
        # 다음 tick run은 기동 지연이 0이어도 예정 뒤다 — 건너뛰지 않는다. 같은 tick의 중복은 여전히 이르다.
        assert due <= tick + timedelta(seconds=FIVE_MINUTES)
        assert due > tick + timedelta(seconds=60)


def test_run_without_a_tick_keeps_the_start_based_due(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    states = _collect(settings, FakeTransportProvider())
    for source in (TRAFFIC_SOURCE, INCIDENT_SOURCE):
        state = states[source]
        assert serialize_utc(state.next_due_at) == serialize_utc(state.last_started_at) + timedelta(seconds=FIVE_MINUTES)


def test_failure_due_still_counts_from_the_failure(tmp_path: Path) -> None:
    """실패 뒤 다음 tick 하나를 건너뛰는 유예는 그대로다(결정적 오류·장애의 재호출을 늦춘다)."""
    settings = build_settings(tmp_path)
    provider = FakeTransportProvider()

    async def failing(*, sources=(TRAFFIC_SOURCE, INCIDENT_SOURCE)):
        raise RuntimeError("upstream 503")

    provider.collect_highway = failing  # type: ignore[method-assign]
    before = now_utc()
    states = _collect(settings, provider, scheduled_at=before - timedelta(seconds=30))
    traffic = states[TRAFFIC_SOURCE]
    assert traffic.last_error and "503" in traffic.last_error
    assert serialize_utc(traffic.next_due_at) >= before + timedelta(seconds=FIVE_MINUTES)
