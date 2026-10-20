import asyncio
from datetime import UTC, datetime

from app.core.config import Settings
from app.main import create_app
from app.models import KricStationCode, RailStationReference
from fastapi.testclient import TestClient

ADMIN_TOKEN = "m" * 40
ADMIN_HEADERS = {"x-transport-admin-token": ADMIN_TOKEN}


def reference(identity: str, number: str, name: str, *, line: str = "1호선"):
    now = datetime.now(UTC)
    return RailStationReference(source="kric_public_file", identity_key=identity,
        rail_operator_name="서울교통공사", operating_line_name=line, station_number=number,
        station_name=name, first_seen_at=now, last_seen_at=now)


def seed(client: TestClient) -> None:
    async def insert():
        now = datetime.now(UTC)
        async with client.app.state.session_factory() as session:
            exact_place = reference("rail|line-1|exact", "001", "서울역")
            manual_place = reference("rail|line-2|manual", "999", "임시 환승역", line="지원선")
            session.add_all([exact_place, manual_place])
            await session.flush()
            session.add_all([
                KricStationCode(operator_code="OP", line_code="L1", station_code="001",
                    operator_name="서울교통공사", line_name="1호선", station_name="서울역",
                    rail_station_id=exact_place.id, active=True, last_seen_at=now),
                KricStationCode(operator_code="OP", line_code="L2", station_code="002",
                    operator_name="서울교통공사", line_name="2호선", station_name="누락역",
                    active=True, last_seen_at=now),
            ])
            await session.commit()
    asyncio.run(insert())


def test_admin_mapping_api_lists_catalog_saves_manual_links_and_rejects_stale_updates(test_settings):
    settings: Settings = test_settings.model_copy(update={"transport_admin_write_token": ADMIN_TOKEN})
    with TestClient(create_app(settings)) as client:
        seed(client)
        path = "/v1/transport/admin/rail-station-mappings"
        assert client.get(path).status_code == 404
        response = client.get(path, headers=ADMIN_HEADERS)
        assert response.status_code == 200
        initial = response.json()
        assert initial["station_count"] == 2
        assert initial["automatic_mapped_count"] == 1
        assert initial["unmatched_count"] == 1
        assert len(initial["stations"]) == 2
        assert initial["stations"][0]["station_name"] == "서울역"

        async def add_updated_reference():
            async with client.app.state.session_factory() as session:
                session.add(reference("rail|line-1|renamed", "001", "서울역(개명)"))
                await session.commit()
        asyncio.run(add_updated_reference())
        stale_target = [{"operator_code": "OP", "line_code": "L2", "station_code": "002",
            "rail_station_identity_key": "rail|line-1|exact", "note": "이전 기준정보"}]
        stale_place_catalog = client.post(path, headers=ADMIN_HEADERS,
            json={"expected_revision": initial["revision"], "mappings": stale_target})
        assert stale_place_catalog.status_code == 409
        initial = client.get(path, headers=ADMIN_HEADERS).json()

        manual = [{"operator_code": "OP", "line_code": "L2", "station_code": "002",
            "rail_station_identity_key": "rail|line-2|manual", "note": "노선 코드와 운영기관 자료 확인"}]
        saved = client.post(path, headers=ADMIN_HEADERS, json={"expected_revision": initial["revision"], "mappings": manual})
        assert saved.status_code == 200, saved.text
        updated = saved.json()
        assert updated["manual_mapped_count"] == 1
        assert updated["mapped_count"] == 2
        linked = next(item for item in updated["stations"] if item["station_code"] == "002")
        assert linked["match_method"] == "manual"
        assert linked["rail_station_identity_key"] == "rail|line-2|manual"

        stale = client.post(path, headers=ADMIN_HEADERS, json={"expected_revision": initial["revision"], "mappings": []})
        assert stale.status_code == 409
        bad_target = client.post(path, headers=ADMIN_HEADERS, json={"expected_revision": updated["revision"],
            "mappings": [{**manual[0], "rail_station_identity_key": "rail|not-found"}]})
        assert bad_target.status_code == 422

        cleared = client.post(path, headers=ADMIN_HEADERS, json={"expected_revision": updated["revision"], "mappings": []})
        assert cleared.status_code == 200
        assert cleared.json()["manual_mapped_count"] == 0
        assert cleared.json()["automatic_mapped_count"] == 1
        assert cleared.json()["unmatched_count"] == 1
