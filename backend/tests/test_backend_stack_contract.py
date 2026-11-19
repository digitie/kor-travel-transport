"""공유 SQLAlchemy/asyncpg 축의 실제 다중 fetch 창·트랜잭션 계약."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from app.models import Airport, ParkingLot, ParkingSnapshot
from app.services import parking_history_cache as history
from sqlalchemy import event, insert


def test_postgres_core_stream_keeps_batches_max_id_live_priority_and_body(client):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL/asyncpg 다중 fetch 창 계약")
    factory = client.app.state.session_factory
    start = datetime(2026, 10, 1, tzinfo=UTC)
    count = history.HISTORY_FETCH_ROWS * 2 + 3
    observed_options = []
    released = []
    engine = client.app.state.engine

    def record(_conn, _cursor, statement, _parameters, context, _many):
        if "history_rows" in statement:
            observed_options.append(context.execution_options.get("yield_per"))

    async def check():
        async with factory() as session:
            airport = Airport(
                code="STK", name_ko="격리 축 시험", source="stack_test",
                created_at=start, updated_at=start,
            )
            session.add(airport)
            await session.flush()
            lot = ParkingLot(
                airport_id=airport.id, source_lot_id="stack-only",
                name="다중 fetch 창", created_at=start, updated_at=start,
            )
            session.add(lot)
            await session.flush()
            lot_id, airport_id = lot.id, airport.id
            rows = [
                {
                    "airport_id": airport_id, "parking_lot_id": lot_id,
                    "source": "stack_live", "observed_at": start + timedelta(seconds=i),
                    "collected_at": start + timedelta(seconds=i, minutes=1),
                    "occupied_spaces": i % 100, "total_spaces": 100,
                    "available_spaces": 100 - i % 100,
                }
                for i in range(count)
            ]
            # 나중에 수집된 migration 행도 같은 관측의 live 값을 대체하지 않는다.
            rows.extend(
                {**rows[i], "source": "migration_stack", "occupied_spaces": 99,
                 "available_spaces": 1, "collected_at": start + timedelta(days=1)}
                for i in range(0, count, 128)
            )
            await session.execute(insert(ParkingSnapshot), rows)
            await session.commit()

        class Session:
            async def __aenter__(self):
                self.inner = factory()
                await self.inner.__aenter__()
                return self

            async def __aexit__(self, *args):
                result = await self.inner.__aexit__(*args)
                released.append(not self.inner.in_transaction())
                return result

            async def scalar(self, statement):
                result = await self.inner.scalar(statement)
                # max ID를 읽은 뒤 들어온 행은 이 읽기 집합에 섞이지 않는다.
                async with factory() as writer:
                    writer.add(ParkingSnapshot(
                        airport_id=airport_id, parking_lot_id=lot_id,
                        source="stack_live", observed_at=start + timedelta(days=1),
                        collected_at=start + timedelta(days=1),
                        occupied_spaces=1, total_spaces=100, available_spaces=99,
                    ))
                    await writer.commit()
                return result

            async def connection(self):
                return await self.inner.connection()

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        try:
            snapshot = await history.load_snapshot(Session, earliest_observed_at=start)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record)
        assert released == [True]
        body = snapshot.render(start, "STK", None)
        expected = {
            "items": [
                {
                    "airport_code": "STK", "parking_lot_id": lot_id,
                    "observed_at": (start + timedelta(seconds=i)).isoformat().replace("+00:00", "Z"),
                    "occupied_spaces": i % 100, "total_spaces": 100,
                    "available_spaces": 100 - i % 100,
                }
                for i in range(count)
            ],
            "next_cursor": None,
        }
        assert body == json.dumps(expected, separators=(",", ":")).encode()
        assert observed_options == [history.HISTORY_FETCH_ROWS]

    asyncio.run(check())
