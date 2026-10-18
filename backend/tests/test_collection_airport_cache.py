"""공항 조회 재사용의 SQL 비용과 저장/실패 계약을 실제 SQLite에서 검증한다."""
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import event, select, func
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.models import Base, Airport, ParkingSnapshot
from app.services.collection import CollectionService, FixturePublicDataClient
from app.services.parsers import ParsedParkingObservation


def observation(index, code="GMP"):
    return ParsedParkingObservation(
        source="fixture", airport_code=code, airport_name_ko=f"공항-{index}",
        airport_name_en=None if index % 2 else f"airport-{index}",
        lot_id="lot", lot_name="주차장", terminal=None, category=None,
        observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=index),
        occupied_spaces=2, total_spaces=10, congestion_label=None,
        congestion_ratio=0.2, raw_item={"index": index},
    )


@pytest.mark.parametrize("existing", [False, True])
def test_batch_looks_up_each_airport_once_and_preserves_observations(existing):
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        service = CollectionService(Settings(), client=FixturePublicDataClient())
        async with factory() as session:
            if existing:
                for code in ("GMP", "PUS", "CJU"):
                    await service._get_or_create_airport(session, code, "기존", "old", "original")
                await session.commit()
            statements = []
            def count(conn, cursor, sql, params, context, many):
                if sql.startswith("SELECT") and "FROM airports" in sql:
                    statements.append(sql)
            event.listen(engine.sync_engine, "before_cursor_execute", count)
            rows = [observation(i, ("GMP", "PUS", "CJU")[i % 3]) for i in range(12)]
            assert await service._store_observations(session, 1, rows) == 12
            assert len(statements) == 3
            # 중복 관측에서도 기준정보의 마지막 이름을 갱신한다.
            duplicate = observation(11, "CJU")
            duplicate.airport_name_ko = "정정"
            assert await service._store_observations(session, 2, [duplicate]) == 0
            assert len(statements) == 4  # 다음 호출에서는 반드시 DB 재조회
            event.remove(engine.sync_engine, "before_cursor_execute", count)
            airports = {a.code: a for a in (await session.scalars(select(Airport))).all()}
            for code, last in (("GMP", 9), ("PUS", 10), ("CJU", 11)):
                airport = airports[code]
                assert airport.name_ko == ("정정" if code == "CJU" else f"공항-{last}")
                assert airport.name_en == (None if last % 2 else f"airport-{last}")
                assert airport.source == ("original" if existing else "kac")
            snapshots = (await session.scalars(select(ParkingSnapshot).order_by(ParkingSnapshot.id))).all()
            assert [s.raw_item_json for s in snapshots] == [{"index": i} for i in range(12)]
            assert all(s.available_spaces == 8 for s in snapshots)
        await engine.dispose()
    asyncio.run(run())


def test_failed_batch_rollback_does_not_reuse_airport_in_next_call():
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        service = CollectionService(Settings(), client=FixturePublicDataClient())
        async with factory() as session:
            with patch.object(service, "_get_or_create_lot", side_effect=RuntimeError("fixture")):
                with pytest.raises(RuntimeError, match="fixture"):
                    await service._store_observations(session, 1, [observation(0)])
            await session.rollback()
            assert await session.scalar(select(func.count()).select_from(Airport)) == 0
            assert await service._store_observations(session, 2, [observation(1)]) == 1
            assert await session.scalar(select(func.count()).select_from(Airport)) == 1
            assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == 1
        await engine.dispose()
    asyncio.run(run())


def test_snapshot_savepoint_conflict_keeps_cached_airport_valid():
    class ConflictOnceSession(AsyncSession):
        conflicted = False

        async def flush(self, objects=None):
            if not self.conflicted and any(isinstance(obj, ParkingSnapshot) for obj in self.new):
                self.conflicted = True
                raise IntegrityError("fixture", {}, RuntimeError("snapshot conflict"))
            return await super().flush(objects)

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=ConflictOnceSession, expire_on_commit=False)
        service = CollectionService(Settings(), client=FixturePublicDataClient())
        async with factory() as session:
            assert await service._store_observations(session, 1, [observation(0), observation(1)]) == 1
            airport = await session.scalar(select(Airport))
            assert airport.name_ko == "공항-1"
            assert airport.name_en is None
            assert await session.scalar(select(func.count()).select_from(Airport)) == 1
            snapshot = await session.scalar(select(ParkingSnapshot))
            assert snapshot.raw_item_json == {"index": 1}
            await session.commit()
        await engine.dispose()
    asyncio.run(run())
