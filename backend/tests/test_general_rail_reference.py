"""일반철도 전국 source의 완결 게시·기존 KRIC/고정 페이지 보존."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from app.core.time_utils import now_utc
from app.models import CollectionRun, RailStationReference, ReferenceExportState
from app.services.general_rail_reference import (
    TAGO_TRAIN_SOURCE,
    TRIGGER,
    GeneralRailReferenceCollectionService,
)
from sqlalchemy import select, update
from test_bus_export import PoolCounter
from test_rail_export import PATH, seed
from test_service_exports import HEADERS, _run
from test_service_exports import (
    export_client as export_client,  # noqa: PLC0414  # pytest fixture 재노출
)


class Train:
    def __init__(self, pool):
        self.pool = pool
        self.calls = []
        self.failure = None
        self.rows = {"35": [("NAT000001", "전주")], "36": [("NAT000002", "순천")]}
        self.incomplete = False

    async def city_list(self):
        assert self.pool.checkedout() == 0
        self.calls.append("cities")
        return SimpleNamespace(total_count=len(self.rows), items=[
            SimpleNamespace(city_code=code, city_name="지역" + code) for code in self.rows])

    async def station_list(self, *, city_code, num_of_rows):
        assert self.pool.checkedout() == 0 and num_of_rows == 1000
        self.calls.append(city_code)
        if self.failure and city_code == max(self.rows):
            raise self.failure
        items = [SimpleNamespace(station_id=code, station_name=name, raw={"nodeid": code, "nodename": name})
                 for code, name in self.rows[city_code]]
        return SimpleNamespace(total_count=len(items) + int(self.incomplete), items=items)


def service(c):
    settings = c.app.state.settings
    settings.transport_map_current_enabled = settings.rail_reference_collection_enabled = True
    settings.data_go_kr_service_key = "fixture-not-a-key"
    train = Train(PoolCounter(c.app.state.engine))
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["max_rps"] == 1
            self.train = train
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
    return GeneralRailReferenceCollectionService(settings, client_factory=Client), train


def test_union_preserves_kric_zeroes_nulls_and_existing_cursor(export_client):
    c = export_client
    collector, train = service(c)
    _run(c, seed)
    old = c.get(PATH, headers=HEADERS, params={"limit": 1}).json()
    result = _run(c, collector.collect)
    assert result["status"] == "success" and result["station_count"] == result["city_count"] == 2
    assert train.calls == ["cities", "35", "36"]
    async def check(s):
        kric = await s.get(ReferenceExportState, ("rail-station", "nationwide"))
        tago = await s.get(ReferenceExportState, ("rail-station", "tago"))
        assert len(kric.member_ids) == len(tago.member_ids) == 2
        return tago.generation
    _run(c, check)
    response = c.get(PATH, headers=HEADERS, params={"limit": 10})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_count"] == 4
    assert data["items"][0]["station_code"] == "001"
    rows = [r for r in data["items"] if r["source"] == TAGO_TRAIN_SOURCE]
    assert [(r["name"], r["station_number"]) for r in rows] == [("전주", "NAT000001"), ("순천", "NAT000002")]
    assert all(r["latitude"] is None and r["longitude"] is None and r["station_code"] is None
               and not r["code_active"] for r in rows)
    assert c.get(PATH, headers={**HEADERS, "If-None-Match": response.headers["etag"]}, params={"limit": 10}).status_code == 304
    previous = c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": old["next_cursor"]}).json()
    assert previous["snapshot_id"] == old["snapshot_id"] and previous["total_count"] == 2
    assert _run(c, collector.collect)["status"] == "skipped" and len(train.calls) == 3


@pytest.mark.parametrize("problem", ["partial", "empty", "duplicate", "conflicting_name", "provider_error"])
def test_incomplete_nationwide_walk_never_changes_published_rows(export_client, problem):
    c = export_client
    collector, train = service(c)
    _run(c, seed)
    _run(c, collector.collect)
    async def make_due(s):
        head = await s.get(ReferenceExportState, ("rail-station", "tago"))
        before = head.generation
        # 원본 row 시각도 같이 과거로 맞춰 stale 입력의 membership 계약을 유지한다.
        when = now_utc() - timedelta(days=3)
        head.confirmed_at = when
        await s.execute(update(RailStationReference).where(RailStationReference.source == TAGO_TRAIN_SOURCE).values(last_seen_at=when))
        return before
    before = _run(c, make_due)
    if problem == "partial": train.incomplete = True
    elif problem == "empty": train.rows = {"35": [], "36": []}
    elif problem == "duplicate": train.rows["35"] *= 2
    elif problem == "conflicting_name": train.rows["36"] = [("NAT000001", "다른역")]
    else: train.failure = ValueError("provider URL and secret must not be stored")
    async def fail(s):
        with pytest.raises(ValueError): await collector.collect(s)
        head = await s.get(ReferenceExportState, ("rail-station", "tago"))
        assert head.generation == before and head.last_error == "ValueError"
        rows = list((await s.scalars(select(RailStationReference).where(RailStationReference.source == TAGO_TRAIN_SOURCE))).all())
        assert [r.station_name for r in sorted(rows, key=lambda r: r.id)] == ["전주", "순천"]
        run = await s.scalar(select(CollectionRun).where(CollectionRun.trigger == TRIGGER).order_by(CollectionRun.id.desc()).limit(1))
        assert run.status == "failed" and run.error_message == "ValueError"
    _run(c, fail)
    result = c.get(PATH, headers=HEADERS).json()
    assert result["total_count"] == 4 and result["meta"]["source_status"] == "stale"


def test_cross_city_same_id_deduplicates_but_same_name_different_ids_survive(export_client):
    c = export_client
    collector, train = service(c)
    train.rows = {"35": [("NAT000001", "중앙")], "36": [("NAT000001", "중앙"), ("NAT000002", "중앙")]}
    _run(c, seed)
    assert _run(c, collector.collect)["station_count"] == 2
    response = c.get(PATH, headers=HEADERS).json()
    assert response["total_count"] == 4
    async def check(s):
        row = await s.scalar(select(RailStationReference).where(RailStationReference.identity_key == "tago_train:NAT000001"))
        assert len(row.raw_item_json["cities"]) == 2
    _run(c, check)


def test_tago_head_cannot_claim_a_kric_member(export_client):
    c = export_client
    collector, _ = service(c)
    _run(c, seed)
    _run(c, collector.collect)
    async def corrupt(s):
        kric = await s.get(ReferenceExportState, ("rail-station", "nationwide"))
        tago = await s.get(ReferenceExportState, ("rail-station", "tago"))
        tago.member_ids = [kric.member_ids[0]]
    _run(c, corrupt)
    assert c.get(PATH, headers=HEADERS).status_code == 503


@pytest.mark.parametrize("failed", [False, True])
def test_native_owned_session_commits_its_terminal_status(export_client, failed):
    from app.dagster.recovery import owned_session_factory
    c = export_client
    collector, train = service(c)
    if failed: train.failure = ValueError("synthetic provider error")
    async def owned(_):
        async with owned_session_factory(c.app.state.engine, "fixture-owner")() as s:
            if failed:
                with pytest.raises(ValueError, match="synthetic"): await collector.collect(s)
            else:
                assert (await collector.collect(s))["status"] == "success"
            run = await s.scalar(select(CollectionRun).where(CollectionRun.trigger == TRIGGER))
            assert run.status == ("failed" if failed else "success")
            assert run.orchestrator_run_id == "fixture-owner"
            assert run.error_message == ("ValueError" if failed else None)
    _run(c, owned)


def test_revoked_owner_never_starts_the_next_city_or_marks_a_source_failure(export_client, monkeypatch):
    from app.dagster.recovery import (
        OWNER_LEASE,
        CollectionLeaseLost,
        collection_owner,
        owned_session_factory,
    )
    c = export_client
    collector, train = service(c)
    station_list = train.station_list
    async def revoke(**kwargs):
        result = await station_list(**kwargs)
        OWNER_LEASE.get().revoked = True
        return result
    train.station_list = revoke
    async def cannot_mark(*args, **kwargs):
        pytest.fail("회수된 owner로 source 실패를 기록하면 안 된다")
    monkeypatch.setattr("app.services.general_rail_reference.mark_reference_failure", cannot_mark)
    async def owned(_):
        with collection_owner("fixture-owner"):
            async with owned_session_factory(c.app.state.engine, "fixture-owner")() as s:
                with pytest.raises(CollectionLeaseLost): await collector.collect(s)
                assert await s.get(ReferenceExportState, ("rail-station", "tago")) is None
    _run(c, owned)
    assert train.calls == ["cities", "35"]
