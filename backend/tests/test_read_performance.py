"""요청 비용·다중 지도·조건부 export의 회귀 계약."""
import asyncio
import logging
import re

import pytest
from app.core import read_timing
from sqlalchemy import event
from starlette.responses import Response


async def seed_places(session, count=3):
    from app.core.time_utils import now_utc
    from app.models import (
        BusTerminalReference,
        FerryPort,
        HighwayIncidentSnapshot,
        PublicParkingLot,
        RailStationReference,
        RestAreaReference,
        TransportCollectionState,
    )
    from app.public_parking_routes import SOURCE
    from sqlalchemy import insert
    now = now_utc()
    raw = {"unused": "폐기할 원문" * 1500, "환승역 여부": " 가능 ",
           "유실물 취급여부": "있음", "안전발판 유무": "없음",
           "스크린도어 설치유무": "있음", "승강장 연결여부": None,
           "_manual_location": {"revision": "검산-revision"}}
    common = {"source": "fixture", "longitude": 127.1, "latitude": 37.5,
                  "first_seen_at": now, "last_seen_at": now, "raw_item_json": raw}
    for model, values in [
        (RailStationReference, [dict(common, identity_key=f"rail-{i}", station_name=f"역-{i}",
                                    rail_operator_name="운영사", operating_line_name="노선") for i in range(count)]),
        (FerryPort, [dict(common, port_id=f"port-{i}", port_name=f"항구-{i}",
                         location_source="admin_manual", location_point_count=1) for i in range(count)]),
        (BusTerminalReference, [dict(common, terminal_id=f"terminal-{i}", terminal_name=f"터미널-{i}",
                                    service_type="express", city_name="도시", location_source="admin_manual") for i in range(count)]),
        (RestAreaReference, [dict(common, identity_key=f"rest-{i}", name=f"휴게소-{i}",
                                 route_name="노선", has_gas_station=True) for i in range(count)]),
        (PublicParkingLot, [{"source": SOURCE, "source_key": f"parking-{i}", "provider_id": f"공영-{i}",
                                "name": f"주차장-{i}", "longitude": 127.2, "latitude": 37.6, "capacity": 100,
                                "fee_info": "무료", "opening_hours_json": {}, "raw_json": raw,
                                "created_at": now, "last_seen_at": now} for i in range(count)]),
        (HighwayIncidentSnapshot, [{"source": "fixture", "identity_key": f"incident-{i}",
                                       "observed_at": now, "collected_at": now, "longitude": 127.1,
                                       "latitude": 37.5, "incident_type": "공사", "point_name": f"돌발-{i}",
                                       "raw_item_json": raw} for i in range(count)]),
    ]:
        await session.execute(insert(model), values)
    session.add(TransportCollectionState(source=SOURCE, last_success_at=now, updated_at=now))


def test_timing_counts_sql_and_uses_only_template(client):
    response = client.get("/v1/transport/features/places", params={"kinds": "fuel_station,rail_station"})
    assert response.status_code == 200
    timing = response.headers["server-timing"]
    assert re.search(r'sql_count;desc="[1-9][0-9]*"', timing)
    assert "cpu;dur=" in timing and "sql;dur=" in timing
    assert client.get("/metrics").status_code == 404


@pytest.mark.anyio
async def test_slow_route_log_never_contains_path_or_query(caplog, monkeypatch):
    ticks = iter([0, 0.1, 1.2])
    monkeypatch.setattr(read_timing, "perf_counter", lambda: next(ticks))
    async def endpoint(scope, receive, send):
        scope["route"] = type("Route", (), {"path": "/items/{item_id}"})()
        await Response("ok")(scope, receive, send)
    async def receive():
        return {"type": "http.request", "body": b""}
    messages = []
    async def send(message):
        messages.append(message)
    with caplog.at_level(logging.INFO, logger=read_timing.__name__):
        await read_timing.ReadTimingMiddleware(endpoint)({"type": "http", "path": "/items/secret-id",
            "query_string": b"api_key=secret-key&longitude=127"}, receive, send)
    assert "route=/items/{item_id}" in caplog.text and "duration_ms=1200.000" in caplog.text
    assert "sql_count=0" in caplog.text and "cpu_ms=" in caplog.text
    assert "secret" not in caplog.text and "longitude" not in caplog.text
    assert read_timing._current.get() is None


@pytest.mark.parametrize("params", [
    {}, {"limit": 1}, {"query": "찾지못할이름"}, {"source": "opinet"},
    {"include_unlocated": True}, {"min_longitude": 126, "max_longitude": 129,
                                 "min_latitude": 33, "max_latitude": 39},
])
def test_all_kinds_sql_budget_and_exact_fallback_equivalence(client, monkeypatch, params):
    from app import main
    engine = client.app.state.engine
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 집합 투영 동등성")
    async def seed():
        async with client.app.state.session_factory() as session:
            await seed_places(session)
            await session.commit()
    asyncio.run(seed())
    statements = []
    def before(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql)
    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        optimized = client.get("/v1/transport/features/places", params=params)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)
    assert optimized.status_code == 200, optimized.text
    assert len(statements) <= 10
    async def fallback(*args):
        return None
    monkeypatch.setattr(main, "read_place_plans", fallback)
    baseline = client.get("/v1/transport/features/places", params=params)
    assert baseline.status_code == 200, baseline.text
    old, new = baseline.json(), optimized.json()
    old.pop("generated_at"); new.pop("generated_at")
    assert new == old
