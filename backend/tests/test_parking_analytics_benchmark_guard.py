from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import make_url
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg

from app.services import analytics, analytics_cache


def _load_benchmark():
    path = Path(__file__).parent / "benchmarks" / "parking_analytics_cache.py"
    spec = importlib.util.spec_from_file_location("parking_analytics_benchmark_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def benchmark(monkeypatch):
    # 회귀가 다시 생겨도 테스트 프로세스의 제품 시계는 teardown에서 복구한다.
    monkeypatch.setattr(analytics, "now_utc", analytics.now_utc)
    monkeypatch.setattr(analytics_cache, "now_utc", analytics_cache.now_utc)
    return _load_benchmark()


def test_benchmark_import_preserves_product_clock_identity_and_values(monkeypatch):
    before = (analytics.now_utc, analytics_cache.now_utc)
    monkeypatch.setattr(analytics, "now_utc", before[0])
    monkeypatch.setattr(analytics_cache, "now_utc", before[1])
    started = before[0]()
    _load_benchmark()
    assert analytics.now_utc is before[0]
    assert analytics_cache.now_utc is before[1]
    assert analytics.now_utc() >= started
    assert analytics_cache.now_utc() >= started


@pytest.mark.parametrize("failed", [False, True])
def test_benchmark_explicit_execution_restores_clocks_even_on_failure(
    benchmark, monkeypatch, tmp_path, failed,
):
    before = (analytics.now_utc, analytics_cache.now_utc)
    disposed = []

    async def dispose():
        disposed.append(True)

    async def measure(_engine, _factory):
        assert analytics.now_utc() == benchmark.NOW
        assert analytics_cache.now_utc() == benchmark.NOW
        if failed:
            raise RuntimeError("검증용 계산 실패")
        return {"synthetic": True}

    monkeypatch.setenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE", "1")
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://test@127.0.0.1/parking_analytics_benchmark_test",
    )
    monkeypatch.setattr(
        benchmark, "create_engine_and_session_factory",
        lambda _url: (SimpleNamespace(dispose=dispose), None),
    )
    monkeypatch.setattr(benchmark, "measure", measure)
    monkeypatch.setattr(
        sys, "argv", ["benchmark", "measure", "--out", str(tmp_path / "new-result.json")],
    )
    if failed:
        with pytest.raises(RuntimeError, match="검증용 계산 실패"):
            asyncio.run(benchmark.main())
    else:
        asyncio.run(benchmark.main())
    assert disposed == [True]
    assert analytics.now_utc is before[0]
    assert analytics_cache.now_utc is before[1]


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
