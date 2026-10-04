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


def _migration(file_name="0015_fuel_statistics_priced.py"):
    path = Path(__file__).parents[1] / "alembic/versions" / file_name
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


@pytest.mark.parametrize("fails", [False, True])
def test_latest_prices_downgrade_bounds_lock_and_preserves_view_on_failure(monkeypatch, fails):
    migration = _migration("0018_fuel_latest_prices.py")
    execute = Mock()
    drop_index = Mock(side_effect=RuntimeError("DDL failure") if fails else None)
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        execute=execute, drop_index=drop_index,
        get_context=lambda: SimpleNamespace(autocommit_block=nullcontext, as_sql=False),
    ))
    if fails:
        with pytest.raises(RuntimeError, match="DDL failure"):
            migration.downgrade()
    else:
        migration.downgrade()
    statements = [call.args[0] for call in execute.call_args_list]
    assert statements[:4] == [
        "SET lock_timeout = '3s'", "SET statement_timeout = '180s'",
        "RESET statement_timeout", "RESET lock_timeout",
    ]
    drop_index.assert_called_once_with(
        "ix_fuel_prices_latest_lookup", table_name="fuel_price_snapshots",
        postgresql_concurrently=True, if_exists=True,
    )
    # index 잠금 실패 뒤 MV를 삭제하지 않으며 정상 경로도 3초 상한을 유지한다.
    assert statements[4:] == ([] if fails else [
        "SET LOCAL lock_timeout = '3s'", "DROP MATERIALIZED VIEW fuel_latest_prices",
    ])


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
                # CLI 초기화·여러 revision 처리 시간과 DB의 잠금 상한은 별개다.
                output, _ = await asyncio.wait_for(process.communicate(), timeout=60)
            except BaseException:
                if process.returncode is None:
                    process.kill()
                # PIPE가 가득 차면 wait()도 멈출 수 있어 출력 회수에 별도 상한을 둔다.
                await asyncio.wait_for(process.communicate(), timeout=10)
                raise
            return process.returncode, output.decode()

        try:
            async with engine.begin() as connection:
                await connection.execute(text("LOCK TABLE fuel_price_snapshots IN ACCESS EXCLUSIVE MODE"))
                migration_task = asyncio.create_task(migrate("downgrade", "0014_kric_timetables"))
                wait_started_at = None
                try:
                    # pg_locks.waitstart는 CLI import 이전 시간을 포함하지 않는다.
                    # 이 테스트 DB에는 observer와 migration만 연결한다.
                    while not migration_task.done():
                        wait_started_at = await connection.scalar(text("""
                            SELECT min(waitstart) FROM pg_locks
                            WHERE NOT granted AND waitstart IS NOT NULL
                              AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
                              AND relation = 'fuel_price_snapshots'::regclass
                              AND pid <> pg_backend_pid()
                        """))
                        if wait_started_at is not None:
                            break
                        await asyncio.sleep(0.1)
                    code, output = await migration_task
                finally:
                    if not migration_task.done():
                        migration_task.cancel()
                        try:
                            await migration_task
                        except asyncio.CancelledError:
                            pass
                wait_finished_at = await connection.scalar(text("SELECT clock_timestamp()"))
                assert code != 0 and "canceling statement due to lock timeout" in output
                assert wait_started_at is not None
                # 종료 시각은 CLI 종료·observer 지연도 포함해 서버 잠금 상한으로 쓰지 않는다.
                # 3초 설정은 위 단위 검사가, 실제 timeout은 오류 문구와 60초 CLI 상한이 검증한다.
                assert (wait_finished_at - wait_started_at).total_seconds() >= 2.5
                # 잠금 경합으로 0018 downgrade가 중단돼도 런타임 MV는 남는다.
                async with engine.connect() as verifier:
                    assert await verifier.scalar(text("SELECT to_regclass('fuel_latest_prices')")) == "fuel_latest_prices"
            # 잠금이 해제된 뒤 동일 migration 재실행과 원래 head 복원이 가능해야 한다.
            code, output = await migrate("downgrade", "0014_kric_timetables")
            assert code == 0, output
            code, output = await migrate("upgrade", "head")
            assert code == 0, output
            async with engine.connect() as connection:
                assert await connection.scalar(text("SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass('ix_fuel_prices_statistics_priced')")) is True
                assert await connection.scalar(text("SELECT to_regclass('ix_fuel_prices_statistics_collected')")) is None
        finally:
            try:
                # assertion 실패로 중간 revision이 남아 다음 테스트가 깨지지 않게 한다.
                code, output = await migrate("upgrade", "head")
                assert code == 0, output
            finally:
                await engine.dispose()

    asyncio.run(exercise())
