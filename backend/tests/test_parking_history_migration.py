"""장기 주차 이력 인덱스 생성은 잠금 제한·중단 복구 계약을 지킨다."""

import importlib.util
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/0021_parking_history_cover.py"
    spec = importlib.util.spec_from_file_location("parking_history_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("valid,expected_creates", [(None, 1), (True, 0)])
def test_cover_index_created_concurrently_and_analyzed(monkeypatch, valid, expected_creates):
    migration = _migration()
    execute = Mock()
    create = Mock()
    scalar = Mock(return_value=valid)
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        get_context=lambda: SimpleNamespace(autocommit_block=nullcontext, as_sql=False),
        get_bind=lambda: SimpleNamespace(scalar=scalar),
        execute=execute,
        create_index=create,
    ))

    migration.upgrade()

    assert "pg_get_indexdef" in str(scalar.call_args.args[0])
    assert "t.relname = 'parking_snapshots'" in str(scalar.call_args.args[0])

    assert create.call_count == expected_creates
    if expected_creates:
        args, kwargs = create.call_args
        assert args[:2] == (migration.INDEX_NAME, "parking_snapshots")
        assert kwargs["postgresql_concurrently"] is True
        assert kwargs["postgresql_include"] == [
            "parking_lot_id", "id", "collected_at", "source",
            "occupied_spaces", "total_spaces", "available_spaces",
        ]
    statements = [call.args[0] for call in execute.call_args_list]
    assert statements[:2] == ["SET lock_timeout = '3s'", "SET statement_timeout = '180s'"]
    assert statements[2:4] == ["RESET statement_timeout", "RESET lock_timeout"]
    assert "ANALYZE parking_snapshots" in statements
    assert "ALTER TABLE parking_snapshots SET (autovacuum_analyze_scale_factor = 0.02)" in statements


def test_invalid_index_fails_before_table_change_and_resets_limits(monkeypatch):
    migration = _migration()
    execute = Mock()
    create = Mock()
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        get_context=lambda: SimpleNamespace(autocommit_block=nullcontext, as_sql=False),
        get_bind=lambda: SimpleNamespace(scalar=Mock(return_value=False)),
        execute=execute,
        create_index=create,
    ))

    with pytest.raises(RuntimeError, match="invalid"):
        migration.upgrade()
    create.assert_not_called()
    assert [call.args[0] for call in execute.call_args_list][-2:] == [
        "RESET statement_timeout", "RESET lock_timeout",
    ]


def test_downgrade_keeps_index_when_table_lock_fails(monkeypatch):
    migration = _migration()
    execute = Mock(side_effect=lambda statement: (_ for _ in ()).throw(RuntimeError("lock timeout"))
                   if statement.startswith("ALTER TABLE") else None)
    drop = Mock()
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        get_context=lambda: SimpleNamespace(autocommit_block=nullcontext, as_sql=False),
        execute=execute,
        drop_index=drop,
    ))

    with pytest.raises(RuntimeError, match="lock timeout"):
        migration.downgrade()
    drop.assert_not_called()


def test_downgrade_resets_table_before_concurrent_drop(monkeypatch):
    migration = _migration()
    operations = []
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        get_context=lambda: SimpleNamespace(autocommit_block=nullcontext, as_sql=False),
        execute=lambda statement: operations.append(statement),
        drop_index=lambda *args, **kwargs: operations.append("DROP INDEX CONCURRENTLY"),
    ))

    migration.downgrade()
    assert operations.index("ALTER TABLE parking_snapshots RESET (autovacuum_analyze_scale_factor)") < operations.index("DROP INDEX CONCURRENTLY")


def test_offline_migration_is_rejected(monkeypatch):
    migration = _migration()
    monkeypatch.setattr(migration, "op", SimpleNamespace(
        get_context=lambda: SimpleNamespace(as_sql=True),
    ))
    with pytest.raises(RuntimeError, match="온라인 migration"):
        migration.upgrade()
