from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, func, select

from app.db.session import create_engine_and_session_factory, init_database
from app.models import Airport, ParkingLot, ParkingSnapshot, ParkingStatisticsBucket
from app.services.parking_statistics_archive import (
    ParkingArchiveConflict, _digest, archive_parking_statistics, bucket_start,
    build_bucket, prune_parking_raw, raw_digest, verify_bucket,
)

AT = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)  # KST 자정
NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


def snapshot(identity, minute, available, *, lot=1, source="live", collected=None, capacity=100):
    return ParkingSnapshot(id=identity, airport_id=1, parking_lot_id=lot, source=source,
        observed_at=AT + timedelta(minutes=minute), collected_at=collected or AT + timedelta(minutes=minute),
        total_spaces=capacity, occupied_spaces=max(capacity - available, 0), available_spaces=available,
        raw_item_json={"provider_detail": "원본 문자열"})


def test_sufficient_statistics_preserve_weights_minmax_and_simultaneous_airport_scope():
    rows = [snapshot(1, 0, 90), snapshot(2, 5, 10), snapshot(3, 5, 20, lot=2)]
    payload, count = build_bucket(rows, {})
    assert count == 3
    assert payload["lots"][0]["available"] == {"count": 2, "sum": 100, "min": 10, "max": 90}
    # 주차장 평균의 평균 (50+20)/2=35가 아니라 전체 표본 평균120/3이다.
    assert sum(lot["available"]["sum"] for lot in payload["lots"]) == 120
    assert sum(lot["available"]["count"] for lot in payload["lots"]) == 3
    # 공휴일 공항 통계는 같은 timestamp 합산(90, 10+20)이다.
    assert payload["airport_cohorts"] == {"count": 2, "sum": 120, "min": 30, "max": 90}
    assert "provider_detail" not in str(payload)
    assert len(payload["lots"]) == 2
    assert payload["lots"][0]["first"]["observed_at"] == AT.isoformat()


def test_live_source_preference_and_capacity_positive_outlook_cohort():
    rows = [snapshot(1, 0, 20), snapshot(2, 0, 90, source="migration_http"),
            snapshot(3, 5, 0, capacity=0), snapshot(4, 6, 40), snapshot(5, 7, 0, capacity=0)]
    payload, count = build_bucket(rows, {})
    assert count == 4
    lot = payload["lots"][0]
    assert lot["available"] == {"count": 4, "sum": 60, "min": 0, "max": 40}
    assert lot["positive_capacity"] == {"count": 2, "sum": 60, "min": 20, "max": 40,
                                         "capacity_min": 100, "capacity_max": 100,
                                         "latest_observed_at": (AT + timedelta(minutes=6)).isoformat()}
    assert lot["last"]["total"] == 0
    assert lot["last"]["observed_at"] == (AT + timedelta(minutes=7)).isoformat()


def test_exact_threshold_crossings_include_previous_bucket_and_preserve_gaps():
    previous = {1: snapshot(1, -60, 60)}
    payload, _ = build_bucket([snapshot(2, 0, 5), snapshot(3, 5, 55)], previous)
    assert [(event["threshold"], event["direction"]) for event in payload["events"]] == [
        (10, "down"), (50, "down"), (10, "up"), (50, "up")]
    assert payload["events"][0]["previous_at"] == (AT - timedelta(hours=1)).isoformat()
    # 기존 원관측 이벤트와 같은 gap 계약이다. 시간 공백을 숨기지 않도록 previous_at을 보존한다.
    assert previous[1].available_spaces == 55
    assert build_bucket([snapshot(4, 0, 5)], {})[0]["events"] == []


def test_bucket_boundary_and_single_airport_validation():
    assert bucket_start(AT + timedelta(minutes=10)) == AT + timedelta(minutes=10)
    assert bucket_start(AT + timedelta(minutes=9, seconds=59)) == AT
    with pytest.raises(ValueError):
        build_bucket([snapshot(1, 0, 10), snapshot(2, 10, 5)], {})


def test_verifier_recomputes_statistics_and_events_instead_of_trusting_stored_checksum():
    rows = [snapshot(1, 0, 50), snapshot(2, 5, 5)]
    payload, count = build_bucket(rows, {})
    record = SimpleNamespace(format_version=1, raw_count=2, selected_count=count, max_snapshot_id=2, airport_id=1,
        bucket_at=AT, bucket_end=AT + timedelta(minutes=10), raw_sha256=raw_digest(rows),
        statistics_sha256=_digest(payload), statistics_json=payload)
    verify_bucket(record, rows, {})
    payload["events"] = []
    record.statistics_sha256 = _digest(payload)
    with pytest.raises(ParkingArchiveConflict):
        verify_bucket(record, rows, {})


async def database(tmp_path, test_settings):
    database_url = test_settings.database_url if test_settings.database_url.startswith("postgresql") else f"sqlite+aiosqlite:///{tmp_path / 'archive.sqlite'}"
    engine, factory = create_engine_and_session_factory(database_url)
    await init_database(engine)
    async with factory() as session:
        session.add(Airport(id=1, code="GMP", name_ko="김포", source="kac", created_at=AT, updated_at=AT))
        await session.flush()
        session.add(ParkingLot(id=1, airport_id=1, source_lot_id="P1", name="제1주차장",
                               is_active=True, created_at=AT, updated_at=AT))
        await session.commit()
    return engine, factory


@pytest.mark.asyncio
async def test_backfill_resumes_after_batch_and_never_changes_originals(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add_all([snapshot(1, 0, 50), snapshot(2, 5, 5), snapshot(3, 10, 55)])
            await session.commit()
            raw_before = raw_digest(list((await session.scalars(select(ParkingSnapshot))).all()))
            one = await archive_parking_statistics(session, checked_at=NOW, max_buckets=1)
            await session.commit()
            assert one["archived_buckets"] == 1
            two = await archive_parking_statistics(session, checked_at=NOW, max_buckets=1)
            await session.commit()
            assert two["archived_buckets"] == 1
            three = await archive_parking_statistics(session, checked_at=NOW)
            assert three["status"] == "no_new_rows"
            assert three["coverage_status"] == "not_audited"
            assert await session.scalar(select(func.count()).select_from(ParkingStatisticsBucket)) == 2
            assert raw_digest(list((await session.scalars(select(ParkingSnapshot))).all())) == raw_before
            buckets = list((await session.scalars(select(ParkingStatisticsBucket).order_by(ParkingStatisticsBucket.bucket_at))).all())
            assert len(buckets[1].statistics_json["events"]) == 2  # 이전 bucket=5 →55
            assert one["pruned_snapshots"] == two["pruned_snapshots"] == 0
            with pytest.raises(RuntimeError, match="읽기 전환"):
                await prune_parking_raw(session)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recent_arrival_is_deferred_and_rollback_leaves_no_archive(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add_all([snapshot(1, 0, 50), snapshot(2, 10, 5, collected=NOW - timedelta(hours=1))])
            await session.commit()
            result = await archive_parking_statistics(session, checked_at=NOW)
            assert result["archived_buckets"] == 1 and result["deferred_buckets"] == 1
            await session.rollback()
            assert await session.scalar(select(func.count()).select_from(ParkingStatisticsBucket)) == 0
            assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_late_new_row_in_sealed_bucket_fails_closed_and_preserves_both(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add(snapshot(1, 0, 50))
            await session.commit()
            await archive_parking_statistics(session, checked_at=NOW)
            await session.commit()
            before = (await session.get(ParkingStatisticsBucket, (1, AT))).statistics_sha256
            session.add(snapshot(2, 5, 5))
            await session.commit()
            with pytest.raises(ParkingArchiveConflict):
                await archive_parking_statistics(session, checked_at=NOW)
            await session.rollback()
            assert (await session.get(ParkingStatisticsBucket, (1, AT))).statistics_sha256 == before
            assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_replayed_old_observation_after_simulated_raw_expiry_cannot_replace_archive(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add_all([snapshot(1, 0, 50), snapshot(2, 5, 5)])
            await session.commit()
            await archive_parking_statistics(session, checked_at=NOW)
            await session.commit()
            original = (await session.get(ParkingStatisticsBucket, (1, AT))).statistics_sha256
            # 이 삭제는 테스트 전용 DB에서만 미래의 48h 정리를 모사한다. 제품 삭제 경로는 차단 상태다.
            await session.execute(delete(ParkingSnapshot))
            session.add(snapshot(3, 0, 50, collected=NOW))
            await session.commit()
            with pytest.raises(ParkingArchiveConflict):
                await archive_parking_statistics(session, checked_at=NOW)
            await session.rollback()
            archived = await session.get(ParkingStatisticsBucket, (1, AT))
            assert archived.statistics_sha256 == original
            assert archived.statistics_json["lots"][0]["available"]["count"] == 2
            assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == 1
    finally:
        await engine.dispose()


def test_archive_job_is_providerless_and_has_no_automatic_schedule(monkeypatch):
    from app.dagster import definitions as module

    invoked = []

    async def run(_settings, action):
        invoked.append(action)
        return {"status": "backfilled", "archived_buckets": 1, "pruned_snapshots": 0}

    monkeypatch.setattr(module, "_settings", lambda: None)
    monkeypatch.setattr(module, "_run_with_session", run)
    result = module.parking_statistics_archive_job.execute_in_process()
    assert result.success
    assert invoked == [archive_parking_statistics]
    assert "parking_statistics_archive_job_schedule" not in {s.name for s in module.definitions.schedules}


@pytest.mark.asyncio
async def test_postgres_collector_lock_busy_does_not_write(tmp_path, test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("실제 PostgreSQL advisory lock 전용")
    from sqlalchemy import text

    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as lease:
            await lease.execute(text("SELECT pg_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"))
            async with factory() as session:
                result = await archive_parking_statistics(session, checked_at=NOW)
                assert {key: result[key] for key in ("status", "coverage_status", "archived_buckets", "pruned_snapshots")} == {
                    "status": "busy", "coverage_status": "not_audited", "archived_buckets": 0, "pruned_snapshots": 0}
                assert result["checked_at"] == NOW.isoformat()
                assert result["raw_cutoff_at"] == (NOW - timedelta(hours=48)).isoformat()
                assert result["selection_start_at"] is None and result["verified_buckets"] == 0
                assert await session.scalar(select(func.count()).select_from(ParkingStatisticsBucket)) == 0
            await lease.rollback()
    finally:
        await engine.dispose()


def test_existing_parking_api_values_are_unchanged_by_archive_only_stage(client):
    import asyncio

    paths = ["/v1/parking/current?airport_code=GMP",
             "/v1/parking/analytics/timeseries?airport_code=GMP",
             "/v1/parking/analytics/by-weekday-hour?airport_code=GMP"]
    before = []
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200
        payload = response.json()
        before.append(payload.get("items", payload) if isinstance(payload, dict) else payload)

    async def run():
        async with client.app.state.session_factory() as session:
            result = await archive_parking_statistics(session, max_buckets=20)
            await session.commit()
            return result

    assert asyncio.run(run())["archived_buckets"] > 0
    for path, expected in zip(paths, before, strict=True):
        response = client.get(path)
        assert response.status_code == 200
        payload = response.json()
        actual = payload.get("items", payload) if isinstance(payload, dict) else payload
        assert actual == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["same_id_correction", "deleted_rows"])
async def test_no_new_id_is_not_a_claim_that_existing_coverage_was_verified(tmp_path, test_settings, change):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            row = snapshot(1, 0, 50)
            session.add(row)
            await session.commit()
            await archive_parking_statistics(session, checked_at=NOW)
            await session.commit()
            if change == "same_id_correction":
                row.raw_item_json = {"corrected": True}
            else:
                await session.execute(delete(ParkingSnapshot))
            await session.commit()
            result = await archive_parking_statistics(session, checked_at=NOW)
            assert result["status"] == "no_new_rows"
            assert result["coverage_status"] == "not_audited"
            record = await session.get(ParkingStatisticsBucket, (1, AT))
            actual = list((await session.scalars(select(ParkingSnapshot))).all())
            with pytest.raises(ParkingArchiveConflict):
                verify_bucket(record, actual, {})
    finally:
        await engine.dispose()
