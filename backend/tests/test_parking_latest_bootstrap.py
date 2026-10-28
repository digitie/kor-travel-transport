"""최초 현재 요약과 최초 전국 seal의 기존 원본/proof 경계를 검증한다."""
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, text

from app.models import (Airport, ParkingArchiveIssue, ParkingGlobalStatisticsBucket,
                        ParkingLatestState, ParkingLot, ParkingSnapshot, ParkingStatisticsBucket)
from app.services.parking_archive_state import capture_latest_snapshot, seed_latest_states
from app.services.parking_global_archive import archive_global_statistics, archive_parking_with_coverage
from app.services.parking_statistics_archive import archive_parking_statistics
from test_parking_statistics_archive import AT, NOW, database, snapshot


@pytest.mark.asyncio
@pytest.mark.parametrize("old_source,new_source,new_minute,expected", [
    ("live", "live", 0, 100),
    ("migration_http", "live", 0, 100),
    ("live", "migration_http", 60, 101),
    ("live", "live", 120, 101),
])
async def test_first_capture_uses_existing_raw_current_order(tmp_path, test_settings, old_source, new_source, new_minute, expected):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            old = snapshot(100, 60, 60, source=old_source)
            session.add(old)
            await session.commit()
            assert await session.get(ParkingLatestState, 1) is None
            incoming = snapshot(101, new_minute, 10, source=new_source, collected=NOW)
            session.add(incoming)
            await session.flush()
            await capture_latest_snapshot(session, incoming)
            await session.commit()
            state = await session.get(ParkingLatestState, 1)
            assert state.snapshot_order == expected
            assert state.available_spaces == (60 if expected == 100 else 10)
            assert state.observed_at.replace(tzinfo=AT.tzinfo) == AT + timedelta(minutes=60 if expected == 100 else new_minute)
            assert state.latest_ingested_at.replace(tzinfo=NOW.tzinfo) == NOW
            # 뒤의 seed가 잘못 초기화된 기존 행을 영원히 건너뛰는 회귀도 함께 막는다.
            assert await seed_latest_states(session) == 0
            assert state.snapshot_order == expected
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_first_capture_preserves_max_ingested_across_older_observations(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add_all([snapshot(100, 60, 60), snapshot(99, -60, 90, collected=NOW + timedelta(hours=1))])
            await session.commit()
            incoming = snapshot(101, 0, 10, collected=NOW)
            session.add(incoming)
            await session.flush()
            await capture_latest_snapshot(session, incoming)
            await session.commit()
            state = await session.get(ParkingLatestState, 1)
            assert state.snapshot_order == 100 and state.available_spaces == 60
            assert state.collected_at.replace(tzinfo=AT.tzinfo) == AT + timedelta(minutes=60)
            assert state.latest_ingested_at.replace(tzinfo=NOW.tzinfo) == NOW + timedelta(hours=1)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_first_capture_outside_seed_512_bound_reads_its_existing_current(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add_all([ParkingLot(id=i, airport_id=1, source_lot_id=f"P{i}", name=f"주차장{i}",
                                       is_active=True, created_at=AT, updated_at=AT) for i in range(2, 514)])
            await session.flush()
            session.add_all([snapshot(i, 60, 60, lot=i) for i in range(1, 514)])
            await session.commit()
            assert await seed_latest_states(session, max_lots=512) == 512
            await session.commit()
            assert await session.get(ParkingLatestState, 513) is None
            incoming = snapshot(5000, 0, 10, lot=513, collected=NOW)
            session.add(incoming)
            await session.flush()
            await capture_latest_snapshot(session, incoming)
            await session.commit()
            assert (await session.get(ParkingLatestState, 513)).snapshot_order == 513
            assert (await session.get(ParkingLatestState, 512)).snapshot_order == 512
            assert await session.scalar(select(func.count()).select_from(ParkingLatestState)) == 513
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("collector_first", [False, True])
async def test_seed_and_first_collection_obey_the_same_postgres_lease(tmp_path, test_settings, collector_first):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 동명 transaction lease 검증")
    engine, factory = await database(tmp_path, test_settings)
    lease = "SELECT pg_try_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"
    try:
        async with factory() as setup:
            setup.add(snapshot(100, 60, 60))
            await setup.commit()
        async with factory() as first, factory() as second:
            assert await first.scalar(text(lease)) is True
            if collector_first:
                incoming = snapshot(101, 0, 10, collected=NOW)
                first.add(incoming)
                await first.flush()
                await capture_latest_snapshot(first, incoming)
                assert (await archive_parking_with_coverage(second, checked_at=NOW))["status"] == "busy"
            else:
                assert await seed_latest_states(first) == 1
                assert await second.scalar(text(lease)) is False
            await second.rollback()
            await first.commit()
            assert await second.scalar(text(lease)) is True
            if collector_first:
                assert await seed_latest_states(second) == 0
            else:
                incoming = snapshot(101, 0, 10, collected=NOW)
                second.add(incoming)
                await second.flush()
                await capture_latest_snapshot(second, incoming)
            await second.commit()
            state = await second.get(ParkingLatestState, 1)
            assert state.snapshot_order == 100 and state.available_spaces == 60
            assert state.latest_ingested_at.replace(tzinfo=NOW.tzinfo) == NOW
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("already_global_sealed", [False, True])
async def test_missing_entire_airport_raw_cannot_publish_first_partial_global_seal(tmp_path, test_settings, already_global_sealed):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add(Airport(id=2, code="CJU", name_ko="제주", source="kac", created_at=AT, updated_at=AT))
            await session.flush()
            session.add(ParkingLot(id=2, airport_id=2, source_lot_id="P2", name="제주주차장",
                                   is_active=True, created_at=AT, updated_at=AT))
            await session.flush()
            other = snapshot(2, 0, 80, lot=2)
            other.airport_id = 2
            session.add_all([snapshot(1, 0, 20), other])
            await session.commit()
            assert (await archive_parking_statistics(session, checked_at=NOW))["archived_buckets"] == 2
            await session.commit()
            if already_global_sealed:
                assert (await archive_global_statistics(session, checked_at=NOW))["global_buckets"] == 1
                await session.commit()
                # 기존 전국 seal이 있는 경우도 강제 검산 대상으로 재발견한다.
                late = snapshot(3, 5, 80, lot=2)
                late.airport_id = 2
                session.add(late)
            # 격리한 시험 DB의 손상 반례다. 제품 prune/운영 삭제는 실행하지 않는다.
            await session.execute(delete(ParkingSnapshot).where(ParkingSnapshot.airport_id == 1))
            await session.commit()
            result = await archive_global_statistics(session, checked_at=NOW)
            await session.commit()
            assert result["status"] == "blocked" and result["coverage_status"] == "conflict"
            assert await session.scalar(select(func.count()).select_from(ParkingGlobalStatisticsBucket)) == int(already_global_sealed)
            assert await session.scalar(select(func.count()).select_from(ParkingStatisticsBucket)) == 2
            assert await session.scalar(select(func.count()).select_from(ParkingArchiveIssue)) == 1
    finally:
        await engine.dispose()
