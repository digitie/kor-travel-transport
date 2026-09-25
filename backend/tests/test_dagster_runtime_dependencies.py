"""Dagster control-plane runtime dependency contracts."""

from sqlalchemy import create_engine


def test_dagster_postgres_runtime_uses_psycopg2_driver() -> None:
    """Dagster's PostgreSQL event storage requires psycopg2 NOTIFY semantics."""

    engine = create_engine("postgresql://unused:unused@127.0.0.1:1/unused")
    try:
        assert engine.dialect.driver == "psycopg2"
    finally:
        engine.dispose()
