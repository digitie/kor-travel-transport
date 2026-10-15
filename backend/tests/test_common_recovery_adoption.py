"""Common pin 변경이 Transport의 실제 retry sensor 대상·예산을 보존하는지 확인한다."""
import pytest
from dagster import DagsterEvent, DagsterEventType, DagsterInstance, DagsterRunStatus, build_sensor_context
from dagster._core.events import JobFailureData, RunFailureReason, StepFailureData
from dagster._core.execution.plan.objects import ErrorSource
from dagster._core.remote_origin import GrpcServerCodeLocationOrigin, RemoteJobOrigin, RemoteRepositoryOrigin
from dagster._utils.error import SerializableErrorInfo

from app.dagster.definitions import definitions


def origin(name):
    return RemoteJobOrigin(
        RemoteRepositoryOrigin(
            GrpcServerCodeLocationOrigin(host="localhost", port=14005, location_name="kor-travel-transport"),
            "__repository__",
        ), name,
    )


@pytest.mark.parametrize("name", [
    "airport_collection_job", "highway_collection_job", "rest_area_reference_collection_job",
])
@pytest.mark.parametrize("case", ["crash", "provider", "mixed", "missing"])
def test_transport_retry_requires_proven_child_crash_and_keeps_one_retry(name, case):
    job = definitions.get_job_def(name)
    sensor = definitions.get_sensor_def("transport_infra_retry_" + name)
    with DagsterInstance.local_temp() as instance:
        run = instance.create_run_for_job(
            job, status=DagsterRunStatus.FAILURE, tags=job.tags, remote_job_origin=origin(name),
        )
        instance.report_dagster_event(DagsterEvent(
            event_type_value=DagsterEventType.RUN_FAILURE.value,
            job_name=name,
            event_specific_data=JobFailureData(
                SerializableErrorInfo("worker exited", [], "DagsterSubprocessError"),
                failure_reason=RunFailureReason.RUN_EXCEPTION,
            ),
        ), run.run_id)
        if case != "missing":
            for provider in ([False, True] if case == "mixed" else [case == "provider"]):
                instance.report_dagster_event(DagsterEvent(
                    event_type_value=DagsterEventType.STEP_FAILURE.value,
                    job_name=name, step_key=job.graph.node_names()[0],
                    event_specific_data=StepFailureData(
                        SerializableErrorInfo("failure", [], "ValueError" if provider else "ChildProcessCrashException"),
                        user_failure_data=None,
                        error_source=ErrorSource.USER_CODE_ERROR if provider else ErrorSource.FRAMEWORK_ERROR,
                    ),
                ), run.run_id)
        result = sensor.evaluate_tick(build_sensor_context(instance=instance))
        assert len(result.run_requests) == (1 if case == "crash" else 0)
        if result.run_requests:
            request = result.run_requests[0]
            assert sensor.job.name == name
            assert request.tags["kortravelcommon/job"] == "transport/" + name
            assert request.run_config == run.run_config
            assert request.tags["kortravelcommon/infra_retry_attempt"] == "1"
            assert request.tags["kortravelcommon/infra_retry_parent"] == run.run_id
            assert request.tags["dagster/max_retries"] == "0"
            assert "kortravelcommon/infra_retry_pending" not in request.tags
            parent = instance.get_run_by_id(run.run_id)
            assert parent.tags["dagster/max_retries"] == "0"
            assert parent.tags["dagster/will_retry"] == "false"
            assert parent.tags["kortravelcommon/infra_retry_pending"] == "true"
            # sensor 재평가는 같은 key를 발급해 daemon의 run-key 중복 방지를 유지한다.
            again = sensor.evaluate_tick(build_sensor_context(instance=instance))
            assert [r.run_key for r in again.run_requests] == [request.run_key]


@pytest.mark.parametrize("late_provider_failure", [False, True])
def test_transport_retry_resumes_step_history_and_rejects_a_late_provider_failure(
    monkeypatch, late_provider_failure,
):
    from types import SimpleNamespace
    import kortravelcommon.dagster as common

    name = "airport_collection_job"
    job = definitions.get_job_def(name)
    sensor = definitions.get_sensor_def("transport_infra_retry_" + name)
    clock = [0.0]
    monkeypatch.setattr(common, "monotonic", lambda: clock[0])
    with DagsterInstance.local_temp() as instance:
        run = instance.create_run_for_job(
            job, status=DagsterRunStatus.FAILURE, tags=job.tags, remote_job_origin=origin(name),
        )
        instance.report_dagster_event(DagsterEvent(
            event_type_value=DagsterEventType.RUN_FAILURE.value, job_name=name,
            event_specific_data=JobFailureData(
                SerializableErrorInfo("worker exited", [], "DagsterSubprocessError"),
                failure_reason=RunFailureReason.RUN_EXCEPTION,
            ),
        ), run.run_id)
        original = instance.get_records_for_run
        pages = []

        def history(**kwargs):
            if kwargs["of_type"] != DagsterEventType.STEP_FAILURE:
                return original(**kwargs)
            assert kwargs["limit"] == 100
            cursor = kwargs.get("cursor")
            pages.append(cursor)
            second = cursor == "page2"
            data = SimpleNamespace(
                error=SimpleNamespace(cls_name="ValueError" if second and late_provider_failure
                                      else "ChildProcessCrashException"),
                error_source=ErrorSource.USER_CODE_ERROR if second and late_provider_failure
                             else ErrorSource.FRAMEWORK_ERROR,
                user_failure_data=None,
            )
            if not second:
                clock[0] = 6.0  # 실제 sleep 없이 첫 page 뒤 tick 예산을 소진한다.
            return SimpleNamespace(
                records=[SimpleNamespace(
                    storage_id=102 if second else index + 2,
                    event_log_entry=SimpleNamespace(dagster_event=SimpleNamespace(event_specific_data=data)),
                ) for index in range(1 if second else 100)],
                has_more=not second, cursor="end" if second else "page2",
            )

        monkeypatch.setattr(instance, "get_records_for_run", history)
        first = sensor.evaluate_tick(build_sensor_context(instance=instance))
        assert first.run_requests == [] and first.cursor.startswith("steps:")
        assert "kortravelcommon/infra_retry_pending" not in instance.get_run_by_id(run.run_id).tags
        clock[0] = 0.0
        second = sensor.evaluate_tick(build_sensor_context(instance=instance, cursor=first.cursor))
        assert pages == [None, "page2"]
        assert len(second.run_requests) == (0 if late_provider_failure else 1)
