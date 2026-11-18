"""실제 이력 밀도에서 장소 집계·조건부 참조 조회의 중복 작업을 방지한다."""
# ruff: noqa: F811

import asyncio
from datetime import timedelta

import pytest
from app.core.time_utils import now_utc
from app.models import HighwayIncidentSnapshot, ReferenceExportArtifact
from sqlalchemy import event, insert, update
from test_read_performance import seed_places
from test_reference_export_reuse import HEADERS, _get, _prepare
from test_service_exports import _run, export_client  # noqa: F401


def test_places_ranks_history_once_and_keeps_latest_before_location_filter(client, monkeypatch):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 실행계획 검증")
    async def seed():
        async with client.app.state.session_factory() as session:
            await seed_places(session)
            now = now_utc()
            rows = [
                {"source": "history", "identity_key": f"incident-{i % 3}",
                 "observed_at": now - timedelta(minutes=i + 1), "collected_at": now - timedelta(minutes=i + 1),
                 "longitude": 127.1, "latitude": 37.5, "point_name": f"이력-{i}"}
                for i in range(600)
            ]
            # 최신 관측에 좌표가 없으면 이전의 좌표 있는 관측을 되살리지 않는다.
            rows.append({"source": "history", "identity_key": "incident-0",
                         "observed_at": now, "collected_at": now,
                         "longitude": None, "latitude": None, "point_name": "최신 좌표 없음"})
            await session.execute(insert(HighwayIncidentSnapshot), rows)
            await session.commit()
    asyncio.run(seed())
    statements = []
    def capture(conn, cursor, sql, params, context, many):
        if "UNION ALL" in sql and "json_agg" in sql:
            statements.append((sql, params))
    engine = client.app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get("/v1/transport/features/places?limit=5000")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind_totals"]["highway_incident"] == 5  # fixture 3 + history 2
    async def explain():
        async with client.app.state.engine.connect() as connection:
            sql, params = statements[0]
            return (await connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, FORMAT JSON) " + sql, params,
            )).scalar()[0]["Plan"]
    plan = asyncio.run(explain())
    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)
    # 집계와 제한 페이지가 같은 이력 범위를 두 번 읽으면 작은 SQL 수로도 느려진다.
    rankings = [node for node in nodes(plan)
                if node.get("Node Type") == "WindowAgg"
                and "PARTITION BY" in node.get("Window", "")]
    assert len(rankings) == 1
    assert rankings[0]["Actual Loops"] == 1
    async def fallback(*args):
        return None
    from app import main
    monkeypatch.setattr(main, "read_place_plans", fallback)
    legacy = client.get("/v1/transport/features/places?limit=5000")
    assert legacy.status_code == 200
    expected = legacy.json()
    body.pop("generated_at")
    expected.pop("generated_at")
    assert body == expected


def test_warm_reference_reads_handle_and_artifact_once_without_losing_guard(export_client):
    client = export_client
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL artifact 경로")
    _prepare(client)
    first = _get(client)
    assert first.status_code == 200, first.text
    statements = []
    def capture(conn, cursor, sql, params, context, many):
        statements.append(sql)
    engine = client.app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        warm = client.get("/v1/service/exports/rail-stations?limit=1", headers={
            **HEADERS,
            "If-None-Match": first.headers["ETag"],
        })
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert warm.status_code == 304, warm.text
    assert not any("reference_export_artifact_items" in sql for sql in statements)
    assert not any("string_agg" in sql for sql in statements)
    assert len(statements) <= 5
    assert sum("reference_export_artifacts" in sql for sql in statements) == 1

    async def corrupt(session):
        await session.execute(update(ReferenceExportArtifact).values(kind="wrong-kind"))
    _run(client, corrupt)
    # 동일 ETag라도 handle/본문의 kind가 어긋나면 304로 숨기지 않는다.
    invalid = client.get("/v1/service/exports/rail-stations?limit=1", headers={
        **HEADERS,
        "If-None-Match": first.headers["ETag"],
    })
    assert invalid.status_code == 503
