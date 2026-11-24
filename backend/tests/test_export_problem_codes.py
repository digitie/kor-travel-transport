"""`/v1/service/exports/*` 503의 가산 `code`·`Retry-After` 계약과 DB 일시 오류 분류(ADR-013 개정 2026-11-24).

감사 G1-F3·MC-01·T23-01·T23-10·RT-12·T1-07·RT-02·RT-04·WLH-09·G1-F4(a). 계약 전문은
`docs/map-service-exports-handoff.md`의 "503 사유 code와 Retry-After" 절이다.
"""

# ruff: noqa: F811

from __future__ import annotations

import asyncio
import socket
import ssl
import threading
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.core import problems
from app.core.problems import (
    CodedHTTPException,
    DatabaseConnectError,
    DatabaseConnectTimeout,
    ProblemCode,
    is_transient_db_error,
    source_retry_after_seconds,
)
from app.core.time_utils import now_utc
from app.db import session as db_session
from app.db.session import create_engine_and_session_factory
from app.main import create_app
from app.models import (
    BusTerminalReference,
    HighwayTrafficCurrentState,
    ReferenceExportState,
    ServiceExportSnapshot,
)
from app.services import export_current, export_references
from app.services.bus_collection import TAGO_BUS_SOURCE
from app.services.public_parking_collection import SOURCE as PUBLIC_PARKING_SOURCE
from app.services.transport_collection import OPINET_SOURCE, TRAFFIC_SOURCE, highway_scope_key
from test_export_current import PATH as TRAFFIC_PATH
from test_export_current import _enable, _seed
from test_service_exports import (  # noqa: F401
    HEADERS,
    LOOPBACK_CLIENT,
    TOKEN,
    _run,
    _seed_fuel_station,
    _set_state,
    export_client,
)

BUS_PATH = "/v1/service/exports/bus-terminals"
FUEL_PATH = "/v1/service/exports/fuel-stations"


class _PgError(Exception):
    """asyncpg 오류처럼 `sqlstate`를 갖는 원래 driver 예외."""

    def __init__(self, message: str, sqlstate: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def _db_error(sqlstate: str, *, cls=DBAPIError) -> DBAPIError:
    return cls("SELECT private_column FROM private_table", {"key": "synthetic-db-secret"},
               _PgError("synthetic driver text postgresql://private-user:private-password@host", sqlstate))


def _problem(response) -> tuple[str | None, str | None]:
    return response.json().get("code"), response.headers.get("retry-after")


# ---------------------------------------------------------------------------
# 순수 helper


def _state(now, *, started=None, success=None, due=None, error=None, updated=None):
    return SimpleNamespace(last_started_at=started, last_success_at=success, next_due_at=due, last_error=error,
                           updated_at=updated if updated is not None else (started or now))


def test_source_retry_after_hint_follows_collection_state() -> None:
    now = now_utc()
    run = timedelta(hours=2)
    hour = timedelta(hours=1)
    assert source_retry_after_seconds(None, run, now=now) == 1800
    # 다음 예정이 가까우면 예정 + 예상 수행 시간, 멀면 상한 1시간(힌트를 넘겨 짚지 않는다).
    assert source_retry_after_seconds(_state(now, success=now - 30 * hour, due=now + timedelta(minutes=5)),
                                      timedelta(minutes=10), now=now) == 900
    assert source_retry_after_seconds(_state(now, success=now - 30 * hour, due=now + 7 * hour), run, now=now) == 3600
    # 예정이 지났거나(수집기 멈춤) 없으면(휴게소 계열은 성공 때 비운다) 1800 — 예전의 고정 60초가 아니다.
    assert source_retry_after_seconds(_state(now, success=now - 30 * hour, due=now - 10 * hour), run, now=now) == 1800
    assert source_retry_after_seconds(_state(now, success=now - 30 * hour), run, now=now) == 1800
    # 진행 중인 복구 run: claim이 예정을 시작 + 7시간 45분으로 옮겨도 시작 + 예상 수행 시간으로 계산한다.
    started = now - timedelta(minutes=110)
    in_flight = _state(now, started=started, success=now - 30 * hour, due=started + timedelta(hours=7, minutes=45),
                       error="previous failure", updated=started + timedelta(seconds=1))
    assert source_retry_after_seconds(in_flight, run, now=now) == 600
    # 예상 수행 시간을 넘긴 진행 중 run은 5분 뒤 다시 본다.
    overrun = _state(now, started=now - timedelta(hours=3), success=now - 30 * hour, due=now + 5 * hour)
    assert source_retry_after_seconds(overrun, run, now=now) == 300
    # 시작 뒤 실패가 기록됐으면 진행 중이 아니다 — 다음 예정으로 계산한다.
    failed = _state(now, started=now - hour, success=now - 30 * hour, due=now + timedelta(minutes=20),
                    error="provider failed", updated=now - timedelta(minutes=10))
    assert source_retry_after_seconds(failed, run, now=now) == 3600
    failed.next_due_at = now - hour
    assert source_retry_after_seconds(failed, run, now=now) == 1800
    # 시작 기록이 예상 수행 시간의 3배보다 오래됐으면(죽은 run) 진행 중으로 보지 않는다.
    dead = _state(now, started=now - 7 * hour, success=now - 30 * hour, due=now - hour)
    assert source_retry_after_seconds(dead, run, now=now) == 1800


def test_coded_exception_sets_integer_retry_after_and_defaults() -> None:
    exc = CodedHTTPException(503, "x", code=ProblemCode.EXPORT_BUSY)
    assert exc.headers == {"Retry-After": "10"} and exc.code == "EXPORT_BUSY" and exc.retry_after == 10
    assert problems.unavailable(ProblemCode.EXPORT_SOURCE_NOT_CURRENT, "x", retry_after=0).headers["Retry-After"] == "1"
    # 모든 code는 UPPER_SNAKE이고 기본 Retry-After가 있다(공통 표준 M3).
    for code in ProblemCode:
        assert code.value.isupper() and " " not in code.value
        assert problems.RETRY_AFTER_SECONDS[code] >= 1
    assert problems.problem_body(status=503, title="t", detail="d", instance="/i") == {
        "type": "about:blank", "title": "t", "status": 503, "detail": "d", "instance": "/i",
    }


@pytest.mark.parametrize(("error", "transient"), [
    (PoolTimeoutError("QueuePool limit of size 5 overflow 5 reached"), True),
    (DatabaseConnectError("refused"), True),
    (DatabaseConnectTimeout("timeout"), True),
    (_db_error("57P03"), True),   # cannot_connect_now(PG 기동 중)
    (_db_error("53300"), True),   # too_many_connections
    (_db_error("57P01"), True),   # admin_shutdown(PG 재시작)
    (_db_error("08006"), True),   # connection_failure
    (_db_error("08003", cls=OperationalError), True),
    (DBAPIError("SELECT 1", {}, RuntimeError("closed"), connection_invalidated=True), True),
    (_db_error("08P01"), False),  # protocol_violation: 결정적이라 다시 불러도 같다
    (DBAPIError("SELECT 1", {}, _PgError("protocol", "08P01"), connection_invalidated=True), False),
    (_db_error("57014"), False),  # statement timeout은 export snapshot 안에서만 따로 바꾼다
    (_db_error("55P03"), False),
    (_db_error("23505"), False),
    (_db_error("42601"), False),
    (OperationalError("SELECT 1", {}, RuntimeError("no sqlstate")), False),
    (RuntimeError("other"), False),
    (ConnectionRefusedError("not from the DB engine"), False),
])
def test_transient_db_classification(error, transient) -> None:
    assert is_transient_db_error(error) is transient


def test_connect_errors_keep_their_builtin_bases() -> None:
    # 기존 `except OSError`·`except TimeoutError` 처리가 그대로 잡는다.
    assert issubclass(DatabaseConnectError, ConnectionError)
    assert issubclass(DatabaseConnectTimeout, TimeoutError) and issubclass(DatabaseConnectTimeout, OSError)


# ---------------------------------------------------------------------------
# app handler: export 경로만 503 TRANSIENT_DB, 그 밖은 예전처럼 500


_ERRORS = {
    "pool": lambda: PoolTimeoutError("QueuePool limit reached, connection timed out, timeout 10.00 synthetic-db-secret"),
    "connect": lambda: DatabaseConnectError("데이터베이스에 접속하지 못했습니다."),
    "connect_timeout": lambda: DatabaseConnectTimeout("데이터베이스 접속 시간이 초과됐습니다."),
    "starting": lambda: _db_error("57P03"),
    "too_many": lambda: _db_error("53300", cls=OperationalError),
    "shutdown": lambda: _db_error("57P01"),
    "link": lambda: _db_error("08006"),
    "syntax": lambda: _db_error("42601"),
    "protocol": lambda: _db_error("08P01"),
    "unique": lambda: _db_error("23505"),
    "runtime": lambda: RuntimeError("synthetic-secret SELECT private_column"),
}
_TRANSIENT = {"pool", "connect", "connect_timeout", "starting", "too_many", "shutdown", "link"}


@pytest.fixture
def raising_client(test_settings):
    test_settings.transport_service_export_token = TOKEN
    test_settings.trusted_hosts_csv = "testserver,127.0.0.1"
    app = create_app(test_settings)

    @app.get("/v1/service/exports/__synthetic-error")
    async def export_error(kind: str) -> None:
        raise _ERRORS[kind]()

    @app.get("/v1/transport/__synthetic-error")
    async def public_error(kind: str) -> None:
        raise _ERRORS[kind]()

    with TestClient(app, client=LOOPBACK_CLIENT, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("kind", sorted(_ERRORS))
def test_transient_db_errors_are_503_only_on_export_routes(raising_client, kind) -> None:
    export = raising_client.get("/v1/service/exports/__synthetic-error", params={"kind": kind})
    public = raising_client.get("/v1/transport/__synthetic-error", params={"kind": kind})
    for response in (export, public):
        assert response.headers["content-type"].startswith("application/problem+json")
        for private in ("synthetic-db-secret", "private_column", "private-password", "SELECT", "QueuePool"):
            assert private not in response.text
    # 공개·관리 경로는 일시 DB 오류도 예전과 같은 500 본문이다(관리 유가 화면은 모든 503을 "이력 없음"으로 읽는다).
    assert public.status_code == 500 and "retry-after" not in public.headers
    assert public.json() == {"type": "about:blank", "title": "Internal Server Error", "status": 500,
                             "detail": "서버 내부 오류가 발생했습니다.", "instance": "/v1/transport/__synthetic-error"}
    if kind in _TRANSIENT:
        assert export.status_code == 503
        assert export.json() == {
            "type": "about:blank", "title": "Service Unavailable", "status": 503,
            "detail": problems.TRANSIENT_DB_DETAIL, "instance": "/v1/service/exports/__synthetic-error",
            "code": "TRANSIENT_DB",
        }
        assert export.headers["retry-after"] == "15"
    else:
        assert export.status_code == 500 and "code" not in export.json() and "retry-after" not in export.headers


def test_non_export_database_errors_keep_their_original_exception(test_settings) -> None:
    """export가 아닌 경로·stream은 DB 예외 handler를 거치지 않는다 — 서버 로그의 예외 종류가 예전과 같다.

    앱 전체에 DB 예외 handler를 등록하면 Starlette가 이미 시작된 stream에서 원래 예외 대신
    `RuntimeError("Caught handled exception, but response already started.")`를 올린다(적대적 리뷰 P2-6).
    """
    from fastapi.responses import StreamingResponse

    test_settings.transport_service_export_token = TOKEN
    test_settings.trusted_hosts_csv = "testserver,127.0.0.1"
    app = create_app(test_settings)

    @app.get("/v1/transport/__synthetic-db-error")
    async def public_error() -> None:
        raise _ERRORS["pool"]()

    @app.get("/v1/transport/__synthetic-db-stream")
    async def public_stream() -> StreamingResponse:
        async def body():
            yield b"{"
            raise _ERRORS["link"]()
        return StreamingResponse(body(), media_type="application/json")

    @app.get("/v1/service/exports/__synthetic-db-stream")
    async def export_stream() -> StreamingResponse:
        async def body():
            yield b"{"
            raise _ERRORS["link"]()
        return StreamingResponse(body(), media_type="application/json")

    with TestClient(app, client=LOOPBACK_CLIENT) as client:
        with pytest.raises(PoolTimeoutError):
            client.get("/v1/transport/__synthetic-db-error")
        with pytest.raises(DBAPIError):
            client.get("/v1/transport/__synthetic-db-stream")
        # 응답이 이미 시작된 export stream은 503으로 바꿀 수 없으므로 원래 예외 그대로 올린다.
        with pytest.raises(DBAPIError):
            client.get("/v1/service/exports/__synthetic-db-stream", headers=HEADERS)


def test_export_outage_is_logged_as_error_once_per_window(raising_client, caplog, monkeypatch) -> None:
    from app.core import export_guard
    monkeypatch.setattr(export_guard, "_outage_log", export_guard._OutageLog())
    with caplog.at_level("WARNING", logger="app.core.export_guard"):
        for _ in range(3):
            raising_client.get("/v1/service/exports/__synthetic-error", params={"kind": "connect"})
    records = [r for r in caplog.records if r.name == "app.core.export_guard"]
    assert [r.levelname for r in records] == ["ERROR", "WARNING", "WARNING"]
    message = records[0].getMessage()
    assert "TRANSIENT_DB" in message and "type=DatabaseConnectError" in message
    monkeypatch.setattr(export_guard, "OUTAGE_LOG_WINDOW_SECONDS", 0.0)
    with caplog.at_level("WARNING", logger="app.core.export_guard"):
        raising_client.get("/v1/service/exports/__synthetic-error", params={"kind": "link"})
    last = [r for r in caplog.records if r.name == "app.core.export_guard"][-1]
    assert last.levelname == "ERROR" and "repeated_in_previous_window=2" in last.getMessage()
    assert "cause=_PgError" in last.getMessage() and "sqlstate=08006" in last.getMessage()


def test_plain_http_exception_body_is_unchanged(raising_client) -> None:
    # code 없는 오류는 예전과 바이트 단위로 같은 키 집합이다(가산 확장).
    response = raising_client.get(FUEL_PATH)  # 토큰 없음 → 404로 경로를 숨긴다
    assert response.status_code == 404
    assert set(response.json()) == {"type", "title", "status", "detail", "instance"}
    assert "retry-after" not in response.headers


def test_unreachable_database_is_503_transient_on_export_and_500_elsewhere(export_client) -> None:
    """실제 asyncpg 접속 거부: export는 503 TRANSIENT_DB, /health는 예전처럼 500."""
    engine, factory = create_engine_and_session_factory("postgresql+asyncpg://u:p@127.0.0.1:1/unreachable")
    original = export_client.app.state.session_factory
    export_client.app.state.session_factory = factory
    lenient = TestClient(export_client.app, client=LOOPBACK_CLIENT, raise_server_exceptions=False)
    try:
        exported = export_client.get(FUEL_PATH, headers=HEADERS)
        health = lenient.get("/health")
    finally:
        export_client.app.state.session_factory = original
        asyncio.run(engine.dispose())
    assert exported.status_code == 503, exported.text
    assert _problem(exported) == ("TRANSIENT_DB", "15")
    assert "127.0.0.1" not in exported.text and "unreachable" not in exported.text
    assert health.status_code == 500 and "code" not in health.json()


# ---------------------------------------------------------------------------
# DB 엔진 옵션


def test_api_engine_bounds_connect_and_pool_wait_and_names_connections(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_engine(url, **options):
        captured["options"] = options
        return SimpleNamespace(sync_engine=None)

    monkeypatch.setattr(db_session, "create_async_engine", fake_engine)
    monkeypatch.delenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE", raising=False)
    db_session.create_engine_and_session_factory("postgresql://u:p@db/x")
    api = captured["options"]
    assert api["pool_timeout"] == 10 and api["connect_args"]["timeout"] == 10
    assert api["connect_args"]["server_settings"] == {
        "statement_timeout": "120s", "application_name": "kor-travel-transport-api",
    }
    db_session.create_engine_and_session_factory("postgresql://u:p@db/x", collector=True)
    collector = captured["options"]
    assert "pool_timeout" not in collector
    assert collector["connect_args"]["server_settings"]["application_name"] == "kor-travel-transport-collector"
    # 세션 advisory lease 연결은 run 내내 idle in transaction이다 — 어느 엔진에도 이 백스톱을 두지 않는다.
    for options in (api, collector):
        settings = options["connect_args"]["server_settings"]
        assert "idle_in_transaction_session_timeout" not in settings and "transaction_timeout" not in settings
    assert "lock_timeout" not in api["connect_args"]["server_settings"]


def test_api_engine_marks_connect_failures_and_collector_keeps_raw_errors(monkeypatch) -> None:
    async def scenario():
        api, _ = create_engine_and_session_factory("postgresql+asyncpg://u:p@127.0.0.1:1/x")
        collector, _ = create_engine_and_session_factory("postgresql+asyncpg://u:p@127.0.0.1:1/x", collector=True)
        try:
            with pytest.raises(DatabaseConnectError) as refused:
                async with api.connect():
                    pass
            assert isinstance(refused.value.__cause__, OSError)
            with pytest.raises(OSError) as raw:
                async with collector.connect():
                    pass
            assert not isinstance(raw.value, DatabaseConnectError)

            def timing_out(*_args, **_kwargs):
                raise TimeoutError()
            monkeypatch.setattr(api.sync_engine.dialect, "connect", timing_out)
            with pytest.raises(DatabaseConnectTimeout):
                async with api.connect():
                    pass

            # 주소·인증서 설정 문제는 기다려도 풀리지 않으므로 TRANSIENT_DB로 표시하지 않는다.
            for error in (socket.gaierror(-2, "Name or service not known"),
                          ssl.SSLCertVerificationError(1, "certificate verify failed")):
                def failing(*_args, _error=error, **_kwargs):
                    raise _error
                monkeypatch.setattr(api.sync_engine.dialect, "connect", failing)
                with pytest.raises(type(error)) as raw:
                    async with api.connect():
                        pass
                assert not isinstance(raw.value, DatabaseConnectError) and not is_transient_db_error(raw.value)
        finally:
            await api.dispose()
            await collector.dispose()
    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# T1(주유소·휴게소·돌발·공공 주차장)


def test_fuel_stale_retry_after_follows_the_collection_state(export_client) -> None:
    from app.service_exports import REFERENCE_STALE_AFTER
    stale_at = now_utc() - REFERENCE_STALE_AFTER[OPINET_SOURCE] - timedelta(minutes=5)
    _run(export_client, lambda s: _set_state(s, OPINET_SOURCE, last_success_at=stale_at,
                                             next_due_at=now_utc() + timedelta(minutes=5)))
    response = export_client.get(FUEL_PATH, headers=HEADERS)
    assert response.status_code == 503 and response.json()["code"] == "EXPORT_SOURCE_NOT_CURRENT"
    # 다음 예정(5분 뒤) + 유가 수집 예상 2시간은 상한 1시간으로 자른다.
    assert response.headers["retry-after"] == "3600"
    # 진행 중인 복구 run(시작 110분 전, 예정은 claim이 7시간 45분 뒤로 옮김)은 시작 + 2시간까지 약 10분이다.
    started = now_utc() - timedelta(minutes=110)
    _run(export_client, lambda s: _set_state(s, OPINET_SOURCE, last_started_at=started, updated_at=started,
                                             next_due_at=started + timedelta(hours=7, minutes=45)))
    assert abs(int(export_client.get(FUEL_PATH, headers=HEADERS).headers["retry-after"]) - 600) <= 5
    # 수집기가 멈춰 예정이 과거에 머물면 고정 60초가 아니라 1800초다.
    _run(export_client, lambda s: _set_state(s, OPINET_SOURCE, last_started_at=stale_at - timedelta(hours=2),
                                             next_due_at=now_utc() - timedelta(hours=9)))
    assert export_client.get(FUEL_PATH, headers=HEADERS).headers["retry-after"] == "1800"


def test_fuel_export_grace_is_public_freshness_plus_one_fuel_run() -> None:
    from app.service_exports import REFERENCE_STALE_AFTER
    from app.services.transport_collection import FUEL_FETCH_TIMEOUT_SECONDS, FUEL_STALE_AFTER
    assert REFERENCE_STALE_AFTER[OPINET_SOURCE] == FUEL_STALE_AFTER + timedelta(seconds=FUEL_FETCH_TIMEOUT_SECONDS)
    # 공개 화면 신선도는 그대로이고 export 유예는 Map Valkey max_age(48시간)보다 작다.
    assert FUEL_STALE_AFTER == timedelta(hours=24)
    assert REFERENCE_STALE_AFTER[OPINET_SOURCE] < timedelta(hours=48)


def test_public_parking_export_codes(export_client) -> None:
    path = "/v1/service/exports/parking-lots"
    never = export_client.get(path, headers=HEADERS)
    assert never.status_code == 503 and _problem(never) == ("EXPORT_NO_HISTORY", "3600")
    assert never.json()["detail"] == "완료된 최신 주차장 기준정보가 없습니다."
    _run(export_client, lambda s: _set_state(s, PUBLIC_PARKING_SOURCE, last_success_at=now_utc() - timedelta(days=91),
                                             next_due_at=None))
    stale = export_client.get(path, headers=HEADERS)
    assert stale.status_code == 503 and _problem(stale) == ("EXPORT_SOURCE_NOT_CURRENT", "1800")


# ---------------------------------------------------------------------------
# T2 교통 current: disabled·no head·크기·membership·예산·57014·55P03·경합


def _seeded_traffic(client):
    _enable(client)
    _run(client, lambda s: _seed(s, client.app.state.settings))


def test_traffic_disabled_and_no_head_codes(export_client) -> None:
    disabled = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert disabled.status_code == 503 and _problem(disabled) == ("EXPORT_DISABLED", "3600")
    assert disabled.json()["detail"] == "교통 current export가 활성화되지 않았습니다."
    _enable(export_client)
    missing = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    # 5분 주기 집합의 첫 성공 전은 1시간이 아니라 5분 뒤 다시 본다.
    assert missing.status_code == 503 and _problem(missing) == ("EXPORT_NO_HISTORY", "300")


@pytest.mark.parametrize(("member_count", "code"), [
    (export_current.MAX_SNAPSHOT_ITEMS + 1, "EXPORT_TOO_LARGE"),
    (4, "EXPORT_SOURCE_INCONSISTENT"),  # head는 4건인데 current 행은 3건
])
def test_traffic_size_and_membership_codes(export_client, member_count, code) -> None:
    _seeded_traffic(export_client)
    _run(export_client, lambda s: s.execute(update(HighwayTrafficCurrentState).values(member_count=member_count)))
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 503 and response.json()["code"] == code


def test_traffic_build_budget_is_prepare_timeout(export_client, monkeypatch) -> None:
    _seeded_traffic(export_client)
    monkeypatch.setattr(export_current, "BUILD_BUDGET_SECONDS", -1)
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 503 and _problem(response) == ("EXPORT_PREPARE_TIMEOUT", "60")
    assert response.json()["detail"] == "snapshot 준비 시간 상한을 초과했습니다."


def _failing_freeze(monkeypatch, failures, *, record=None):
    original = export_current._freeze_traffic
    calls = []

    async def freeze(session, scope, head):
        calls.append(export_current.build_started())
        if record is not None:
            record(len(calls))
        if failures:
            raise failures.pop(0)
        return await original(session, scope, head)

    monkeypatch.setattr(export_current, "_freeze_traffic", freeze)
    return calls


def _sleeps(monkeypatch):
    slept = []

    async def sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(export_current, "asyncio", SimpleNamespace(sleep=sleep))
    return slept


def test_lock_timeout_retries_once_after_jitter_sharing_one_budget(export_client, monkeypatch) -> None:
    _seeded_traffic(export_client)
    slept = _sleeps(monkeypatch)
    calls = _failing_freeze(monkeypatch, [_db_error("55P03")])
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert len(calls) == 2 and len(slept) == 1 and 0.3 <= slept[0] <= 1.0
    # 두 시도가 같은 시작 시각(예산 하나)을 쓴다 — 재시도가 15초를 새로 받지 않는다.
    assert calls[0] == calls[1]
    # 요청 밖에서는 예산 시작이 남지 않는다.
    assert export_current._build_started.get() is None


def test_repeated_lock_timeout_is_busy(export_client, monkeypatch) -> None:
    _seeded_traffic(export_client)
    slept = _sleeps(monkeypatch)
    calls = _failing_freeze(monkeypatch, [_db_error("55P03"), _db_error("55P03")])
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 503 and _problem(response) == ("EXPORT_BUSY", "10")
    assert response.json()["detail"] == "snapshot 준비가 겹쳤습니다. 잠시 후 다시 요청하세요."
    assert len(calls) == 2 and len(slept) == 1


def test_lock_timeout_without_remaining_budget_is_busy_without_retry(export_client, monkeypatch) -> None:
    _seeded_traffic(export_client)
    slept = _sleeps(monkeypatch)
    monkeypatch.setattr(export_current, "BUILD_BUDGET_SECONDS", 0)
    calls = _failing_freeze(monkeypatch, [_db_error("55P03")])
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 503 and response.json()["code"] == "EXPORT_BUSY"
    assert len(calls) == 1 and slept == []


@pytest.mark.parametrize(("failures", "attempts"), [
    (["40001"], 2), (["race"], 2), (["40001", "race"], 2),
])
def test_serialization_and_snapshot_races_retry_immediately(export_client, monkeypatch, failures, attempts) -> None:
    _seeded_traffic(export_client)
    slept = _sleeps(monkeypatch)
    errors = [export_current.SnapshotRace() if f == "race" else _db_error(f) for f in failures]
    calls = _failing_freeze(monkeypatch, errors)
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert len(calls) == attempts and slept == []
    if len(failures) == 1:
        assert response.status_code == 200, response.text
    else:
        assert response.status_code == 503 and _problem(response) == ("EXPORT_BUSY", "10")


def test_statement_timeout_in_snapshot_is_prepare_timeout_without_retry(export_client, monkeypatch) -> None:
    _seeded_traffic(export_client)
    calls = _failing_freeze(monkeypatch, [_db_error("57014"), _db_error("57014")])
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 503 and _problem(response) == ("EXPORT_PREPARE_TIMEOUT", "60")
    assert len(calls) == 1
    assert "private_column" not in response.text


def test_other_database_errors_in_snapshot_stay_500(export_client, monkeypatch) -> None:
    _seeded_traffic(export_client)
    client = TestClient(export_client.app, client=LOOPBACK_CLIENT, raise_server_exceptions=False)
    _failing_freeze(monkeypatch, [_db_error("23505")])
    response = client.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 500 and "code" not in response.json()


def test_contention_retry_needs_room_for_delay_lock_timeout_and_margin(export_client, monkeypatch) -> None:
    _seeded_traffic(export_client)
    slept = _sleeps(monkeypatch)
    monkeypatch.setattr(export_current, "LOCK_RETRY_DELAY_SECONDS", (0.6, 0.6))
    # 남은 예산 < 대기 0.6 + lock_timeout 2 + 여유 3 → 다시 시도하지 않고 곧바로 EXPORT_BUSY.
    monkeypatch.setattr(export_current, "BUILD_BUDGET_SECONDS", 5.5)
    calls = _failing_freeze(monkeypatch, [_db_error("55P03")])
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 503 and response.json()["code"] == "EXPORT_BUSY"
    assert len(calls) == 1 and slept == []
    monkeypatch.setattr(export_current, "BUILD_BUDGET_SECONDS", 8)
    calls = _failing_freeze(monkeypatch, [_db_error("55P03")])
    assert export_client.get(TRAFFIC_PATH, headers=HEADERS).status_code == 200
    assert len(calls) == 2 and slept == [0.6]


def test_deadlock_is_retried_like_a_lock_timeout(export_client, monkeypatch) -> None:
    _seeded_traffic(export_client)
    slept = _sleeps(monkeypatch)
    calls = _failing_freeze(monkeypatch, [_db_error("40P01")])
    assert export_client.get(TRAFFIC_PATH, headers=HEADERS).status_code == 200
    assert len(calls) == 2 and len(slept) == 1


@pytest.mark.parametrize("late", [
    lambda: problems.unavailable(ProblemCode.EXPORT_PREPARE_TIMEOUT, "budget"),
    lambda: _db_error("57014"),
])
def test_late_retry_after_contention_is_busy_not_prepare_timeout(export_client, monkeypatch, late) -> None:
    _seeded_traffic(export_client)
    _sleeps(monkeypatch)
    calls = _failing_freeze(monkeypatch, [_db_error("55P03"), late()])
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 503 and _problem(response) == ("EXPORT_BUSY", "10")
    assert len(calls) == 2


def test_retry_statement_timeout_never_exceeds_the_remaining_budget(monkeypatch) -> None:
    from time import monotonic
    assert export_current.snapshot_statement_timeout_ms() == 10_000  # 요청 밖(Dagster 준비 op)
    token = export_current._build_started.set(monotonic() - 12)
    try:
        assert 2_500 <= export_current.snapshot_statement_timeout_ms() <= 3_000
        export_current._build_started.set(monotonic() - 14.9)
        assert export_current.snapshot_statement_timeout_ms() == 1_000
        export_current._build_started.set(monotonic())
        assert export_current.snapshot_statement_timeout_ms() == 10_000
    finally:
        export_current._build_started.reset(token)


@pytest.mark.parametrize(("building", "code"), [(False, "TRANSIENT_DB"), (True, "EXPORT_PREPARE_TIMEOUT")])
def test_export_handler_deadline_returns_a_coded_503(export_client, monkeypatch, building, code) -> None:
    from time import monotonic

    from app.core import export_guard
    _seeded_traffic(export_client)
    monkeypatch.setattr(export_guard, "EXPORT_HANDLER_DEADLINE_SECONDS", 0.5)

    async def hang(session, scope, head):
        if building:
            export_current.build_started()
        await asyncio.sleep(30)

    monkeypatch.setattr(export_current, "_freeze_traffic", hang)
    started = monotonic()
    response = export_client.get(TRAFFIC_PATH, headers=HEADERS)
    assert monotonic() - started < 10
    assert response.status_code == 503 and response.json()["code"] == code
    assert response.json()["detail"] == export_guard.DEADLINE_DETAIL


def test_handler_deadline_covers_t2_t3_t4_but_not_t1(export_client) -> None:
    from fastapi.routing import APIRoute

    from app.core.export_guard import EXPORT_HANDLER_DEADLINE_SECONDS, ExportDeadlineRoute
    from app.service_exports import build_service_export_router
    assert EXPORT_HANDLER_DEADLINE_SECONDS < 30  # Map read timeout
    t1 = {"/fuel-stations", "/rest-areas", "/rest-area-fuel-prices", "/highway-incidents/active", "/airports",
          "/parking-lots"}
    routes = {}

    def walk(items):  # FastAPI 0.165는 포함한 router를 그대로(_IncludedRouter.original_router) 둔다.
        for item in items:
            if getattr(item, "original_router", None) is not None:
                walk(item.original_router.routes)
            elif isinstance(item, APIRoute):
                routes[item.path.removeprefix("/service/exports")] = item

    async def get_db():  # pragma: no cover - 라우트 구성만 본다
        yield None
    walk(build_service_export_router(export_client.app.state.settings, get_db).routes)
    assert t1 <= set(routes) and "/highway-traffic/current" in routes and "/bus-terminals" in routes
    assert "/fuel-stations/{station_key}/price-history" in routes
    for path, route in routes.items():
        assert isinstance(route, ExportDeadlineRoute) is (path not in t1), path


# ---------------------------------------------------------------------------
# 실제 PostgreSQL driver: pool 대기 초과·도중 끊긴 연결·접속 수 초과


def _require_postgres(client):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL driver 회귀")


def test_postgres_pool_timeout_is_transient_503(export_client) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    c = export_client
    _require_postgres(c)
    engine = create_async_engine(c.app.state.settings.database_url, pool_size=1, max_overflow=0, pool_timeout=0.5)
    original = c.app.state.session_factory

    async def checkout():
        connection = engine.connect()
        await connection.start()
        return connection

    factory = async_sessionmaker(**{**original.kw, "bind": engine})
    held = c.portal.call(checkout)
    try:
        c.app.state.session_factory = factory
        response = c.get(FUEL_PATH, headers=HEADERS)
    finally:
        c.app.state.session_factory = original
        c.portal.call(held.close)
        c.portal.call(engine.dispose)
    assert response.status_code == 503, response.text
    assert _problem(response) == ("TRANSIENT_DB", "15")


def test_postgres_connection_terminated_mid_query_is_transient_503(export_client, monkeypatch) -> None:
    from sqlalchemy import text
    c = export_client
    _require_postgres(c)
    _seeded_traffic(c)

    async def slow(session, scope, head):
        await session.execute(text("SELECT pg_sleep(30) /* terminate-me */"))

    monkeypatch.setattr(export_current, "_freeze_traffic", slow)
    terminated, failure = [], []

    def terminate() -> None:
        async def run():
            engine, factory = create_engine_and_session_factory(c.app.state.settings.database_url)
            try:
                async with factory() as session:
                    for _ in range(200):
                        pid = await session.scalar(text(
                            "SELECT pid FROM pg_stat_activity WHERE query LIKE '%terminate-me%' "
                            "AND pid <> pg_backend_pid() AND state = 'active' LIMIT 1"))
                        if pid is not None:
                            terminated.append(await session.scalar(text("SELECT pg_terminate_backend(:pid)"),
                                                                   {"pid": pid}))
                            return
                        # pg_stat_activity는 transaction 안에서 처음 읽은 순간으로 고정된다 — 매번 transaction을 끝낸다.
                        await session.rollback()
                        await asyncio.sleep(0.05)
            finally:
                await engine.dispose()
        try:
            asyncio.run(run())
        except BaseException as exc:  # pragma: no cover - 진단용
            failure.append(exc)

    thread = threading.Thread(target=terminate, daemon=True)
    thread.start()
    response = c.get(TRAFFIC_PATH, headers=HEADERS)
    thread.join(15)
    assert not failure and terminated == [True]
    assert response.status_code == 503, response.text
    assert _problem(response) == ("TRANSIENT_DB", "15")


def test_postgres_too_many_connections_for_role_is_transient_503(export_client) -> None:
    from sqlalchemy import text
    from sqlalchemy.engine import make_url
    c = export_client
    _require_postgres(c)
    role = f"ktt_conn_limit_{uuid4().hex[:12]}"

    async def admin(statement):
        async with c.app.state.session_factory() as session:
            await session.execute(text(statement))
            await session.commit()

    try:
        asyncio.run(admin(f"CREATE ROLE {role} LOGIN PASSWORD 'limit-test' CONNECTION LIMIT 0"))
    except DBAPIError as exc:  # pragma: no cover - 권한 없는 DB
        pytest.skip(f"CREATE ROLE 권한 없음: {type(exc.orig).__name__}")
    url = make_url(c.app.state.settings.database_url).set(username=role, password="limit-test")
    engine, factory = create_engine_and_session_factory(url.render_as_string(hide_password=False))
    original = c.app.state.session_factory
    c.app.state.session_factory = factory
    try:
        response = c.get(FUEL_PATH, headers=HEADERS)
    finally:
        c.app.state.session_factory = original
        asyncio.run(engine.dispose())
        asyncio.run(admin(f"DROP ROLE {role}"))
    assert response.status_code == 503, response.text
    assert _problem(response) == ("TRANSIENT_DB", "15")


def test_postgres_statement_timeout_inside_snapshot_is_prepare_timeout(export_client, monkeypatch) -> None:
    """실제 asyncpg 57014(query_canceled)가 SQLSTATE 그대로 분류된다."""
    from sqlalchemy import text
    c = export_client
    if c.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL statement_timeout 회귀")
    _seeded_traffic(c)
    calls = []

    async def slow(session, scope, head):
        calls.append(True)
        await session.execute(text("SET LOCAL statement_timeout = '100ms'"))
        await session.execute(text("SELECT pg_sleep(2)"))

    monkeypatch.setattr(export_current, "_freeze_traffic", slow)
    response = c.get(TRAFFIC_PATH, headers=HEADERS)
    assert response.status_code == 503, response.text
    assert _problem(response) == ("EXPORT_PREPARE_TIMEOUT", "60") and len(calls) == 1


def test_postgres_admission_lock_timeout_retries_in_fresh_rr_then_busy(export_client, monkeypatch) -> None:
    """다른 transaction이 같은 (kind, scope, generation)을 admission한 채 commit하지 않으면 unique 대기가
    lock_timeout(2초)에 걸린다(55P03). 한 번 새 RR로 다시 시도하고, 그래도 막히면 503 EXPORT_BUSY다."""
    c = export_client
    if c.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL unique admission 대기 회귀")
    _seeded_traffic(c)
    moment = now_utc()
    monkeypatch.setattr(export_current, "now_utc", lambda: moment)
    monkeypatch.setattr(export_current, "LOCK_RETRY_DELAY_SECONDS", (0.3, 0.3))
    scope = highway_scope_key(c.app.state.settings, TRAFFIC_SOURCE)

    async def head_generation(session):
        return await session.scalar(select(HighwayTrafficCurrentState.generation))
    generation = export_current.cache_generation(_run(c, head_generation), moment)
    calls = _failing_freeze(monkeypatch, [])
    ready, done, failure = threading.Event(), threading.Event(), []

    def hold() -> None:
        async def holder():
            engine, factory = create_engine_and_session_factory(c.app.state.settings.database_url)
            try:
                async with factory() as session:
                    session.add(ServiceExportSnapshot(
                        id=str(uuid4()), kind=export_current.KIND, scope_key=scope, generation=generation,
                        source_collected_at=moment, created_at=moment, expires_at=moment + timedelta(minutes=30),
                        item_count=3, content_digest="pending"))
                    await session.flush()
                    ready.set()
                    while not done.is_set():
                        await asyncio.sleep(0.05)
                    await session.rollback()
            finally:
                await engine.dispose()
        try:
            asyncio.run(holder())
        except BaseException as exc:  # pragma: no cover - 진단용
            failure.append(exc)
            ready.set()

    thread = threading.Thread(target=hold, daemon=True)
    thread.start()
    assert ready.wait(15) and not failure
    try:
        response = c.get(TRAFFIC_PATH, headers=HEADERS)
    finally:
        done.set()
        thread.join(15)
    assert not failure
    assert response.status_code == 503, response.text
    assert _problem(response) == ("EXPORT_BUSY", "10")
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# T3 기준정보(버스터미널 대표)


async def _bus_heads(session, *, scopes=("express", "intercity"), complete=True):
    now = now_utc()
    for scope in scopes:
        row = BusTerminalReference(source=TAGO_BUS_SOURCE, service_type=scope, terminal_id="001",
                                   terminal_name=scope, city_name="서울", first_seen_at=now, last_seen_at=now)
        session.add(row)
        await session.flush()
        session.add(ReferenceExportState(kind="bus-terminal", scope_key=scope, generation=str(uuid4()),
                                         attempt_order=1, confirmed_at=now, member_ids=[row.id],
                                         proof={"complete": complete, "item_count": 1}, last_attempt_at=now))


def test_reference_disabled_missing_and_inconsistent_head_codes(export_client) -> None:
    c = export_client
    disabled = c.get(BUS_PATH, headers=HEADERS)
    assert disabled.status_code == 503 and _problem(disabled) == ("EXPORT_DISABLED", "3600")
    assert disabled.json()["detail"] == "터미널 export가 활성화되지 않았습니다."
    c.app.state.settings.transport_map_current_enabled = True
    never = c.get(BUS_PATH, headers=HEADERS)
    assert never.status_code == 503 and _problem(never) == ("EXPORT_NO_HISTORY", "3600")
    assert never.json()["detail"] == "기준정보 source의 완결 성공 집합이 없습니다."
    # 설정에 활성인 scope(intercity)의 승인 head가 아직 없다 → 첫 성공 전.
    _run(c, lambda s: _bus_heads(s, scopes=("express",)))
    partial = c.get(BUS_PATH, headers=HEADERS)
    assert partial.status_code == 503 and partial.json()["code"] == "EXPORT_NO_HISTORY"
    # head는 다 있는데 완결 증거가 없다 → 정합 문제.
    _run(c, lambda s: _bus_heads(s, scopes=("intercity",), complete=False))
    broken = c.get(BUS_PATH, headers=HEADERS)
    assert broken.status_code == 503 and _problem(broken) == ("EXPORT_SOURCE_INCONSISTENT", "300")


def test_reference_lock_timeout_retries_once_then_serves(export_client, monkeypatch) -> None:
    c = export_client
    c.app.state.settings.transport_map_current_enabled = True
    _run(c, _bus_heads)
    slept = _sleeps(monkeypatch)
    original = export_references._freeze_reference
    calls = []

    async def freeze(*args, **kwargs):
        calls.append(export_current.build_started())
        if len(calls) == 1:
            raise _db_error("55P03")
        return await original(*args, **kwargs)

    monkeypatch.setattr(export_references, "_freeze_reference", freeze)
    response = c.get(BUS_PATH, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert len(calls) == 2 and calls[0] == calls[1] and len(slept) == 1


def test_reference_too_large_code(export_client, monkeypatch) -> None:
    c = export_client
    c.app.state.settings.transport_map_current_enabled = True
    _run(c, _bus_heads)
    monkeypatch.setattr(export_references, "MAX_SNAPSHOT_ITEMS", 1)
    monkeypatch.setattr("app.services.reference_artifacts.MAX_SNAPSHOT_ITEMS", 1)
    response = c.get(BUS_PATH, headers=HEADERS)
    assert response.status_code == 503 and _problem(response) == ("EXPORT_TOO_LARGE", "3600")


@pytest.mark.parametrize(("members", "code", "retry_after"), [
    ([], "EXPORT_EMPTY_SET", "3600"),
    (list(range(1, export_references.MAX_HEAD_MEMBERS + 2)), "EXPORT_TOO_LARGE", "3600"),
    ([1, 1], "EXPORT_SOURCE_INCONSISTENT", "300"),
])
def test_reference_head_membership_codes(export_client, members, code, retry_after) -> None:
    c = export_client
    c.app.state.settings.transport_map_current_enabled = True
    _run(c, _bus_heads)

    async def set_members(session):
        await session.execute(update(ReferenceExportState).where(ReferenceExportState.scope_key == "intercity")
                              .values(member_ids=members))
    _run(c, set_members)
    response = c.get(BUS_PATH, headers=HEADERS)
    assert response.status_code == 503 and _problem(response) == (code, retry_after)


def test_parking_current_without_sources_is_disabled_and_waits_five_minutes_for_first_success(test_settings) -> None:
    path = "/v1/service/exports/parking/current"
    test_settings.transport_service_export_token = TOKEN
    test_settings.trusted_hosts_csv = "testserver,127.0.0.1"
    test_settings.transport_map_current_enabled = True
    with TestClient(create_app(test_settings), client=LOOPBACK_CLIENT) as client:
        # 설정된 주차장 source가 있는데 첫 성공 전이면 5분 주기 집합이라 300초다.
        if export_references.parking_sources(test_settings):
            first = client.get(path, headers=HEADERS)
            assert first.status_code == 503 and _problem(first) == ("EXPORT_NO_HISTORY", "300")
    test_settings.airport_codes_csv = "ICN"
    test_settings.enable_incheon_collection = False
    assert export_references.parking_sources(test_settings) == ()
    with TestClient(create_app(test_settings), client=LOOPBACK_CLIENT) as client:
        none = client.get(path, headers=HEADERS)
        assert none.status_code == 503 and _problem(none) == ("EXPORT_DISABLED", "3600")


# ---------------------------------------------------------------------------
# T4 가격 이력: export 경로만 code를 더하고 meta는 그대로, native 경로는 바뀌지 않는다


def test_price_history_no_history_code_only_on_export_route(export_client) -> None:
    _run(export_client, lambda s: _seed_fuel_station(s, seen_at=now_utc()))

    async def station_id(session):
        from app.models import FuelStation
        return await session.scalar(select(FuelStation.id))
    native_id = _run(export_client, station_id)
    exported = export_client.get(f"{FUEL_PATH}/A0000001/price-history", headers=HEADERS)
    assert exported.status_code == 503
    body = exported.json()
    assert body["code"] == "EXPORT_NO_HISTORY" and exported.headers["retry-after"] == "3600"
    assert body["meta"]["source_status"] == "failed" and body["meta"]["item_count"] == 0
    assert body["detail"] == "성공한 유가 수집 이력이 없습니다."
    native = export_client.get(f"/v1/transport/fuel/stations/{native_id}/price-history",
                               params={"source": OPINET_SOURCE})
    assert native.status_code == 503
    assert "code" not in native.json() and "retry-after" not in native.headers
    assert native.json()["meta"]["source_status"] == "failed"


# ---------------------------------------------------------------------------
# OpenAPI 계약


def test_openapi_declares_optional_code_and_export_retry_after(tmp_path) -> None:
    from app.core.config import Settings
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'openapi.sqlite3'}",
                        data_go_kr_service_key=None, use_sample_client_when_no_key=True, enable_api_docs=True)
    schema = create_app(settings).openapi()
    problem = schema["components"]["schemas"]["ProblemDetails"]
    assert "code" in problem["properties"] and "code" not in problem["required"]
    assert problem["properties"]["code"]["pattern"] == "^[A-Z][A-Z0-9_]*$"
    export_paths = [path for path in schema["paths"] if path.startswith("/v1/service/exports/")]
    assert export_paths
    for path in export_paths:
        responses = schema["paths"][path]["get"]["responses"]
        if path.endswith("/rest-area-fuel-prices/{station_key}/price-history"):
            assert "503" not in responses  # DB를 읽지 않는 501 경로
            continue
        assert "503" in responses, path
        assert responses["503"]["headers"]["Retry-After"]["schema"]["type"] == "integer"
    # 다른 경로의 503은 Retry-After를 약속하지 않는다.
    backups = schema["paths"]["/v1/admin/backups"]["post"]["responses"]["503"]
    assert "headers" not in backups
    # T4 503의 meta는 이력 없음 503에만 있다(TRANSIENT_DB·handler 상한 503에는 없다).
    t4 = schema["components"]["schemas"]["ServiceExportProblemDetails"]["allOf"][1]
    assert "meta" in t4["properties"] and "meta" not in t4.get("required", [])


# ---------------------------------------------------------------------------
# 실행 중 확인: export 경로의 모든 503은 code와 Retry-After를 싣는다(정규식 대신 실제 응답, 적대적 리뷰 P1)


_NO_DATABASE_ROUTES = {"/v1/service/exports/airports",
                       "/v1/service/exports/rest-area-fuel-prices/{station_key}/price-history"}


def test_every_export_503_carries_a_code_at_runtime(export_client) -> None:
    import re

    c = export_client
    routes = sorted(path for path, item in c.app.openapi()["paths"].items()
                    if path.startswith("/v1/service/exports/") and "get" in item)
    assert len(routes) >= 10
    lenient = TestClient(c.app, client=LOOPBACK_CLIENT, raise_server_exceptions=False)
    seen: dict[str, set[str]] = {}

    def call(path):
        response = lenient.get(path.replace("{station_key}", "A0000001"), headers=HEADERS)
        if response.status_code == 503:
            body = response.json()
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", str(body.get("code"))), (path, body)
            assert int(response.headers["retry-after"]) >= 1, path
            assert body["status"] == 503 and body["instance"].startswith("/v1/service/exports/")
            seen.setdefault(path, set()).add(body["code"])
        return response

    # 1) 빈 DB에서 current export 꺼짐·켜짐.
    for enabled in (False, True):
        c.app.state.settings.transport_map_current_enabled = enabled
        for path in routes:
            call(path)
    # 2) T4 이력 없음 503은 meta(source_status=failed)를 유지하면서 code도 싣는다.
    _run(c, lambda s: _seed_fuel_station(s, seen_at=now_utc()))
    t4 = call("/v1/service/exports/fuel-stations/{station_key}/price-history")
    assert t4.status_code == 503 and t4.json()["code"] == "EXPORT_NO_HISTORY"
    assert t4.json()["meta"]["source_status"] == "failed"
    # 3) DB에 닿지 못함(실제 asyncpg 접속 거부).
    engine, factory = create_engine_and_session_factory("postgresql+asyncpg://u:p@127.0.0.1:1/unreachable")
    original = c.app.state.session_factory
    c.app.state.session_factory = factory
    try:
        for path in routes:
            call(path)
    finally:
        c.app.state.session_factory = original
        asyncio.run(engine.dispose())
    # DB를 읽는 export는 모두 한 번 이상 503을 냈고(그래서 위 검사를 실제로 거쳤고) 그 code는 모두 있었다.
    assert not set(routes) - set(seen) - _NO_DATABASE_ROUTES, sorted(set(routes) - set(seen))
    assert all("TRANSIENT_DB" in codes for path, codes in seen.items()), seen
