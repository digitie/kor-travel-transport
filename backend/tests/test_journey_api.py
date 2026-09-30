"""여행 UI용 읽기 계약: 누락/빈 응답 구분, 다중 선택, 제공자 호출 금지."""
import asyncio
import pytest
from datetime import timedelta
from unittest.mock import patch

from app.core.time_utils import now_utc, to_seoul
from app.models import BusTerminalReference, CollectionRun, FerryPort, FerryTimetableSnapshot, HighwayIncidentSnapshot, RestAreaReference, TransportCollectionState


def test_map_incidents_use_latest_saved_observation_and_rest_areas_remain_visible(client):
    async def seed():
        now = now_utc()
        async with client.app.state.session_factory() as session:
            for identity, hours, longitude, status in [
                ("same", 2, 127, "처리중"), ("same", 1, 127.1, "처리완료"),
                ("old", 25, 127, "처리중"), ("unlocated", 1, None, "처리중"),
                ("moved", 2, 127, "처리중"), ("moved", 1, 129, "처리중"),
            ]:
                session.add(HighwayIncidentSnapshot(source="krex_traffic_incident", identity_key=identity,
                    observed_at=now - timedelta(hours=hours), collected_at=now - timedelta(hours=hours),
                    route_no="0010", route_name="경부고속도로", point_name=identity,
                    incident_type="사고", process_status=status, message="차로 통제 정보",
                    longitude=longitude, latitude=37 if longitude is not None else None))
            session.add(RestAreaReference(source="krex_rest_area", identity_key="rest-one", name="시험휴게소",
                route_name="경부고속도로", longitude=127, latitude=37, first_seen_at=now, last_seen_at=now))
            await session.commit()
    asyncio.run(seed())
    path = "/v1/transport/features/places"
    response = client.get(path, params={"kind": "highway_incident"})
    assert response.status_code == 200
    assert response.json()["total"] == 2
    assert {r["provider_id"] for r in response.json()["items"]} == {"same", "moved"}
    row = next(r for r in response.json()["items"] if r["provider_id"] == "same")
    assert row["line_names"] == ["0010 · 경부고속도로"]
    assert row["subtitle"] == "사고 · 처리완료"
    assert row["address"] == "차로 통제 정보"
    bounded = client.get(path, params={"kind": "highway_incident", "min_longitude": 126,
        "max_longitude": 128, "min_latitude": 36, "max_latitude": 38, "product_codes": "B034"}).json()
    assert bounded["total"] == 1  # 범위 안의 오래된 moved 행을 되살리지 않는다.
    assert client.get(path, params={"kind": "highway_incident", "include_unlocated": True}).json()["total"] == 3
    assert client.get(path, params={"kind": "highway_incident", "query": "0010", "limit": 1}).json()["truncated"] is True
    assert client.get(path, params={"kind": "highway_incident", "sources": "absent"}).json()["total"] == 0
    rest = client.get(path, params={"kind": "rest_area", "query": "경부"}).json()
    assert rest["total"] == 1
    assert rest["items"][0]["name"] == "시험휴게소"


def test_unchanged_incident_reobservation_preserves_history_and_map_visibility(client):
    from sqlalchemy import select
    from krex import Incident
    from app.services.transport_collection import TransportCollectionService, INCIDENT_SOURCE

    old = now_utc() - timedelta(hours=25)
    recent = now_utc() - timedelta(minutes=1)
    item = Incident(series_no=123, incident_type="공사", process_status="처리중",
        route_no="0010", route_name="경부고속도로", latitude=37, longitude=127,
        occurred_date=old.strftime("%Y%m%d"), occurred_time="0900", incident_type_code="02",
        direction=None, message="공사 중", point_name="시험 구간", process_status_code="01",
        congestion_length=None, raw={})

    async def run():
        service = TransportCollectionService(client.app.state.settings)
        async with client.app.state.session_factory() as session:
            run = CollectionRun(trigger="test", started_at=old, status="success")
            session.add(run)
            await session.flush()
            with patch("app.services.transport_collection.now_utc", return_value=old):
                assert await service._store_incidents(session, run.id, (item,)) == 1
            await session.commit()
            with patch("app.services.transport_collection.now_utc", return_value=recent):
                assert await service._store_incidents(session, run.id, (item,)) == 0
            await session.commit()
            rows = (await session.scalars(select(HighwayIncidentSnapshot).where(
                HighwayIncidentSnapshot.source == INCIDENT_SOURCE))).all()
            assert len(rows) == 1
            from app.core.time_utils import serialize_utc
            assert serialize_utc(rows[0].observed_at) == old
            assert serialize_utc(rows[0].collected_at) == recent
        await service.close()

    asyncio.run(run())
    response = client.get("/v1/transport/features/places", params={"kind": "highway_incident"})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    from datetime import datetime
    assert datetime.fromisoformat(response.json()["items"][0]["updated_at"]) == recent


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
            session.add(TransportCollectionState(source="fuel_latest_prices", last_started_at=now,
                                                 last_error="secret-view-lock", next_due_at=now + timedelta(minutes=5),
                                                 updated_at=now))
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
    assert rows["fuel_latest_prices"]["status"] == "failed"
    assert rows["fuel_latest_prices"]["error_code"] == "read_model_refresh_failed"
    assert rows["fuel_latest_prices"]["next_due_at"] is not None
    assert rows["fuel_latest_prices"]["job_status"] is None
    assert "test-key" not in response.text
    assert "secret-provider-key" not in response.text
    assert "secret-view-lock" not in response.text


def test_bus_terminal_map_uses_only_verified_coordinates_and_preserves_code(client):
    async def seed():
        now = now_utc()
        async with client.app.state.session_factory() as session:
            session.add(BusTerminalReference(source="data_go_kr_tago", service_type="intercity",
                terminal_id="NAI2551901", terminal_name="강릉", city_name="강원도",
                longitude=128.8788, latitude=37.7546, location_source="vworld_place",
                first_seen_at=now, last_seen_at=now))
            session.add(BusTerminalReference(source="data_go_kr_tago", service_type="express",
                terminal_id="NAEK200", terminal_name="강릉", city_name=None,
                first_seen_at=now, last_seen_at=now))
            await session.commit()

    asyncio.run(seed())
    located = client.get("/v1/transport/features/places", params={"kind": "bus_terminal"})
    assert located.status_code == 200
    assert located.json()["total"] == 1
    assert located.json()["items"][0]["provider_id"] == "NAI2551901"
    assert located.json()["items"][0]["location_source"] == "vworld_place"
    all_rows = client.get("/v1/transport/features/places", params={
        "kind": "bus_terminal", "include_unlocated": True, "query": "강릉"})
    assert all_rows.status_code == 200
    assert {row["provider_id"] for row in all_rows.json()["items"]} == {"NAI2551901", "NAEK200"}
    assert client.get("/v1/transport/features/places", params={
        "kind": "bus_terminal", "min_longitude": 128, "max_longitude": 129,
        "min_latitude": 37, "max_latitude": 38}).json()["total"] == 1
    terminals = client.get("/v1/transport/bus/terminals?service_type=intercity").json()["items"]
    assert terminals[0]["longitude"] == 128.8788


def test_kakao_port_position_is_labeled_as_facility_not_unverified(client):
    async def seed():
        now = now_utc()
        async with client.app.state.session_factory() as session:
            session.add(FerryPort(source="data_go_kr_maritime", port_id="SEA22010",
                port_name="대천", longitude=126.5, latitude=36.3,
                location_source="kakao_place", first_seen_at=now, last_seen_at=now))
            await session.commit()

    asyncio.run(seed())
    places = client.get("/v1/transport/features/places", params={"kind": "ferry_port"}).json()
    assert places["total"] == 1
    assert places["items"][0]["location_source"] == "kakao_place"
    assert places["items"][0]["subtitle"] == "지도 시설 위치 · 승선 장소 확인 필요"


def test_same_name_ferry_ports_keep_distinct_codes_and_timetables(client):
    today = to_seoul(now_utc()).date()

    async def seed():
        now = now_utc()
        async with client.app.state.session_factory() as session:
            for code, vessel in [("SEA10070", "첫째호"), ("SEA96540", "둘째호")]:
                session.add(FerryPort(source="data_go_kr_maritime", port_id=code,
                    port_name="육도", first_seen_at=now, last_seen_at=now))
                session.add(FerryTimetableSnapshot(source="data_go_kr_maritime",
                    departure_port_id=code, service_date=today, collected_at=now,
                    items_json=[{"vessel_name": vessel, "departure_port_name": "육도"}]))
            await session.commit()

    asyncio.run(seed())
    with patch("app.main.DataGoKrMaritimeClient", side_effect=AssertionError("외부 호출 금지")):
        places = client.get("/v1/transport/features/places", params={
            "kind": "ferry_port", "include_unlocated": True, "query": "육도"}).json()
        assert {row["provider_id"] for row in places["items"]} == {"SEA10070", "SEA96540"}
        for code, vessel in [("SEA10070", "첫째호"), ("SEA96540", "둘째호")]:
            for path, params in [
                ("/v1/transport/ports/timetables", {"port_ids": code}),
                (f"/v1/transport/ports/{code}/timetable", {}),
            ]:
                response = client.get(path, params=params)
                assert response.status_code == 200
                row = response.json()["items"][0] if "port_ids" in params else response.json()
                assert (row["port_id"], row["port_name"]) == (code, "육도")
                assert row["items"][0]["vessel_name"] == vessel
        assert client.get("/v1/transport/ports/timetables?port_ids=육도").status_code == 404


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
