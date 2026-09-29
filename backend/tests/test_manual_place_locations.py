"""공식 항구·버스터미널에 대한 관리자 수동 좌표 보정 계약."""

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient
from datagokr import TagoBusTerminal
from kric import DomesticFerryPort
from sqlalchemy import select

from app.core.time_utils import now_utc
from app.main import create_app
from app.models import BusTerminalReference, FerryPort
from app.services.bus_collection import BusReferenceCollectionService
from app.services.rail_maritime_collection import RailMaritimeCollectionService


def test_manual_place_location_requires_token_and_existing_matching_reference(test_settings):
    app = create_app(test_settings.model_copy(update={"transport_admin_write_token": "s" * 40}))
    with TestClient(app) as client:
        assert client.get("/v1/transport/admin/place-locations/capability").status_code == 404
        assert client.get("/v1/transport/admin/place-locations/capability",
            headers={"x-transport-admin-token": "s" * 40}).json() == {"contract": "coordinate-write-v1"}
        now = now_utc()

        async def seed():
            async with app.state.session_factory() as session:
                session.add(FerryPort(source="data_go_kr_maritime", port_id="P1", port_name="시험항",
                    first_seen_at=now, last_seen_at=now, raw_item_json={"official": True}))
                session.add(FerryPort(source="data_go_kr_maritime", port_id="P2", port_name="안내항",
                    latitude=35.0, longitude=128.0, location_source="data_go_kr_port_guideline",
                    first_seen_at=now, last_seen_at=now, raw_item_json={"official": True}))
                session.add(FerryPort(source="data_go_kr_maritime", port_id="P3", port_name="범위밖항",
                    latitude=31.9, longitude=127.0, location_source="legacy_geocode",
                    first_seen_at=now, last_seen_at=now, raw_item_json={"official": True}))
                session.add(BusTerminalReference(source="data_go_kr_tago", service_type="express",
                    terminal_id="B1", terminal_name="시험터미널", first_seen_at=now,
                    last_seen_at=now, raw_item_json={"official": True}))
                await session.commit()
                return (await session.scalar(select(FerryPort.id).where(FerryPort.port_id == "P1")),
                    await session.scalar(select(BusTerminalReference.id).where(BusTerminalReference.terminal_id == "B1")),
                    await session.scalar(select(FerryPort.id).where(FerryPort.port_id == "P2")),
                    await session.scalar(select(FerryPort.id).where(FerryPort.port_id == "P3")))

        port_id, bus_id, guideline_id, outside_id = asyncio.run(seed())
        path = "/v1/transport/admin/place-locations"
        payload = {"kind": "ferry_port", "id": port_id, "source": "data_go_kr_maritime",
            "provider_id": "P1", "expected_name": "시험항", "expected_city_name": None,
            "expected_latitude": None, "expected_longitude": None, "expected_manual_revision": None,
            "expected_location_source": None, "latitude": 34.1, "longitude": 127.2,
            "note": "공식 항구 주소와 시설점 대조"}
        assert client.post(path, json=payload).status_code == 404
        assert client.post(path, json=payload, headers={"x-transport-admin-token": "wrong"}).status_code == 404
        headers = {"x-transport-admin-token": "s" * 40}
        assert client.post(path, json={**payload, "id": 999999}, headers=headers).status_code == 404
        assert client.post(path, json={**payload, "provider_id": "other"}, headers=headers).status_code == 409
        assert client.post(path, json={**payload, "latitude": 45}, headers=headers).status_code == 422
        assert client.post(path, json={**payload, "note": "     "}, headers=headers).status_code == 422
        response = client.post(path, json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["location_source"] == "admin_manual"
        assert response.json()["latitude"] == 34.1
        assert client.post(path, json=payload, headers=headers).status_code == 409
        first_revision = response.json()["manual_location_revision"]
        repeated = {**payload, "expected_latitude": 34.1, "expected_longitude": 127.2,
            "expected_location_source": "admin_manual", "expected_manual_revision": first_revision,
            "note": "새 공식 지도 근거 재검증"}
        newer = client.post(path, json=repeated, headers=headers)
        assert newer.status_code == 200
        assert newer.json()["manual_location_revision"] != first_revision
        assert client.post(path, json=repeated, headers=headers).status_code == 409
        bus = {**payload, "kind": "bus_terminal", "id": bus_id, "source": "data_go_kr_tago",
            "provider_id": "B1", "expected_name": "시험터미널"}
        assert client.post(path, json=bus, headers=headers).status_code == 200
        assert client.get("/v1/transport/features/places", params={"kind": "ferry_port"}).json()["total"] == 2
        assert client.get("/v1/transport/features/places", params={"kind": "bus_terminal"}).json()["total"] == 1
        guideline = {**payload, "id": guideline_id, "provider_id": "P2", "expected_name": "안내항",
            "expected_location_source": "data_go_kr_port_guideline"}
        assert client.post(path, json=guideline, headers=headers).status_code == 200
        outside = {**payload, "id": outside_id, "provider_id": "P3", "expected_name": "범위밖항",
            "expected_latitude": 31.9, "expected_longitude": 127.0, "expected_location_source": "legacy_geocode"}
        assert client.post(path, json=outside, headers=headers).status_code == 200
        assert client.get("/v1/transport/features/places", params={"kind": "ferry_port"}).json()["total"] == 3

        async def verify():
            async with app.state.session_factory() as session:
                port = await session.get(FerryPort, port_id)
                terminal = await session.get(BusTerminalReference, bus_id)
                assert port.location_point_count == 1
                assert port.raw_item_json["_manual_location"]["note"] == repeated["note"]
                assert terminal.raw_item_json["official"] is True
                assert terminal.location_source == "admin_manual"
                corrected = await session.get(FerryPort, guideline_id)
                assert corrected.raw_item_json["_manual_location"]["previous"]["location_source"] == "data_go_kr_port_guideline"

                await RailMaritimeCollectionService(app.state.settings)._upsert_port(session,
                    DomesticFerryPort(port_id="P1", port_name="시험항", raw={"official": "updated"}),
                    now_utc(), SimpleNamespace(latitude=35.0, longitude=128.0, raw={"official": "komsa"}),
                    location_verified=True)
                await BusReferenceCollectionService(app.state.settings)._upsert_terminal(session, "express",
                    TagoBusTerminal(terminalId="B1", terminalNm="시험터미널"), now_utc())
                await session.commit()
                assert (port.latitude, port.longitude, port.location_source) == (34.1, 127.2, "admin_manual")
                assert (terminal.latitude, terminal.longitude, terminal.location_source) == (34.1, 127.2, "admin_manual")
                assert port.raw_item_json["_manual_location"]["note"] == repeated["note"]
                assert terminal.raw_item_json["_manual_location"]["note"] == payload["note"]
                await RailMaritimeCollectionService(app.state.settings)._upsert_port(session,
                    DomesticFerryPort(port_id="P1", port_name="새시험항", raw={}), now_utc(), None)
                await BusReferenceCollectionService(app.state.settings)._upsert_terminal(session, "express",
                    TagoBusTerminal(terminalId="B1", terminalNm="새시험터미널", cityName="시험시"), now_utc())
                await session.commit()
                assert (port.latitude, port.longitude, port.location_source) == (None, None, None)
                assert (terminal.latitude, terminal.longitude, terminal.location_source) == (None, None, None)

        asyncio.run(verify())
        assert client.post(path, json={**payload, "expected_latitude": None,
            "expected_longitude": None, "expected_location_source": None}, headers=headers).status_code == 409


def test_manual_endpoint_disabled_without_separate_token(client):
    assert client.get("/v1/transport/admin/place-locations/capability").status_code == 404
    assert client.post("/v1/transport/admin/place-locations", json={"kind": "ferry_port", "id": 1,
        "source": "data_go_kr_maritime", "provider_id": "P1", "expected_latitude": None,
        "expected_longitude": None, "expected_location_source": None, "expected_manual_revision": None, "expected_name": "시험항",
        "expected_city_name": None, "latitude": 34, "longitude": 127,
        "note": "공식 항구 위치 확인"}).status_code == 404
