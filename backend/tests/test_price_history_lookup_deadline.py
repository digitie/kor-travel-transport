"""가격 이력(T4 export·지도 상세 native)의 주유소 조회 경로와 DB 문장 상한.

감사(2026-11-24) T4-01·T4-08·T4 deadline 후속이다.

- export 자연키는 수집기 identity_key(`uq_fuel_station_identity`)로 찾는다. 옛 `source_station_id` 조건과 같은
  행을 고르는지 실제 수집 저장 경로(`_store_fuel_snapshot`)로 만든 fixture에서 고정한다.
- native 응답은 주유소를 한 번만 읽고, `include_latest=false`면 현재 가격 조회를 생략한다.
- statement_timeout(57014)은 500이 아니라 export 503·native 504 + Retry-After problem이다. native가 503을 쓰지 않는
  것은 화면이 503을 '성공한 수집 이력 없음'으로 안내하기 때문이다. PostgreSQL에서는 실제 lock 대기로 재현한다.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from opinet import ProductCode
from sqlalchemy import event, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core.time_utils import now_utc
from app.main import create_app
from app.models import CollectionRun, FuelStation
from app.services import export_price_history, fuel_price_history
from app.services.export_price_history import (
    HISTORY_TIMEOUT_DETAIL, HISTORY_TIMEOUT_RETRY_AFTER_SECONDS, opinet_station_identity, read_price_history_page,
    station_lookup_statement,
)
from app.services.transport_collection import OPINET_SOURCE
from test_fuel_store_bulk import make_snapshot, make_station, price
from test_service_exports import HEADERS, TOKEN, _run, _set_state

EXPORT = "/v1/service/exports/fuel-stations/{key}/price-history"
NATIVE = "/v1/transport/fuel/stations/{id}/price-history"
STATION_KEYS = ("A0000001", "0123")  # 선행0 자연키도 그대로 보존한다.


@pytest.fixture
def history_client(test_settings):
    test_settings.transport_service_export_token = TOKEN
    test_settings.trusted_hosts_csv = "testserver,127.0.0.1"
    with TestClient(create_app(test_settings), client=("127.0.0.1", 50123)) as client:
        collected = now_utc() - timedelta(hours=1)
        observed = collected - timedelta(hours=1)

        async def seed(session):
            run = CollectionRun(started_at=collected, status="running", trigger="t4_lookup_test")
            session.add(run)
            await session.flush()
            service = client.app.state.transport_collection_service
            await service._store_fuel_snapshot(session, run.id, make_snapshot(collected, [
                make_station("A0000001", name="에이", prices=(price(ProductCode.GASOLINE, 1700, observed),
                                                              price(ProductCode.DIESEL, None, None))),
                make_station("0123", name="선행영", sigungu="종로구", katec=(1.0, 2.0),
                             prices=(price(ProductCode.DIESEL, 1600, observed),)),
                # 안정 ID가 없는 주유소는 지문 identity라 자연키로 찾을 수 없다(T1 export에서도 빠진다).
                make_station(None, name="코드없음", sigungu="중구", katec=(3.0, 4.0),
                             prices=(price(ProductCode.LPG, 1000, observed),)),
            ]))
            await _set_state(session, OPINET_SOURCE, last_success_at=collected, updated_at=collected)
        _run(client, seed)
        yield client


def _postgres(client) -> bool:
    return client.app.state.engine.dialect.name == "postgresql"


def _station_ids(client) -> dict[str, int]:
    async def read(session):
        rows = (await session.execute(select(FuelStation.source_station_id, FuelStation.id).where(
            FuelStation.source == OPINET_SOURCE, FuelStation.source_station_id.is_not(None),
        ))).all()
        return {key: station_id for key, station_id in rows}
    return _run(client, read)


def test_identity_lookup_selects_the_same_station_as_source_station_id(history_client):
    """수집 저장이 만든 모든 행에서 identity_key 조회와 옛 source_station_id 조회가 같은 1행이다."""
    async def compare(session):
        rows = (await session.execute(select(
            FuelStation.id, FuelStation.identity_key, FuelStation.source_station_id,
        ).where(FuelStation.source == OPINET_SOURCE))).all()
        assert len(rows) == 3
        for row in rows:
            if row.source_station_id is None:
                assert row.identity_key.startswith("fallback:")
                continue
            assert row.identity_key == opinet_station_identity(row.source_station_id)
            legacy = (await session.scalars(select(FuelStation.id).where(
                FuelStation.source == OPINET_SOURCE, FuelStation.source_station_id == row.source_station_id,
            ))).all()
            current = (await session.execute(station_lookup_statement(row.source_station_id))).all()
            assert legacy == [row.id] and [found.id for found in current] == [row.id]
            assert current[0].source_station_id == row.source_station_id
        return {row.source_station_id for row in rows if row.source_station_id is not None}
    assert _run(history_client, compare) == set(STATION_KEYS)

    for key in STATION_KEYS:
        response = history_client.get(EXPORT.format(key=key), headers=HEADERS)
        assert response.status_code == 200, response.text
        assert response.json()["station_key"] == key and response.json()["items"]
    # 수집 identity의 접두어를 자연키로 넣어도 다른 행을 고르지 않는다.
    assert history_client.get(EXPORT.format(key="station:A0000001"), headers=HEADERS).status_code == 404
    assert history_client.get(EXPORT.format(key="A0000001 "), headers=HEADERS).status_code == 404


def test_native_reads_station_once_and_include_latest_false_skips_latest(history_client):
    station_id = _station_ids(history_client)["A0000001"]
    statements: list[str] = []
    engine = history_client.app.state.engine.sync_engine

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        path = NATIVE.format(id=station_id)
        full = history_client.get(path, params={"source": OPINET_SOURCE, "days": 30})
        station_reads = [s for s in statements if "fuel_stations.brand_code" in s]
        latest_reads = [s for s in statements if "fuel_latest_prices.snapshot_id" in s]
        statements.clear()
        lean = history_client.get(path, params={"source": OPINET_SOURCE, "days": 30, "include_latest": "false"})
        lean_station_reads = [s for s in statements if "fuel_stations.brand_code" in s]
        lean_latest_reads = [s for s in statements if "fuel_latest_prices.snapshot_id" in s]
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert full.status_code == lean.status_code == 200
    # 주유소 행은 이력 조회의 첫 문장에서 한 번만 읽는다(옛 구현은 응답 조립 때 한 번 더 읽었다).
    assert len(station_reads) == len(lean_station_reads) == 1
    assert len(latest_reads) == 1 and lean_latest_reads == []
    full_body, lean_body = full.json(), lean.json()
    assert {row["product_code"] for row in full_body["latest"]} == {"B027", "D047"}
    assert lean_body["latest"] == []
    # 이력·revision·주유소 표시값은 include_latest와 무관하다(창은 요청 시각 기준 rolling이라 비교하지 않는다).
    for key in ("items", "source_revision", "provider_id", "brand_code", "brand_name", "source", "station_id"):
        assert lean_body[key] == full_body[key], key
    assert full_body["provider_id"] == "A0000001" and full_body["brand_code"] == "SKE"


def test_native_include_latest_false_keeps_cursor_walk(history_client):
    """include_latest는 cursor 범위(scope)·revision에 들어가지 않는다. 기존 cursor 의미를 바꾸지 않는다."""
    station_id = _station_ids(history_client)["A0000001"]
    path = NATIVE.format(id=station_id)
    params = {"source": OPINET_SOURCE, "days": 30, "limit": 1}
    first = history_client.get(path, params=params | {"include_latest": "false"}).json()
    assert first["has_more"] and first["next_cursor"]
    second = history_client.get(path, params=params | {"cursor": first["next_cursor"]})
    assert second.status_code == 200
    assert second.json()["source_revision"] == first["source_revision"]
    assert second.json()["latest"]  # cursor를 이어도 기본값(true)이면 현재 가격을 싣는다.


class _QueryCanceled(Exception):
    sqlstate = "57014"


class _OtherDatabaseError(Exception):
    sqlstate = "XX000"


def _db_error(orig: Exception) -> DBAPIError:
    return DBAPIError("SELECT 1", None, orig)


def _assert_timeout_problem(response, status: int) -> None:
    assert response.status_code == status, response.text
    assert response.headers["retry-after"] == str(HISTORY_TIMEOUT_RETRY_AFTER_SECONDS)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "etag" not in response.headers
    body = response.json()
    assert body["status"] == status and body["detail"] == HISTORY_TIMEOUT_DETAIL
    # native 화면의 503 문구('성공한 수집 이력 없음')와 겹치지 않는다.
    assert "수집 이력" not in body["detail"]
    # 예외 원문(SQL·접속 정보)은 응답에 싣지 않는다.
    assert "SELECT" not in response.text and "statement timeout" not in response.text


def test_statement_timeout_is_export_503_and_native_504_with_retry_after(history_client, monkeypatch):
    async def canceled_read(*args, **kwargs):
        raise _db_error(_QueryCanceled("canceling statement due to statement timeout"))

    monkeypatch.setattr(export_price_history, "read_price_history_page", canceled_read)
    # Map은 T4 503을 upstream_unavailable로 강등한다.
    _assert_timeout_problem(history_client.get(EXPORT.format(key="A0000001"), headers=HEADERS), 503)

    # native는 현재 가격 조회까지 같은 상한 처리 안에 있다.
    async def canceled_latest(*args, **kwargs):
        raise _db_error(_QueryCanceled("canceling statement due to statement timeout"))

    monkeypatch.setattr(fuel_price_history, "_latest_prices", canceled_latest)
    station_id = _station_ids(history_client)["A0000001"]
    _assert_timeout_problem(history_client.get(NATIVE.format(id=station_id), params={"source": OPINET_SOURCE}), 504)
    # latest를 생략하면 그 조회의 상한 초과도 생기지 않는다.
    lean = history_client.get(NATIVE.format(id=station_id), params={"source": OPINET_SOURCE, "include_latest": "false"})
    assert lean.status_code == 200


def test_other_database_errors_are_not_reported_as_timeouts(history_client, monkeypatch):
    async def broken_read(*args, **kwargs):
        raise _db_error(_OtherDatabaseError("internal"))

    monkeypatch.setattr(export_price_history, "read_price_history_page", broken_read)
    with pytest.raises(DBAPIError):
        history_client.get(EXPORT.format(key="A0000001"), headers=HEADERS)


# --- PostgreSQL 전용 ---------------------------------------------------------------------------------------------

def _require_postgres(client) -> None:
    if not _postgres(client):
        pytest.skip("PostgreSQL 전용: 실제 statement_timeout·실행 계획")


def test_postgres_history_transaction_sets_local_timeout_without_xid(history_client):
    """문장 상한은 transaction 범위(`SET LOCAL`)이고, 이력 조회는 XID를 받지 않는 읽기 전용 transaction이다."""
    _require_postgres(history_client)
    statements: list[str] = []
    engine = history_client.app.state.engine.sync_engine

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    async def read(session):
        read = await read_price_history_page(
            SimpleNamespace(url=SimpleNamespace(path="/test")), "A0000001", None, None, None, 1000, None,
            session, b"k" * 32,
        )
        assert read.station.source_station_id == "A0000001" and read.rows
        timeout = await session.scalar(text("SHOW statement_timeout"))
        xid = await session.scalar(text("SELECT pg_current_xact_id_if_assigned()"))
        isolation = await session.scalar(text("SHOW transaction_isolation"))
        await session.rollback()
        return timeout, xid, isolation

    event.listen(engine, "before_cursor_execute", capture)
    try:
        timeout, xid, isolation = _run(history_client, read)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert timeout == "5s" and xid is None and isolation == "repeatable read"
    sets = [s for s in statements if "statement_timeout" in s and s.lstrip().upper().startswith("SET")]
    assert sets == ["SET LOCAL statement_timeout = 5000"]


def test_postgres_export_station_lookup_uses_identity_unique_index(history_client):
    """감사 T4-01: 자연키 조회가 유니크 인덱스 1행 조회다. 검출기 전제: 옛 source_station_id 조건은 전체 스캔이다."""
    _require_postgres(history_client)
    stamp = now_utc()

    async def plans(session):
        await session.execute(insert(FuelStation), [{
            "source": OPINET_SOURCE, "identity_key": opinet_station_identity(f"K{index:05d}"),
            "source_station_id": f"K{index:05d}", "name": f"주유소{index}", "query_level": "sigungu",
            "source_kinds": [], "sido_value": "11", "sido_name": "서울", "sigungu_value": "110", "sigungu_name": "종로",
            "raw_item_json": {"pad": "x" * 600}, "first_seen_at": stamp, "last_seen_at": stamp,
        } for index in range(3000)])
        await session.commit()
        await session.execute(text("ANALYZE fuel_stations"))
        result = {}
        for name, statement in (
            ("current", station_lookup_statement("K01234")),
            ("legacy", select(FuelStation.id).where(
                FuelStation.source == OPINET_SOURCE, FuelStation.source_station_id == "K01234",
            )),
        ):
            compiled = statement.compile(dialect=session.bind.dialect, compile_kwargs={"literal_binds": True})
            raw = await session.scalar(text(f"EXPLAIN (FORMAT JSON) {compiled}"))
            result[name] = (json.loads(raw) if isinstance(raw, str) else raw)[0]["Plan"]
        return result

    result = _run(history_client, plans)
    assert result["current"]["Node Type"] in {"Index Scan", "Index Only Scan"}, result["current"]
    assert result["current"]["Index Name"] == "uq_fuel_station_identity"
    assert result["legacy"]["Node Type"] == "Seq Scan", result["legacy"]


@pytest.mark.parametrize(("route", "status"), [("export", 503), ("native", 504)])
def test_postgres_lock_wait_past_statement_timeout_is_problem_and_connection_recovers(
    history_client, monkeypatch, route, status,
):
    """fuel_stations에 ACCESS EXCLUSIVE(예: 잠금을 오래 잡는 DDL)가 걸리면 기본 120초가 아니라 이력 상한에서 끝낸다."""
    _require_postgres(history_client)
    monkeypatch.setattr(export_price_history, "HISTORY_STATEMENT_TIMEOUT_MS", 300)
    path = EXPORT.format(key="A0000001") if route == "export" else NATIVE.format(id=_station_ids(history_client)["A0000001"])
    kwargs = {"headers": HEADERS} if route == "export" else {"params": {"source": OPINET_SOURCE}}

    loop = asyncio.new_event_loop()
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"], poolclass=NullPool)
    holder = loop.run_until_complete(engine.connect())
    try:
        loop.run_until_complete(holder.begin())
        loop.run_until_complete(holder.execute(text("LOCK TABLE fuel_stations IN ACCESS EXCLUSIVE MODE")))
        _assert_timeout_problem(history_client.get(path, **kwargs), status)
    finally:
        loop.run_until_complete(holder.rollback())
        loop.run_until_complete(holder.close())
        loop.run_until_complete(engine.dispose())
        loop.close()
    # 상한 초과 transaction은 rollback됐고 다음 요청은 정상이다.
    recovered = history_client.get(path, **kwargs)
    assert recovered.status_code == 200, recovered.text
