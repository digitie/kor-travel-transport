from __future__ import annotations

import asyncio
from pathlib import Path

from app.core.config import Settings
from app.dagster import definitions as dagster_definitions
from app.dagster.definitions import definitions


def test_dagster_definitions_evaluates_kric_rail_due_daily_with_a_48_hour_guard() -> None:
    rail_schedule = definitions.get_schedule_def("rail_reference_collection_job_schedule")
    maritime_schedule = definitions.get_schedule_def("maritime_reference_collection_job_schedule")
    ferry_timetable_schedule = definitions.get_schedule_def("ferry_timetable_collection_job_schedule")
    bus_schedule = definitions.get_schedule_def("bus_reference_collection_job_schedule")

    assert rail_schedule.cron_schedule == "0 3 * * *"
    assert maritime_schedule.cron_schedule == "0 3 */3 * *"
    assert ferry_timetable_schedule.cron_schedule == "45 3 * * *"
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
    assert 'image: "${BACKEND_RUNTIME_IMAGE:-kor-travel-airport-backend:latest}"' in shared_compose


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
