"""주소·수동 위치·특수 float와 동시 writer가 재사용 지문에서 누락되지 않는다."""

# ruff: noqa: F811

import math
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

import pytest
from kortravelcommon.address_providers import VworldKakaoAddressResolver
from kortravelcommon.reverse_address import AddressTarget, reverse_address_tables
from sqlalchemy import select, text, update

from app.core.time_utils import now_utc
from app.models import Base, BusTerminalReference, FerryPort, ParkingCurrent, RailStationReference, ReferenceExportState
from app.services import export_references
from app.services.rail_maritime_collection import MARITIME_SOURCE
from test_reference_export_reuse import _get, _prepare
from test_service_exports import HEADERS, _run, export_client  # noqa: F401


@pytest.mark.parametrize("kind", ["bus", "parking"])
def test_bus_and_parking_reuse_and_live_value_invalidation(export_client, monkeypatch, kind):
    c = export_client
    if c.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 입력 지문 검증")
    c.app.state.settings.transport_map_current_enabled = True
    c.app.state.settings.release_sha = "other-reference-test-v1"
    if kind == "bus":
        from test_bus_export import seed, PATH
        _run(c, seed)
    else:
        from test_parking_export import service, PATH
        collector = service(c)
        async def seed(s):
            assert (await collector.collect(s))["status"] == "success"
        _run(c, seed)
    first = c.get(PATH, headers=HEADERS)
    assert first.status_code == 200, first.text
    original = export_references.reference_payload_revision
    seen = []
    async def track(*args, **kwargs):
        value = await original(*args, **kwargs)
        seen.append(value)
        return value
    monkeypatch.setattr(export_references, "reference_payload_revision", track)
    repeated = c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["ETag"]})
    assert repeated.status_code == 304, repeated.text
    assert len(seen) == 1 and seen[0] is not None
    async def change(s):
        model = BusTerminalReference if kind == "bus" else ParkingCurrent
        await s.execute(update(model).values(**({"terminal_name": "새 터미널"} if kind == "bus" else {"name": "새 주차장"})))
    _run(c, change)
    changed = c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["ETag"]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["snapshot_id"] != first.json()["snapshot_id"]
    assert changed.json()["items"] != first.json()["items"]


@pytest.mark.parametrize("change", ["payload", "coordinate", "not_found", "failure_metadata"])
def test_address_changes_and_failure_metadata_have_distinct_effects(export_client, change):
    c = export_client
    _prepare(c)
    payload = {"provider": "vworld", "address": {"road_address": "원래 도로"}, "region": {"sido": "원래 시도"}}
    async def add(s):
        row = await s.scalar(select(RailStationReference).where(RailStationReference.identity_key == "rail-0"))
        target = AddressTarget(f"rail_station:{row.id}", row.longitude, row.latitude)
        entries, _ = reverse_address_tables(Base.metadata)
        now = now_utc()
        await s.execute(entries.insert().values(provider_id=VworldKakaoAddressResolver.provider_id,
            target_key=target.key, coordinate_key=target.coordinate_key, longitude=row.longitude, latitude=row.latitude,
            status="ok", failures=0, checked_at=now, resolved_at=now, payload=payload))
    _run(c, add)
    first = _get(c)
    assert first.status_code == 200, first.text
    assert first.json()["items"][0]["admin"]["sido_name"] == "원래 시도"
    async def mutate(s):
        entries, _ = reverse_address_tables(Base.metadata)
        if change == "payload":
            changed = deepcopy(payload)
            changed["region"]["sido"] = "변경 시도"
            values = {"payload": changed}
        elif change == "coordinate":
            values = {"coordinate_key": "different-coordinate"}
        elif change == "not_found":
            values = {"status": "not_found"}
        else:
            values = {"checked_at": now_utc() + timedelta(seconds=1), "failures": 1}
        await s.execute(entries.update().values(**values))
    _run(c, mutate)
    response = c.get("/v1/service/exports/rail-stations", params={"limit": 1},
                     headers={**HEADERS, "If-None-Match": first.headers["ETag"]})
    if change == "failure_metadata":
        assert response.status_code == 304, response.text
    else:
        assert response.status_code == 200, response.text
        assert response.json()["snapshot_id"] != first.json()["snapshot_id"]
        admin = response.json()["items"][0]["admin"]
        if change == "payload":
            assert admin["sido_name"] == "변경 시도"
        else:
            assert admin is None


def test_manual_revision_and_signed_zero_are_not_hidden_by_jsonb(export_client):
    c = export_client
    if c.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL float bit 지문 검증")
    c.app.state.settings.transport_map_current_enabled = True
    c.app.state.settings.release_sha = "ferry-revision-test-v1"
    async def seed(s):
        now = now_utc()
        port = FerryPort(source=MARITIME_SOURCE, port_id="001", port_name="항구", latitude=35.0,
                         longitude=-0.0, location_source="admin_manual", location_point_count=1,
                         first_seen_at=now, last_seen_at=now, raw_item_json={"_manual_location": {"revision": "1"}, "extra": "a"})
        s.add(port)
        await s.flush()
        s.add(ReferenceExportState(kind="ferry-port", scope_key="ports", generation=str(uuid4()), attempt_order=1,
                                  confirmed_at=now, last_attempt_at=now, member_ids=[port.id], proof={"complete": True}))
    _run(c, seed)
    path = "/v1/service/exports/ferry-ports"
    first = c.get(path, headers=HEADERS)
    assert first.status_code == 200, first.text
    async def stored_longitude(s):
        return await s.scalar(select(FerryPort.longitude))
    assert math.copysign(1.0, _run(c, stored_longitude)) == -1
    # 기존 snapshot의 JSONB 응답은 음수0을0으로 정규화한다. 원천 double의 변화는 감지한다.
    assert first.json()["items"][0]["longitude"] == 0
    async def unrelated(s):
        await s.execute(update(FerryPort).values(raw_item_json={"_manual_location": {"revision": "1"}, "extra": "b"}))
    _run(c, unrelated)
    assert c.get(path, headers={**HEADERS, "If-None-Match": first.headers["ETag"]}).status_code == 304
    async def manual(s):
        await s.execute(update(FerryPort).values(raw_item_json={"_manual_location": {"revision": "2"}}))
    _run(c, manual)
    second = c.get(path, headers=HEADERS)
    assert second.status_code == 200 and second.json()["items"][0]["manual_location_revision"] == "2"
    async def positive(s):
        await s.execute(update(FerryPort).values(longitude=0.0))
    _run(c, positive)
    third = c.get(path, headers=HEADERS)
    assert third.status_code == 200
    assert third.json()["snapshot_id"] != second.json()["snapshot_id"]
    assert third.headers["ETag"] != second.headers["ETag"]
    assert math.copysign(1.0, third.json()["items"][0]["longitude"]) == 1


def test_reader_rr_does_not_block_writer_or_mix_its_later_commit(export_client, monkeypatch):
    import asyncio
    c = export_client
    _prepare(c)
    first = _get(c)
    assert first.status_code == 200
    entered, release = Event(), Event()
    original = export_references.reference_payload_revision
    async def paused(*args, **kwargs):
        revision = await original(*args, **kwargs)
        entered.set()
        assert await asyncio.to_thread(release.wait, 15), "reader test gate timed out"
        return revision
    monkeypatch.setattr(export_references, "reference_payload_revision", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_get, c)
        try:
            assert entered.wait(15)
            async def mutate(s):
                await s.execute(text("SET LOCAL lock_timeout = '500ms'"))
                await s.execute(update(RailStationReference).where(RailStationReference.identity_key == "rail-0").values(station_name="다음 세대 역명"))
            _run(c, mutate)
        finally:
            release.set()
        old_view = future.result(timeout=15)
    assert old_view.status_code == 200 and old_view.json()["items"] == first.json()["items"]
    newest = _get(c)
    assert newest.status_code == 200 and newest.json()["items"][0]["name"] == "다음 세대 역명"
    assert newest.json()["snapshot_id"] != first.json()["snapshot_id"]
