"""실제 PostgreSQL에서 준비/공개 분리와 세대 역전을 검증한다."""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text, update

from app.db.session import create_engine_and_session_factory
from app.models import FuelLatestPrice, FuelStatisticsPoint, FuelStatisticsState
from app.services import fuel_statistics as stats
from test_fuel_statistics import seed

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"),
    reason="실제 PostgreSQL 동시성 검증",
)


def test_preparation_does_not_hold_publication_lock_and_older_cannot_replace_newer(test_settings):
    async def exercise():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        stamp = datetime.now(timezone.utc)
        async with factory() as session:
            await seed(session, stamp)
            await stats.publish_fuel_statistics(session, stats.OPINET, stamp)
            await session.commit()
        older, newer = stamp + timedelta(hours=1), stamp + timedelta(hours=2)
        preparing, release = asyncio.Event(), asyncio.Event()
        original_lock = stats.lock_fuel_statistics

        async def delayed_lock(session, source):
            # 최초 소비자가 point 준비를 마친 뒤 멈춘다. 다른 세대의 공개는 진행한다.
            if session.info.get("delay"):
                preparing.set()
                await release.wait()
            await original_lock(session, source)

        async def publish_old():
            async with factory() as session:
                session.info["delay"] = True
                await stats.publish_fuel_statistics(session, stats.OPINET, older)
                await session.commit()

        with patch.object(stats, "lock_fuel_statistics", delayed_lock):
            task = asyncio.create_task(publish_old())
            try:
                await asyncio.wait_for(preparing.wait(), 5)
                async with factory() as session:
                    assert await session.scalar(text("SELECT pg_try_advisory_xact_lock(420061)"))
                    before = await stats.fuel_statistics_page(session, "nationwide", "B027")
                    assert before["items"][0]["average_price"] == 1666.67
                    await session.rollback()
                    await session.execute(update(FuelLatestPrice).values(price=2100))
                    await session.commit()
                    await stats.publish_fuel_statistics(session, stats.OPINET, newer)
                    await session.commit()
                release.set()
                await asyncio.wait_for(task, 5)
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        async with factory() as session:
            current = await stats.fuel_statistics_page(session, "nationwide", "B027")
            assert current["items"][0]["average_price"] == 2100
            viewport = await stats.viewport_fuel_statistics(session, (124, 32, 132, 39), [], [], None)
            assert viewport[0]["average_price"] == 2100
            assert await session.scalar(select(func.count()).select_from(FuelStatisticsPoint).where(
                FuelStatisticsPoint.generated_at == older,
            )) == 0
            await stats.cleanup_fuel_statistics(session, stats.OPINET)
            assert await session.scalar(select(func.count()).select_from(FuelStatisticsPoint)) == 3
        await engine.dispose()
    asyncio.run(exercise())


def test_duplicate_generation_waits_then_keeps_public_rows(test_settings):
    async def exercise():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        stamp = datetime.now(timezone.utc)
        async with factory() as session:
            await seed(session, stamp)
            await session.commit()
        prepared, release = asyncio.Event(), asyncio.Event()
        original_lock = stats.lock_fuel_statistics

        async def delayed_lock(session, source):
            if session.info.get("delay"):
                prepared.set()
                await release.wait()
            await original_lock(session, source)

        async def publish(delay):
            async with factory() as session:
                session.info["delay"] = delay
                await stats.publish_fuel_statistics(session, stats.OPINET, stamp)
                await session.commit()

        with patch.object(stats, "lock_fuel_statistics", delayed_lock):
            first = asyncio.create_task(publish(True))
            second = None
            try:
                await asyncio.wait_for(prepared.wait(), 5)
                second = asyncio.create_task(publish(False))
                await asyncio.sleep(0.05)
                assert not second.done()
                release.set()
                await asyncio.wait_for(asyncio.gather(first, second), 5)
            finally:
                release.set()
                tasks = [task for task in (first, second) if task is not None]
                for task in tasks:
                    if not task.done(): task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(FuelStatisticsPoint)) == 3
            assert (await session.get(FuelStatisticsState, stats.OPINET)).generated_at == stamp
        await engine.dispose()
    asyncio.run(exercise())
