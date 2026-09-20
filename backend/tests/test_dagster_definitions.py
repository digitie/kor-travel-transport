from __future__ import annotations

from app.dagster.definitions import definitions


def test_dagster_definitions_keep_rail_and_maritime_reference_jobs_every_three_days() -> None:
    rail_schedule = definitions.get_schedule_def("rail_reference_collection_job_schedule")
    maritime_schedule = definitions.get_schedule_def("maritime_reference_collection_job_schedule")

    assert rail_schedule.cron_schedule == "0 3 */3 * *"
    assert maritime_schedule.cron_schedule == "0 3 */3 * *"
    assert rail_schedule.execution_timezone == "Asia/Seoul"
    assert maritime_schedule.execution_timezone == "Asia/Seoul"


def test_dagster_definitions_register_every_collection_domain() -> None:
    job_names = {
        "airport_collection_job",
        "highway_collection_job",
        "fuel_collection_job",
        "rail_reference_collection_job",
        "maritime_reference_collection_job",
    }
    assert {definitions.get_job_def(name).name for name in job_names} == job_names
