from __future__ import annotations

import asyncio
from datetime import timedelta

from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import (
    CollectionRun,
    HighwayTrafficCurrent,
    HighwayTrafficCurrentState,
    HighwayTrafficSnapshot,
)
from app.services.traffic_current import update_traffic_current
from app.services.transport_collection import TRAFFIC_SOURCE, TransportCollectionService
from sqlalchemy import event, select
from test_transport_collection import FakeTransportProvider


def _execute(settings, function):
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run():
        await init_database(engine)
        try:
            await function(factory, engine)
        finally:
            await engine.dispose()

    asyncio.run(run())


async def _run(session, *, started_at=None):
    row = CollectionRun(
        started_at=started_at or now_utc(), status="running", trigger="test"
    )
    session.add(row)
    await session.flush()
    return row.id


def replace(item, **changes):
    return item.model_copy(update=changes)


async def _flow():
    return (await FakeTransportProvider().collect_highway()).traffic[0]


async def _state(session, service):
    return await session.get(
        HighwayTrafficCurrentState,
        (TRAFFIC_SOURCE, service._highway_scope_key(TRAFFIC_SOURCE)),
    )


def test_default_off_keeps_existing_store_without_current(test_settings):
    async def check(factory, _engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        async with factory() as session:
            run_id = await _run(session)
            assert await service._store_traffic(session, run_id, (await _flow(),)) == 1
            await session.commit()
            assert await session.scalar(select(HighwayTrafficCurrent)) is None
            assert await _state(session, service) is None

    assert not test_settings.transport_map_current_enabled
    _execute(test_settings, check)


def test_replay_correction_and_older_observation_keep_latest_without_new_history(
    test_settings,
):
    test_settings.transport_map_current_enabled = True

    async def check(factory, _engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        flow = await _flow()
        async with factory() as session:
            first = await _run(session)
            assert await service._store_traffic(session, first, (flow,)) == 1
            await session.commit()
            state = await _state(session, service)
            generation = state.generation
            current = await session.scalar(select(HighwayTrafficCurrent))
            point_id = current.snapshot_id
            await session.rollback()
            second = await _run(session)
            assert (
                await service._store_traffic(
                    session, second, (replace(flow, speed=45.0),)
                )
                == 0
            )
            await session.commit()
            await session.refresh(current)
            state = await _state(session, service)
            assert current.snapshot_id == point_id and current.speed == 45.0
            assert (
                current.generation == state.generation != generation
                and state.member_count == 1
            )
            await session.rollback()
            third = await _run(session)
            older = replace(flow, updated_at="20200101000000", speed=1.0)
            assert await service._store_traffic(session, third, (older,)) == 1
            await session.commit()
            await session.refresh(current)
            state = await _state(session, service)
            assert current.snapshot_id == point_id and current.speed == 45.0
            assert current.generation == state.generation and state.member_count == 1

    _execute(test_settings, check)


def test_multiple_times_same_identity_and_confirmed_empty_membership(test_settings):
    test_settings.transport_map_current_enabled = True

    async def check(factory, _engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        flow = await _flow()
        async with factory() as session:
            run_id = await _run(session)
            items = (replace(flow, updated_at="20200101000000", speed=1), flow, flow)
            assert await service._store_traffic(session, run_id, items) == 2
            await session.commit()
            rows = (await session.scalars(select(HighwayTrafficCurrent))).all()
            assert len(rows) == 1 and rows[0].speed == flow.speed
            previous = rows[0].generation
            await session.rollback()
            run_id = await _run(session)
            assert await service._store_traffic(session, run_id, ()) == 0
            await session.commit()
            state = await _state(session, service)
            assert state.member_count == 0 and state.generation != previous
            # 삭제하지 않고 현재 성공 membership에서 제외한다.
            assert (
                await session.scalar(
                    select(HighwayTrafficCurrent).where(
                        HighwayTrafficCurrent.generation == state.generation,
                    )
                )
                is None
            )

    _execute(test_settings, check)


def test_late_old_run_cannot_change_approved_typed_current(test_settings):
    test_settings.transport_map_current_enabled = True

    async def check(factory, _engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        flow = await _flow()
        async with factory() as session:
            old = await _run(session, started_at=now_utc() - timedelta(hours=1))
            new = await _run(session)
            assert await service._store_traffic(session, new, (flow,)) == 1
            await session.commit()
            generation = (await _state(session, service)).generation
            await session.rollback()
            assert (
                await service._store_traffic(session, old, (replace(flow, speed=3.0),))
                == 0
            )
            await session.commit()
            current = await session.scalar(select(HighwayTrafficCurrent))
            history = await session.get(HighwayTrafficSnapshot, current.snapshot_id)
            assert history.speed == 3.0  # 기존 mutable history의 정정 정책은 유지한다.
            assert current.speed == flow.speed and current.generation == generation
            assert (await _state(session, service)).attempt_order == new

    _execute(test_settings, check)


def test_source_rollback_restores_history_pointer_and_head(test_settings):
    test_settings.transport_map_current_enabled = True

    async def check(factory, _engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        flow = await _flow()
        async with factory() as session:
            first = await _run(session)
            await service._store_traffic(session, first, (flow,))
            await session.commit()
            before = (await _state(session, service)).generation
            await session.rollback()
            next_id = await _run(session)
            await service._store_traffic(session, next_id, (replace(flow, speed=2.0),))
            await (
                session.rollback()
            )  # 뒤의 통계/commit/fence 실패와 같은 원자적 경계다.
            current = await session.scalar(select(HighwayTrafficCurrent))
            assert current.speed == flow.speed and current.generation == before
            assert (await _state(session, service)).generation == before
            assert (
                await session.get(HighwayTrafficSnapshot, current.snapshot_id)
            ).speed == flow.speed

    _execute(test_settings, check)


def test_scope_filters_have_independent_membership(test_settings):
    test_settings.transport_map_current_enabled = True

    async def check(factory, _engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        flow = await _flow()
        async with factory() as session:
            run_id = await _run(session)
            await service._store_traffic(session, run_id, (flow,))
            first_scope = service._highway_scope_key(TRAFFIC_SOURCE)
            test_settings.transport_route_nos_csv = "001"
            await service._store_traffic(session, run_id, (flow,))
            second_scope = service._highway_scope_key(TRAFFIC_SOURCE)
            await session.commit()
            assert first_scope != second_scope
            assert (
                len((await session.scalars(select(HighwayTrafficCurrent))).all()) == 2
            )
            assert (
                len((await session.scalars(select(HighwayTrafficCurrentState))).all())
                == 2
            )

    _execute(test_settings, check)


def test_current_lookup_and_upsert_are_bounded_not_history_scans(test_settings):
    async def check(factory, engine):
        seen = []

        def record(_conn, _cursor, sql, _params, _context, _many):
            seen.append(sql)

        async with factory() as session:
            run_id = await _run(session)
            now = now_utc()
            await session.execute(
                HighwayTrafficSnapshot.__table__.insert(),
                [
                    {
                        "collection_run_id": run_id,
                        "source": TRAFFIC_SOURCE,
                        "identity_key": f"x-{i}",
                        "observed_at": now,
                        "collected_at": now,
                        "speed": 80.0,
                    }
                    for i in range(805)
                ],
            )
            event.listen(engine.sync_engine, "before_cursor_execute", record)
            try:
                assert await update_traffic_current(
                    session,
                    source=TRAFFIC_SOURCE,
                    scope_key="a" * 64,
                    collection_run_id=run_id,
                    pairs={(f"x-{i}", now) for i in range(805)},
                    confirmed_at=now,
                )
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", record)
            await session.commit()
            queries = [
                sql
                for sql in seen
                if sql.lstrip().upper().startswith("SELECT")
                and "highway_traffic_snapshots" in sql
            ]
            writes = [
                sql
                for sql in seen
                if sql.lstrip()
                .upper()
                .startswith("INSERT INTO HIGHWAY_TRAFFIC_CURRENT (")
            ]
            assert len(queries) == len(writes) == 3
            assert all(" IN (" in sql and "raw_item_json" not in sql for sql in queries)
            assert (
                await session.get(
                    HighwayTrafficCurrentState, (TRAFFIC_SOURCE, "a" * 64)
                )
            ).member_count == 805

    _execute(test_settings, check)


def test_owned_bulk_pointer_cannot_commit_after_worker_lease_revoked(test_settings):
    import pytest
    from app.dagster.recovery import CollectionLeaseLost, owned_session_factory

    test_settings.transport_map_current_enabled = True

    async def check(factory, engine):
        owned = owned_session_factory(engine, "pointer-owner")
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        async with owned() as session:
            run_id = await _run(session)
            await session.commit()
            await service._store_traffic(session, run_id, (await _flow(),))
            session.info["collector_owner_lease"].revoked = True
            with pytest.raises(CollectionLeaseLost):
                await session.commit()
            await session.rollback()
        async with factory() as session:
            assert await session.scalar(select(HighwayTrafficCurrent)) is None
            assert await session.scalar(select(HighwayTrafficCurrentState)) is None
            assert await session.scalar(select(HighwayTrafficSnapshot)) is None

    _execute(test_settings, check)


def test_unconfirmed_empty_source_keeps_previous_current_and_success_clock(
    test_settings,
):
    from app.models import TransportCollectionState
    from app.services.transport_collection import HighwayPayload

    test_settings.transport_map_current_enabled = True
    test_settings.transport_collection_enabled = True

    async def check(factory, _engine):
        provider = FakeTransportProvider()
        provider.enabled_sources = (TRAFFIC_SOURCE,)
        service = TransportCollectionService(test_settings, provider)
        async with factory() as session:
            await service.collect(session, trigger="test", scope="highway")
            before = (await _state(session, service)).generation
            state = await session.scalar(
                select(TransportCollectionState).where(
                    TransportCollectionState.source == TRAFFIC_SOURCE
                )
            )
            success = state.last_success_at
            state.next_due_at = now_utc() - timedelta(seconds=1)
            await session.commit()

        async def empty(**_kwargs):
            return HighwayPayload(traffic=())

        provider.collect_highway = empty
        async with factory() as session:
            result = await service.collect(session, trigger="test", scope="highway")
            assert result["status"] == "failed"
            assert (await _state(session, service)).generation == before
            state = await session.scalar(
                select(TransportCollectionState).where(
                    TransportCollectionState.source == TRAFFIC_SOURCE
                )
            )
            assert state.last_success_at == success and state.last_error
            assert (
                await session.scalar(select(HighwayTrafficCurrent))
            ).generation == before

    _execute(test_settings, check)
