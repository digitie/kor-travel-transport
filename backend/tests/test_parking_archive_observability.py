"""실제 Dagster 성공 event와 저장 로그에 주차 backfill의 업무 결과가 남는다."""
import logging
import asyncio
from datetime import timedelta

import pytest
from dagster import DagsterInstance
from sqlalchemy import create_engine, select, text

from app.dagster import definitions as module
from app.db.session import create_engine_and_session_factory
from app.models import Airport, ParkingLot, ParkingStatisticsBucket
from app.services.parking_statistics_archive import archive_parking_statistics
from test_parking_statistics_archive import AT, NOW, database, snapshot


@pytest.mark.parametrize("status,coverage,archived,deferred", [
    ("busy", "not_audited", 0, 0),
    ("no_new_rows", "not_audited", 0, 0),
    ("batch_complete", "partial", 0, 1),
    ("batch_complete", "partial", 2, 1),
    ("deferred", "partial", 0, 1),
])
def test_successful_job_persists_business_outcome_and_scope(monkeypatch, status, coverage, archived, deferred):
    selected = status == "batch_complete"
    payload = {"status": status, "coverage_status": coverage,
               "archived_buckets": archived, "deferred_buckets": deferred, "pruned_snapshots": 0,
               "checked_at": "2026-10-27T15:00:00+00:00",
               "raw_cutoff_at": "2026-10-25T15:00:00+00:00",
               "complete_before": "2026-10-25T15:00:00+00:00",
               "selection_start_at": "2026-10-20T15:00:00+00:00" if selected else None,
               "selection_end_exclusive": "2026-10-21T15:00:00+00:00" if selected else None,
               "selected_snapshots": 8 if selected else 0, "selected_buckets": 4 if selected else 0,
               "verified_buckets": 3 if selected else 0,
               "verified_min_bucket_at": "2026-10-20T15:00:00+00:00" if selected else None,
               "verified_max_bucket_at": "2026-10-20T15:20:00+00:00" if selected else None,
               "archived_min_bucket_at": "2026-10-20T15:10:00+00:00" if archived else None,
               "archived_max_bucket_at": "2026-10-20T15:20:00+00:00" if archived else None,
               "verification_scope": "selected_bucket_subset" if selected else "none",
               "verification_domain": "airport_statistics", "airport_status": status,
               "airport_coverage_status": coverage, "global_status": "no_new_rows",
               "global_coverage_status": "not_audited", "global_buckets": 0,
               "global_verified_buckets": 0, "global_deferred_buckets": 0,
               "global_selection_start_at": None, "global_selection_end_exclusive": None,
               "global_verification_scope": "none", "latest_seeded": 2}

    async def fake_run(_settings, action):
        assert action is module.archive_parking_with_coverage
        return payload

    monkeypatch.setattr(module, "_settings", lambda: None)
    monkeypatch.setattr(module, "_run_with_session", fake_run)
    with DagsterInstance.ephemeral() as instance:
        result = module.parking_statistics_archive_job.execute_in_process(instance=instance)
        assert result.success  # busy/미검산을 강제 실패로 바꾸는 보완이 아니다.
        output = next(event.event_specific_data for event in result.all_events
                      if event.step_key == "archive_airport_parking_statistics" and event.event_type_value == "STEP_OUTPUT")
        metadata = {key: value.value for key, value in output.metadata.items()}
        for key, value in payload.items():
            assert metadata[key] == value
        logs = [entry.user_message for entry in instance.all_logs(result.run_id)
                if entry.step_key == "archive_airport_parking_statistics" and entry.level == logging.INFO]
        assert any(f"status={status}" in line and f"coverage_status={coverage}" in line
                   and "pruned_snapshots=0" in line and "global_status=no_new_rows" in line for line in logs)


def test_blocked_job_persists_failure_scope_without_exposing_unlisted_payload(monkeypatch):
    payload = {"status": "blocked", "coverage_status": "conflict", "pruned_snapshots": 0,
               "blocked_scope": "global", "blocked_reason": "sealed_raw_mismatch",
               "blocked_bucket_at": AT.isoformat(), "global_buckets": 1,
               "global_verified_buckets": 2, "global_status": "blocked",
               "global_coverage_status": "conflict", "raw_payload": "공개 금지"}

    async def fake_run(_settings, action):
        assert action is module.archive_parking_with_coverage
        return payload

    monkeypatch.setattr(module, "_settings", lambda: None)
    monkeypatch.setattr(module, "_run_with_session", fake_run)
    with DagsterInstance.ephemeral() as instance:
        result = module.parking_statistics_archive_job.execute_in_process(instance=instance, raise_on_error=False)
        assert not result.success
        failure = next(event.event_specific_data for event in result.all_events
                       if event.event_type_value == "STEP_FAILURE")
        metadata = {k: v.value for k, v in failure.user_failure_data.metadata.items()}
        assert metadata["status"] == "blocked" and metadata["global_buckets"] == 1
        assert metadata["blocked_reason"] == "sealed_raw_mismatch"
        assert "raw_payload" not in metadata


@pytest.mark.parametrize("busy", [False, True])
def test_real_database_job_success_records_no_audit_outcome(tmp_path, test_settings, monkeypatch, busy):
    if busy and not test_settings.database_url.startswith("postgresql"):
        pytest.skip("실제 PostgreSQL advisory lock 검증")
    async def prepare():
        engine, _factory = await database(tmp_path, test_settings)
        url = engine.url.render_as_string(hide_password=False)
        await engine.dispose()
        return url
    database_url = asyncio.run(prepare())

    async def real_run(_settings, action):
        engine, factory = create_engine_and_session_factory(database_url)
        try:
            async with factory() as session:
                result = await action(session, checked_at=NOW)
                await session.commit()
                return result
        finally:
            await engine.dispose()

    monkeypatch.setattr(module, "_settings", lambda: None)
    monkeypatch.setattr(module, "_run_with_session", real_run)
    lock_engine = connection = None
    try:
        if busy:
            lock_engine = create_engine(test_settings.database_url.replace("+asyncpg", "+psycopg2"))
            connection = lock_engine.connect()
            connection.execute(text("SELECT pg_advisory_lock(hashtext('kor_travel_transport:airport_collection'))"))
        result = module.parking_statistics_archive_job.execute_in_process()
        assert result.success
        metadata = next(event.event_specific_data.metadata for event in result.all_events
                        if event.step_key == "archive_airport_parking_statistics" and event.event_type_value == "STEP_OUTPUT")
        assert metadata["status"].value == ("busy" if busy else "no_new_rows")
        assert metadata["coverage_status"].value == "not_audited"
        assert metadata["verification_scope"].value == "none"
        assert metadata["selection_start_at"].value is None
        assert metadata["verified_buckets"].value == metadata["archived_buckets"].value == 0
        assert metadata["raw_cutoff_at"].value == (NOW - timedelta(hours=48)).isoformat()
    finally:
        if connection is not None:
            connection.execute(text("SELECT pg_advisory_unlock(hashtext('kor_travel_transport:airport_collection'))"))
            connection.close()
        if lock_engine is not None:
            lock_engine.dispose()


@pytest.mark.asyncio
async def test_service_reports_selection_and_verified_published_extrema_separately(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add(Airport(id=2, code="CJU", name_ko="제주", source="kac", created_at=AT, updated_at=AT))
            await session.flush()
            session.add(ParkingLot(id=2, airport_id=2, source_lot_id="P2", name="제주주차장",
                                   is_active=True, created_at=AT, updated_at=AT))
            await session.flush()
            second = snapshot(2, 0, 20, lot=2)
            second.airport_id = 2
            session.add_all([snapshot(1, 0, 40), second])
            await session.commit()
            first = await archive_parking_statistics(session, checked_at=NOW, max_buckets=1)
            await session.commit()
            assert first["selected_snapshots"] == first["selected_buckets"] == 2
            assert first["selection_start_at"] == first["selected_observed_min_at"] == AT.isoformat()
            assert first["selection_end_exclusive"] == (AT + timedelta(days=1)).isoformat()
            assert first["verified_buckets"] == first["archived_buckets"] == 1
            second_run = await archive_parking_statistics(session, checked_at=NOW, max_buckets=1)
            await session.commit()
            assert second_run["verified_buckets"] == 2 and second_run["archived_buckets"] == 1
            assert second_run["verified_min_bucket_at"] == second_run["verified_max_bucket_at"] == AT.isoformat()
            assert second_run["archived_min_bucket_at"] == second_run["archived_max_bucket_at"] == AT.isoformat()
            assert second_run["verification_scope"] == "selected_bucket_subset"
            assert len(list((await session.scalars(select(ParkingStatisticsBucket))).all())) == 2
            final = await archive_parking_statistics(session, checked_at=NOW)
            assert final["coverage_status"] == "not_audited" and final["verified_buckets"] == 0
            assert final["selection_start_at"] is final["archived_min_bucket_at"] is None
    finally:
        await engine.dispose()
