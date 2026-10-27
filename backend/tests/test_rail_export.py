"""역 위치파일·active 코드·수동 FK를 동일 read snapshot에서 제공한다."""

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.core.time_utils import now_utc
from app.models import CollectionRun, KricStationCode, KricStationMappingRegistry, RailStationReference, ReferenceExportState
from app.services.rail_maritime_collection import KRIC_FILE_SOURCE, RailMaritimeCollectionService
from test_bus_export import PoolCounter
from test_rail_maritime_collection import _station
from test_service_exports import HEADERS, _run, export_client  # noqa: F401

PATH = "/v1/service/exports/rail-stations"


async def seed(s):
    now = now_utc()
    ids = []
    for i in range(2):
        row = RailStationReference(source=KRIC_FILE_SOURCE, identity_key=f"rail-{i}",
                                   rail_operator_name=f"운영사-{i}", operating_line_name=f"노선-{i}",
                                   station_name="중앙", station_number=f"00{i}",
                                   longitude=127.1 if i == 0 else 0, latitude=37.5 if i == 0 else 0,
                                   first_seen_at=now, last_seen_at=now)
        s.add(row)
        await s.flush()
        ids.append(row.id)
    s.add(ReferenceExportState(kind="rail-station", scope_key="nationwide", generation=str(uuid4()),
                              attempt_order=1, confirmed_at=now, member_ids=ids,
                              proof={"complete": True}, last_attempt_at=now))
    s.add(KricStationCode(operator_code="00", line_code="01", station_code="001", operator_name="다른 표기",
                          line_name="다른 노선 표기", station_name="중앙역", rail_station_id=ids[0], active=True, last_seen_at=now))
    s.add(KricStationMappingRegistry(id=1, catalog_json=[], catalog_sha256="a" * 64,
                                   automatic_mappings_json=[], manual_mappings_json=[{
                                       "operator_code": "00", "line_code": "01", "station_code": "001",
                                       "rail_station_identity_key": "rail-0"}], updated_at=now))


def test_manual_persisted_link_preserves_code_zeroes_and_frozen_pages(export_client):
    c = export_client
    c.app.state.settings.transport_map_current_enabled = True
    assert c.get(PATH).status_code == 404
    assert c.get(PATH, headers=HEADERS).status_code == 503
    _run(c, seed)
    first = c.get(PATH, headers=HEADERS, params={"limit": 1})
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["items"][0]["station_code"] == "001"
    assert data["items"][0]["operator_code"] == "00" and data["items"][0]["mapping_method"] == "manual"
    assert c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]}, params={"limit": 1}).status_code == 304
    async def remap(s):
        target = await s.scalar(select(RailStationReference).where(RailStationReference.identity_key == "rail-1"))
        await s.execute(update(KricStationCode).values(rail_station_id=target.id))
        await s.execute(update(KricStationMappingRegistry).values(manual_mappings_json=[{
            "operator_code": "00", "line_code": "01", "station_code": "001", "rail_station_identity_key": "rail-1"}]))
    _run(c, remap)
    old = c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": data["next_cursor"]})
    assert old.status_code == 200, old.text
    assert old.json()["items"][0]["station_code"] is None and old.json()["items"][0]["latitude"] is None
    newest = c.get(PATH, headers=HEADERS, params={"limit": 2})
    assert newest.status_code == 200, newest.text
    assert newest.json()["items"][0]["station_code"] is None
    assert newest.json()["items"][1]["station_code"] == "001"
    assert newest.json()["snapshot_id"] != data["snapshot_id"]


def test_inactive_code_is_not_exported_and_registry_mismatch_fails_closed(export_client):
    c = export_client
    c.app.state.settings.transport_map_current_enabled = True
    _run(c, seed)
    async def inconsistent(s):
        await s.execute(update(KricStationMappingRegistry).values(manual_mappings_json=[{
            "operator_code": "00", "line_code": "01", "station_code": "001", "rail_station_identity_key": "rail-1"}]))
    _run(c, inconsistent)
    assert c.get(PATH, headers=HEADERS).status_code == 503
    async def inactive(s):
        await s.execute(update(KricStationCode).values(active=False))
    _run(c, inactive)
    result = c.get(PATH, headers=HEADERS)
    assert result.status_code == 200, result.text
    assert all(not row["code_active"] and row["station_code"] is None for row in result.json()["items"])


def test_empty_file_retry_retains_success_and_fetch_has_no_db_connection(export_client):
    c = export_client
    settings = c.app.state.settings
    settings.transport_map_current_enabled = True
    settings.rail_reference_collection_enabled = True
    pool = PoolCounter(c.app.state.engine)
    calls = []
    values = [(_station(),)]
    async def fetch():
        assert pool.checkedout() == 0
        calls.append(True)
        return values[0]
    service = RailMaritimeCollectionService(settings, rail_fetcher=fetch)
    async def first(s):
        assert (await service.collect_rail_reference(s))["status"] == "success"
        head = await s.get(ReferenceExportState, ("rail-station", "nationwide"))
        return head.generation
    before = _run(c, first)
    async def due(s):
        await s.execute(update(CollectionRun).values(finished_at=now_utc() - timedelta(days=3)))
    _run(c, due)
    values[0] = ()
    async def failed(s):
        with pytest.raises(ValueError):
            await service.collect_rail_reference(s)
        head = await s.get(ReferenceExportState, ("rail-station", "nationwide"))
        assert head.generation == before and head.last_error == "ValueError"
        run = await s.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
        assert run.status == "failed"
    _run(c, failed)
    assert len(calls) == 3
    response = c.get(PATH, headers=HEADERS)
    assert response.status_code == 200 and response.json()["meta"]["source_status"] == "stale"


@pytest.mark.parametrize(("flag", "head", "expected"), [
    (True, False, "success"), (False, False, "skipped"), (True, True, "skipped"),
])
def test_flag_on_without_a_head_bootstraps_despite_a_recent_success(export_client, flag, head, expected):
    """플래그를 켠 직후 최근(플래그 OFF) 성공 때문에 48시간 동안 head 없이 503이 되지 않는다."""
    c = export_client
    settings = c.app.state.settings
    settings.rail_reference_collection_enabled = True
    calls = []
    async def fetch():
        calls.append(True)
        return (_station(),)
    service = RailMaritimeCollectionService(settings, rail_fetcher=fetch)
    settings.transport_map_current_enabled = head  # 첫 성공이 head를 만들지 정한다.
    async def first(s):
        assert (await service.collect_rail_reference(s))["status"] == "success"
    _run(c, first)
    settings.transport_map_current_enabled = flag
    async def second(s):
        status = (await service.collect_rail_reference(s))["status"]
        return status, await s.get(ReferenceExportState, ("rail-station", "nationwide")) is not None
    status, has_head = _run(c, second)
    assert status == expected
    assert len(calls) == (2 if expected == "success" else 1)
    assert has_head is (head or expected == "success")


def test_duplicate_file_identity_never_gets_a_success_head(export_client):
    c = export_client
    settings = c.app.state.settings
    settings.transport_map_current_enabled = True
    settings.rail_reference_collection_enabled = True
    async def fetch():
        return (_station(), _station())
    service = RailMaritimeCollectionService(settings, rail_fetcher=fetch)
    async def collect(s):
        with pytest.raises(ValueError):
            await service.collect_rail_reference(s)
        assert await s.get(ReferenceExportState, ("rail-station", "nationwide")) is None
    _run(c, collect)
    assert c.get(PATH, headers=HEADERS).status_code == 503
