from datetime import timedelta
from types import SimpleNamespace

import pytest
from app.core.time_utils import now_utc
from app.dagster.recovery import (
    CollectionLeaseLost,
    collection_owner,
    owned_session_factory,
    reconcile_collection_runs,
)
from app.db.session import create_engine_and_session_factory
from app.models import Base, CollectionRun, RawApiResponse
from sqlalchemy import select, update


async def database(settings):
    engine, factory = create_engine_and_session_factory(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, factory


@pytest.mark.parametrize("bulk", [False, True])
async def test_recovered_worker_cannot_publish_or_overwrite_finished_status(test_settings, bulk):
    engine, factory = await database(test_settings)
    owned = owned_session_factory(engine, "worker")
    try:
        async with owned() as worker:
            run = CollectionRun(started_at=now_utc(), status="running", trigger="test")
            worker.add(run)
            await worker.commit()
            run_id = run.id
            async with factory() as reaper:
                await reaper.execute(
                    update(CollectionRun).where(CollectionRun.id == run_id).values(status="failed")
                )
                await reaper.commit()
            if bulk:
                await worker.execute(
                    RawApiResponse.__table__.insert().values(
                        collection_run_id=run_id,
                        source="test",
                        endpoint="test",
                        status_code=200,
                        body_text="late",
                        received_at=now_utc(),
                        parse_status="success",
                    )
                )
            else:
                worker.add(
                    RawApiResponse(
                        collection_run_id=run_id,
                        source="test",
                        endpoint="test",
                        status_code=200,
                        body_text="late",
                        received_at=now_utc(),
                        parse_status="success",
                    )
                )
                run.status = "success"
            with pytest.raises(CollectionLeaseLost):
                await worker.commit()
            await worker.rollback()
        async with factory() as reader:
            assert (await reader.get(CollectionRun, run_id)).status == "failed"
            assert (await reader.scalars(select(RawApiResponse))).all() == []
    finally:
        await engine.dispose()


@pytest.mark.parametrize("bulk", [False, True])
async def test_rollback_then_error_commit_keeps_fence_for_late_publication(test_settings, bulk):
    engine, factory = await database(test_settings)
    try:
        async with owned_session_factory(engine, "worker")() as worker:
            run = CollectionRun(started_at=now_utc(), status="running", trigger="test")
            worker.add(run)
            await worker.commit()
            run_id = run.id
            await worker.execute(select(CollectionRun.id))
            await worker.rollback()
            assert "status" not in run.__dict__
            worker.add(
                RawApiResponse(
                    collection_run_id=run_id,
                    source="test",
                    endpoint="error",
                    status_code=500,
                    body_text="error receipt",
                    received_at=now_utc(),
                    parse_status="failed",
                )
            )
            await worker.commit()
            async with factory() as reaper:
                await reaper.execute(
                    update(CollectionRun).where(CollectionRun.id == run_id).values(status="failed")
                )
                await reaper.commit()
            values = dict(
                collection_run_id=run_id,
                source="test",
                endpoint="late",
                status_code=200,
                body_text="late",
                received_at=now_utc(),
                parse_status="success",
            )
            if bulk:
                await worker.execute(RawApiResponse.__table__.insert().values(**values))
            else:
                worker.add(RawApiResponse(**values))
                run.status = "success"
            with pytest.raises(CollectionLeaseLost):
                await worker.commit()
            await worker.rollback()
        async with factory() as reader:
            assert (await reader.get(CollectionRun, run_id)).status == "failed"
            assert [
                row.body_text for row in (await reader.scalars(select(RawApiResponse))).all()
            ] == ["error receipt"]
    finally:
        await engine.dispose()


async def test_revoked_owner_cannot_create_a_new_run_through_a_fresh_session(test_settings):
    engine, factory = await database(test_settings)
    try:
        with collection_owner("worker"):
            async with owned_session_factory(engine, "worker")() as worker:
                run = CollectionRun(started_at=now_utc(), status="running", trigger="first")
                worker.add(run)
                await worker.commit()
                run_id = run.id
                async with factory() as reaper:
                    await reaper.execute(
                        update(CollectionRun)
                        .where(CollectionRun.id == run_id)
                        .values(status="failed")
                    )
                    await reaper.commit()
                with pytest.raises(CollectionLeaseLost):
                    await worker.commit()
                await worker.rollback()
            async with owned_session_factory(engine, "worker")() as next_provider:
                next_provider.add(
                    CollectionRun(started_at=now_utc(), status="running", trigger="late")
                )
                with pytest.raises(CollectionLeaseLost):
                    await next_provider.commit()
                await next_provider.rollback()
        async with factory() as reader:
            rows = (await reader.scalars(select(CollectionRun))).all()
            assert [(row.trigger, row.status) for row in rows] == [("first", "failed")]
    finally:
        await engine.dispose()


async def test_reconciliation_scans_live_first_page_and_preserves_unknown_or_live_workers(
    test_settings,
):
    engine, factory = await database(test_settings)
    try:
        now = now_utc()
        async with factory() as session:
            for owner, heartbeat in [
                ("live", now - timedelta(days=1)),
                ("terminal", now),
                ("missing_old", now - timedelta(hours=6)),
                ("missing_new", now),
                (None, now),
            ]:
                session.add(
                    CollectionRun(
                        started_at=now,
                        heartbeat_at=heartbeat,
                        status="running",
                        trigger="test",
                        orchestrator_run_id=owner,
                    )
                )
            await session.commit()

        class Instance:
            def get_run_by_id(self, owner):
                return {
                    "live": SimpleNamespace(is_finished=False),
                    "terminal": SimpleNamespace(is_finished=True),
                }.get(owner)

        assert await reconcile_collection_runs(factory, Instance(), page_size=1) == 2
        async with factory() as session:
            rows = (await session.scalars(select(CollectionRun).order_by(CollectionRun.id))).all()
            assert [row.status for row in rows] == [
                "running",
                "failed",
                "failed",
                "running",
                "running",
            ]

        class Broken:
            def get_run_by_id(self, owner):
                raise ConnectionError("metadata unavailable")

        assert await reconcile_collection_runs(factory, Broken(), page_size=1) == 0
    finally:
        await engine.dispose()


async def test_committed_partial_data_is_replayable_before_and_after_recovery(
    test_settings,
):
    engine, factory = await database(test_settings)
    try:
        async with owned_session_factory(engine, "worker")() as session:
            run = CollectionRun(started_at=now_utc(), status="running", trigger="test")
            session.add(run)
            await session.commit()
            session.add(
                RawApiResponse(
                    collection_run_id=run.id,
                    source="test",
                    endpoint="test",
                    status_code=200,
                    body_text="committed",
                    received_at=now_utc(),
                    parse_status="success",
                )
            )
            await session.commit()
        instance = SimpleNamespace(get_run_by_id=lambda _: SimpleNamespace(is_finished=True))
        assert await reconcile_collection_runs(factory, instance) == 1
        async with factory() as reader:
            assert [
                row.body_text for row in (await reader.scalars(select(RawApiResponse))).all()
            ] == ["committed"]
    finally:
        await engine.dispose()
