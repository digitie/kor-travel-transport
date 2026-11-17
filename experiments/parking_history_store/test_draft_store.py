"""임시 SQLite에서 미연결 reader의 fail-closed 계약만 확인한다."""
import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, insert, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from experiments.parking_history_store import draft_store as store


@pytest.mark.parametrize("change,hit", [
    ("unchanged", True), ("other_writer", False), ("incomplete", False),
    ("format", False), ("scope", False), ("encoding", False),
    ("before_range", False), ("after_range", False),
])
def test_independent_reader_requires_current_complete_exact_payload(change, hit):
    async def check():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        factory = async_sessionmaker(engine)
        now = datetime(2026, 11, 18, tzinfo=UTC)
        start, end = now-timedelta(days=30), now-timedelta(days=30)+timedelta(minutes=1)
        body = b"precompressed-fixture"
        async with engine.begin() as connection:
            await connection.run_sync(store.metadata.create_all)
        async with factory() as session:
            await session.execute(insert(store.source).values(singleton=1, revision=7))
            await session.execute(insert(store.generations).values(id="g1", source_revision=7,
                format_version=1, complete=True, byte_count=len(body), payload_count=1))
            await session.execute(insert(store.payloads).values(generation_id="g1", scope="all", days=30,
                encoding="gzip", cutoff_from=start, cutoff_through=end, item_count=10,
                sha256=hashlib.sha256(body).hexdigest(), body=body))
            await session.execute(insert(store.heads).values(singleton=1, generation_id="g1"))
            await session.commit()
            if change == "other_writer":
                await session.execute(update(store.source).values(revision=8))
            elif change == "incomplete":
                await session.execute(update(store.generations).values(complete=False))
            elif change == "format":
                await session.execute(update(store.generations).values(format_version=2))
            await session.commit()
            statements = []
            def seen(conn, cursor, statement, parameters, context, many):
                statements.append(statement)
            event.listen(engine.sync_engine, "before_cursor_execute", seen)
            cutoff = start-timedelta(microseconds=1) if change == "before_range" else (
                     end+timedelta(microseconds=1) if change == "after_range" else start)
            value = await store.read(session, scope="airport:GMP" if change == "scope" else "all",
                days=30, encoding="br" if change == "encoding" else "gzip", cutoff=cutoff, checked_at=now)
            event.remove(engine.sync_engine, "before_cursor_execute", seen)
            assert (value is not None) is hit
            assert len(statements) == 1 and statements[0].lstrip().startswith("SELECT")
            if hit:
                assert value.body == body and value.item_count == 10 and value.checked_at == now
                assert await store.read(session, scope="all", days=30, encoding="gzip", cutoff=end, checked_at=now)
        await engine.dispose()
    asyncio.run(check())
