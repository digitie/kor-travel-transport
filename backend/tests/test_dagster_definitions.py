from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.dagster import definitions as dagster_definitions
from app.dagster.definitions import definitions


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


def test_dagster_definitions_evaluates_kric_rail_due_daily_with_a_48_hour_guard() -> None:
    rail_schedule = definitions.get_schedule_def("rail_reference_collection_job_schedule")
    maritime_schedule = definitions.get_schedule_def("maritime_reference_collection_job_schedule")
    ferry_timetable_schedule = definitions.get_schedule_def("ferry_timetable_collection_job_schedule")
    bus_schedule = definitions.get_schedule_def("bus_reference_collection_job_schedule")
    kric_schedule = definitions.get_schedule_def("kric_timetable_collection_job_schedule")
    assert kric_schedule.cron_schedule == "0 * * * *"
    assert kric_schedule.execution_timezone == "Asia/Seoul"
    assert kric_schedule.default_status.name == "RUNNING"

    assert rail_schedule.cron_schedule == "0 3 * * *"
    assert maritime_schedule.cron_schedule == "0 3 */3 * *"
    assert ferry_timetable_schedule.cron_schedule == "45 */4 * * *"
    assert bus_schedule.cron_schedule == "30 3 * * *"
    assert rail_schedule.execution_timezone == "Asia/Seoul"
    assert maritime_schedule.execution_timezone == "Asia/Seoul"
    assert ferry_timetable_schedule.execution_timezone == "Asia/Seoul"
    assert bus_schedule.execution_timezone == "Asia/Seoul"
    assert rail_schedule.default_status.name == "RUNNING"
    assert maritime_schedule.default_status.name == "RUNNING"
    assert ferry_timetable_schedule.default_status.name == "RUNNING"
    assert bus_schedule.default_status.name == "RUNNING"


def test_dagster_definitions_register_every_collection_domain() -> None:
    job_names = {
        "airport_collection_job",
        "highway_collection_job",
        "fuel_collection_job",
        "rail_reference_collection_job",
        "maritime_reference_collection_job",
        "ferry_timetable_collection_job",
        "bus_reference_collection_job",
        "kric_timetable_collection_job",
    }
    assert {definitions.get_job_def(name).name for name in job_names} == job_names


def test_dagster_definitions_enable_every_schedule_and_serialize_overlapping_groups() -> None:
    schedule_names = {
        "airport_collection_job_schedule",
        "highway_collection_job_schedule",
        "fuel_collection_job_schedule",
        "rail_reference_collection_job_schedule",
        "maritime_reference_collection_job_schedule",
        "ferry_timetable_collection_job_schedule",
        "bus_reference_collection_job_schedule",
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
    from dagster import Failure

    async def fake_run(*_args, **_kwargs):
        return {"status": "partial_success", "run_id": 10, "port_location_failed_calls": failed_calls,
                "port_location_deferred_count": 2}
    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "RailMaritimeCollectionService",
                        lambda _: SimpleNamespace(collect_maritime_reference=None))
    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run)
    with pytest.raises(Failure, match="기항지") as raised:
        dagster_definitions._collect_reference("maritime")
    assert raised.value.allow_retries is False
    assert raised.value.metadata["deferred_port_locations"].value == 2


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
