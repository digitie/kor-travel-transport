"""본문 pin·유한 cursor·실제 bulk 저장·조회 밖 준비의 정합성."""
# ruff: noqa: F811
import hashlib
import json
from datetime import timedelta
from time import monotonic
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update

from app.core.time_utils import now_utc
from app.models import ReferenceExportArtifact as Artifact, ReferenceExportArtifactHead as Head, ReferenceExportArtifactItem as Item, ServiceExportSnapshot as Snapshot, ServiceExportSnapshotItem, RailStationReference
from app.services import export_current, export_references as refs
from app.services.reference_artifacts import _store_items, collect_unused_artifact
from app.services.reference_export_preparation import prepare_reference_exports
from test_reference_export_reuse import _prepare, _get
from test_rail_export import seed
from test_service_exports import _run, export_client  # noqa: F401


def test_long_idle_keeps_body_but_expires_only_old_cursor(export_client, monkeypatch):
    c = export_client;_prepare(c);moment = now_utc()
    monkeypatch.setattr(refs, "now_utc", lambda: moment)
    first = _get(c);assert first.status_code == 200, first.text
    old = first.json()
    async def identity(s):return (await s.get(Snapshot, old["snapshot_id"])).artifact_id
    artifact_id = _run(c, identity);assert artifact_id
    async def forbidden(*_args, **_kwargs):raise AssertionError("유휴 뒤 같은 본문을 다시 구성했습니다")
    monkeypatch.setattr(refs, "export_admin_addresses", forbidden)
    later = moment + timedelta(days=2)
    monkeypatch.setattr(refs, "now_utc", lambda: later)
    monkeypatch.setattr(export_current, "now_utc", lambda: later)
    renewed = _get(c);assert renewed.status_code == 200, renewed.text
    value = renewed.json()
    assert value["snapshot_id"] != old["snapshot_id"] and value["items"] == old["items"]
    assert value["meta"]["source_collected_at"] == old["meta"]["source_collected_at"]
    assert _get(c, cursor=old["next_cursor"]).status_code == 410
    assert _get(c, cursor=value["next_cursor"]).status_code == 200
    async def check(s):
        new = await s.get(Snapshot, value["snapshot_id"])
        assert new.artifact_id == artifact_id
        assert await s.scalar(select(func.count()).select_from(Artifact)) == 1
        assert await s.scalar(select(func.count()).select_from(Item)) == 2
        assert await s.scalar(select(func.count()).select_from(ServiceExportSnapshotItem)) == 0
    _run(c, check)


def test_old_cursor_pins_old_body_and_gc_keeps_current_without_handles(export_client, monkeypatch):
    c = export_client;_prepare(c);moment = now_utc()
    first = _get(c).json()
    async def change(s):await s.execute(update(RailStationReference).values(station_name="갱신 역"))
    _run(c, change)
    second = _get(c).json()
    assert _get(c, cursor=first["next_cursor"]).json()["items"][0]["name"] == "중앙"
    assert _get(c, cursor=second["next_cursor"]).json()["items"][0]["name"] == "갱신 역"
    async def protected(s):
        assert await collect_unused_artifact(s) == 0
        assert await s.scalar(select(func.count()).select_from(Artifact)) == 2
    _run(c, protected)
    monkeypatch.setattr(export_current, "now_utc", lambda: moment + timedelta(days=2))
    async def expire(s):
        assert await export_current.expire_snapshots(s, limit=2) == 2
        assert await collect_unused_artifact(s) == 1
        assert await collect_unused_artifact(s) == 0
        current = await s.scalar(select(Head))
        assert await s.get(Artifact, current.artifact_id) is not None
        assert await s.scalar(select(func.count()).select_from(Artifact)) == 1
    _run(c, expire)


def test_legacy_cursor_remains_readable_with_new_artifact_reader(export_client):
    c = export_client
    if c.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL의 가산 artifact 전환")
    c.app.state.settings.transport_map_current_enabled = True
    c.app.state.settings.release_sha = "unknown"
    _run(c, seed)
    old = _get(c).json()
    c.app.state.settings.release_sha = "artifact-policy-v2"
    new = _get(c).json()
    assert new["snapshot_id"] != old["snapshot_id"] and new["items"] == old["items"]
    assert _get(c, cursor=old["next_cursor"]).status_code == 200
    async def check(s):
        assert (await s.get(Snapshot, old["snapshot_id"])).artifact_id is None
        assert (await s.get(Snapshot, new["snapshot_id"])).artifact_id
        assert await s.scalar(select(func.count()).select_from(ServiceExportSnapshotItem)) == 2
    _run(c, check)


def test_publisher_prepares_first_http_without_source_rebuild(export_client, monkeypatch):
    c = export_client;_prepare(c)
    async def prepare(s):return await prepare_reference_exports(s, settings=c.app.state.settings)
    ready = _run(c, prepare)
    assert ready["status"] == "success" and ready["prepared"] == 1
    assert [v["kind"] for v in ready["kinds"] if v["status"] == "prepared"] == ["rail-stations-v1"]
    async def forbidden(*_args, **_kwargs):raise AssertionError("준비된 첫 HTTP에서 본문을 다시 구성했습니다")
    monkeypatch.setattr(refs, "export_admin_addresses", forbidden)
    assert _get(c).status_code == 200
    again = _run(c, prepare)
    assert again["prepared"] == 0 and again["reused"] == 1


def test_bulk_uses_single_json_bind_per_batch_and_preserves_values(export_client, monkeypatch):
    c = export_client;_prepare(c)
    values = [{"n": i, "한글": "익산 / ' 001", "price": 2000.35, "zero": -0.0, "missing": None} for i in range(402)]
    bodies = [json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() for v in values]
    artifact_id = str(uuid4());calls=[]
    async def store(s):
        s.add(Artifact(id=artifact_id, kind="bulk-test", scope_key="test", input_revision="a" * 64,
            created_at=now_utc(), source_collected_at=now_utc(), item_count=len(values), byte_count=sum(map(len, bodies)),
            content_digest=hashlib.sha256(b"\n".join(bodies) + b"\n").hexdigest()))
        await s.flush()
        def track(conn,cursor,statement,parameters,context,executemany):
            if statement.startswith("INSERT INTO reference_export_artifact_items"):
                calls.append({"executemany":executemany,"parameters":len(parameters)})
        event.listen(s.bind.sync_engine, "before_cursor_execute", track)
        try:
            with monkeypatch.context() as m:
                def forbidden(*_args, **_kwargs):raise AssertionError("bulk INSERT에서 JSON을 다시 loads했습니다")
                m.setattr(json, "loads", forbidden)
                await _store_items(s, artifact_id, bodies, monotonic())
        finally:event.remove(s.bind.sync_engine, "before_cursor_execute", track)
        rows = (await s.execute(select(Item.ordinal, Item.payload).where(Item.artifact_id==artifact_id).order_by(Item.ordinal))).all()
        assert [r.ordinal for r in rows] == list(range(1,403))
        assert [r.payload for r in rows] == values
    _run(c, store)
    assert len(calls) == 2 and all(not r["executemany"] and r["parameters"] < 10 for r in calls)


def test_reader_key_share_makes_gc_skip_an_artifact_before_repin(export_client, monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.services import reference_artifacts
    c = export_client;_prepare(c)
    first = _get(c).json()
    async def change(s):await s.execute(update(RailStationReference).values(station_name="다른 세대"))
    _run(c, change)
    _get(c)
    async def restore(s):
        old = await s.get(Snapshot, first["snapshot_id"])
        artifact_id = old.artifact_id
        await s.delete(old)
        await s.execute(update(RailStationReference).values(station_name="중앙"))
        return artifact_id
    old_artifact = _run(c, restore)
    entered, release = Event(), Event();original = reference_artifacts._pin_current
    async def paused(s, artifact):
        if artifact.id == old_artifact:
            entered.set()
            assert await asyncio.to_thread(release.wait, 20)
        return await original(s, artifact)
    monkeypatch.setattr(reference_artifacts, "_pin_current", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_get,c)
        try:
            assert entered.wait(20)
            async def gc(s):return await collect_unused_artifact(s)
            assert _run(c,gc) == 0
        finally:release.set()
        assert future.result(timeout=20).status_code == 200


def test_same_input_first_readers_publish_one_body(export_client, monkeypatch):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock
    c=export_client;_prepare(c);gate=Event();lock=Lock();calls=0
    moment=now_utc()
    monkeypatch.setattr(refs,"now_utc",lambda:moment)
    original=refs.reference_payload_revision
    async def paired(*args,**kwargs):
        nonlocal calls
        value=await original(*args,**kwargs)
        with lock:
            calls+=1
            if calls==2:gate.set()
        assert await asyncio.to_thread(gate.wait,20)
        return value
    monkeypatch.setattr(refs,"reference_payload_revision",paired)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _: _get(c),range(2)))
    assert all(r.status_code==200 for r in responses),[r.text for r in responses]
    assert responses[0].json()["snapshot_id"]==responses[1].json()["snapshot_id"]
    async def check(s):
        assert await s.scalar(select(func.count()).select_from(Artifact))==1
        assert await s.scalar(select(func.count()).select_from(Item))==2
    _run(c,check)


def test_additive_migration_preserves_legacy_snapshot_and_refuses_destructive_downgrade(test_settings):
    import asyncio
    from sqlalchemy import text
    from test_parking_coverage_migration import _engine, _step
    engine=_engine(test_settings)
    async def run():
        try:
            async with engine.begin() as connection:
                await connection.run_sync(lambda c:_step(c,"downgrade","0041_public_parking_lots"))
                await connection.execute(text("INSERT INTO service_export_snapshots (id,kind,scope_key,generation,source_collected_at,created_at,expires_at,item_count,content_digest) VALUES ('legacy-fixture','rail-stations-v1','scope','generation',now(),now(),now()+interval '20 minutes',1,:digest)"),{"digest":"a"*64})
                await connection.execute(text("INSERT INTO service_export_snapshot_items (snapshot_id,ordinal,payload) VALUES ('legacy-fixture',1,'{\"name\":\"전주\"}'::jsonb)"))
                before=(await connection.execute(text("SELECT id,generation,source_collected_at,item_count,content_digest FROM service_export_snapshots"))).all()
            async with engine.begin() as connection:
                await connection.run_sync(lambda c:_step(c,"upgrade","0042_reference_export_artifacts"))
                assert (await connection.execute(text("SELECT id,generation,source_collected_at,item_count,content_digest FROM service_export_snapshots"))).all()==before
                assert await connection.scalar(text("SELECT artifact_id IS NULL FROM service_export_snapshots"))
                assert await connection.scalar(text("SELECT payload->>'name' FROM service_export_snapshot_items"))=="전주"
                await connection.execute(text("INSERT INTO reference_export_artifacts VALUES ('artifact','rail-stations-v1','scope',:revision,now(),now(),1,2,:digest)"),{"revision":"b"*64,"digest":"c"*64})
            with pytest.raises(RuntimeError,match="downgrade"):
                async with engine.begin() as connection:
                    await connection.run_sync(lambda c:_step(c,"downgrade","0041_public_parking_lots"))
        finally:
            async with engine.begin() as connection:
                await connection.run_sync(lambda c:_step(c,"upgrade","0042_reference_export_artifacts"))
            await engine.dispose()
    asyncio.run(run())
