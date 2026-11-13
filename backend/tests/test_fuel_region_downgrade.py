"""빈 원장 검사 중 수집 writer가 들어와 영구 자료를 잃지 않도록 보호한다."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/0037_regional_fuel_and_rail_daily.py"
    spec = importlib.util.spec_from_file_location("fuel_region_downgrade", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("isolation,options", [
    ("REPEATABLE READ", {}), ("SERIALIZABLE", {}),
    ("READ COMMITTED", {"isolation_level": "AUTOCOMMIT"}),
])
def test_stale_or_autocommit_snapshot_cannot_drop(monkeypatch, isolation, options):
    migration = _migration()
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"),
                           get_isolation_level=lambda: isolation,
                           get_execution_options=lambda: options, execute=Mock())
    ddl = SimpleNamespace(get_bind=lambda: bind, execute=Mock(), drop_table=Mock())
    monkeypatch.setattr(migration, "op", ddl)
    with pytest.raises(RuntimeError, match="READ COMMITTED"):
        migration.downgrade()
    bind.execute.assert_not_called()
    ddl.execute.assert_not_called()
    ddl.drop_table.assert_not_called()


@pytest.mark.parametrize("table", ["fuel_region_summaries", "kric_timetable_attempts"])
def test_committed_writer_is_visible_after_waiting_for_lock(test_settings, table):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("별도 PostgreSQL 시험 DB에서만 두 세션 경합을 실행합니다")

    async def scenario():
        engine = create_async_engine(test_settings.database_url, poolclass=NullPool,
                                     connect_args={"command_timeout": 15})
        schema = "fuel_downgrade_" + uuid4().hex
        try:
            async with engine.begin() as setup:
                await setup.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
                for name in ("fuel_region_summaries", "kric_timetable_attempts"):
                    await setup.execute(sa.text(f'CREATE TABLE "{schema}".{name} (id int)'))
            async with (
                engine.connect() as writer,
                engine.connect() as ddl,
                writer.begin(),
            ):
                await writer.execute(sa.text(f'INSERT INTO "{schema}".{table} VALUES (1)'))

                async def downgrade():
                    async with ddl.begin():
                        await ddl.execute(sa.text(f'SET LOCAL search_path TO "{schema}"'))
                        def invoke(connection):
                            migration = _migration()
                            migration.op = Operations(MigrationContext.configure(connection))
                            migration.downgrade()
                        await ddl.run_sync(invoke)

                pid = await ddl.scalar(sa.text("SELECT pg_backend_pid()"))
                await ddl.rollback()
                attempt = asyncio.create_task(downgrade())
                try:
                    async def waiting():
                        # observer는 매 조회 새 READ COMMITTED snapshot을 사용한다.
                        async with engine.connect() as observer:
                            while not attempt.done():
                                blocked = await observer.scalar(sa.text(
                                    "SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=:pid"
                                ), {"pid": pid})
                                await observer.rollback()
                                if blocked:
                                    return
                                await asyncio.sleep(.01)
                        raise AssertionError("downgrade가 writer를 기다리지 않았습니다")
                    await asyncio.wait_for(waiting(), 3)
                    await writer.commit()
                    with pytest.raises(RuntimeError, match="downgrade할 수 없습니다"):
                        await asyncio.wait_for(attempt, 7)
                finally:
                    if not attempt.done():
                        attempt.cancel()
                        await asyncio.gather(attempt, return_exceptions=True)
            async with engine.connect() as check:
                assert await check.scalar(sa.text(f'SELECT count(*) FROM "{schema}".{table}')) == 1
                for name in ("fuel_region_summaries", "kric_timetable_attempts"):
                    assert await check.scalar(sa.text("SELECT to_regclass(:name)"), {"name": f"{schema}.{name}"})
        finally:
            async with engine.begin() as cleanup:
                await cleanup.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(scenario())


def test_lock_failure_never_drops_tables(monkeypatch):
    migration = _migration()
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"),
                           get_isolation_level=lambda: "READ COMMITTED",
                           get_execution_options=dict, execute=Mock())
    def execute(sql):
        if str(sql).startswith("LOCK TABLE"):
            raise RuntimeError("lock timeout")
    ddl = SimpleNamespace(get_bind=lambda: bind, execute=execute, drop_table=Mock())
    monkeypatch.setattr(migration, "op", ddl)
    with pytest.raises(RuntimeError, match="lock timeout"):
        migration.downgrade()
    bind.execute.assert_not_called()
    ddl.drop_table.assert_not_called()
