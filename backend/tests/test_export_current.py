"""실제 service router의 고정 페이지·실패 보존·권한·TTL 회귀."""

import asyncio

import pytest
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

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


def test_snapshot_admission_race_retries_in_fresh_transaction(export_client, monkeypatch):
    from app.services import export_current
    c = export_client
    _enable(c)
    _run(c, lambda s: _seed(s, c.app.state.settings))
    original = export_current._freeze_traffic
    calls = []
    async def conflicting_first(session, scope, head):
        calls.append(True)
        if len(calls) == 1:
            raise export_current.SnapshotRace()
        return await original(session, scope, head)
    monkeypatch.setattr(export_current, "_freeze_traffic", conflicting_first)
    result = c.get(PATH, headers=HEADERS)
    assert result.status_code == 200, result.text
    assert len(calls) == 2


def test_repeated_snapshot_admission_race_is_bounded(export_client, monkeypatch):
    from app.services import export_current
    c = export_client
    _enable(c)
    _run(c, lambda s: _seed(s, c.app.state.settings))
    calls = []
    async def conflict(*args):
        calls.append(True)
        raise export_current.SnapshotRace()
    monkeypatch.setattr(export_current, "_freeze_traffic", conflict)
    assert c.get(PATH, headers=HEADERS).status_code == 503
    assert len(calls) == 2


def test_postgres_invisible_cache_conflict_does_not_rematerialize(export_client, monkeypatch):
    from app.services import export_current
    c = export_client
    if c.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL RR MVCC 충돌 회귀")
    _enable(c)
    _run(c, lambda s: _seed(s, c.app.state.settings))
    scope = highway_scope_key(c.app.state.settings, TRAFFIC_SOURCE)
    original = export_current.expire_snapshots
    async def race():
        paused, committed = asyncio.Event(), asyncio.Event()
        async with c.app.state.session_factory() as a, c.app.state.session_factory() as b:
            async def pause_b(session, **kwargs):
                if session is b:
                    paused.set()
                    await committed.wait()
                return await original(session, **kwargs)
            monkeypatch.setattr(export_current, "expire_snapshots", pause_b)
            async def old_reader():
                await export_current._snapshot_transaction(b)
                head = await b.get(HighwayTrafficCurrentState, (TRAFFIC_SOURCE, scope))
                try:
                    await export_current._freeze_traffic(b, scope, head)
                    pytest.fail("같은 generation을 재물질화했습니다")
                except DBAPIError as exc:
                    assert exc.orig.sqlstate == "40001"
                except export_current.SnapshotRace:
                    pass
                await b.rollback()
                await export_current._snapshot_transaction(b)
                head = await b.get(HighwayTrafficCurrentState, (TRAFFIC_SOURCE, scope))
                recovered = await export_current._freeze_traffic(b, scope, head)
                await b.commit()
                return recovered.id
            task = asyncio.create_task(old_reader())
            await asyncio.wait_for(paused.wait(), 5)
            await export_current._snapshot_transaction(a)
            head = await a.get(HighwayTrafficCurrentState, (TRAFFIC_SOURCE, scope))
            winner = await export_current._freeze_traffic(a, scope, head)
            winner_id = winner.id
            await a.commit()
            committed.set()
            assert await asyncio.wait_for(task, 10) == winner_id
        async with c.app.state.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(ServiceExportSnapshot)) == 1
            assert await session.scalar(select(func.count()).select_from(ServiceExportSnapshotItem)) == 3
    asyncio.run(race())


def test_postgres_concurrent_gc_skips_a_victim_another_freeze_is_deleting(export_client):
    """다른 종류의 첫 페이지 freeze가 같은 만료 victim을 고르면 행 잠금 2초 대기(55P03→503) 대신 건너뛴다."""
    from time import monotonic

    from app.services import export_current
    c = export_client
    if c.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL 행 잠금·lock_timeout 회귀")
    async def seed_expired(s):
        snapshot_id, past = str(uuid4()), now_utc() - timedelta(minutes=1)
        s.add(ServiceExportSnapshot(id=snapshot_id, kind="fixture-kind-v1", scope_key="fixture", generation="expired",
                                    source_collected_at=past, created_at=past - timedelta(minutes=15),
                                    expires_at=past, item_count=2, content_digest="fixture"))
        await s.flush()
        s.add_all([ServiceExportSnapshotItem(snapshot_id=snapshot_id, ordinal=i, payload={"i": i}) for i in (1, 2)])
    _run(c, seed_expired)
    async def race():
        async with c.app.state.session_factory() as a, c.app.state.session_factory() as b:
            await export_current._snapshot_transaction(a)
            assert await expire_snapshots(a) == 1  # A는 commit 전까지 victim과 항목의 행 잠금을 쥔다.
            await export_current._snapshot_transaction(b)
            started = monotonic()
            assert await asyncio.wait_for(expire_snapshots(b), 5) == 0
            assert monotonic() - started < 1
            await b.rollback()
            await a.commit()
        async with c.app.state.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(ServiceExportSnapshot)) == 0
            assert await session.scalar(select(func.count()).select_from(ServiceExportSnapshotItem)) == 0
    asyncio.run(race())


def test_snapshot_reused_at_epoch_end_still_serves_its_next_page(export_client, monkeypatch):
    """같은 epoch의 cache 재사용은 남은 수명 TTL 이상을 보장한다 — epoch 끝 재사용 직후 다음 페이지가 410이 아니다."""
    from datetime import UTC, datetime

    from app.services import export_current
    c = export_client
    _enable(c)
    _run(c, lambda s: _seed(s, c.app.state.settings))
    ttl = export_current.SNAPSHOT_TTL
    seconds = int(ttl.total_seconds())
    start = datetime.fromtimestamp((int(now_utc().timestamp()) // seconds + 1) * seconds, tz=UTC)
    end = start + ttl
    clock = {"now": start + timedelta(seconds=1)}
    monkeypatch.setattr(export_current, "now_utc", lambda: clock["now"])
    first = c.get(PATH, headers=HEADERS, params={"limit": 1})
    assert first.status_code == 200, first.text
    clock["now"] = end - timedelta(seconds=0.5)
    reused = c.get(PATH, headers=HEADERS, params={"limit": 1})
    assert reused.status_code == 200, reused.text
    assert reused.json()["snapshot_id"] == first.json()["snapshot_id"]
    assert datetime.fromisoformat(reused.json()["snapshot_expires_at"]) - clock["now"] >= ttl
    clock["now"] = end + timedelta(seconds=10)
    page = c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": reused.json()["next_cursor"]})
    assert page.status_code == 200, page.text
    assert page.json()["snapshot_id"] == first.json()["snapshot_id"]


def test_authoritative_zero_head_is_empty_snapshot_not_unready(export_client):
    c = export_client
    _enable(c)
    assert c.get(PATH, headers=HEADERS).status_code == 503
    _run(c, lambda s: _seed(s, c.app.state.settings, count=0))
    first = c.get(PATH, headers=HEADERS)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["total_count"] == 0 and body["items"] == [] and body["meta"]["item_count"] == 0
    assert body["has_more"] is False and body["next_cursor"] is None
    assert c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]}).status_code == 304
    async def expire(s):
        await s.execute(update(ServiceExportSnapshot).values(expires_at=now_utc() - timedelta(seconds=1)))
        await expire_snapshots(s)
    _run(c, expire)
    renewed = c.get(PATH, headers=HEADERS)
    assert renewed.status_code == 200 and renewed.json()["total_count"] == 0


def test_authoritative_three_to_zero_keeps_old_snapshot_and_allows_retirement(export_client):
    c = export_client
    _enable(c)
    _run(c, lambda s: _seed(s, c.app.state.settings))
    before = c.get(PATH, headers=HEADERS, params={"limit": 1}).json()
    async def confirmed_zero(s):
        await s.execute(update(HighwayTrafficCurrentState).values(generation="confirmed-empty", member_count=0))
    _run(c, confirmed_zero)
    empty = c.get(PATH, headers=HEADERS, params={"limit": 1})
    assert empty.status_code == 200 and empty.json()["total_count"] == 0 and empty.json()["items"] == []
    old = c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": before["next_cursor"]})
    assert old.status_code == 200 and old.json()["total_count"] == 3
    assert old.json()["snapshot_id"] == before["snapshot_id"]
