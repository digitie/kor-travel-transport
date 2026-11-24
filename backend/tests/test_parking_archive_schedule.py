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
    # 주 1회, KST 새벽(유가 00:00 시작·최대 3.5시간, 새벽 기준정보 02:30~04:45가 끝난 뒤).
    assert (second - first).days == 7
    assert first.weekday() == 0 and (first.hour, first.minute) == (5, 10)
    # 같은 시각에 시작하는 다른 transport schedule이 없다(5분 공항·고속도로, 매시 정각 KRIC는 늘 돈다).
    others = [s for s in module.definitions.schedules if s.name != schedule.name]
    tick = datetime(2026, 11, 23, 5, 10, tzinfo=KST)
    for other in others:
        if other.cron_schedule.startswith(("*/", "0 * ", "1-", "3-")) or "/5" in other.cron_schedule:
            continue
        nearby = schedule_execution_time_iterator((tick.timestamp() - 1), other.cron_schedule, "Asia/Seoul")
        assert next(nearby) != tick, other.name
    with DagsterInstance.local_temp() as instance:
        result = schedule.evaluate_tick(build_schedule_context(instance=instance))
    assert len(result.run_requests) == 1
    assert result.run_requests[0].run_config == SCHEDULED
    # 정기 실행은 하루 범위(공항 14곳 x 144)를 배치 하나로 끝내고 여러 배치를 이어 한다.
    assert module.PARKING_ARCHIVE_SCHEDULED_CONFIG["max_buckets"] == 2016
    assert module.PARKING_ARCHIVE_SCHEDULED_CONFIG["max_batches"] > 7


def test_archive_job_tags_priority_zero_bounded_runtime_and_airport_serialization() -> None:
    tags = module.definitions.get_job_def("parking_statistics_archive_job").tags
    assert tags["dagster/priority"] == "0"
    runtime = int(tags["dagster/max_runtime"])
    assert runtime == module.job_max_runtime_seconds("parking_statistics_archive_job") == 900
    # 공항 수집과 같은 run group(상한 1) — Dagster가 직렬화한다. 시간 예산은 공항 5분 주기 안이다.
    assert tags["kortraveltransport/run_group"] == "parking"
    assert module.definitions.get_job_def("airport_collection_job").tags["kortraveltransport/run_group"] == "parking"
    assert module.PARKING_ARCHIVE_SCHEDULED_TIME_BUDGET_SECONDS < 300 < runtime


def test_cleanup_is_still_manual_and_blocked() -> None:
    with pytest.raises(RuntimeError):
        asyncio.run(prune_parking_raw())
    # 정기 실행은 적재 job 하나뿐이다(정리 job·schedule은 없다).
    jobs = {s.job_name for s in module.definitions.schedules}
    assert "parking_statistics_archive_job" in jobs
    assert not any("prune" in name or "cleanup" in name for name in jobs if name.startswith("parking"))


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


def _run(monkeypatch, batches, *, run_config=None, batch_seconds=5.0):
    clock = _Clock()
    calls: list[dict] = []
    queue = list(batches)

    async def fake_run(_settings, action, **kwargs):
        assert action is module.archive_parking_with_coverage
        calls.append(kwargs)
        clock.now += batch_seconds
        return dict(queue.pop(0))

    monkeypatch.setattr(module, "_settings", lambda: None)
    monkeypatch.setattr(module, "_run_with_session", fake_run)
    monkeypatch.setattr(module, "_archive_clock", lambda: clock.now)
    monkeypatch.setattr(module, "_archive_sleep", clock.sleep)
    with DagsterInstance.ephemeral() as instance:
        result = module.parking_statistics_archive_job.execute_in_process(
            instance=instance, run_config=run_config or {}, raise_on_error=False)
        warnings = [entry.user_message for entry in instance.all_logs(result.run_id)
                    if entry.level == logging.WARNING and entry.step_key == OP]
        outcome = instance.get_run_by_id(result.run_id).tags.get("kortravel/collection-outcome")
    return result, calls, clock, warnings, outcome


def _metadata(result) -> dict:
    output = next(event.event_specific_data for event in result.all_events
                  if event.step_key == OP and event.event_type_value == "STEP_OUTPUT")
    return {key: value.value for key, value in output.metadata.items()}


def test_manual_default_is_one_batch_without_retry(monkeypatch) -> None:
    """수동 실행 기본값은 예전 그대로다: 배치 하나(144 버킷), busy면 다시 시도하지 않는다, 부분 완료 태그도 없다."""
    for status in ("batch_complete", "busy"):
        result, calls, clock, warnings, outcome = _run(
            monkeypatch, [_batch(status, archived=3 if status != "busy" else 0)])
        assert result.success
        assert [call["max_buckets"] for call in calls] == [144]
        assert clock.sleeps == [] and warnings == [] and outcome is None
        assert _metadata(result)["stop_reason"] == ("max_batches" if status == "batch_complete" else "busy")


def test_scheduled_run_continues_batches_until_caught_up(monkeypatch) -> None:
    batches = [_batch("batch_complete", 2016, 144), _batch("batch_complete", 2016, 144),
               _batch("batch_complete", 1000, 0), _batch("no_new_rows")]
    result, calls, _clock, warnings, outcome = _run(monkeypatch, batches, run_config=SCHEDULED)
    assert result.success
    assert [call["max_buckets"] for call in calls] == [2016] * 4
    # 배치의 취소 시한은 run 기록(`dagster/max_runtime` 900, 시작 시각) 기준으로 남은 상한이다.
    assert all(800 < call["max_runtime_seconds"] <= 900 for call in calls)
    metadata = _metadata(result)
    assert metadata["stop_reason"] == "no_new_rows"
    assert metadata["batches"] == 4
    assert metadata["total_archived_buckets"] == 5032 and metadata["total_global_buckets"] == 288
    assert metadata["status"] == "no_new_rows"  # 서비스 결과 필드는 마지막 배치 기준
    assert warnings == [] and outcome is None  # 따라잡았으면 경고·부분 완료 태그가 없다


def test_scheduled_run_stops_on_deferred_without_spinning(monkeypatch) -> None:
    result, calls, _clock, _warnings, outcome = _run(
        monkeypatch, [_batch("batch_complete", 2016), _batch("deferred")], run_config=SCHEDULED)
    assert result.success and len(calls) == 2 and outcome is None
    assert _metadata(result)["stop_reason"] == "deferred"


def test_scheduled_run_retries_lease_contention_then_stops_as_partial(monkeypatch) -> None:
    retries = module.PARKING_ARCHIVE_SCHEDULED_CONFIG["busy_retries"]
    batches = [_batch("busy"), _batch("batch_complete", 10), _batch("no_new_rows")]
    result, calls, clock, _warnings, outcome = _run(monkeypatch, batches, run_config=SCHEDULED)
    assert result.success and len(calls) == 3 and outcome is None
    assert clock.sleeps == [module.PARKING_ARCHIVE_BUSY_WAIT_SECONDS]
    assert _metadata(result)["busy_retries_used"] == 1

    result, calls, clock, warnings, outcome = _run(monkeypatch, [_batch("busy")] * (retries + 1), run_config=SCHEDULED)
    assert result.success  # busy는 미실행이지 실패가 아니다(예전 계약)
    assert len(calls) == retries + 1
    metadata = _metadata(result)
    assert metadata["stop_reason"] == "busy" and metadata["batches"] == 0
    assert any("busy로 멈췄습니다" in line for line in warnings)
    assert outcome == "partial"


def test_scheduled_run_respects_its_time_budget_and_marks_backlog_partial(monkeypatch) -> None:
    """공항 수집과 같은 run group이라 보관 run 동안 공항 run은 대기열에서 기다린다 — 예산 안에서만 새 배치를 시작한다."""
    per_batch = 40.0
    expected = math.ceil(module.PARKING_ARCHIVE_SCHEDULED_TIME_BUDGET_SECONDS / per_batch)
    result, calls, _clock, warnings, outcome = _run(
        monkeypatch, [_batch("batch_complete", 2016)] * (expected + 5), run_config=SCHEDULED, batch_seconds=per_batch)
    assert result.success
    assert len(calls) == expected
    assert _metadata(result)["stop_reason"] == "time_budget"
    assert any("time_budget로 멈췄습니다" in line and "2026-10-01T15:00:00+00:00" in line for line in warnings)
    assert outcome == "partial"  # 남은 보관분이 있다는 신호(실패는 아니다)


def test_scheduled_run_max_batches_is_a_backlog_signal(monkeypatch) -> None:
    config = {"ops": {OP: {"config": {**module.PARKING_ARCHIVE_SCHEDULED_CONFIG, "max_batches": 2}}}}
    result, calls, _clock, _warnings, outcome = _run(monkeypatch, [_batch("batch_complete", 2016)] * 3, run_config=config)
    assert result.success and len(calls) == 2 and outcome == "partial"
    assert _metadata(result)["stop_reason"] == "max_batches"


def test_blocked_batch_fails_the_run_with_totals(monkeypatch) -> None:
    blocked = {**_batch("blocked"), "coverage_status": "conflict", "blocked_reason": "sealed_raw_mismatch"}
    result, calls, _clock, _warnings, _outcome = _run(
        monkeypatch, [_batch("batch_complete", 7), blocked], run_config=SCHEDULED)
    assert not result.success and len(calls) == 2
    failure = next(event.event_specific_data for event in result.all_events if event.event_type_value == "STEP_FAILURE")
    metadata = {key: value.value for key, value in failure.user_failure_data.metadata.items()}
    assert metadata["status"] == "blocked" and metadata["stop_reason"] == "blocked"
    assert metadata["batches"] == 1 and metadata["total_archived_buckets"] == 7


@pytest.mark.parametrize("config", [
    {"max_batches": 0}, {"max_batches": 501}, {"max_buckets": 0}, {"max_buckets": 2017}, {"busy_retries": -1},
    {"time_budget_seconds": -1},
])
def test_out_of_range_config_fails_before_touching_the_database(monkeypatch, config) -> None:
    result, calls, _clock, _warnings, _outcome = _run(monkeypatch, [], run_config={"ops": {OP: {"config": config}}})
    assert not result.success and calls == []


def test_coverage_service_rejects_out_of_range_bucket_limits() -> None:
    session = SimpleNamespace(bind=None)
    for value in (0, 2017):
        with pytest.raises(ValueError):
            asyncio.run(archive_parking_with_coverage(session, max_buckets=value))


def test_manual_backfill_has_no_budget_and_uses_the_run_tag_runtime(monkeypatch) -> None:
    """수동 backfill은 시간 예산 없이(기본 0) 실행 상한까지 배치를 잇고, 배치 시한은 run의 `dagster/max_runtime` 태그를 따른다
    (운영자가 태그를 바꾼 긴 수동 run이 코드 상수 900초에 묶이지 않는다)."""
    calls: list[dict] = []
    queue = [_batch("batch_complete", 2016)] * 10 + [_batch("no_new_rows")]

    async def fake_run(_settings, action, **kwargs):
        calls.append(kwargs)
        return dict(queue.pop(0))

    clock = _Clock()

    async def slow(_settings, action, **kwargs):
        clock.now += 300.0  # 배치마다 5분 — 정기 예산(240초)이면 첫 배치 뒤 멈췄을 것이다
        return await fake_run(_settings, action, **kwargs)

    monkeypatch.setattr(module, "_settings", lambda: None)
    monkeypatch.setattr(module, "_run_with_session", slow)
    monkeypatch.setattr(module, "_archive_clock", lambda: clock.now)
    config = {"ops": {OP: {"config": {"max_batches": 500, "max_buckets": 2016}}}}
    with DagsterInstance.ephemeral() as instance:
        result = module.parking_statistics_archive_job.execute_in_process(
            instance=instance, run_config=config, tags={"dagster/max_runtime": "7200"}, raise_on_error=False)
    assert result.success
    assert len(calls) == 11
    assert _metadata(result)["stop_reason"] == "no_new_rows"
    assert all(7000 < call["max_runtime_seconds"] <= 7200 for call in calls)
