from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import make_url
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg


@pytest.fixture
def benchmark():
    path = Path(__file__).parent / "benchmarks" / "parking_analytics_cache.py"
    spec = importlib.util.spec_from_file_location("parking_analytics_benchmark_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_benchmark_accepts_only_explicit_loopback_test_database(benchmark, monkeypatch, host):
    url = f"postgresql+asyncpg://test@{host}/parking_analytics_benchmark_test"
    monkeypatch.setenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE", "1")
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    accepted = benchmark.benchmark_database_url()
    assert accepted == url
    _args, kwargs = PGDialect_asyncpg().create_connect_args(make_url(accepted))
    assert kwargs["host"] == host
    assert kwargs["database"] == "parking_analytics_benchmark_test"


@pytest.mark.parametrize("suffix", [
    "?host=192.0.2.123",
    "?database=existing_app",
    "?host=192.0.2.123&database=existing_app",
    "?host=%2Fvar%2Frun%2Fpostgresql",
    "?port=6543",
    "?server_settings=search_path%3Dother_schema",
    "?ssl=disable",
])
def test_benchmark_rejects_all_connection_query_options(benchmark, monkeypatch, suffix):
    monkeypatch.setenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE", "1")
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://test@127.0.0.1/parking_analytics_benchmark_test" + suffix,
    )
    with pytest.raises(RuntimeError, match="전용 PostgreSQL"):
        benchmark.benchmark_database_url()


@pytest.mark.parametrize("url", [
    "postgresql+asyncpg://test@192.0.2.123/parking_analytics_benchmark_test",
    "postgresql+asyncpg://test@127.0.0.1/existing_app",
    "sqlite:///parking_analytics_benchmark_test",
])
def test_benchmark_rejects_other_hosts_databases_and_drivers(benchmark, monkeypatch, url):
    monkeypatch.setenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE", "1")
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    with pytest.raises(RuntimeError, match="전용 PostgreSQL"):
        benchmark.benchmark_database_url()


def test_benchmark_requires_explicit_test_opt_in(benchmark, monkeypatch):
    monkeypatch.delenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE", raising=False)
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://test@127.0.0.1/parking_analytics_benchmark_test",
    )
    with pytest.raises(RuntimeError, match="격리 테스트 표지"):
        benchmark.benchmark_database_url()
