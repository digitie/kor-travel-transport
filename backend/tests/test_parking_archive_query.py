"""단일 PostgreSQL snapshot·경계 원문 제한·삭제 후 pattern 동등성을 검증한다."""
from datetime import timedelta

import pytest
from sqlalchemy import delete, event, exists, select

from app.models import Airport, ParkingLot, ParkingSnapshot, ParkingStatisticsBucket
from app.services.analytics import build_hourly_buckets, build_weekday_buckets, build_weekday_hour_patterns, deduplicate_snapshots
from app.services.parking_archive_query import build_pattern_statistics_query, load_pattern_statistics
from app.services.parking_archive_reader import ParkingArchivePrecisionUnavailable, read_pattern_statistics
from app.services.parking_statistics_archive import BUCKET_INTERVAL, ParkingArchiveConflict, _digest, bucket_start, build_bucket, raw_digest
from test_parking_statistics_archive import AT, NOW, database, snapshot


def records_for(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row.airport_id, bucket_start(row.observed_at)), []).append(row)
    result = []
    for (airport, at), members in sorted(groups.items()):
        payload, count = build_bucket(members, {})
        result.append(ParkingStatisticsBucket(
            airport_id=airport, bucket_at=at, bucket_end=at + BUCKET_INTERVAL, format_version=1,
            raw_count=len(members), selected_count=count, max_snapshot_id=max(row.id for row in members),
            raw_sha256=raw_digest(members), statistics_sha256=_digest(payload), statistics_json=payload,
            created_at=NOW,
        ))
    return result


def assert_patterns(result, rows):
    selected = deduplicate_snapshots(rows)
    assert result.by_hour == build_hourly_buckets(selected)
    assert result.by_weekday == build_weekday_buckets(selected)
    assert result.by_weekday_hour == build_weekday_hour_patterns(selected)
    assert result.metadata["database_snapshot"] == "single_statement"
    assert result.metadata["coverage"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("days", [7, 14, 21, 28, 90])
async def test_archive_and_recent_raw_match_after_old_fixture_raw_is_removed(tmp_path, test_settings, days):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 단일 snapshot/LATERAL 회귀")
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            session.add(Airport(id=2, code="CJU", name_ko="제주", source="kac", created_at=AT, updated_at=AT))
            await session.flush()
            session.add(ParkingLot(id=2, airport_id=2, source_lot_id="P2", name="제주 주차장", is_active=True,
                                   created_at=AT, updated_at=AT))
            await session.flush()
            rows = []
            for day in range(days):
                for airport, lot in ((1, 1), (2, 2)):
                    row = snapshot(len(rows) + 1, day * 1440, (day + lot) % 100, lot=lot)
                    row.airport_id = airport
                    rows.append(row)
            session.add_all(rows)
            await session.commit()
            old = [row for row in rows if row.observed_at < AT + timedelta(days=days - 2)]
            session.add_all(records_for(old))
            await session.commit()
            end = AT + timedelta(days=days)
            for scope in ({}, {"airport_id": 1}, {"parking_lot_id": 2}, {"airport_id": 1, "parking_lot_id": 2}):
                expected = [row for row in rows if (row.parking_lot_id == scope["parking_lot_id"]
                    if scope.get("parking_lot_id") else row.airport_id == scope["airport_id"] if scope.get("airport_id") else True)]
                assert_patterns(await load_pattern_statistics(session, start=AT, end=end, **scope), expected)
            # 운영 삭제가 아니라 새 nonce DB의 명시적인 보존 정책 회귀 fixture다.
            await session.execute(delete(ParkingSnapshot).where(ParkingSnapshot.id.in_([row.id for row in old])))
            await session.commit()
            for scope in ({}, {"airport_id": 1}, {"parking_lot_id": 2}, {"airport_id": 1, "parking_lot_id": 2}):
                expected = [row for row in rows if (row.parking_lot_id == scope["parking_lot_id"]
                    if scope.get("parking_lot_id") else row.airport_id == scope["airport_id"] if scope.get("airport_id") else True)]
                assert_patterns(await load_pattern_statistics(session, start=AT, end=end, **scope), expected)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_raw_body_is_only_returned_for_archived_cut_boundary(tmp_path, test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 단일 snapshot/LATERAL 회귀")
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            rows = [snapshot(1, 0, 10), snapshot(2, 5, 70), snapshot(3, 20, 30)]
            session.add_all(rows)
            await session.commit()
            session.add_all(records_for(rows[:2]))
            await session.commit()
            projected = (await session.execute(build_pattern_statistics_query(start=AT, end=AT + timedelta(hours=1)))).mappings().all()
            raw = [row for row in projected if row["kind"] == "raw"]
            assert len(raw) == 1 and raw[0]["raw_id"] == 3 and raw[0]["raw_raw_item_json"] is None
            boundary = (await session.execute(build_pattern_statistics_query(
                start=AT + timedelta(minutes=2), end=AT + timedelta(minutes=9),
            ))).mappings().all()
            assert [row["raw_id"] for row in boundary if row["kind"] == "raw"] == [1, 2]
            assert all(row["raw_raw_item_json"] == rows[0].raw_item_json for row in boundary if row["kind"] == "raw")
            result = await load_pattern_statistics(session, start=AT + timedelta(minutes=2), end=AT + timedelta(minutes=9))
            assert_patterns(result, rows[1:2])
            await session.execute(delete(ParkingSnapshot).where(ParkingSnapshot.id.in_([1, 2])))
            await session.commit()
            with pytest.raises(ParkingArchivePrecisionUnavailable):
                await load_pattern_statistics(session, start=AT + timedelta(minutes=2), end=AT + timedelta(minutes=9))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_new_id_replay_after_raw_prune_is_detected_by_seal_lookup(tmp_path, test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 단일 snapshot/LATERAL 회귀")
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            rows = [snapshot(1, 0, 10), snapshot(2, 5, 70)]
            session.add_all(rows)
            await session.commit()
            session.add_all(records_for(rows))
            await session.commit()
            await session.execute(delete(ParkingSnapshot))
            await session.commit()
            assert_patterns(await load_pattern_statistics(session, start=AT, end=AT + timedelta(hours=1)), rows)
            session.add(snapshot(3, 0, 10, collected=NOW))
            await session.commit()
            with pytest.raises(ParkingArchiveConflict):
                await load_pattern_statistics(session, start=AT, end=AT + timedelta(hours=1))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_backfill_between_split_queries_loses_rows_but_single_statement_does_not(tmp_path, test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 실제 별도 transaction 발행 회귀")
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as setup:
            rows = [snapshot(1, 0, 10), snapshot(2, 5, 70)]
            setup.add_all(rows)
            await setup.commit()

        async def publish():
            async with factory() as other:
                other.add_all(records_for(rows))
                await other.commit()

        async def run(paired):
            fired = []

            def after_first_query(connection, cursor, statement, parameters, context, executemany):
                if not fired:
                    fired.append(True)
                    connection.connection.dbapi_connection.run_async(lambda _: publish())

            event.listen(engine.sync_engine, "after_cursor_execute", after_first_query)
            try:
                async with factory() as session:
                    if not paired:
                        result = await load_pattern_statistics(session, start=AT, end=AT + timedelta(hours=1))
                    else:
                        # 처음 archive 결과가 빈 뒤 publish되면 후속 raw NOT EXISTS에서도 모두 빠진다.
                        archived = list((await session.scalars(select(ParkingStatisticsBucket))).all())
                        present = exists(select(1).where(ParkingStatisticsBucket.airport_id == ParkingSnapshot.airport_id,
                            ParkingStatisticsBucket.bucket_at == AT))
                        raw = list((await session.scalars(select(ParkingSnapshot).where(~present))).all())
                        result = read_pattern_statistics(archived, raw, start=AT, end=AT + timedelta(hours=1))
                    assert fired
                    return result
            finally:
                event.remove(engine.sync_engine, "after_cursor_execute", after_first_query)

        red = await run(paired=True)
        assert red.by_hour == []
        async with factory() as reset:
            await reset.execute(delete(ParkingStatisticsBucket))
            await reset.commit()
        green = await run(paired=False)
        assert_patterns(green, rows)
    finally:
        await engine.dispose()
