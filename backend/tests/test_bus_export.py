"""고속/시외 source 완결 membership과 실제 고정 reference route."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from datagokr import OpenApiPage, TagoBusTerminal
from sqlalchemy import event, select, update

from app.core.time_utils import now_utc
from app.models import BusTerminalReference, ReferenceExportState
from app.services.bus_collection import BusReferenceCollectionService, TAGO_BUS_SOURCE
from test_service_exports import HEADERS, _run, export_client  # noqa: F401

PATH = "/v1/service/exports/bus-terminals"


class Pages:
    def __init__(self, pages):
        self.pages = pages

    async def iter_pages(self, **kwargs):
        for page in self.pages:
            yield page


@pytest.mark.parametrize("pages", [
    [],
    [OpenApiPage(items=[TagoBusTerminal(terminalId="01", terminalNm="역")])],
    [OpenApiPage(total_count=2, page_no=1, num_of_rows=100,
                 items=[TagoBusTerminal(terminalId="01", terminalNm="역")])],
    [OpenApiPage(total_count=1, page_no=2, num_of_rows=100,
                 items=[TagoBusTerminal(terminalId="01", terminalNm="역")])],
])
def test_unconfirmed_page_never_gets_success_receipt(test_settings, pages):
    test_settings.transport_map_current_enabled = True
    service = BusReferenceCollectionService(test_settings)
    with pytest.raises(ValueError):
        asyncio.run(service._fetch_terminals(SimpleNamespace(terminals=Pages(pages))))


def test_complete_page_receipt_and_unique_identity(test_settings):
    test_settings.transport_map_current_enabled = True
    service = BusReferenceCollectionService(test_settings)
    page = OpenApiPage(total_count=1, page_no=1, num_of_rows=100,
                       items=[TagoBusTerminal(terminalId="001", terminalNm="시험")])
    items, proof = asyncio.run(service._fetch_terminals(SimpleNamespace(terminals=Pages([page]))))
    assert proof["complete"] and proof["item_count"] == 1
    assert service._terminal_identity(items)[0][0] == "001"
    with pytest.raises(ValueError):
        service._terminal_identity(items + items)
    with pytest.raises(ValueError):
        service._terminal_identity(())


async def seed(session):
    now = now_utc()
    for scope in ("express", "intercity"):
        row = BusTerminalReference(source=TAGO_BUS_SOURCE, service_type=scope, terminal_id="001",
                                   terminal_name=scope, city_name="서울", first_seen_at=now, last_seen_at=now)
        session.add(row)
        await session.flush()
        session.add(ReferenceExportState(kind="bus-terminal", scope_key=scope,
                    generation=str(uuid4()), attempt_order=1, confirmed_at=now, member_ids=[row.id],
                    proof={"complete": True, "item_count": 1}, last_attempt_at=now))


def test_reference_snapshot_updates_manual_data_without_source_recollection(export_client):
    c = export_client
    c.app.state.settings.transport_map_current_enabled = True
    assert c.get(PATH).status_code == 404
    assert c.get(PATH, headers=HEADERS).status_code == 503
    _run(c, seed)
    first = c.get(PATH, headers=HEADERS, params={"limit": 1})
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["total_count"] == 2 and data["items"][0]["terminal_id"] == "001"
    assert c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]},
                 params={"limit": 1}).status_code == 304
    async def manual(s):
        await s.execute(update(BusTerminalReference).where(BusTerminalReference.service_type == "intercity")
                        .values(latitude=37, longitude=127, location_source="admin_manual",
                                raw_item_json={"_manual_location": {"revision": "manual-1"}}))
        await s.execute(update(ReferenceExportState).values(last_error="provider failure"))
    _run(c, manual)
    old = c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": data["next_cursor"]})
    assert old.status_code == 200, old.text
    assert old.json()["items"][0]["name"] == "intercity"
    assert old.json()["meta"]["source_status"] == "stale"
    new = c.get(PATH, headers=HEADERS, params={"limit": 2})
    assert new.status_code == 200, new.text
    assert new.json()["items"][1]["latitude"] == 37
    assert new.json()["items"][1]["manual_location_revision"] == "manual-1"
    assert new.json()["snapshot_id"] != data["snapshot_id"]


class PoolCounter:
    def __init__(self, engine):
        self.count = 0
        self.expected = 1 if engine.dialect.name == "postgresql" else 0
        event.listen(engine.sync_engine, "checkout", lambda *args: self.change(1))
        event.listen(engine.sync_engine, "checkin", lambda *args: self.change(-1))

    def change(self, delta):
        self.count += delta

    def checkedout(self):
        return self.count


class CompleteProvider:
    def __init__(self, scope, pool, *, empty=False):
        self.scope, self.pool, self.empty = scope, pool, empty
        self.terminals = self
        self.calls = 0

    async def iter_pages(self, **kwargs):
        assert self.pool.checkedout() == self.pool.expected, "fetch 동안 저장 session 연결을 보유했습니다"
        self.calls += 1
        items = [] if self.empty else [TagoBusTerminal(terminalId="001", terminalNm=self.scope, cityName="서울")]
        yield OpenApiPage(total_count=len(items), page_no=1, num_of_rows=100, items=items)

    async def city_list(self):
        return SimpleNamespace(items=[])

    async def class_list(self):
        return SimpleNamespace(items=[])


class CompleteClient:
    def __init__(self, pool, *, empty=False):
        self.express_bus = CompleteProvider("express", pool, empty=empty)
        self.intercity_bus = CompleteProvider("intercity", pool)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def test_source_complete_and_empty_failure_keeps_success(export_client):
    from app.models import CollectionRun
    c = export_client
    settings = c.app.state.settings
    settings.transport_map_current_enabled = True
    settings.bus_reference_collection_enabled = True
    settings.data_go_kr_service_key = "fixture"
    engine = c.app.state.engine
    pool = PoolCounter(engine)
    providers = []
    def client_factory(**kwargs):
        value = CompleteClient(pool, empty=len(providers) > 0)
        providers.append(value)
        return value
    service = BusReferenceCollectionService(settings, client_factory=client_factory)
    async def collect(s):
        result = await service.collect(s, trigger="first")
        assert result["status"] == "success"
    _run(c, collect)
    before = c.get(PATH, headers=HEADERS).json()
    async def fail(s):
        with pytest.raises(ValueError):
            await service.collect(s, trigger="second")
        runs = list((await s.scalars(select(CollectionRun).where(CollectionRun.trigger == "second"))).all())
        assert len(runs) == 1 and runs[0].status == "failed"
        assert len((await s.scalars(select(BusTerminalReference))).all()) == 2
    _run(c, fail)
    assert providers[1].express_bus.calls == 2
    after = c.get(PATH, headers=HEADERS).json()
    assert after["snapshot_id"] == before["snapshot_id"]
    assert after["items"] == before["items"]
    assert after["meta"]["source_status"] == "stale"


def test_late_store_failure_rolls_back_refs_and_heads_without_expired_run_access(export_client):
    from app.models import CollectionRun
    c = export_client
    settings = c.app.state.settings
    settings.transport_map_current_enabled = True
    settings.bus_reference_collection_enabled = True
    settings.data_go_kr_service_key = "fixture"
    pool = PoolCounter(c.app.state.engine)
    factory = lambda **kwargs: CompleteClient(pool)
    service = BusReferenceCollectionService(settings, client_factory=factory)
    async def first(s):
        await service.collect(s, trigger="first")
    _run(c, first)
    async def snapshot(s):
        return [(h.scope_key, h.generation) for h in (await s.scalars(select(ReferenceExportState))).all()]
    before = _run(c, snapshot)
    original = service._upsert_terminal
    async def fail_second(session, scope, item, collected):
        if scope == "intercity":
            raise RuntimeError("second store failure")
        await original(session, scope, item, collected)
    service._upsert_terminal = fail_second
    async def second(s):
        with pytest.raises(RuntimeError, match="second store failure"):
            await service.collect(s, trigger="second")
        assert [(h.scope_key, h.generation) for h in (await s.scalars(select(ReferenceExportState))).all()] == before
        run = await s.scalar(select(CollectionRun).where(CollectionRun.trigger == "second"))
        assert run.status == "failed" and run.error_message == "RuntimeError"
    _run(c, second)


def test_unapproved_off_mode_source_row_cannot_reuse_old_success(export_client):
    from datetime import timedelta
    c = export_client
    c.app.state.settings.transport_map_current_enabled = True
    _run(c, seed)
    first = c.get(PATH, headers=HEADERS)
    assert first.status_code == 200
    async def off_mode_source(s):
        await s.execute(update(BusTerminalReference).values(
            terminal_name="미승인 원천 변경", city_name="새 도시", last_seen_at=now_utc() + timedelta(seconds=1),
        ))
    _run(c, off_mode_source)
    assert c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]}).status_code == 503


def test_postgres_old_failure_cannot_mark_new_success_stale(export_client):
    from app.models import CollectionRun
    from app.services.reference_exports import mark_reference_failure
    c = export_client
    if c.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL 조건부 UPDATE interleave 회귀")
    _run(c, seed)
    async def race():
        paused, committed = asyncio.Event(), asyncio.Event()
        async with c.app.state.session_factory() as old, c.app.state.session_factory() as newer:
            original_execute = old.execute
            async def pause_old_update(statement, *args, **kwargs):
                if getattr(statement, "is_update", False):
                    paused.set()
                    await committed.wait()
                return await original_execute(statement, *args, **kwargs)
            old.execute = pause_old_update
            async def fail_old():
                await mark_reference_failure(old, kind="bus-terminal", run_id=1, error="OldFailure")
                await old.commit()
            task = asyncio.create_task(fail_old())
            await asyncio.wait_for(paused.wait(), 5)
            await newer.execute(update(ReferenceExportState).values(
                attempt_order=2, generation="new-success", last_error=None,
            ))
            await newer.commit()
            committed.set()
            await asyncio.wait_for(task, 10)
        async with c.app.state.session_factory() as session:
            states = list((await session.scalars(select(ReferenceExportState))).all())
            assert all(h.attempt_order == 2 and h.generation == "new-success" and h.last_error is None for h in states)
    asyncio.run(race())
