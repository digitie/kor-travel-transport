"""공항 주차장 source별 완결 receipt와 작은 typed current의 API 회귀."""

# ruff: noqa: F811

import json
from dataclasses import replace
from datetime import timedelta

from sqlalchemy import func, select, update

from app.core.time_utils import now_utc
from app.models import CollectionRun, ParkingCurrent, ParkingSnapshot, ReferenceExportState
from app.services.collection import CollectionService, FixturePublicDataClient
from app.services.parking_exports import KIND, parking_scope
from test_bus_export import PoolCounter
from test_service_exports import HEADERS, _run, export_client  # noqa: F401

PATH = "/v1/service/exports/parking/current"


class Fixture(FixturePublicDataClient):
    empty_kac = False
    missing_proof = False
    calls = 0
    pool = None
    subset = None

    def __init__(self):
        self.moment = now_utc() + timedelta(hours=9)

    async def fetch_kac_parking(self):
        self.calls += 1
        if self.pool:
            # PG advisory lease connection 하나는 owner context의 종료까지 유지한다.
            assert self.pool.checkedout() <= 1
        response = await super().fetch_kac_parking()
        rows = json.loads(response.body_text)
        now = self.moment
        for row in rows:
            row["parkingGetdate"] = now.strftime("%Y-%m-%d")
            row["parkingGettime"] = now.strftime("%H:%M:%S")
        if self.subset is not None:
            rows = rows[:self.subset]
        if self.empty_kac:
            rows = []
        return replace(response, body_text=json.dumps(rows),
                       completion=None if self.missing_proof else {"complete": True, "item_count": len(rows)})

    async def fetch_incheon_parking(self):
        response = await super().fetch_incheon_parking()
        rows = json.loads(response.body_text)
        now = self.moment
        for row in rows:
            row["datetm"] = now.strftime("%Y-%m-%d %H:%M")
        return replace(response, body_text=json.dumps(rows))


def service(c, client=None):
    settings = c.app.state.settings
    settings.transport_map_current_enabled = True
    settings.enable_fee_collection = False
    settings.enable_incheon_fee_collection = False
    return CollectionService(settings, client=client or Fixture())


def test_parking_current_replay_and_frozen_pagination(export_client):
    c = export_client
    client = Fixture()
    collector = service(c, client)
    assert c.get(PATH).status_code == 404
    assert c.get(PATH, headers=HEADERS).status_code == 503
    async def collect(s):
        result = await collector.collect(s)
        assert result["status"] == "success", result
        return await s.scalar(select(func.count()).select_from(ParkingSnapshot))
    count = _run(c, collect)
    assert count >= 12
    first = c.get(PATH, headers=HEADERS, params={"limit": 3})
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["total_count"] == 12
    assert data["meta"]["source_status"] == "ok"
    assert first.headers["content-encoding"] == "gzip"
    assert c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]}, params={"limit": 3}).status_code == 304
    assert all(item["location_source"] == "airport_anchor" for item in data["items"])
    async def update_current(s):
        await s.execute(update(ParkingCurrent).values(available_spaces=7))
    _run(c, update_current)
    items = list(data["items"])
    cursor = data["next_cursor"]
    while cursor:
        page = c.get(PATH, headers=HEADERS, params={"limit": 3, "cursor": cursor})
        assert page.status_code == 200, page.text
        items.extend(page.json()["items"])
        cursor = page.json()["next_cursor"]
    assert len(items) == 12 and len({row["natural_key"] for row in items}) == 12
    assert all(row["available_spaces"] != 7 for row in items)
    assert c.get(PATH, headers=HEADERS).json()["items"][0]["available_spaces"] == 7
    assert c.get(PATH, headers=HEADERS, params={"limit": 5001}).status_code == 422
    assert c.get(PATH, headers=HEADERS, params={"limit": 2, "cursor": data["next_cursor"]}).status_code == 422
    # 같은 timestamp raw를 replay해도 current와 성공 membership은 계속 존재한다.
    assert _run(c, collect) == count
    assert c.get(PATH, headers=HEADERS).status_code == 200


def test_empty_source_retry_preserves_other_success_and_stale_head(export_client):
    c = export_client
    client = Fixture()
    collector = service(c, client)
    _run(c, lambda s: collector.collect(s))
    async def before(s):
        head = await s.get(ReferenceExportState, (KIND, parking_scope(c.app.state.settings, "kac_parking")))
        return head.generation
    generation = _run(c, before)
    client.empty_kac = True
    client.pool = PoolCounter(c.app.state.engine)
    result = _run(c, lambda s: collector.collect(s))
    assert result["status"] == "partial_success"
    assert client.calls == 3
    assert _run(c, before) == generation
    page = c.get(PATH, headers=HEADERS)
    assert page.status_code == 200, page.text
    assert page.json()["total_count"] == 12 and page.json()["meta"]["source_status"] == "stale"
    async def native(s):
        run = await s.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
        return run.status
    assert _run(c, native) == "partial_success"


def test_unverified_raw_list_cannot_publish_parking_current(export_client):
    c = export_client
    client = Fixture()
    client.missing_proof = True
    collector = service(c, client)
    result = _run(c, lambda s: collector.collect(s))
    assert result["status"] == "partial_success" and client.calls == 2
    assert c.get(PATH, headers=HEADERS).status_code == 503


def test_rapid_shrink_reconfirmed_still_preserves_success_membership(export_client):
    c = export_client
    client = Fixture()
    collector = service(c, client)
    _run(c, lambda s: collector.collect(s))
    client.subset = 2
    assert _run(c, lambda s: collector.collect(s))["status"] == "partial_success"
    assert client.calls == 3
    page = c.get(PATH, headers=HEADERS)
    assert page.status_code == 200 and page.json()["total_count"] == 12
    assert page.json()["meta"]["source_status"] == "stale"


def test_late_history_failure_rolls_back_pointer_and_success_head(export_client):
    import pytest
    c = export_client
    client = Fixture()
    collector = service(c, client)
    _run(c, lambda s: collector.collect(s))
    async def generation(s):
        head = await s.get(ReferenceExportState, (KIND, parking_scope(c.app.state.settings, "kac_parking")))
        return head.generation
    before = _run(c, generation)
    original = collector._store_observations
    async def fail_late(s, run_id, rows, **kwargs):
        if rows[0].source == "incheon_parking":
            raise RuntimeError("fixture late source store failure")
        return await original(s, run_id, rows, **kwargs)
    collector._store_observations = fail_late
    with pytest.raises(RuntimeError):
        _run(c, lambda s: collector.collect(s))
    assert _run(c, generation) == before
    assert c.get(PATH, headers=HEADERS).json()["total_count"] == 12
