"""항구 source 목록과 부차 좌표 성공을 분리하고 고정 참조를 제공한다."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from kric import DomesticFerryPort
from sqlalchemy import select, update

from app.core.time_utils import now_utc
from app.models import CollectionRun, FerryPort, ReferenceExportState
from app.services.rail_maritime_collection import MARITIME_SOURCE, RailMaritimeCollectionService
from test_rail_maritime_collection import _MaritimeClient
from test_service_exports import HEADERS, _run, export_client  # noqa: F401

PATH = "/v1/service/exports/ferry-ports"


async def seed(s):
    now = now_utc()
    ids = []
    for i, source in enumerate(("admin_manual", "data_go_kr_port_guideline")):
        row = FerryPort(source=MARITIME_SOURCE, port_id=f"P{i:03}", port_name=f"시험항-{i}",
                        latitude=37, longitude=127, location_source=source, location_point_count=1,
                        first_seen_at=now, last_seen_at=now)
        s.add(row)
        await s.flush()
        ids.append(row.id)
    s.add(ReferenceExportState(kind="ferry-port", scope_key="ports", generation=str(uuid4()),
                              attempt_order=1, confirmed_at=now, member_ids=ids,
                              proof={"complete": True, "item_count": 2}, last_attempt_at=now))


def test_port_projection_blocks_guideline_and_keeps_pages_fixed(export_client):
    c = export_client
    c.app.state.settings.transport_map_current_enabled = True
    assert c.get(PATH).status_code == 404
    assert c.get(PATH, headers=HEADERS).status_code == 503
    _run(c, seed)
    first = c.get(PATH, headers=HEADERS, params={"limit": 1})
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["items"][0]["port_id"] == "P000"
    assert c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]},
                 params={"limit": 1}).status_code == 304
    old = c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": data["next_cursor"]})
    assert old.status_code == 200
    item = old.json()["items"][0]
    assert item["latitude"] is None and item["longitude"] is None and item["admin"] is None
    assert item["location_point_count"] == 0
    async def manual(s):
        await s.execute(update(FerryPort).where(FerryPort.port_id == "P001").values(
            latitude=36, longitude=128, location_source="admin_manual",
            raw_item_json={"_manual_location": {"revision": "manual-2"}},
        ))
        await s.execute(update(ReferenceExportState).values(last_error="fixture failure"))
    _run(c, manual)
    old_again = c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": data["next_cursor"]})
    assert old_again.json()["items"][0]["latitude"] is None
    assert old_again.json()["meta"]["source_status"] == "stale"
    newest = c.get(PATH, headers=HEADERS, params={"limit": 2})
    assert newest.status_code == 200, newest.text
    assert newest.json()["items"][1]["latitude"] == 36
    assert newest.json()["items"][1]["manual_location_revision"] == "manual-2"
    assert newest.json()["snapshot_id"] != data["snapshot_id"]


def test_unapproved_port_source_change_and_cross_kind_cursor_rejected(export_client):
    c = export_client
    c.app.state.settings.transport_map_current_enabled = True
    _run(c, seed)
    page = c.get(PATH, headers=HEADERS, params={"limit": 1}).json()
    assert c.get(PATH, headers=HEADERS, params={"limit": 2, "cursor": page["next_cursor"]}).status_code == 422
    async def off_mode(s):
        await s.execute(update(FerryPort).values(port_name="미승인변경", last_seen_at=now_utc() + timedelta(seconds=1)))
    _run(c, off_mode)
    assert c.get(PATH, headers=HEADERS).status_code == 503


class EmptyPorts(_MaritimeClient):
    calls = 0
    async def iter_ports(self, **kwargs):
        self.calls += 1
        if False:
            yield None


def test_empty_port_retry_preserves_native_success_head(export_client):
    c = export_client
    settings = c.app.state.settings
    settings.transport_map_current_enabled = True
    settings.maritime_reference_collection_enabled = True
    settings.port_guideline_collection_enabled = False
    settings.data_go_kr_service_key = "fixture"
    current = [_MaritimeClient()]
    service = RailMaritimeCollectionService(settings, maritime_client_factory=lambda *args, **kwargs: current[0])
    async def first(s):
        result = await service.collect_maritime_reference(s)
        assert result["status"] == "success"
        state = await s.get(ReferenceExportState, ("ferry-port", "ports"))
        return state.generation, state.confirmed_at
    generation, clock = _run(c, first)
    empty = EmptyPorts()
    current[0] = empty
    async def second(s):
        with pytest.raises(ValueError):
            await service.collect_maritime_reference(s)
        state = await s.get(ReferenceExportState, ("ferry-port", "ports"))
        assert state.generation == generation and state.confirmed_at == clock and state.last_error == "ValueError"
        run = await s.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
        assert run.status == "failed"
    _run(c, second)
    assert empty.calls == 2
    response = c.get(PATH, headers=HEADERS)
    assert response.status_code == 200 and response.json()["meta"]["source_status"] == "stale"


class IncheonPorts(_MaritimeClient):
    async def iter_ports(self, **kwargs):
        yield DomesticFerryPort(port_id="SEA10100", port_name="인천", raw={})


def test_coordinate_deferral_does_not_erase_core_port_success(export_client):
    c = export_client
    settings = c.app.state.settings
    settings.transport_map_current_enabled = True
    settings.maritime_reference_collection_enabled = True
    settings.port_guideline_collection_enabled = False
    settings.data_go_kr_service_key = "fixture"
    service = RailMaritimeCollectionService(settings, maritime_client_factory=lambda *args, **kwargs: IncheonPorts())
    async def deferred(*args):
        return None, False
    service._port_call_location = deferred
    async def collect(s):
        result = await service.collect_maritime_reference(s)
        assert result["status"] == "partial_success"
        head = await s.get(ReferenceExportState, ("ferry-port", "ports"))
        assert head.proof["complete"] and head.proof["coordinate_deferred"] == 1
    _run(c, collect)
    response = c.get(PATH, headers=HEADERS)
    assert response.status_code == 200 and response.json()["items"][0]["port_id"] == "SEA10100"
    assert response.json()["items"][0]["latitude"] is None


def test_shrinking_port_list_stays_unconfirmed_without_authoritative_total(export_client):
    c = export_client
    settings = c.app.state.settings
    settings.transport_map_current_enabled = True
    settings.maritime_reference_collection_enabled = True
    settings.port_guideline_collection_enabled = False
    settings.data_go_kr_service_key = "fixture"
    async def large(s):
        now = now_utc()
        ids = []
        for i in range(10):
            port = FerryPort(source=MARITIME_SOURCE, port_id=f"old-{i}", port_name=f"기존항-{i}", first_seen_at=now, last_seen_at=now)
            s.add(port)
            await s.flush()
            ids.append(port.id)
        s.add(ReferenceExportState(kind="ferry-port", scope_key="ports", generation="old-full",
                                  attempt_order=1, confirmed_at=now, member_ids=ids,
                                  proof={"complete": True}, last_attempt_at=now))
    _run(c, large)
    provider = _MaritimeClient()
    service = RailMaritimeCollectionService(settings, maritime_client_factory=lambda *args, **kwargs: provider)
    async def collect(s):
        with pytest.raises(ValueError, match="total receipt"):
            await service.collect_maritime_reference(s)
        head = await s.get(ReferenceExportState, ("ferry-port", "ports"))
        assert head.generation == "old-full" and len(head.member_ids) == 10
        assert len((await s.scalars(select(FerryPort))).all()) == 10
    _run(c, collect)


def test_late_companion_store_failure_rolls_back_port_membership(export_client):
    c = export_client
    settings = c.app.state.settings
    settings.transport_map_current_enabled = True
    settings.maritime_reference_collection_enabled = True
    settings.port_guideline_collection_enabled = False
    settings.data_go_kr_service_key = "fixture"
    _run(c, seed)
    service = RailMaritimeCollectionService(settings, maritime_client_factory=lambda *args, **kwargs: _MaritimeClient())
    async def fail(*args):
        raise RuntimeError("terminal store failed")
    service._upsert_terminal = fail
    async def collect(s):
        with pytest.raises(RuntimeError, match="terminal store failed"):
            await service.collect_maritime_reference(s)
        rows = list((await s.scalars(select(FerryPort).order_by(FerryPort.id))).all())
        assert [row.port_name for row in rows] == ["시험항-0", "시험항-1"]
        head = await s.get(ReferenceExportState, ("ferry-port", "ports"))
        assert len(head.member_ids) == 2 and head.last_error == "RuntimeError"
        run = await s.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
        assert run.status == "failed"
    _run(c, collect)
