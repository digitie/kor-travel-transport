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
            # sensor 재평가는 같은 key를 발급해 daemon의 run-key 중복 방지를 유지한다.
            again = sensor.evaluate_tick(build_sensor_context(instance=instance))
            assert [r.run_key for r in again.run_requests] == [request.run_key]
