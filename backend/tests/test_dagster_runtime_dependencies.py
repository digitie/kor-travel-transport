"""Dagster control-plane runtime dependency contracts."""

from pathlib import Path

from sqlalchemy import create_engine


_ROOT = Path(__file__).resolve().parents[2]


def test_dagster_postgres_runtime_uses_psycopg2_driver() -> None:
    """Dagster's PostgreSQL event storage requires psycopg2 NOTIFY semantics."""

    engine = create_engine("postgresql+psycopg2://unused:unused@127.0.0.1:1/unused")
    try:
        assert engine.dialect.driver == "psycopg2"
    finally:
        engine.dispose()

    example = (_ROOT / ".env.server14.example").read_text(encoding="utf-8")
    assert "DAGSTER_POSTGRES_URL=postgresql+psycopg2://" in example
