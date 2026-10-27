from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import event, select

from app.core.time_utils import serialize_utc
from app.models import HighwayTrafficCurrent, HighwayTrafficSnapshot
from app.services import transport_collection
from app.services.transport_collection import TransportCollectionService
from test_traffic_current import _execute, _flow, _run, _state, replace
from test_transport_collection import FakeTransportProvider


@pytest.mark.parametrize("map_current", [False, True])
def test_batch_boundaries_keep_first_pair_and_update_same_utc_instant(
    test_settings, monkeypatch, map_current,
):
    test_settings.transport_map_current_enabled = map_current
    confirmed_at = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(transport_collection, "now_utc", lambda: confirmed_at)

    async def check(factory, _engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        base = await _flow()
        points = tuple(
            replace(base, conzone_id=f"batch-{index}", updated_at="2026-10-27T18:00:00+09:00")
            for index in range(801)
        )
        items = (
            points[:400]
            + (replace(points[0], speed=1.0, updated_at="2026-10-27T09:00:00Z"),)
            + points[400:]
            + (replace(points[400], speed=2.0),)
        )
        async with factory() as session:
            first = await _run(session)
            assert await service._store_traffic(session, first, items) == 801
            await session.commit()
            rows = (await session.scalars(select(HighwayTrafficSnapshot))).all()
            assert len(rows) == 801
            ids = {row.conzone_id: row.id for row in rows}
            assert all(row.speed == base.speed for row in rows)
            assert all(serialize_utc(row.observed_at) == datetime(2026, 10, 27, 9, tzinfo=timezone.utc) for row in rows)
            await session.rollback()
            second = await _run(session)
            corrected = tuple(
                replace(point, speed=45.0, route_name="정정 노선", raw={"revision": 2}, updated_at="2026-10-27T09:00:00Z")
                for point in points
            )
            assert await service._store_traffic(session, second, corrected) == 0
            await session.commit()
            # SQLite의 naive 반환과 PostgreSQL의 aware 반환 모두 기존 PK를 재사용해야 한다.
            rows = (await session.scalars(select(HighwayTrafficSnapshot))).all()
            assert {row.conzone_id: row.id for row in rows} == ids
            assert all(row.speed == 45.0 and row.route_name == "정정 노선" for row in rows)
            assert all(row.collection_run_id == second and serialize_utc(row.collected_at) == confirmed_at for row in rows)
            assert all(row.raw_item_json["raw"] == {"revision": 2} for row in rows)
            if map_current:
                state = await _state(session, service)
                current = (await session.scalars(select(HighwayTrafficCurrent))).all()
                assert state.member_count == len(current) == 801
                assert all(row.speed == 45.0 and row.generation == state.generation for row in current)
            else:
                assert await session.scalar(select(HighwayTrafficCurrent)) is None
                assert await _state(session, service) is None

    _execute(test_settings, check)


def test_batch_query_dispatches_are_bounded_for_new_and_existing_points(test_settings):
    async def check(factory, engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        base = await _flow()
        points = tuple(replace(base, conzone_id=f"sql-{index}") for index in range(801))
        selections = []

        def observed(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith("SELECT") and "highway_traffic_snapshots" in statement:
                selections.append(statement)

        async with factory() as session:
            for expected_new, items in [(801, points), (0, tuple(replace(point, speed=45.0) for point in points))]:
                run_id = await _run(session)
                selections.clear()
                event.listen(engine.sync_engine, "before_cursor_execute", observed)
                try:
                    assert await service._store_traffic(session, run_id, items) == expected_new
                finally:
                    event.remove(engine.sync_engine, "before_cursor_execute", observed)
                assert len(selections) == 3
                await session.commit()

    _execute(test_settings, check)


def test_unparseable_timestamp_uses_one_collection_time_across_batches(test_settings, monkeypatch):
    confirmed_at = datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
    calls = []

    def now():
        calls.append(True)
        return confirmed_at

    monkeypatch.setattr(transport_collection, "now_utc", now)

    async def check(factory, _engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        base = await _flow()
        points = tuple(replace(base, conzone_id=f"fallback-{index}", updated_at="invalid") for index in range(401))
        items = points[:400] + (replace(points[0], updated_at=None, speed=1.0),) + points[400:]
        async with factory() as session:
            run_id = await _run(session)
            assert await service._store_traffic(session, run_id, items) == 401
            assert len(calls) == 1
            rows = (await session.scalars(select(HighwayTrafficSnapshot))).all()
            assert len(rows) == 401
            assert all(serialize_utc(row.observed_at) == serialize_utc(row.collected_at) == confirmed_at for row in rows)
            assert all(row.speed == base.speed for row in rows)

    _execute(test_settings, check)


def test_later_batch_failure_rolls_back_prior_flushed_history_and_current(test_settings):
    test_settings.transport_map_current_enabled = True

    async def check(factory, engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        base = await _flow()
        points = tuple(replace(base, conzone_id=f"rollback-{index}") for index in range(801))
        async with factory() as session:
            first = await _run(session)
            assert await service._store_traffic(session, first, points) == 801
            await session.commit()
            generation = (await _state(session, service)).generation
            await session.rollback()
            next_run = await _run(session)
            selects = 0

            def fail_later(_connection, _cursor, statement, _parameters, _context, _executemany):
                nonlocal selects
                if statement.lstrip().upper().startswith("SELECT") and "highway_traffic_snapshots" in statement:
                    selects += 1
                    if selects == 3:
                        raise RuntimeError("later batch failed after earlier flushes")

            event.listen(engine.sync_engine, "before_cursor_execute", fail_later)
            try:
                with pytest.raises(RuntimeError, match="later batch failed"):
                    await service._store_traffic(session, next_run, tuple(replace(point, speed=1.0) for point in points))
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", fail_later)
                await session.rollback()
            rows = (await session.scalars(select(HighwayTrafficSnapshot))).all()
            assert len(rows) == 801
            assert all(row.speed == base.speed and row.collection_run_id == first for row in rows)
            assert (await _state(session, service)).generation == generation
            current = (await session.scalars(select(HighwayTrafficCurrent))).all()
            assert len(current) == 801 and all(row.speed == base.speed and row.generation == generation for row in current)

    _execute(test_settings, check)
