"""실제 service router의 고정 페이지·실패 보존·권한·TTL 회귀."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select, update

from app.core.time_utils import now_utc
from app.models import (
    HighwayTrafficCurrent, HighwayTrafficCurrentState, ServiceExportSnapshot,
    ServiceExportSnapshotItem, TransportCollectionState,
)
from app.services.export_current import expire_snapshots
from app.services.transport_collection import TRAFFIC_SOURCE, highway_scope_key
from test_service_exports import HEADERS, _run, export_client  # noqa: F401

PATH = "/v1/service/exports/highway-traffic/current"


def _enable(client):
    # create_app은 동일 Settings 인스턴스를 보존한다.
    client.app.state.settings.transport_map_current_enabled = True


async def _seed(session, settings, *, count=3):
    scope = highway_scope_key(settings, TRAFFIC_SOURCE)
    now = now_utc()
    generation = str(uuid4())
    session.add(HighwayTrafficCurrentState(
        source=TRAFFIC_SOURCE, scope_key=scope, generation=generation,
        attempt_started_at=now, attempt_order=1, confirmed_at=now, member_count=count,
    ))
    session.add(TransportCollectionState(source=TRAFFIC_SOURCE, last_success_at=now, updated_at=now))
    for i in range(count):
        session.add(HighwayTrafficCurrent(
            source=TRAFFIC_SOURCE, scope_key=scope, identity_key=f"road-{i}", generation=generation,
            snapshot_order=i, snapshot_id=None, observed_at=now, collected_at=now,
            route_no="001", route_name="경부", conzone_id=str(i), conzone_name="서울",
            direction="up", speed=80.0 + i, free_flow_speed=100.0, congestion_level="smooth",
        ))


def test_unready_and_auth(export_client):
    c = export_client
    assert c.get(PATH).status_code == 404
    assert c.get(PATH, headers=HEADERS).status_code == 503
    _enable(c)
    assert c.get(PATH, headers=HEADERS).status_code == 503


def test_fixed_pages_survive_current_mutation_and_etag_health(export_client):
    c = export_client
    _enable(c)
    _run(c, lambda s: _seed(s, c.app.state.settings))
    first = c.get(PATH, headers=HEADERS, params={"limit": 1})
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["total_count"] == 3 and data["meta"]["source_status"] == "ok"
    assert first.headers["content-encoding"] == "gzip"
    assert c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]},
                 params={"limit": 1}).status_code == 304

    async def mutate(s):
        await s.execute(update(HighwayTrafficCurrent).values(speed=1.0, generation="new"))
        await s.execute(update(HighwayTrafficCurrentState).values(generation="new"))
        await s.execute(update(TransportCollectionState).values(last_error="provider timeout"))
    _run(c, mutate)
    page = c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": data["next_cursor"]})
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["speed"] == 81.0
    assert page.json()["meta"]["source_status"] == "stale"
    assert page.json()["snapshot_id"] == data["snapshot_id"]
    newest = c.get(PATH, headers=HEADERS, params={"limit": 1})
    assert newest.json()["items"][0]["speed"] == 1.0
    assert newest.json()["snapshot_id"] != data["snapshot_id"]
    assert newest.headers["etag"] != first.headers["etag"]


def test_cursor_expiry_tampering_and_limit(export_client):
    c = export_client
    _enable(c)
    _run(c, lambda s: _seed(s, c.app.state.settings))
    first = c.get(PATH, headers=HEADERS, params={"limit": 1}).json()
    cursor = first["next_cursor"]
    assert c.get(PATH, headers=HEADERS, params={"limit": 2, "cursor": cursor}).status_code == 422
    assert c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": cursor + "x"}).status_code == 422
    assert c.get(PATH, headers=HEADERS, params={"limit": 5001}).status_code == 422
    async def expire(s):
        await s.execute(update(ServiceExportSnapshot).values(expires_at=now_utc() - timedelta(seconds=1)))
    _run(c, expire)
    assert c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": cursor}).status_code == 410
    async def gc(s):
        assert await expire_snapshots(s) == 1
        assert (await s.scalars(select(ServiceExportSnapshotItem))).all() == []
    _run(c, gc)
    assert c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": cursor}).status_code == 410


def test_membership_mismatch_is_not_partial_success(export_client):
    c = export_client
    _enable(c)
    _run(c, lambda s: _seed(s, c.app.state.settings))
    async def corrupt(s):
        await s.execute(update(HighwayTrafficCurrentState).values(member_count=4))
    _run(c, corrupt)
    assert c.get(PATH, headers=HEADERS).status_code == 503
