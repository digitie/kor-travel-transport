"""유가 인덱스 DDL은 성공·실패 모두 연결 제한을 정리한다."""

import importlib.util
import asyncio
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/0015_fuel_statistics_priced.py"
    spec = importlib.util.spec_from_file_location("fuel_statistics_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("fails", [False, True])
def test_concurrent_ddl_limits_are_set_and_reset(monkeypatch, fails):
    migration = _migration()
    execute = Mock()
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        execute=execute,
        get_context=lambda: SimpleNamespace(autocommit_block=nullcontext, as_sql=False),
    ))
    try:
        with migration._bounded_concurrent_ddl():
            assert [call.args[0] for call in execute.call_args_list] == [
                "SET lock_timeout = '3s'", "SET statement_timeout = '180s'",
            ]
            if fails:
                raise RuntimeError("DDL failure")
    except RuntimeError:
        assert fails
    assert [call.args[0] for call in execute.call_args_list][-2:] == [
        "RESET statement_timeout", "RESET lock_timeout",
    ]


def test_invalid_concurrent_index_is_not_treated_as_success(monkeypatch):
    migration = _migration()
    create = Mock()
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        get_bind=lambda: SimpleNamespace(scalar=Mock(return_value=False)),
        create_index=create,
    ))
    with pytest.raises(RuntimeError, match="invalid index"):
        migration._ensure_index("ix_fuel_prices_statistics_priced", priced=True)
    create.assert_not_called()


def test_offline_migration_reports_the_required_online_validation(monkeypatch):
    migration = _migration()
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        get_context=lambda: SimpleNamespace(as_sql=True),
    ))
    with pytest.raises(RuntimeError, match="온라인 migration"):
        migration.upgrade()


def test_postgres_migration_lock_timeout_and_recovery(test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 전용 DDL 잠금·복구 검증")
    from sqlalchemy import text
    from app.db.session import create_engine_and_session_factory

    async def exercise():
        engine, _ = create_engine_and_session_factory(test_settings.database_url)
        env = {**os.environ, "DATABASE_URL": test_settings.database_url}

        async def migrate(*args):
            process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "alembic", *args,
                cwd=Path(__file__).parents[1], env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout=20)
            except BaseException:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                raise
            return process.returncode, output.decode()

        try:
            async with engine.begin() as connection:
                await connection.execute(text("LOCK TABLE fuel_price_snapshots IN ACCESS EXCLUSIVE MODE"))
                started = asyncio.get_running_loop().time()
                code, output = await migrate("downgrade", "0014_kric_timetables")
                elapsed = asyncio.get_running_loop().time() - started
                assert code != 0 and "lock timeout" in output
                assert 2.5 <= elapsed < 15
            # 잠금이 해제된 뒤 동일 migration 재실행과 원래 head 복원이 가능해야 한다.
            code, output = await migrate("downgrade", "0014_kric_timetables")
            assert code == 0, output
            code, output = await migrate("upgrade", "head")
            assert code == 0, output
            async with engine.connect() as connection:
                assert await connection.scalar(text("SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass('ix_fuel_prices_statistics_priced')")) is True
                assert await connection.scalar(text("SELECT to_regclass('ix_fuel_prices_statistics_collected')")) is None
        finally:
            await engine.dispose()

    asyncio.run(exercise())
