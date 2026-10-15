"""Transport의 실제 Dagster cron과 coalescing 계약을 달력 기준으로 확인한다."""
from collections import Counter
from datetime import datetime, timedelta
from itertools import takewhile
from zoneinfo import ZoneInfo

import pytest
from dagster import DagsterInstance, DagsterRunStatus, build_schedule_context
from dagster._utils.schedules import schedule_execution_time_iterator
from dagster._core.remote_origin import GrpcServerCodeLocationOrigin, RemoteJobOrigin, RemoteRepositoryOrigin

from app.dagster.definitions import definitions

KST = ZoneInfo("Asia/Seoul")
JOBS = [("airport", 1, "parking"), ("highway", 3, "highway")]


def ticks(cron, start, days):
    stop = start + timedelta(days=days)
    return list(takewhile(
        lambda tick: tick < stop,
        schedule_execution_time_iterator(start.timestamp(), cron, "Asia/Seoul"),
    ))


@pytest.mark.parametrize("start", [
    datetime(2026, 1, 1, tzinfo=KST),
    datetime(2028, 2, 27, tzinfo=KST),
    datetime(2026, 12, 30, tzinfo=KST),
])
def test_five_minute_calendar_preserves_daily_volume_and_separates_phases(start):
    calendars = []
    for domain, phase, _group in JOBS:
        schedule = definitions.get_schedule_def(f"{domain}_collection_job_schedule")
        actual = ticks(schedule.cron_schedule, start, 4)
        # 같은 달력의 기존 */5와 일일 총량 및 순환 간격을 비교한다.
        old = ticks("*/5 * * * *", start, 4)
        assert Counter(t.date() for t in actual) == Counter(t.date() for t in old)
        assert set(Counter(t.date() for t in actual).values()) == {288}
        assert actual[0] == start + timedelta(minutes=phase)
        assert all(t.minute % 5 == phase for t in actual)
        assert all(b - a == timedelta(minutes=5) for a, b in zip(actual, actual[1:]))
        assert actual[0] + timedelta(days=4) - actual[-1] == timedelta(minutes=5)
        calendars.append(actual)
    assert set(calendars[0]).isdisjoint(calendars[1])
    assert all(b - a == timedelta(minutes=2) for a, b in zip(*calendars))


@pytest.mark.parametrize("domain,phase,group", JOBS)
def test_staggering_preserves_execution_and_resource_contract(domain, phase, group):
    name = f"{domain}_collection_job"
    schedule = definitions.get_schedule_def(name + "_schedule")
    job = definitions.get_job_def(name)
    assert schedule.job.name == name
    assert schedule.execution_timezone == "Asia/Seoul"
    assert schedule.default_status.name == "RUNNING"
    assert job.executor_def.name == "multiprocess"
    assert job.executor_def.apply_config_mapping({}).value["config"]["max_concurrent"] == 1
    assert set(job.resource_defs) == {"io_manager"}
    assert job.tags == {
        "kortravelcommon/project": "transport",
        "kortravelcommon/job": f"transport/{name}",
        "dagster/max_runtime": "14400",
        "dagster/max_retries": "1",
        "dagster/retry_on_asset_or_op_failure": "false",
        "kortraveltransport/run_group": group,
        "dagster/code_location": "kor-travel-transport",
    }


@pytest.mark.parametrize("domain,phase,group", JOBS)
@pytest.mark.parametrize("status", [
    DagsterRunStatus.QUEUED, DagsterRunStatus.STARTING,
    DagsterRunStatus.STARTED, DagsterRunStatus.CANCELING,
])
def test_staggered_schedules_still_coalesce_until_terminal(domain, phase, group, status):
    name = f"{domain}_collection_job"
    schedule = definitions.get_schedule_def(name + "_schedule")
    job = definitions.get_job_def(name)
    with DagsterInstance.local_temp() as instance:
        remote_origin = RemoteJobOrigin(
            RemoteRepositoryOrigin(
                GrpcServerCodeLocationOrigin(host="localhost", port=14005, location_name="kor-travel-transport"),
                "__repository__",
            ), name,
        )
        run = instance.create_run_for_job(job, status=status, tags=job.tags, remote_job_origin=remote_origin)
        context = build_schedule_context(instance=instance)
        assert schedule.evaluate_tick(context).skip_message
        instance.report_run_failed(run)
        assert len(schedule.evaluate_tick(context).run_requests) == 1
