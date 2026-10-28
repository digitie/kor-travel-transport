"""0037의 빈 상태 검사와 DROP 사이에 영구 행이 커밋되지 않도록 검증한다."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.environment import EnvironmentContext
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.util import await_only


TABLES = ("parking_archive_issues", "parking_global_statistics_buckets", "parking_latest_states")
OLD = "0036_parking_statistics_archive"
NEW = "0037_parking_archive_coverage"
INSERTS = {
    "parking_archive_issues": """INSERT INTO parking_archive_issues VALUES
        ('airport:1', '2026-01-01T00:00:00Z', 'fixture', 1, now(), now())""",
    "parking_global_statistics_buckets": """INSERT INTO parking_global_statistics_buckets
        (bucket_at,bucket_end,format_version,raw_count,selected_count,max_snapshot_id,
         raw_sha256,statistics_sha256,statistics_json,airport_proofs_json,sealed_at)
        VALUES ('2026-01-01T00:00:00Z','2026-01-01T00:10:00Z',1,1,1,1,'raw','stats','{}','{}',now())""",
    "parking_latest_states": """INSERT INTO parking_latest_states
        (parking_lot_id,airport_id,snapshot_order,source,observed_at,collected_at,latest_ingested_at,
         occupied_spaces,total_spaces,available_spaces)
        VALUES (1,1,1,'fixture',now(),now(),now(),2,10,8)""",
}


def _step(connection, direction):
    """실제 Alembic step/version 갱신을 호출한 connection의 transaction 안에서 수행한다."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    script = ScriptDirectory.from_config(config)
    target = OLD if direction == "downgrade" else NEW
    planner = script._downgrade_revs if direction == "downgrade" else script._upgrade_revs
    with EnvironmentContext(config, script, fn=lambda revision, _: planner(target, revision),
                            destination_rev=target) as context:
        context.configure(connection=connection, transactional_ddl=True, transaction_per_migration=False)
        context.run_migrations()


def _engine(test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("전용 PostgreSQL DB에서만 실제 세션 경합을 검증합니다")
    return create_async_engine(test_settings.database_url, poolclass=NullPool,
                              connect_args={"command_timeout": 15})


async def _seed(engine):
    async with engine.begin() as connection:
        await connection.execute(sa.text("""INSERT INTO airports
            (id,code,name_ko,source,created_at,updated_at) VALUES (1,'FIX','검증','fixture',now(),now())"""))
        await connection.execute(sa.text("""INSERT INTO parking_lots
            (id,airport_id,source_lot_id,name,is_active,created_at,updated_at)
            VALUES (1,1,'fixture','검증',true,now(),now())"""))
        await connection.execute(sa.text("""INSERT INTO parking_snapshots
            (airport_id,parking_lot_id,observed_at,collected_at,source,occupied_spaces,total_spaces,available_spaces,raw_item_json)
            VALUES (1,1,'2026-01-01T00:00:00Z',now(),'fixture',2,10,8,'{"keep":"raw"}')"""))
        await connection.execute(sa.text("""INSERT INTO parking_statistics_buckets
            (airport_id,bucket_at,bucket_end,format_version,raw_count,selected_count,max_snapshot_id,
             raw_sha256,statistics_sha256,statistics_json,created_at)
            VALUES (1,'2026-01-01T00:00:00Z','2026-01-01T00:10:00Z',1,1,1,1,'raw','stats','{"keep":"archive"}',now())"""))


async def _state(engine):
    async with engine.connect() as connection:
        head = await connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
        tables = [await connection.scalar(sa.text("SELECT to_regclass(:name)::text"), {"name": name})
                  for name in TABLES]
        raw = await connection.scalar(sa.text("SELECT raw_item_json FROM parking_snapshots"))
        archive = await connection.scalar(sa.text("SELECT statistics_json FROM parking_statistics_buckets"))
        return head, tables, raw, archive


async def _restore(engine):
    async with engine.begin() as connection:
        if await connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == OLD:
            await connection.run_sync(lambda sync: _step(sync, "upgrade"))


@pytest.mark.parametrize("table", TABLES)
def test_downgrade_blocks_insert_after_last_empty_read(test_settings, table, record_testsuite_property):
    async def run():
        engine = _engine(test_settings)
        writer = None
        fired = False
        proof = {"table": table, "writer_committed_before_drop": False, "writer_waited_for_ddl": False}
        await _seed(engine)
        try:
            async with engine.connect() as write_connection, engine.connect() as monitor:
                writer_pid = await write_connection.scalar(sa.text("SELECT pg_backend_pid()"))
                await write_connection.commit()
                async def insert():
                    try:
                        async with write_connection.begin():
                            await write_connection.execute(sa.text(INSERTS[table]))
                        return {"committed": True}
                    except sa.exc.DBAPIError as error:
                        return {"committed": False, "sqlstate": error.orig.sqlstate}
                async def window(ddl_pid):
                    nonlocal writer
                    writer = asyncio.create_task(insert())
                    for _ in range(100):
                        if writer.done():
                            proof["writer_committed_before_drop"] = (await writer)["committed"]
                            break
                        blockers = await monitor.scalar(sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": writer_pid})
                        await monitor.commit()
                        if ddl_pid in blockers:
                            proof["writer_waited_for_ddl"] = True
                            break
                        await asyncio.sleep(.01)
                    else:
                        raise AssertionError("writer의 실제 commit/DDL lock 대기를 확인하지 못했습니다")
                def hook(connection, _cursor, statement, _parameters, _context, _many):
                    nonlocal fired
                    if not fired and statement.strip().startswith("SELECT 1 FROM parking_latest_states LIMIT 1"):
                        fired = True
                        ddl_pid = connection.scalar(sa.text("SELECT pg_backend_pid()"))
                        await_only(window(ddl_pid))
                sa.event.listen(engine.sync_engine, "after_cursor_execute", hook)
                try:
                    async with engine.begin() as connection:
                        await connection.run_sync(lambda sync: _step(sync, "downgrade"))
                finally:
                    sa.event.remove(engine.sync_engine, "after_cursor_execute", hook)
                assert fired
                proof["writer_result"] = await asyncio.wait_for(writer, 5)
                head, tables, raw, archive = await _state(engine)
                proof.update(head_after=head, tables_after=tables, raw_preserved=raw == {"keep": "raw"},
                             archive36_preserved=archive == {"keep": "archive"})
                record_testsuite_property(f"actual_pg_race_{table}", json.dumps(proof, sort_keys=True))
                assert proof["writer_waited_for_ddl"], proof
                assert proof["writer_committed_before_drop"] is False, proof
                assert proof["writer_result"] == {"committed": False, "sqlstate": "42P01"}, proof
                assert head == OLD and tables == [None] * 3
                assert proof["raw_preserved"] and proof["archive36_preserved"]
        finally:
            if writer is not None and not writer.done():
                await asyncio.wait_for(writer, 5)
            await _restore(engine)
            await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("table", TABLES)
def test_existing_row_rejects_drop_and_keeps_revision(test_settings, table):
    async def run():
        engine = _engine(test_settings)
        await _seed(engine)
        try:
            async with engine.begin() as connection:
                await connection.execute(sa.text(INSERTS[table]))
            with pytest.raises(RuntimeError, match="영구 통계"):
                async with engine.begin() as connection:
                    await connection.run_sync(lambda sync: _step(sync, "downgrade"))
            head, tables, raw, archive = await _state(engine)
            assert head == NEW and tables == list(TABLES)
            assert raw == {"keep": "raw"} and archive == {"keep": "archive"}
            async with engine.connect() as connection:
                assert await connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 1
        finally:
            await _restore(engine)
            await engine.dispose()
    asyncio.run(run())


def test_partial_ddl_error_rolls_back_tables_and_revision(test_settings):
    async def run():
        engine = _engine(test_settings)
        await _seed(engine)
        def fail(_connection, _cursor, statement, _parameters, _context, _many):
            if statement.strip().startswith("DROP TABLE parking_archive_issues"):
                raise RuntimeError("DDL fixture failure")
        sa.event.listen(engine.sync_engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(RuntimeError, match="DDL fixture failure"):
                async with engine.begin() as connection:
                    await connection.run_sync(lambda sync: _step(sync, "downgrade"))
            head, tables, raw, archive = await _state(engine)
            assert head == NEW and tables == list(TABLES)
            assert raw == {"keep": "raw"} and archive == {"keep": "archive"}
        finally:
            sa.event.remove(engine.sync_engine, "before_cursor_execute", fail)
            await _restore(engine)
            await engine.dispose()
    asyncio.run(run())


async def _wait_for_lock(monitor, waiting_pid, blocking_pid):
    for _ in range(100):
        blockers = await monitor.scalar(sa.text("SELECT pg_blocking_pids(:pid)"), {"pid": waiting_pid})
        await monitor.commit()
        if blocking_pid in blockers:
            return
        await asyncio.sleep(.01)
    raise AssertionError("실제 PostgreSQL 잠금 경합이 관측되지 않았습니다")


@pytest.mark.parametrize("table", TABLES)
def test_writer_before_lock_commits_then_empty_recheck_refuses_drop(test_settings, table):
    async def run():
        engine = _engine(test_settings)
        await _seed(engine)
        migration = None
        try:
            async with engine.connect() as writer, engine.connect() as ddl, engine.connect() as monitor:
                writer_pid = await writer.scalar(sa.text("SELECT pg_backend_pid()"))
                await writer.commit()
                ddl_pid = await ddl.scalar(sa.text("SELECT pg_backend_pid()"))
                await ddl.commit()
                await writer.execute(sa.text(INSERTS[table]))
                async def downgrade():
                    async with ddl.begin():
                        await ddl.run_sync(lambda sync: _step(sync, "downgrade"))
                migration = asyncio.create_task(downgrade())
                await _wait_for_lock(monitor, ddl_pid, writer_pid)
                await writer.commit()
                with pytest.raises(RuntimeError, match="영구 통계"):
                    await asyncio.wait_for(migration, 10)
                head, tables, raw, archive = await _state(engine)
                assert head == NEW and tables == list(TABLES)
                assert raw == {"keep": "raw"} and archive == {"keep": "archive"}
                assert await monitor.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 1
        finally:
            if migration is not None and not migration.done():
                await asyncio.wait_for(migration, 15)
            await _restore(engine)
            await engine.dispose()
    asyncio.run(run())


def test_lock_timeout_preserves_tables_revision_and_writer_row(test_settings):
    async def run():
        engine = _engine(test_settings)
        await _seed(engine)
        try:
            async with engine.connect() as writer:
                await writer.execute(sa.text(INSERTS["parking_global_statistics_buckets"]))
                with pytest.raises(sa.exc.DBAPIError) as failure:
                    async with engine.begin() as connection:
                        await connection.run_sync(lambda sync: _step(sync, "downgrade"))
                assert failure.value.orig.sqlstate == "55P03"
                await writer.commit()
            head, tables, raw, archive = await _state(engine)
            assert head == NEW and tables == list(TABLES)
            assert raw == {"keep": "raw"} and archive == {"keep": "archive"}
            async with engine.connect() as connection:
                assert await connection.scalar(sa.text("SELECT count(*) FROM parking_global_statistics_buckets")) == 1
        finally:
            await _restore(engine)
            await engine.dispose()
    asyncio.run(run())


def test_sqlite_empty_drop_and_nonempty_refusal():
    path = Path(__file__).parents[1] / "alembic/versions/0037_parking_archive_coverage.py"
    spec = importlib.util.spec_from_file_location("coverage_sqlite_fixture", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE parking_lots (id INTEGER, airport_id INTEGER, UNIQUE(id,airport_id))"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            connection.execute(sa.text("""INSERT INTO parking_archive_issues VALUES
                ('airport:1','2026-01-01','fixture',1,'2026-01-01','2026-01-01')"""))
            with pytest.raises(RuntimeError, match="영구 통계"):
                migration.downgrade()
            assert all(sa.inspect(connection).has_table(table) for table in TABLES)
            connection.execute(sa.text("DELETE FROM parking_archive_issues"))
            migration.downgrade()
            assert not any(sa.inspect(connection).has_table(table) for table in TABLES)
    finally:
        engine.dispose()
