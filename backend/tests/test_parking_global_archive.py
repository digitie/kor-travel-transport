"""실제 DB 검증용 회귀. 2A 전용 새 nonce 자원에서 실행한다."""
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, text

from app.models import (Airport, ParkingArchiveIssue, ParkingGlobalStatisticsBucket,
                        ParkingLatestState, ParkingLot, ParkingSnapshot, ParkingStatisticsBucket)
from app.services.legacy_parking_guard import ensure_legacy_import_allowed
from app.services.parking_archive_state import capture_latest_snapshot, seed_latest_states
from app.services.parking_global_archive import archive_global_statistics, archive_parking_with_coverage
from app.services.parking_statistics_archive import archive_parking_statistics, bucket_start, prune_parking_raw
from test_parking_statistics_archive import AT, NOW, database, snapshot


@pytest.mark.asyncio
async def test_global_seal_preserves_simultaneous_cohort_and_raw(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add(Airport(id=2, code="CJU", name_ko="제주", source="kac", created_at=AT, updated_at=AT))
            await session.flush()
            session.add(ParkingLot(id=2, airport_id=2, source_lot_id="P2", name="제주주차장",
                                   is_active=True, created_at=AT, updated_at=AT))
            await session.flush()
            rows = [snapshot(1, 0, 0), snapshot(2, 5, 100), snapshot(3, 0, 100, lot=2), snapshot(4, 5, 0, lot=2)]
            rows[2].airport_id = rows[3].airport_id = 2
            session.add_all(rows)
            await session.commit()
            result = await archive_parking_with_coverage(session, checked_at=NOW)
            await session.commit()
            assert result["pruned_snapshots"] == 0 and result["global_buckets"] == 1
            record = await session.get(ParkingGlobalStatisticsBucket, AT)
            assert record.statistics_json["cohorts"] == {"count": 2, "sum": 200, "min": 100, "max": 100}
            assert set(record.airport_proofs_json) == {"1", "2"}
            assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == 4
            assert await session.scalar(select(func.count()).select_from(ParkingLatestState)) == 2
            again = await archive_parking_with_coverage(session, checked_at=NOW)
            assert again["coverage_status"] == "not_audited"
            assert await session.scalar(select(func.count()).select_from(ParkingGlobalStatisticsBucket)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_global_waits_for_airport_coverage_instead_of_publishing_partial_scope(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add(snapshot(1, 0, 50))
            await session.commit()
            pending = await archive_global_statistics(session, checked_at=NOW)
            assert pending["global_deferred_buckets"] == 1
            assert await session.scalar(select(func.count()).select_from(ParkingGlobalStatisticsBucket)) == 0
            await archive_parking_statistics(session, checked_at=NOW)
            complete = await archive_global_statistics(session, checked_at=NOW)
            assert complete["global_buckets"] == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sealed_old_replay_preserves_statistics_and_durable_block_status(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add_all([snapshot(1, 0, 60), snapshot(2, 5, 20)])
            await session.commit()
            await archive_parking_with_coverage(session, checked_at=NOW)
            await session.commit()
            original = deepcopy((await session.get(ParkingGlobalStatisticsBucket, AT)).statistics_json)
            # 검증 전용 새 DB의 반례다. 제품 prune는 이 시점에도 항상 거절한다.
            await session.execute(delete(ParkingSnapshot))
            replay = snapshot(99, 0, 60, collected=NOW)
            session.add(replay)
            await session.flush()
            await capture_latest_snapshot(session, replay)
            await session.commit()
            result = await archive_parking_with_coverage(session, checked_at=NOW + timedelta(days=3))
            await session.commit()
            assert result["status"] == "blocked"
            assert (await session.get(ParkingGlobalStatisticsBucket, AT)).statistics_json == original
            assert await session.scalar(select(func.count()).select_from(ParkingArchiveIssue)) == 1
            assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == 1
            assert (await archive_global_statistics(session, checked_at=NOW + timedelta(days=4)))["status"] == "blocked"
            with pytest.raises(RuntimeError):
                await prune_parking_raw(session)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_latest_seed_and_delayed_ingest_keep_existing_current_selection(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add_all([snapshot(1, 0, 60), snapshot(9, 0, 9, source="migration_http")])
            await session.commit()
            assert await seed_latest_states(session) == 1
            await session.commit()
            latest = await session.get(ParkingLatestState, 1)
            assert latest.available_spaces == 9 and latest.snapshot_order == 9
            old = snapshot(10, -10, 1, collected=NOW)
            session.add(old)
            await session.flush()
            await capture_latest_snapshot(session, old)
            await session.commit()
            await session.refresh(latest)
            assert latest.available_spaces == 9
            assert latest.latest_ingested_at.replace(tzinfo=NOW.tzinfo) == NOW
            assert latest.collected_at.replace(tzinfo=AT.tzinfo) == AT
            assert await session.scalar(select(func.count()).select_from(ParkingStatisticsBucket)) == 0
            # 현재 요약만 있는 기간에도 identity를 legacy upsert로 바꿀 수 없다.
            with pytest.raises(RuntimeError, match="현재 요약"):
                await ensure_legacy_import_allowed(session)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_latest_seed_skips_empty_lots_before_applying_bound(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add(ParkingLot(id=2, airport_id=1, source_lot_id="P2", name="자료있는곳",
                                   is_active=True, created_at=AT, updated_at=AT))
            await session.flush()
            session.add(snapshot(1, 0, 40, lot=2))
            await session.commit()
            assert await seed_latest_states(session, max_lots=1) == 1
            assert await session.get(ParkingLatestState, 2) is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stage2_uses_collector_lease_and_never_blocks_waiting_for_it(tmp_path, test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL advisory lock 검증")
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as owner, factory() as contender:
            await owner.execute(text("SELECT pg_advisory_lock(hashtext('kor_travel_transport:airport_collection'))"))
            try:
                result = await archive_parking_with_coverage(contender, checked_at=NOW)
                assert result["status"] == "busy" and result["pruned_snapshots"] == 0
                assert await contender.scalar(select(func.count()).select_from(ParkingGlobalStatisticsBucket)) == 0
            finally:
                await owner.execute(text("SELECT pg_advisory_unlock(hashtext('kor_travel_transport:airport_collection'))"))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_oldest_deferred_bucket_cannot_starve_later_dates_and_is_resumable(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            # 첫 bucket에 오래된 행과 방금 적재된 행이 섞여도 전체를 보류해야 한다.
            session.add_all([snapshot(1, 0, 60), snapshot(2, 5, 5, collected=NOW - timedelta(hours=1)),
                             snapshot(3, 2 * 24 * 60, 40)])
            await session.commit()
            first = await archive_parking_statistics(session, checked_at=NOW)
            await session.commit()
            assert first["archived_buckets"] == 1
            assert await session.get(ParkingStatisticsBucket, (1, AT)) is None
            assert await session.get(ParkingStatisticsBucket, (1, AT + timedelta(days=2))) is not None
            second = await archive_parking_statistics(session, checked_at=NOW)
            assert second["status"] == "deferred" and second["coverage_status"] == "partial"
            assert second["deferred_count_scope"] == "first_pending_bucket"
            assert second["oldest_pending_at"] == AT.isoformat()
            resumed = await archive_parking_statistics(session, checked_at=NOW + timedelta(days=3))
            await session.commit()
            assert resumed["archived_buckets"] == 1
            assert await session.scalar(select(func.count()).select_from(ParkingStatisticsBucket)) == 2
            assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == 3
            assert (await archive_parking_statistics(session, checked_at=NOW + timedelta(days=3)))["status"] == "no_new_rows"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_global_deferred_old_date_does_not_starve_later_complete_scope(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add_all([snapshot(1, 0, 60, collected=NOW - timedelta(hours=1)),
                             snapshot(2, 3 * 24 * 60, 40)])
            await session.commit()
            result = await archive_parking_with_coverage(session, checked_at=NOW)
            await session.commit()
            assert result["global_buckets"] == 1
            assert await session.get(ParkingGlobalStatisticsBucket, AT) is None
            assert await session.get(ParkingGlobalStatisticsBucket, AT + timedelta(days=3)) is not None
            assert (await archive_parking_with_coverage(session, checked_at=NOW))["status"] == "deferred"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["global", "airport"])
@pytest.mark.parametrize("analyzed", [False, True])
async def test_candidate_discovery_does_not_hash_entire_permanent_archive(tmp_path, test_settings, scope, analyzed):
    """PG16이 적격 후보의 seal 존재 검사를 전체 hash로 바꾸는 실제 반례를 막는다."""
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 실행계획 검증")
    from sqlalchemy.dialects import postgresql
    from app.services.parking_global_archive import _next_global_at_query
    from app.services.parking_statistics_archive import _next_unarchived_at_query

    engine, factory = await database(tmp_path, test_settings)
    table = "parking_global_statistics_buckets" if scope == "global" else "parking_statistics_buckets"
    # 이 행은 조회계획 전용 합성 seal이다. 내용 검산·원본 삭제 수용을 뜻하지 않는다.
    columns = "bucket_at,bucket_end,format_version,raw_count,selected_count,max_snapshot_id,raw_sha256,statistics_sha256,statistics_json"
    values = "CAST(:at AS timestamptz)-interval '20 days'+g*interval '10 minutes',CAST(:at AS timestamptz)-interval '20 days'+(g+1)*interval '10 minutes',1,1,1,100000,repeat('a',64),repeat('b',64),'{}'::jsonb"
    if scope == "global":
        columns += ",airport_proofs_json,sealed_at"
        values += ",'{}'::jsonb,CAST(:at AS timestamptz)"
    else:
        columns = "airport_id," + columns + ",created_at"
        values = "1," + values + ",CAST(:at AS timestamptz)"
    try:
        async with factory() as session:
            session.add_all([snapshot(i + 1, i * 5, 10) for i in range(900)])
            await session.execute(text(f"INSERT INTO {table}({columns}) SELECT {values} FROM generate_series(0,9999) AS g"), {"at": AT})
            await session.commit()
            if analyzed:
                await session.execute(text("ANALYZE parking_snapshots"))
                await session.execute(text("ANALYZE " + table))
            query_fn = _next_global_at_query if scope == "global" else _next_unarchived_at_query
            cutoff = NOW - timedelta(hours=48)
            for collected_before in [None, cutoff]:
                query = query_fn("postgresql", bucket_start(cutoff), collected_before)
                assert await session.scalar(query) is None
                sql = str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
                plan = (await session.execute(text("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + sql))).scalar_one()
                scans = []

                def walk(node):
                    if node.get("Relation Name") == table and node.get("Actual Loops", 0) > 0:
                        scans.append(node)
                    for child in node.get("Plans", []):
                        walk(child)

                walk(plan[0]["Plan"])
                assert scans and all(node.get("Index Name") == table + "_pkey"
                                     and "bucket_at =" in node.get("Index Cond", "")
                                     and node["Actual Rows"] <= 1 for node in scans)
    finally:
        await engine.dispose()
