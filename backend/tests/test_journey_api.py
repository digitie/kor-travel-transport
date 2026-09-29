"""여행 UI용 읽기 계약: 누락/빈 응답 구분, 다중 선택, 제공자 호출 금지."""
import asyncio
import pytest
from datetime import timedelta
from unittest.mock import patch

from app.core.time_utils import now_utc, to_seoul
from app.models import CollectionRun, FerryPort, FerryTimetableSnapshot, TransportCollectionState


@pytest.mark.parametrize("params", [
    {"sources": ""}, {"sources": "a,,b"}, {"sources": "a, "},
    {"sources": ",".join(["a"] * 11)}, {"sources": "x" * 81},
    {"source": "a", "sources": "a,b"}, {"source": "", "sources": "a"},
    {"product_codes": ""}, {"product_codes": "B027,"},
    {"product_codes": ",".join(["B027"] * 6)}, {"product_codes": "x" * 21},
    {"product_code": "B027", "product_codes": "D047"},
])
def test_place_multi_filters_reject_ambiguous_or_unbounded_input(client, params):
    assert client.get("/v1/transport/features/places", params=params).status_code == 422


def test_stored_ferry_search_never_calls_provider_and_keeps_missing_distinct(client):
    today = to_seoul(now_utc()).date()

    async def seed():
        now = now_utc()
        async with client.app.state.session_factory() as session:
            for number in range(6):
                session.add(FerryPort(source="data_go_kr_maritime", port_id=f"P{number}", port_name=f"항구{number}", first_seen_at=now, last_seen_at=now))
            session.add_all([
                FerryTimetableSnapshot(source="data_go_kr_maritime", departure_port_id="P0", service_date=today, collected_at=now, items_json=[]),
                FerryTimetableSnapshot(source="data_go_kr_maritime", departure_port_id="P1", service_date=today, collected_at=now, items_json=[{"vessel_name": "테스트호", "departure_planned_time": "0900", "fare": "12000"}]),
            ])
            await session.commit()

    asyncio.run(seed())
    with patch("app.main.DataGoKrMaritimeClient", side_effect=AssertionError("저장 조회에서 provider 생성 금지")):
        for _ in range(3):
            response = client.get("/v1/transport/ports/timetables", params={"port_ids": "P0,P1,P2,P1", "date": today.isoformat()})
            assert response.status_code == 200
            body = response.json()
            assert body["missing_port_ids"] == ["P2"]
            rows = {item["port_id"]: item for item in body["items"]}
            assert rows["P0"]["items"] == []
            assert rows["P1"]["items"][0]["vessel_name"] == "테스트호"
            assert rows["P1"]["fetched_at"].endswith(("Z", "+00:00"))
        tomorrow = client.get("/v1/transport/ports/timetables", params={"port_ids": "P0", "date": (today + timedelta(days=9)).isoformat()})
        assert tomorrow.status_code == 200
        assert tomorrow.json()["missing_port_ids"] == ["P0"]
        for port_ids in [",,", "P0,P1,P2,P3,P4,P5", "x" * 121]:
            assert client.get("/v1/transport/ports/timetables", params={"port_ids": port_ids}).status_code == 422
        for offset in [-1, 10]:
            assert client.get("/v1/transport/ports/timetables", params={"port_ids": "P0", "date": (today + timedelta(days=offset)).isoformat()}).status_code == 422
        assert client.get("/v1/transport/ports/timetables?port_ids=unknown").status_code == 404
    assert client.get("/v1/transport/features/places?kind=ferry_port").json()["total"] == 0
    unlocated = client.get("/v1/transport/features/places?kind=ferry_port&include_unlocated=true").json()
    assert unlocated["total"] == 6
    assert all(row["latitude"] is None for row in unlocated["items"])
    assert client.get("/v1/transport/features/places?kind=ferry_port&include_unlocated=true&source=absent").json()["total"] == 0
    status = client.get("/v1/transport/providers")
    assert status.status_code == 200
    assert status.json()["ferry_expected_snapshots"] == 60
    assert status.json()["ferry_stored_snapshots"] == 2


def test_provider_status_does_not_confuse_enabled_or_shared_job_with_success(client):
    async def seed():
        now = now_utc()
        async with client.app.state.session_factory() as session:
            session.add(CollectionRun(trigger="dagster_airport", status="success", started_at=now, finished_at=now))
            session.add(CollectionRun(trigger="dagster_rail", status="failed", started_at=now, finished_at=now, error_message="secret-provider-key"))
            session.add(CollectionRun(trigger="transport_dagster_highway", status="partial_success", started_at=now, finished_at=now))
            session.add(TransportCollectionState(source="krex_traffic_flow", last_started_at=now, last_success_at=now, updated_at=now))
            session.add(TransportCollectionState(source="krex_traffic_incident", last_started_at=now, last_error="secret-failed", updated_at=now))
            await session.commit()
    asyncio.run(seed())
    client.app.state.settings.data_go_kr_service_key = "test-key"
    client.app.state.settings.rail_reference_collection_enabled = True
    client.app.state.settings.kex_ex_api_key = "test-key"
    client.app.state.settings.transport_collection_enabled = True
    response = client.get("/v1/transport/providers")
    assert response.status_code == 200
    rows = {row["source"]: row for row in response.json()["items"]}
    assert rows["kac_parking"]["status"] == "shared_job_success"
    assert rows["kric_public_file"]["status"] == "failed"
    assert rows["kric_public_file"]["error_code"] == "collection_failed"
    assert rows["kric_timetable"]["mode"] == "scheduled"
    assert rows["kric_timetable"]["enabled"] is False
    assert rows["bus_timetable"]["mode"] == "on_demand"
    assert rows["krex_traffic_flow"]["status"] == "success"
    assert rows["krex_traffic_flow"]["job_status"] == "partial_success"
    assert rows["krex_traffic_incident"]["status"] == "failed"
    assert "test-key" not in response.text
    assert "secret-provider-key" not in response.text


def test_place_sources_survive_response_limit_and_empty_bounds(client):
    async def seed():
        now = now_utc()
        async with client.app.state.session_factory() as session:
            for number, source in enumerate(["source_one", "source_two"]):
                session.add(FerryPort(source=source, port_id=f"S{number}", port_name=f"출처항{number}", longitude=127, latitude=37, first_seen_at=now, last_seen_at=now))
            await session.commit()
    asyncio.run(seed())
    for extra in ["limit=1", "min_longitude=129&max_longitude=130&min_latitude=35&max_latitude=36"]:
        response = client.get(f"/v1/transport/features/places?kind=ferry_port&{extra}")
        assert response.status_code == 200
        body = response.json()
        assert set(body["available_sources"]) == {"source_one", "source_two"}
        assert len(body["items"]) <= 1
    airport = client.get("/v1/transport/features/places?kind=airport&query=GMP")
    assert airport.status_code == 200
    assert any(row["provider_id"] == "GMP" for row in airport.json()["items"])
