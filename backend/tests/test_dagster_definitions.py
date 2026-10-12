from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.dagster import definitions as dagster_definitions
from app.dagster.definitions import definitions
from app.services.transport_collection import TransportCollectionService


def test_native_disabled_retry_sensors_target_only_three_idempotent_jobs():
    from dagster import Definitions

    Definitions.validate_loadable(definitions)
    sensors = definitions.get_repository_def().sensor_defs
    retry_sensors = [item for item in sensors if item.name.startswith("transport_infra_retry_")]
    expected = {"airport_collection_job", "highway_collection_job", "rest_area_reference_collection_job"}
    assert {item.name.removeprefix("transport_infra_retry_") for item in retry_sensors} == expected
    assert all(item.default_status.name == "RUNNING" for item in retry_sensors)
    assert all(item.minimum_interval_seconds == 60 for item in retry_sensors)
    assert {item.job.name for item in retry_sensors} == expected


@pytest.mark.parametrize("scope", ["fuel", "highway"])
@pytest.mark.parametrize("status", ["success", "skipped", "failed", "partial_success"])
def test_transport_failure_is_visible_after_commit_without_retry(monkeypatch, scope, status):
    lifecycle = []

    class FakeService:
        def __init__(self, settings):
            pass

        async def collect(self, session, **kwargs):
            # 손으로 쓴 dict가 아니라 실제 서비스의 요약 함수로 만든다. 예전 대역은 `run_id`를 돌려줘
            # 실제 키(`collection_run_id`)와 어긋난 채 통과했고, 운영에서는 실패마다 KeyError가 났다.
            return TransportCollectionService._summary(
                SimpleNamespace(id=19387, status=status), client_mode="live", raw_count=0,
                traffic_count=0, incident_count=0, fuel_station_count=0, fuel_price_count=0,
                errors=["Opinet browser action failed: phase=search:station:region=경기도/용인시수지구:attempt=2; cause=TimeoutError",
                        "GET https://api.example/x?serviceKey=raw-service-key&page=1 secret-provider-detail",
                        "Opinet browser action failed: phase=search:station:region=경기도/용인시수지구:attempt=2; cause=TimeoutError"],
            )

        async def close(self):
            lifecycle.append("closed")

    async def committed_run(settings, action, **kwargs):
        result = await action(None, **kwargs)
        lifecycle.append("committed")
        return result

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "_secret_forms", lambda: ["secret-provider-detail"])
    monkeypatch.setattr(dagster_definitions, "TransportCollectionService", FakeService)
    monkeypatch.setattr(dagster_definitions, "_run_with_session", committed_run)
    job = getattr(dagster_definitions, f"{scope}_collection_job")
    result = job.execute_in_process(raise_on_error=False)
    assert lifecycle == ["committed", "closed"]
    assert result.success is (status in {"success", "skipped"})
    assert not any(event.is_step_up_for_retry for event in result.all_events)
    if not result.success:
        failure = result.failure_data_for_node(f"collect_{scope}_transport").user_failure_data
        assert failure.metadata["run_id"].value == 19387
        assert failure.metadata["status"].value == status
        assert failure.metadata["error_count"].value == 3
        assert failure.description.startswith(f"교통정보 수집에 실패했습니다(status={status}): ")
        # 다음 진단이 DB를 보지 않아도 되게 실제 원인을 싣되(중복은 한 번), 비밀값과 serviceKey 값은 가린다.
        assert failure.description.count("phase=search:station:region=경기도/용인시수지구:attempt=2; cause=TimeoutError") == 1
        assert "serviceKey=<redacted>" in failure.description
        assert "raw-service-key" not in str(failure)
        assert "secret-provider-detail" not in str(failure)


def test_transport_failure_cause_is_redacted_stripped_and_bounded(monkeypatch):
    """krex WAF 차단 페이지(HTML) 같은 긴 원인도 태그를 걷고 잘라서 싣는다. 가림은 태그 제거보다 먼저 한다."""
    monkeypatch.setattr(dagster_definitions, "_secret_forms", lambda: ["k<e>y"])
    waf = ('<!DOCTYPE HTML PUBLIC "-//IETF/DTD HTML 2.0//EN"> <HTML><HEAD> <TITLE>400 Bad Request</TITLE> </HEAD>'
           "<BODY> <H1>Request Blocked</H1> </BODY></HTML> <br><br><br>")
    cause = dagster_definitions._redacted_causes([waf, "x" * 1000, "token k<e>y leaked", waf])
    assert cause.startswith("400 Bad Request Request Blocked | ")
    assert "<" not in cause.replace("<redacted>", "")
    assert "k<e>y" not in cause and "token <redacted> leaked" in cause
    assert max(len(part) for part in cause.split(" | ")) <= dagster_definitions.MAX_FAILURE_CAUSE_CHARS
    assert dagster_definitions._redacted_causes([]) == "원인 미기록"
    assert dagster_definitions._redacted_causes(None) == "원인 미기록"


@pytest.mark.parametrize("status", ["failed", "partial_success"])
def test_airport_failure_reports_collection_run_id(monkeypatch, status):
    """공항 수집 결과도 `collection_run_id`를 쓴다(`CollectionService.collect` 반환 계약)."""

    async def committed_run(settings, action, **kwargs):
        return {"collection_run_id": 512, "status": status, "client_mode": "live", "raw_response_count": 0,
                "snapshot_count": 0, "fee_rule_count": 0, "errors": ["secret-provider-detail"]}

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "CollectionService", lambda _settings: SimpleNamespace(collect=None))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", committed_run)
    result = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False)
    assert not result.success
    failure = result.failure_data_for_node("collect_airport_parking").user_failure_data
    assert failure.description.startswith("공항 수집의 성공분은 저장했지만")
    assert failure.metadata["run_id"].value == 512
    assert failure.metadata["status"].value == status


@pytest.mark.parametrize("status", ["success", "skipped", "partial_success"])
def test_ferry_partial_result_is_a_dagster_failure_without_retry(monkeypatch, status):
    committed = []

    async def fake_run_with_session(*args, **kwargs):
        committed.append(True)
        return {"status": status, "run_id": 7, "failed_provider_calls": int(status == "partial_success")}

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "RailMaritimeCollectionService",
                        lambda _: SimpleNamespace(collect_ferry_timetables=None))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run_with_session)
    result = dagster_definitions.ferry_timetable_collection_job.execute_in_process(raise_on_error=False)
    assert committed == [True]
    assert result.success is (status != "partial_success")
    assert not any(event.is_step_up_for_retry for event in result.all_events)
    if status == "partial_success":
        failure = result.failure_data_for_node("collect_ferry_timetable")
        assert failure.user_failure_data.metadata["failed_provider_calls"].value == 1


_PLACE_JOBS = {
    "vworld": ("place_location_collection_job", "collect_place_locations", "PlaceLocationCollectionService"),
    "kakao": ("kakao_place_location_collection_job", "collect_kakao_place_locations", "KakaoPlaceCollectionService"),
}


def _run_place_job(monkeypatch, provider: str, result: dict | Exception):
    """job을 돌리고 (실행 결과, 그 op의 WARNING 로그 문장들)을 돌려준다."""
    from dagster import DagsterInstance

    job_name, op_name, service_name = _PLACE_JOBS[provider]

    async def fake_run_with_session(*_args, **_kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, service_name, lambda _: SimpleNamespace(collect=None))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run_with_session)
    with DagsterInstance.ephemeral() as instance:
        run = getattr(dagster_definitions, job_name).execute_in_process(raise_on_error=False, instance=instance)
        warnings = [entry.user_message for entry in instance.all_logs(run.run_id)
                    if entry.level == logging.WARNING and entry.step_key == op_name]
    return run, warnings


def _output_metadata(result, op_name: str) -> dict:
    events = [event for event in result.all_events
              if event.step_key == op_name and event.event_type_value == "STEP_OUTPUT"]
    return events[0].event_specific_data.metadata


@pytest.mark.parametrize("provider", ["vworld", "kakao"])
@pytest.mark.parametrize("result", [
    {"status": "success", "run_id": 12, "provider_calls": 3, "deferred": 0, "provider_failed": 0},
    {"status": "skipped", "reason": "another place collection is active"},
    # 호출 예산 소진·VWorld `incomplete`(결과가 100건 상한을 넘어 확정 불가): 오류 없는 유예
    {"status": "partial_success", "run_id": 13, "provider_calls": 9, "deferred": 9, "provider_failed": 0},
    # 카카오 429 뒤 24시간 유예: 호출 없이 대상 전체를 유예한다
    {"status": "partial_success", "run_id": 14, "provider_calls": 0, "deferred": 41, "provider_failed": 0},
])
def test_place_job_deferral_only_ends_success_with_metadata(monkeypatch, provider, result):
    """bus_reference(PR #73)와 같은 규칙: 유예만 있는 실행은 SUCCESS, 건수는 metadata와 warning으로 남긴다.

    운영(2026-09-28~10-11)에서 dagster_place_locations 실행 32회 중 12회가 유예만으로 partial_success였다.
    """
    _job, op_name, _service = _PLACE_JOBS[provider]
    run, warnings = _run_place_job(monkeypatch, provider, result)
    assert run.success
    assert not any(event.is_step_up_for_retry for event in run.all_events)
    metadata = _output_metadata(run, op_name)
    assert metadata["deferred"].value == result.get("deferred", 0)
    assert metadata["provider_failed"].value == 0
    assert metadata["status"].value == result["status"]
    deferred = result.get("deferred", 0)
    if deferred:
        assert len(warnings) == 1 and f"{deferred}건이 유예됐습니다(오류 없음)" in warnings[0]
    else:
        assert warnings == []


@pytest.mark.parametrize("provider", ["vworld", "kakao"])
@pytest.mark.parametrize("result", [
    {"status": "partial_success", "run_id": 15, "provider_calls": 4, "deferred": 2, "provider_failed": 1},
    {"status": "success", "run_id": 16, "provider_calls": 4, "deferred": 0, "provider_failed": 1},
    {"status": "failed", "run_id": 17},
    # 유예로 설명되지 않는 부분 성공은 실패 쪽으로 둔다
    {"status": "partial_success", "run_id": 18, "deferred": 0, "provider_failed": 0},
])
def test_place_job_real_errors_still_fail_without_retry(monkeypatch, provider, result):
    _job, op_name, _service = _PLACE_JOBS[provider]
    run, _warnings = _run_place_job(monkeypatch, provider, result)
    assert not run.success
    assert not any(event.is_step_up_for_retry for event in run.all_events)
    failure = run.failure_data_for_node(op_name).user_failure_data
    assert failure.metadata["run_id"].value == result["run_id"]
    assert failure.metadata["provider_failed"].value == result.get("provider_failed", 0)
    assert "제공기관 호출이 실패했습니다" in failure.description


@pytest.mark.parametrize("provider", ["vworld", "kakao"])
def test_place_job_exception_still_fails_redacted(monkeypatch, provider):
    _job, op_name, _service = _PLACE_JOBS[provider]
    run, _warnings = _run_place_job(monkeypatch, provider,
                                    RuntimeError("https://dapi.kakao.com/?query=x serviceKey=leak"))
    assert not run.success
    failure = run.failure_data_for_node(op_name).user_failure_data
    assert failure.metadata["error_type"].value == "builtins.RuntimeError"
    assert "leak" not in failure.description


def test_dagster_definitions_evaluates_kric_rail_due_daily_with_a_48_hour_guard() -> None:
    rail_schedule = definitions.get_schedule_def("rail_reference_collection_job_schedule")
    maritime_schedule = definitions.get_schedule_def("maritime_reference_collection_job_schedule")
    ferry_timetable_schedule = definitions.get_schedule_def("ferry_timetable_collection_job_schedule")
    bus_schedule = definitions.get_schedule_def("bus_reference_collection_job_schedule")
    place_schedule = definitions.get_schedule_def("place_location_collection_job_schedule")
    kakao_schedule = definitions.get_schedule_def("kakao_place_location_collection_job_schedule")
    kric_schedule = definitions.get_schedule_def("kric_timetable_collection_job_schedule")
    assert kric_schedule.cron_schedule == "0 * * * *"
    assert kric_schedule.execution_timezone == "Asia/Seoul"
    assert kric_schedule.default_status.name == "RUNNING"

    assert rail_schedule.cron_schedule == "0 3 * * *"
    assert maritime_schedule.cron_schedule == "0 3 */3 * *"
    assert ferry_timetable_schedule.cron_schedule == "45 */4 * * *"
    assert bus_schedule.cron_schedule == "30 3 * * *"
    assert place_schedule.cron_schedule == "30 4 * * *"
    assert kakao_schedule.cron_schedule == "30 6 * * *"
    assert rail_schedule.execution_timezone == "Asia/Seoul"
    assert maritime_schedule.execution_timezone == "Asia/Seoul"
    assert ferry_timetable_schedule.execution_timezone == "Asia/Seoul"
    assert bus_schedule.execution_timezone == "Asia/Seoul"
    assert place_schedule.execution_timezone == "Asia/Seoul"
    assert kakao_schedule.execution_timezone == "Asia/Seoul"
    assert rail_schedule.default_status.name == "RUNNING"
    assert maritime_schedule.default_status.name == "RUNNING"
    assert ferry_timetable_schedule.default_status.name == "RUNNING"
    assert bus_schedule.default_status.name == "RUNNING"
    assert place_schedule.default_status.name == "RUNNING"
    assert kakao_schedule.default_status.name == "RUNNING"


def test_dagster_definitions_register_every_collection_domain() -> None:
    job_names = {
        "airport_collection_job",
        "highway_collection_job",
        "fuel_collection_job",
        "rail_reference_collection_job",
        "maritime_reference_collection_job",
        "ferry_timetable_collection_job",
        "bus_reference_collection_job",
        "place_location_collection_job",
        "kakao_place_location_collection_job",
        "kric_timetable_collection_job",
    }
    assert {definitions.get_job_def(name).name for name in job_names} == job_names


@pytest.mark.parametrize("job_name,first_op", [
    ("maritime_reference_collection_job", "collect_maritime_reference"),
    ("bus_reference_collection_job", "collect_bus_reference"),
])
def test_reference_jobs_enrich_coordinates_after_official_rows(job_name: str, first_op: str) -> None:
    graph = definitions.get_job_def(job_name).graph
    assert graph.node_names() == [first_op, "enrich_new_reference_locations"]


def test_dagster_definitions_enable_every_schedule_and_serialize_overlapping_groups() -> None:
    schedule_names = {
        "airport_collection_job_schedule",
        "highway_collection_job_schedule",
        "fuel_collection_job_schedule",
        "rail_reference_collection_job_schedule",
        "maritime_reference_collection_job_schedule",
        "ferry_timetable_collection_job_schedule",
        "bus_reference_collection_job_schedule",
        "place_location_collection_job_schedule",
        "kakao_place_location_collection_job_schedule",
        "kric_timetable_collection_job_schedule",
    }
    assert {definitions.get_schedule_def(name).default_status.name for name in schedule_names} == {"RUNNING"}

    dagster_yaml = (Path(__file__).parents[1] / "dagster_home" / "dagster.yaml").read_text(encoding="utf-8")
    assert "value: parking\n        limit: 1" in dagster_yaml
    assert "value: highway\n        limit: 1" in dagster_yaml
    shared_compose_path = Path(__file__).parents[2] / "docker-compose.shared.yml"
    if not shared_compose_path.exists():
        shared_compose_path = Path("/app/compose-contract/docker-compose.shared.yml")
    shared_compose = shared_compose_path.read_text(encoding="utf-8")
    assert 'RUSTFS_REGION_NAME: "${RUSTFS_REGION_NAME:-us-east-1}"' in shared_compose
    assert 'RUSTFS_RAW_PREFIX: "${RUSTFS_RAW_PREFIX:-provider-raw}"' in shared_compose
    assert 'RUN_DB_MIGRATIONS: "false"' in shared_compose
    assert 'image: "${BACKEND_RUNTIME_IMAGE:-kor-travel-transport-backend:latest}"' in shared_compose


def _run_maritime_with(monkeypatch, reference: dict):
    invoked = []

    async def fake_run(_settings, action, *_args, **_kwargs):
        invoked.append(action)
        if action == "reference":
            return reference
        return {"status": "success", "run_id": 11, "deferred": 0, "provider_failed": 0}
    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "RailMaritimeCollectionService",
                        lambda _: SimpleNamespace(collect_maritime_reference="reference"))
    monkeypatch.setattr(dagster_definitions, "PlaceLocationCollectionService",
                        lambda _: SimpleNamespace(collect="vworld"))
    monkeypatch.setattr(dagster_definitions, "KakaoPlaceCollectionService",
                        lambda _: SimpleNamespace(collect="kakao"))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run)
    result = dagster_definitions.maritime_reference_collection_job.execute_in_process(raise_on_error=False)
    assert invoked == ["reference", "vworld", "kakao"]
    assert not any(event.is_step_up_for_retry for event in result.all_events)
    return result


@pytest.mark.parametrize("deferred", [0, 2])
def test_maritime_port_lookup_failure_is_not_dagster_success(monkeypatch, deferred) -> None:
    """이번 실행의 기항지 위치 조회가 실패(`port_location_failed_calls>0`)한 partial_success는 계속 실패다."""
    result = _run_maritime_with(monkeypatch, {"status": "partial_success", "run_id": 10,
                                              "port_location_failed_calls": 1,
                                              "port_location_deferred_count": deferred})
    assert result.success is False
    failure = result.failure_data_for_node("enrich_new_reference_locations").user_failure_data
    assert failure.metadata["reference_failed_calls"].value == 1
    assert failure.metadata["reference_deferred"].value == deferred
    assert failure.metadata["failed_parts"].value == "reference"
    assert "reference_failed_calls>0" in failure.description


def test_maritime_port_lookup_deferral_only_is_success(monkeypatch) -> None:
    """PR #73 리뷰 지적: 유예(`port_location_deferred_count>0`)만으로 maritime job이 FAILURE가 됐다.

    유예는 실패 TTL(전날 실패한 항구는 하루 쉬기)·429 뒤 24시간 유예·일일 80회 예산이며, 이번 실행에 호출 실패가 없다.
    """
    result = _run_maritime_with(monkeypatch, {"status": "partial_success", "run_id": 10,
                                              "port_location_failed_calls": 0,
                                              "port_location_deferred_count": 2})
    assert result.success
    metadata = _output_metadata(result, "enrich_new_reference_locations")
    assert metadata["reference_deferred"].value == 2
    assert metadata["reference_failed_calls"].value == 0


def test_unexplained_reference_partial_success_still_fails(monkeypatch) -> None:
    """유예로도 호출 실패로도 설명되지 않는 기준정보 partial_success는 실패 쪽으로 둔다."""
    result = _run_maritime_with(monkeypatch, {"status": "partial_success", "run_id": 10,
                                              "port_location_failed_calls": 0,
                                              "port_location_deferred_count": 0})
    assert result.success is False


def test_reference_enrichment_continues_kakao_after_vworld_exception(monkeypatch) -> None:
    invoked = []
    async def fake_run(_settings, action, *_args, **_kwargs):
        invoked.append(action)
        if action == "vworld":
            raise RuntimeError("provider URL with secret must not be logged")
        return {"status": "success", "run_id": 42}
    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "BusReferenceCollectionService",
                        lambda _: SimpleNamespace(collect="reference"))
    monkeypatch.setattr(dagster_definitions, "PlaceLocationCollectionService",
                        lambda _: SimpleNamespace(collect="vworld"))
    monkeypatch.setattr(dagster_definitions, "KakaoPlaceCollectionService",
                        lambda _: SimpleNamespace(collect="kakao"))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run)
    result = dagster_definitions.bus_reference_collection_job.execute_in_process(raise_on_error=False)
    assert result.success is False
    assert invoked == ["reference", "vworld", "kakao"]
    failure = result.failure_data_for_node("enrich_new_reference_locations").user_failure_data
    assert failure.metadata["vworld_status"].value == "failed"
    assert "provider URL with secret" not in str(failure)


def _run_bus_reference_with(monkeypatch, vworld: dict, kakao: dict):
    async def fake_run(_settings, action, *_args, **_kwargs):
        return {"reference": {"status": "success", "run_id": 40}, "vworld": vworld, "kakao": kakao}[action]

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "BusReferenceCollectionService", lambda _: SimpleNamespace(collect="reference"))
    monkeypatch.setattr(dagster_definitions, "PlaceLocationCollectionService", lambda _: SimpleNamespace(collect="vworld"))
    monkeypatch.setattr(dagster_definitions, "KakaoPlaceCollectionService", lambda _: SimpleNamespace(collect="kakao"))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run)
    return dagster_definitions.bus_reference_collection_job.execute_in_process(raise_on_error=False)


def test_reference_enrichment_deferral_only_is_success_with_metadata(monkeypatch):
    """유예만 있는 날(예: VWorld 검색 결과가 100건 상한을 넘어 `incomplete`)은 run을 실패로 만들지 않는다.

    운영(2026-10-03~09)에서 같은 9개 이름이 매일 `incomplete`로 유예돼 bus_reference_collection_job이
    매일 FAILURE였다. 유예 건수는 output metadata로 남긴다.
    """
    vworld = {"status": "partial_success", "run_id": 26132, "provider_calls": 9, "deferred": 9, "provider_failed": 0}
    kakao = {"status": "success", "run_id": 26133, "provider_calls": 0, "deferred": 0, "provider_failed": 0}
    result = _run_bus_reference_with(monkeypatch, vworld, kakao)
    assert result.success
    output = result.output_for_node("enrich_new_reference_locations")
    assert output["vworld"]["deferred"] == 9
    materialized = [event for event in result.all_events
                    if event.step_key == "enrich_new_reference_locations" and event.event_type_value == "STEP_OUTPUT"]
    metadata = materialized[0].event_specific_data.metadata
    assert metadata["vworld_deferred"].value == 9
    assert metadata["vworld_status"].value == "partial_success"
    assert metadata["kakao_deferred"].value == 0


@pytest.mark.parametrize("provider", ["vworld", "kakao"])
def test_reference_enrichment_provider_errors_still_fail(monkeypatch, provider):
    partial = {"status": "partial_success", "run_id": 7, "deferred": 1, "provider_failed": 1}
    ok = {"status": "success", "run_id": 8, "deferred": 0, "provider_failed": 0}
    result = _run_bus_reference_with(monkeypatch, *((partial, ok) if provider == "vworld" else (ok, partial)))
    assert not result.success
    failure = result.failure_data_for_node("enrich_new_reference_locations").user_failure_data
    assert failure.metadata[f"{provider}_provider_failed"].value == 1
    assert failure.metadata[f"{provider}_status"].value == "partial_success"


def test_reference_enrichment_does_not_continue_after_lease_revocation(monkeypatch):
    from app.dagster.recovery import CollectionLeaseLost

    invoked = []

    async def fake_run(_settings, action, *_args, **_kwargs):
        invoked.append(action)
        if action == "vworld":
            raise CollectionLeaseLost("revoked")
        return {"status": "success", "run_id": 42}

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "BusReferenceCollectionService", lambda _: SimpleNamespace(collect="reference"))
    monkeypatch.setattr(dagster_definitions, "PlaceLocationCollectionService", lambda _: SimpleNamespace(collect="vworld"))
    monkeypatch.setattr(dagster_definitions, "KakaoPlaceCollectionService", lambda _: SimpleNamespace(collect="kakao"))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run)
    result = dagster_definitions.bus_reference_collection_job.execute_in_process(raise_on_error=False)
    assert not result.success
    assert invoked == ["reference", "vworld"]


async def test_terminal_native_owner_does_not_start_a_fresh_provider_session():
    from dagster import DagsterInstance, DagsterRunStatus
    from app.dagster.recovery import CollectionLeaseLost, collection_owner

    async def provider(_session):
        pytest.fail("종료된 owner의 provider를 호출해서는 안 된다")

    with DagsterInstance.local_temp() as instance:
        run = instance.create_run_for_job(dagster_definitions.airport_collection_job, status=DagsterRunStatus.FAILURE)
        with collection_owner(run.run_id, instance):
            with pytest.raises(CollectionLeaseLost):
                await dagster_definitions._run_with_session(
                    Settings(database_url="sqlite+aiosqlite:///unused.sqlite3"), provider
                )


async def test_owner_metadata_error_is_fail_closed_without_revoking_a_live_owner(monkeypatch):
    from dagster import DagsterInstance, DagsterRunStatus
    from app.dagster.recovery import collection_owner

    calls = []

    async def provider(_session):
        calls.append("provider")
        return {"status": "success"}

    with DagsterInstance.local_temp() as instance:
        run = instance.create_run_for_job(dagster_definitions.airport_collection_job, status=DagsterRunStatus.STARTED)
        original = instance.get_run_by_id
        with collection_owner(run.run_id, instance):
            monkeypatch.setattr(instance, "get_run_by_id", lambda _: (_ for _ in ()).throw(ConnectionError("metadata offline")))
            with pytest.raises(ConnectionError):
                await dagster_definitions._run_with_session(Settings(database_url="sqlite+aiosqlite://"), provider)
            assert calls == []
            monkeypatch.setattr(instance, "get_run_by_id", original)
            assert await dagster_definitions._run_with_session(Settings(database_url="sqlite+aiosqlite://"), provider) == {"status": "success"}
            assert calls == ["provider"]


def test_transport_provider_lifecycle_stays_in_one_event_loop(monkeypatch) -> None:
    loop_ids: list[int] = []

    class FakeTransportService:
        def __init__(self, _settings: Settings) -> None:
            pass

        async def collect(self, _session, *, trigger: str, scope: str) -> dict[str, str]:
            loop_ids.append(id(asyncio.get_running_loop()))
            assert trigger == "dagster_fuel"
            assert scope == "fuel"
            return {"status": "success"}

        async def close(self) -> None:
            loop_ids.append(id(asyncio.get_running_loop()))

    async def fake_run_with_session(_settings, action, *args, **kwargs):
        return await action(None, *args, **kwargs)

    monkeypatch.setattr(dagster_definitions, "TransportCollectionService", FakeTransportService)
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run_with_session)

    result = asyncio.run(
        dagster_definitions._collect_transport_in_one_loop(
            Settings(database_url="sqlite+aiosqlite:///unused.sqlite3", scheduler_mode="dagster"), "fuel"
        )
    )

    assert result == {"status": "success"}
    assert len(loop_ids) == 2
    assert loop_ids[0] == loop_ids[1]
