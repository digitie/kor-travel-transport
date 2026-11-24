"""요청 관측 로그·Server-Timing의 임계 설정, export 전수 기록, 루프 CPU, 풀 대기 계약."""
import asyncio
import logging
import re
import time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.responses import Response
from starlette.routing import Mount

from app.core import read_timing
from app.core.config import Settings
from app.main import create_app


def _route(path):
    return type("Route", (), {"path": path})()


async def _call(middleware, scope):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    await middleware({"type": "http", "method": "GET", **scope}, receive, send)
    return messages


def _fields(caplog):
    lines = [record.getMessage() for record in caplog.records if record.name == read_timing.__name__]
    assert len(lines) == 1, lines
    kind, _, rest = lines[0].partition(" ")
    return kind, dict(item.split("=", 1) for item in rest.split(" "))


async def test_fast_request_below_default_threshold_is_not_logged(caplog):
    async def endpoint(scope, receive, send):
        await Response("ok")(scope, receive, send)

    with caplog.at_level(logging.INFO, logger=read_timing.__name__):
        await _call(read_timing.ReadTimingMiddleware(endpoint), {"path": "/v1/transport/features/places"})
    assert not [record for record in caplog.records if record.name == read_timing.__name__]


async def test_threshold_is_configurable_and_line_carries_build_counts_and_start(caplog):
    async def endpoint(scope, receive, send):
        scope["route"] = _route("/v1/transport/features/places")
        read_timing.observe_page_build()
        read_timing.observe_fingerprint()
        read_timing.observe_fingerprint()
        await Response("ok", status_code=203)(scope, receive, send)

    with caplog.at_level(logging.INFO, logger=read_timing.__name__):
        await _call(read_timing.ReadTimingMiddleware(endpoint, slow_threshold_ms=0),
                    {"path": "/v1/transport/features/places"})
    kind, fields = _fields(caplog)
    assert kind == "slow_request"
    assert fields["route"] == "/v1/transport/features/places" and fields["method"] == "GET"
    assert fields["status"] == "203"
    assert fields["page_builds"] == "1" and fields["fingerprint_calculations"] == "2"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", fields["start"])
    for name in ("duration_ms", "sql_ms", "cpu_ms", "loop_cpu_ms", "pool_ms"):
        assert float(fields[name]) >= 0, name
    # 풀을 쓰지 않은 요청은 0/none이다.
    assert fields["pool_checkouts"] == "0" and fields["pool_checkedout"] == "none"
    assert fields["inflight_start"] == "1" and fields["inflight_end"] == "0"


async def test_export_requests_are_always_logged_without_query_or_ids(caplog):
    async def endpoint(scope, receive, send):
        scope["route"] = _route("/v1/service/exports/fuel-stations/{station_key}/price-history")
        await Response("not modified", status_code=304)(scope, receive, send)

    with caplog.at_level(logging.INFO, logger=read_timing.__name__):
        await _call(read_timing.ReadTimingMiddleware(endpoint), {
            "path": "/v1/service/exports/fuel-stations/opinet:SECRET-ID/price-history",
            "query_string": b"cursor=SECRET-CURSOR&limit=500",
        })
    kind, fields = _fields(caplog)
    assert kind == "export_request"
    assert fields["route"] == "/v1/service/exports/fuel-stations/{station_key}/price-history"
    assert fields["status"] == "304"
    assert "SECRET" not in caplog.text and "cursor" not in caplog.text


@pytest.mark.parametrize(("error", "status"), [(asyncio.CancelledError, "none"), (RuntimeError, "500")])
async def test_status_distinguishes_unstarted_response_from_unhandled_error(caplog, error, status):
    async def endpoint(scope, receive, send):
        raise error()

    with caplog.at_level(logging.INFO, logger=read_timing.__name__), pytest.raises(error):
        await _call(read_timing.ReadTimingMiddleware(endpoint), {"path": "/v1/service/exports/airports"})
    fields = _fields(caplog)[1]
    assert fields["status"] == status
    assert fields["error"] == error.__name__
    assert read_timing._current.get() is None and read_timing._inflight == 0


async def test_error_after_response_start_is_not_logged_as_plain_success(caplog):
    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{", "more_body": True})
        raise RuntimeError("SECRET-DSN")

    with caplog.at_level(logging.INFO, logger=read_timing.__name__), pytest.raises(RuntimeError):
        await _call(read_timing.ReadTimingMiddleware(endpoint), {"path": "/v1/service/exports/fuel-stations"})
    fields = _fields(caplog)[1]
    assert fields["status"] == "200" and fields["error"] == "RuntimeError"
    # 예외 메시지는 남기지 않는다.
    assert "SECRET" not in caplog.text


async def test_successful_request_logs_error_none(caplog):
    async def endpoint(scope, receive, send):
        await Response("ok")(scope, receive, send)

    with caplog.at_level(logging.INFO, logger=read_timing.__name__):
        await _call(read_timing.ReadTimingMiddleware(endpoint), {"path": "/v1/service/exports/airports"})
    assert _fields(caplog)[1]["error"] == "none"


@pytest.mark.parametrize(("route", "label"), [
    (None, "unmatched"),
    (_route("/v1/transport/features/places"), "/v1/transport/features/places"),
    # app.mount("/", 공개 유가 MCP)의 Mount.path는 ""다. 빈 route= 대신 fallback mount로 남긴다.
    (Mount("/", app=Response("x")), "/*"),
    (Mount("/tools", app=Response("x")), "/tools/*"),
])
async def test_route_label_is_never_empty(caplog, route, label):
    async def endpoint(scope, receive, send):
        if route is not None:
            scope["route"] = route
        await Response("nf", status_code=404)(scope, receive, send)

    with caplog.at_level(logging.INFO, logger=read_timing.__name__):
        await _call(read_timing.ReadTimingMiddleware(endpoint, slow_threshold_ms=0), {"path": "/random/SECRET-ID"})
    assert _fields(caplog)[1]["route"] == label
    assert "SECRET" not in caplog.text


async def test_server_timing_keeps_existing_fields_first_and_adds_pool_and_loop_cpu():
    async def endpoint(scope, receive, send):
        await Response("ok")(scope, receive, send)

    messages = await _call(read_timing.ReadTimingMiddleware(endpoint), {"path": "/health"})
    timing = dict(messages[0]["headers"])[b"server-timing"].decode()
    names = [entry.split(";", 1)[0].strip() for entry in timing.split(",")]
    assert names == ["app", "sql", "sql_count", "cpu", "page_builds", "fingerprint_calculations", "pool", "loop_cpu"]


async def test_loop_cpu_excludes_worker_thread_cpu_but_process_cpu_includes_it(caplog):
    def burn():
        deadline = time.thread_time() + 0.25
        while time.thread_time() < deadline:
            pass

    async def endpoint(scope, receive, send):
        await asyncio.to_thread(burn)
        await Response("ok")(scope, receive, send)

    with caplog.at_level(logging.INFO, logger=read_timing.__name__):
        await _call(read_timing.ReadTimingMiddleware(endpoint, slow_threshold_ms=0), {"path": "/health"})
    fields = _fields(caplog)[1]
    assert float(fields["cpu_ms"]) >= 200
    assert float(fields["cpu_ms"]) - float(fields["loop_cpu_ms"]) >= 150


async def test_pool_wait_counts_exhausted_pool_timeout_and_survives_dispose(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pool.sqlite3'}",
                                 pool_size=1, max_overflow=0, pool_timeout=0.2)
    read_timing.observe_engine(engine)
    timing = read_timing.ReadTiming()
    token = read_timing._current.set(timing)
    try:
        async with engine.connect() as held:
            await held.execute(text("SELECT 1"))
            assert timing.pool_checkouts == 1 and timing.pool_connects == 1 and timing.pool_checkedout == 1
            with pytest.raises(Exception, match="QueuePool limit"):
                async with engine.connect():
                    pass
        assert timing.pool_checkouts == 2
        # 풀 고갈로 실패한 대기(약 0.2초)도 pool 시간에 남는다.
        assert timing.pool_wait_seconds >= 0.15
        await engine.dispose()
        async with engine.connect() as fresh:
            await fresh.execute(text("SELECT 1"))
        assert timing.pool_checkouts == 3 and timing.pool_connects == 2
    finally:
        read_timing._current.reset(token)
        await engine.dispose()
    # 요청 밖의 연결은 어느 요청 계수에도 더하지 않는다.
    async with engine.connect() as outside:
        await outside.execute(text("SELECT 1"))
    assert timing.pool_checkouts == 3
    await engine.dispose()


def test_app_request_records_pool_checkout_in_log_and_header(test_settings, caplog):
    from fastapi.testclient import TestClient

    settings = test_settings.model_copy(update={"slow_request_threshold_ms": 0})
    with TestClient(create_app(settings)) as client, caplog.at_level(logging.INFO, logger=read_timing.__name__):
        caplog.clear()
        response = client.get("/health")
    assert response.status_code == 200
    assert re.search(r"pool;dur=\d+\.\d{3}", response.headers["server-timing"])
    assert re.search(r"loop_cpu;dur=\d+\.\d{3}", response.headers["server-timing"])
    kind, fields = _fields(caplog)
    assert kind == "slow_request" and fields["route"] == "/health" and fields["status"] == "200"
    assert int(fields["pool_checkouts"]) >= 1
    # PostgreSQL 시험 엔진은 NullPool(checkedout 없음)이라 none, SQLite 시험은 QueuePool이라 1 이상이다.
    assert fields["pool_checkedout"] == "none" or int(fields["pool_checkedout"]) >= 1


def test_slow_request_threshold_setting_reaches_the_middleware(monkeypatch):
    monkeypatch.setenv("SLOW_REQUEST_THRESHOLD_MS", "250")
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///:memory:")
    assert settings.slow_request_threshold_ms == 250
    app = create_app(settings)
    middleware = next(item for item in app.user_middleware if item.cls is read_timing.ReadTimingMiddleware)
    assert middleware.kwargs == {"slow_threshold_ms": 250}
    assert Settings.model_fields["slow_request_threshold_ms"].default == 1000
    with pytest.raises(ValueError):
        Settings(_env_file=None, slow_request_threshold_ms=-1)
    with pytest.raises(ValueError):
        read_timing.ReadTimingMiddleware(None, slow_threshold_ms=-1)
