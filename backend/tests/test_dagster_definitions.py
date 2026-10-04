from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.dagster import definitions as dagster_definitions
from app.dagster.definitions import definitions


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
            return {"status": status, "run_id": 19387, "errors": ["secret-provider-detail"]}

        async def close(self):
            lifecycle.append("closed")

    async def committed_run(settings, action, **kwargs):
        result = await action(None, **kwargs)
        lifecycle.append("committed")
        return result

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
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
        assert "secret-provider-detail" not in str(failure)


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


@pytest.mark.parametrize("status", ["success", "skipped", "partial_success"])
def test_kakao_place_partial_result_is_a_dagster_failure_without_retry(monkeypatch, status):
    async def fake_run_with_session(*_args, **_kwargs):
        return {"status": status, "run_id": 12, "deferred": int(status == "partial_success")}

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "KakaoPlaceCollectionService",
                        lambda _: SimpleNamespace(collect=None))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run_with_session)
    result = dagster_definitions.kakao_place_location_collection_job.execute_in_process(raise_on_error=False)
    assert result.success is (status != "partial_success")
    assert not any(event.is_step_up_for_retry for event in result.all_events)
    if status == "partial_success":
        failure = result.failure_data_for_node("collect_kakao_place_locations").user_failure_data
        assert failure.metadata["deferred"].value == 1


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


@pytest.mark.parametrize("failed_calls", [0, 1])
def test_maritime_partial_collection_is_not_dagster_success(monkeypatch, failed_calls) -> None:
    invoked = []
    async def fake_run(_settings, action, *_args, **_kwargs):
        invoked.append(action)
        if action == "reference":
            return {"status": "partial_success", "run_id": 10, "port_location_failed_calls": failed_calls,
                    "port_location_deferred_count": 2}
        return {"status": "success", "run_id": 11}
    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "RailMaritimeCollectionService",
                        lambda _: SimpleNamespace(collect_maritime_reference="reference"))
    monkeypatch.setattr(dagster_definitions, "PlaceLocationCollectionService",
                        lambda _: SimpleNamespace(collect="vworld"))
    monkeypatch.setattr(dagster_definitions, "KakaoPlaceCollectionService",
                        lambda _: SimpleNamespace(collect="kakao"))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run)
    result = dagster_definitions.maritime_reference_collection_job.execute_in_process(raise_on_error=False)
    assert result.success is False
    assert invoked == ["reference", "vworld", "kakao"]
    assert not any(event.is_step_up_for_retry for event in result.all_events)
    failure = result.failure_data_for_node("enrich_new_reference_locations").user_failure_data
    assert failure.metadata["reference_deferred"].value == 2


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
