"""주차 통계 보관 적재의 주 1회 정기 실행(PARKING-ARCHIVE-WEEKLY-20261124).

소유자 결정(2026-11-24): `parking_statistics_archive_job`은 **적재만** 주 1회 자동으로 돌린다. 정리(원본 삭제)는 수동 유지 —
`prune_parking_raw`는 계속 항상 거부한다. 수집 감사(Map `docs/reports/2026-11-23-collection-failure-audit.md` §2.2)의
"코드에 있으나 40일간 실행 0" 후속.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from dagster import DagsterInstance, build_schedule_context
from dagster._utils.schedules import schedule_execution_time_iterator

from app.dagster import definitions as module
from app.services.collection import CollectionService, FixturePublicDataClient
from app.core.config import Settings
from app.services.parking_global_archive import archive_parking_with_coverage
from app.services.parking_statistics_archive import prune_parking_raw

KST = ZoneInfo("Asia/Seoul")
OP = "archive_airport_parking_statistics"
SCHEDULED = {"ops": {OP: {"config": dict(module.PARKING_ARCHIVE_SCHEDULED_CONFIG)}}}


def test_weekly_schedule_runs_the_scheduled_config_at_low_load_dawn() -> None:
    schedule = module.definitions.get_schedule_def("parking_statistics_archive_job_schedule")
    assert schedule.job.name == "parking_statistics_archive_job"
    assert schedule.execution_timezone == "Asia/Seoul"
    assert schedule.default_status.name == "RUNNING"
    start = datetime(2026, 11, 23, tzinfo=KST)  # 월요일
    ticks = schedule_execution_time_iterator(start.timestamp(), schedule.cron_schedule, "Asia/Seoul")
    first, second = next(ticks), next(ticks)
    # 주 1회, KST 새벽(유가 00:00 시작·최대 3.5시간, 새벽 기준정보 02:30~04:45가 끝난 뒤, 06:00 KRIC 전).
    assert (second - first).days == 7
    assert first.weekday() == 0 and (first.hour, first.minute) == (5, 10)
    with DagsterInstance.local_temp() as instance:
        result = schedule.evaluate_tick(build_schedule_context(instance=instance))
    assert len(result.run_requests) == 1
    assert result.run_requests[0].run_config == SCHEDULED
    # 정기 실행은 하루 범위(공항 14곳 x 144)를 배치 하나로 끝내고 여러 배치를 이어 한다.
    assert module.PARKING_ARCHIVE_SCHEDULED_CONFIG["max_buckets"] == 2016
    assert module.PARKING_ARCHIVE_SCHEDULED_CONFIG["max_batches"] > 7


def test_archive_job_tags_priority_zero_bounded_runtime_and_own_run_group() -> None:
    tags = module.definitions.get_job_def("parking_statistics_archive_job").tags
    assert tags["dagster/priority"] == "0"
    runtime = int(tags["dagster/max_runtime"])
    assert runtime == module.job_max_runtime_seconds("parking_statistics_archive_job") == 2700
    # 시간 예산 뒤 배치 하나와 마무리 여유가 상한 안에 든다.
    assert module.PARKING_ARCHIVE_TIME_BUDGET_SECONDS + module.PARKING_ARCHIVE_SLOW_BATCH_SECONDS * 4 < runtime
    # 공항 수집(run group `parking`, 상한 1)과 다른 group이라 보관 run이 5분 수집을 Dagster 대기열에 묶지 않는다.
    assert tags["kortraveltransport/run_group"] == "parking_archive"
    assert module.definitions.get_job_def("airport_collection_job").tags["kortraveltransport/run_group"] == "parking"
    # 배치가 lease를 쥐는 시간은 공항 수집의 lease 대기보다 충분히 짧다.
    assert module.PARKING_ARCHIVE_SLOW_BATCH_SECONDS * 2 <= module.AIRPORT_LEASE_WAIT_SECONDS


def test_cleanup_is_still_manual_and_blocked() -> None:
    with pytest.raises(RuntimeError):
        asyncio.run(prune_parking_raw())


def _batch(status: str, archived: int = 0, global_buckets: int = 0) -> dict:
    return {"status": status, "coverage_status": "partial" if status in {"batch_complete", "deferred"} else "not_audited",
            "archived_buckets": archived, "global_buckets": global_buckets, "deferred_buckets": 0,
            "pruned_snapshots": 0, "oldest_pending_at": "2026-10-01T15:00:00+00:00"}


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _run(monkeypatch, batches, *, run_config=None, batch_seconds=5.0, active=()):
    clock = _Clock()
    calls: list[dict] = []
    queue = list(batches)
    activity = list(active)

    async def fake_run(_settings, action, **kwargs):
        assert action is module.archive_parking_with_coverage
        calls.append(kwargs)
        clock.now += batch_seconds
        return dict(queue.pop(0))

    monkeypatch.setattr(module, "_settings", lambda: None)
    monkeypatch.setattr(module, "_run_with_session", fake_run)
    monkeypatch.setattr(module, "_archive_clock", lambda: clock.now)
    monkeypatch.setattr(module, "_archive_sleep", clock.sleep)
    monkeypatch.setattr(module, "_airport_collection_active", lambda _context: activity.pop(0) if activity else False)
    with DagsterInstance.ephemeral() as instance:
        result = module.parking_statistics_archive_job.execute_in_process(
            instance=instance, run_config=run_config or {}, raise_on_error=False)
        warnings = [entry.user_message for entry in instance.all_logs(result.run_id)
                    if entry.level == logging.WARNING and entry.step_key == OP]
    return result, calls, clock, warnings


def _metadata(result) -> dict:
    output = next(event.event_specific_data for event in result.all_events
                  if event.step_key == OP and event.event_type_value == "STEP_OUTPUT")
    return {key: value.value for key, value in output.metadata.items()}


def test_manual_default_is_one_batch_and_still_yields_to_airport_collection(monkeypatch) -> None:
    """수동 실행 기본값은 예전 그대로다: 배치 하나(144 버킷), busy면 다시 시도하지 않는다. 다만 보관 job이 공항 수집과
    다른 run group이 됐으므로 수동 실행도 공항 수집 run이 대기·진행 중이면 기다린 뒤 시작한다."""
    for status in ("batch_complete", "busy"):
        result, calls, clock, warnings = _run(monkeypatch, [_batch(status, archived=3 if status != "busy" else 0)],
                                              active=[True, True])
        assert result.success
        assert [call["max_buckets"] for call in calls] == [144]
        assert clock.sleeps == [module.PARKING_ARCHIVE_YIELD_POLL_SECONDS] * 2 and warnings == []
        metadata = _metadata(result)
        assert metadata["stop_reason"] == ("max_batches" if status == "batch_complete" else "busy")


def test_scheduled_run_continues_batches_until_caught_up(monkeypatch) -> None:
    batches = [_batch("batch_complete", 2016, 144), _batch("batch_complete", 2016, 144),
               _batch("batch_complete", 1000, 0), _batch("no_new_rows")]
    result, calls, _clock, warnings = _run(monkeypatch, batches, run_config=SCHEDULED)
    assert result.success
    assert [call["max_buckets"] for call in calls] == [2016] * 4
    assert all(call["max_runtime_seconds"] == 2700 for call in calls)
    metadata = _metadata(result)
    assert metadata["stop_reason"] == "no_new_rows"
    assert metadata["batches"] == 4
    assert metadata["total_archived_buckets"] == 5032 and metadata["total_global_buckets"] == 288
    assert metadata["status"] == "no_new_rows"  # 서비스 결과 필드는 마지막 배치 기준
    assert warnings == []  # 따라잡았으면 경고가 없다


def test_scheduled_run_stops_on_deferred_without_spinning(monkeypatch) -> None:
    result, calls, _clock, _warnings = _run(
        monkeypatch, [_batch("batch_complete", 2016), _batch("deferred")], run_config=SCHEDULED)
    assert result.success and len(calls) == 2
    assert _metadata(result)["stop_reason"] == "deferred"


def test_scheduled_run_retries_lease_contention_then_gives_up_green(monkeypatch) -> None:
    retries = module.PARKING_ARCHIVE_SCHEDULED_CONFIG["busy_retries"]
    batches = [_batch("busy"), _batch("batch_complete", 10), _batch("no_new_rows")]
    result, calls, clock, _warnings = _run(monkeypatch, batches, run_config=SCHEDULED)
    assert result.success and len(calls) == 3
    assert clock.sleeps == [module.PARKING_ARCHIVE_BUSY_WAIT_SECONDS]
    assert _metadata(result)["busy_retries_used"] == 1

    always_busy = [_batch("busy")] * (retries + 1)
    result, calls, clock, warnings = _run(monkeypatch, always_busy, run_config=SCHEDULED)
    assert result.success  # busy는 미실행이지 실패가 아니다(예전 계약)
    assert len(calls) == retries + 1
    metadata = _metadata(result)
    assert metadata["stop_reason"] == "busy" and metadata["batches"] == 0
    assert any("busy로 멈췄습니다" in line for line in warnings)


def test_scheduled_run_yields_while_airport_collection_is_active(monkeypatch) -> None:
    """공항 수집 run이 대기·진행 중이면 배치를 시작하지 않고 기다린다(같은 lease·수집 뒤 사전집계 갱신과 겹치지 않게)."""
    result, calls, clock, _warnings = _run(
        monkeypatch, [_batch("batch_complete", 5), _batch("no_new_rows")], run_config=SCHEDULED,
        active=[True, True, False, True, False])
    assert result.success and len(calls) == 2
    assert clock.sleeps == [module.PARKING_ARCHIVE_YIELD_POLL_SECONDS] * 3


def test_scheduled_run_stops_after_a_slow_batch(monkeypatch) -> None:
    """배치가 느리면(공항 수집이 lease를 기다리는 시간과 겨룬다) 더 시작하지 않는다. 적재분은 commit했고 run은 성공이다."""
    result, calls, _clock, warnings = _run(
        monkeypatch, [_batch("batch_complete", 2016)] * 3, run_config=SCHEDULED,
        batch_seconds=module.PARKING_ARCHIVE_SLOW_BATCH_SECONDS + 1)
    assert result.success and len(calls) == 1
    assert _metadata(result)["stop_reason"] == "slow_batch"
    assert any("slow_batch로 멈췄습니다" in line and "2026-10-01T15:00:00+00:00" in line for line in warnings)


def test_scheduled_run_respects_its_time_budget(monkeypatch) -> None:
    per_batch = 40.0
    expected = math.ceil(module.PARKING_ARCHIVE_TIME_BUDGET_SECONDS / per_batch)  # 예산을 넘긴 뒤에는 새 배치를 시작하지 않는다
    result, calls, _clock, warnings = _run(
        monkeypatch, [_batch("batch_complete", 2016)] * (expected + 5), run_config=SCHEDULED, batch_seconds=per_batch)
    assert result.success
    assert len(calls) == expected
    assert _metadata(result)["stop_reason"] == "time_budget"
    assert warnings


def test_scheduled_run_does_not_start_when_airport_stays_active_past_the_budget(monkeypatch) -> None:
    polls = int(module.PARKING_ARCHIVE_TIME_BUDGET_SECONDS // module.PARKING_ARCHIVE_YIELD_POLL_SECONDS) + 5
    result, calls, _clock, _warnings = _run(monkeypatch, [], run_config=SCHEDULED, active=[True] * polls)
    assert result.success and calls == []
    metadata = _metadata(result)
    assert metadata["stop_reason"] == "time_budget" and metadata["batches"] == 0


def test_blocked_batch_fails_the_run_with_totals(monkeypatch) -> None:
    blocked = {**_batch("blocked"), "coverage_status": "conflict", "blocked_reason": "sealed_raw_mismatch"}
    result, calls, _clock, _warnings = _run(
        monkeypatch, [_batch("batch_complete", 7), blocked], run_config=SCHEDULED)
    assert not result.success and len(calls) == 2
    failure = next(event.event_specific_data for event in result.all_events if event.event_type_value == "STEP_FAILURE")
    metadata = {key: value.value for key, value in failure.user_failure_data.metadata.items()}
    assert metadata["status"] == "blocked" and metadata["stop_reason"] == "blocked"
    assert metadata["batches"] == 1 and metadata["total_archived_buckets"] == 7


@pytest.mark.parametrize("config", [
    {"max_batches": 0}, {"max_batches": 501}, {"max_buckets": 0}, {"max_buckets": 2017}, {"busy_retries": -1},
])
def test_out_of_range_config_fails_before_touching_the_database(monkeypatch, config) -> None:
    result, calls, _clock, _warnings = _run(monkeypatch, [], run_config={"ops": {OP: {"config": config}}})
    assert not result.success and calls == []


def test_coverage_service_rejects_out_of_range_bucket_limits() -> None:
    session = SimpleNamespace(bind=None)
    for value in (0, 2017):
        with pytest.raises(ValueError):
            asyncio.run(archive_parking_with_coverage(session, max_buckets=value))


class _LockConnection:
    def __init__(self, answers: list[bool]) -> None:
        self.answers = list(answers)
        self.statements: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def scalar(self, statement):
        self.statements.append(str(statement))
        if "pg_advisory_unlock" in str(statement):
            return True
        return self.answers.pop(0)


def _lease(connection: _LockConnection, wait_seconds: float) -> bool:
    async def run() -> bool:
        engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: connection)
        service = CollectionService(Settings(use_sample_client_when_no_key=True), client=FixturePublicDataClient())
        async with service._postgres_collection_lease(SimpleNamespace(bind=engine), wait_seconds=wait_seconds) as acquired:
            return acquired

    return asyncio.run(run())


def test_airport_lease_waits_for_a_short_holder(monkeypatch) -> None:
    """보관 배치가 lease를 쥔 동안 공항 수집은 기다렸다가 잡는다(5분 수집 한 주기를 통째로 잃지 않는다)."""
    import app.services.collection as collection

    monkeypatch.setattr(collection, "AIRPORT_LEASE_POLL_SECONDS", 0.01)
    connection = _LockConnection([False, False, True])
    assert _lease(connection, wait_seconds=5) is True
    assert sum("pg_try_advisory_lock" in statement for statement in connection.statements) == 3
    assert "pg_advisory_unlock" in connection.statements[-1]


def test_airport_lease_without_wait_keeps_the_old_skip(monkeypatch) -> None:
    connection = _LockConnection([False])
    assert _lease(connection, wait_seconds=0) is False
    assert len(connection.statements) == 1  # 한 번 시도하고, 잡지 못했으니 해제도 없다


def test_airport_lease_wait_is_bounded(monkeypatch) -> None:
    import app.services.collection as collection

    monkeypatch.setattr(collection, "AIRPORT_LEASE_POLL_SECONDS", 0.01)
    connection = _LockConnection([False] * 1000)
    assert _lease(connection, wait_seconds=0.05) is False
    attempts = sum("pg_try_advisory_lock" in statement for statement in connection.statements)
    assert 2 <= attempts < 50


def test_dagster_airport_collection_passes_the_lease_wait(monkeypatch) -> None:
    seen = {}

    class Service:
        async def collect(self, session, *, trigger, lease_wait_seconds):
            seen["wait"] = lease_wait_seconds
            return {"status": "skipped", "snapshot_count": 0}

    monkeypatch.setattr(module, "CollectionService", lambda _settings: Service())

    async def run():
        session = SimpleNamespace(bind=None, commit=None, rollback=None)
        try:
            await module._collect_airport_with_analytics(session, settings=None, trigger="dagster_airport")
        except Exception:  # noqa: BLE001 — 사전집계 판정 실패는 결과를 바꾸지 않는다(여기서는 대기값만 본다).
            pass

    asyncio.run(run())
    assert seen["wait"] == module.AIRPORT_LEASE_WAIT_SECONDS
