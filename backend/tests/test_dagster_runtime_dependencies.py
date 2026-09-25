"""Dagster control-plane runtime dependency contracts."""


def test_dagster_postgres_runtime_includes_sync_driver() -> None:
    """Dagster storage uses SQLAlchemy's synchronous PostgreSQL dialect."""

    import psycopg

    assert psycopg.__version__
