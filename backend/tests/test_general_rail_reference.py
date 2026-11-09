"""일반철도 전국 source의 완결 게시·기존 KRIC/고정 페이지 보존."""
from dataclasses import replace
from datetime import timedelta

from kric import KricDirectoryRow, KricGeneralStation

import pytest
from app.core.time_utils import now_utc
from app.models import CollectionRun, RailStationReference, ReferenceExportState
from app.services.general_rail_reference import (
    KRIC_GENERAL_SOURCE,
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


def station(code, name, *, located=False):
    row = KricDirectoryRow(1, name, "전라권", "공식 주소", "일반철도", code)
    return KricGeneralStation("korail:" + code, name, code, "001" if located else None,
        ("전라권",), ("일반철도",), "공식 주소", 35.1 if located else None,
        127.1 if located else None, (row,))


class Train:
    def __init__(self, pool):
        self.pool = pool
        self.calls = []
        self.failure = None
        self.rows = [station("0001", "전주", located=True), station("0002", "순천")]
        self.incomplete = False
        self.revoke = None
        self.guard = None

    async def get_general_stations(self):
        assert self.pool.checkedout() == 0
        self.guard()
        self.calls.append("general")
        if self.revoke: self.revoke()
        self.guard()
        self.calls.append("ktx")
        if self.failure: raise self.failure
        if self.incomplete: raise ValueError("provider incomplete directory")
        return tuple(self.rows)


def service(c):
    settings = c.app.state.settings
    settings.transport_map_current_enabled = settings.rail_reference_collection_enabled = True
    settings.data_go_kr_service_key = None
    train = Train(PoolCounter(c.app.state.engine))
    class Client:
        def __init__(self, **kwargs): train.guard = kwargs["before_request"]
        async def __aenter__(self): return train
        async def __aexit__(self, *_): pass
    return GeneralRailReferenceCollectionService(settings, client_factory=Client), train


def test_union_preserves_kric_zeroes_nulls_and_existing_cursor(export_client):
    c = export_client
    collector, train = service(c)
    _run(c, seed)
    old = c.get(PATH, headers=HEADERS, params={"limit": 1}).json()
    result = _run(c, collector.collect)
    assert result["status"] == "success" and result["station_count"] == 2
    assert train.calls == ["general", "ktx"]
    async def check(s):
        kric = await s.get(ReferenceExportState, ("rail-station", "nationwide"))
        general = await s.get(ReferenceExportState, ("rail-station", "kric-general"))
        assert len(kric.member_ids) == len(general.member_ids) == 2
        return general.generation
    _run(c, check)
    response = c.get(PATH, headers=HEADERS, params={"limit": 10})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_count"] == 4
    assert data["items"][0]["station_code"] == "001"
    rows = [r for r in data["items"] if r["source"] == KRIC_GENERAL_SOURCE]
    assert [(r["name"], r["station_number"]) for r in rows] == [("전주", "001"), ("순천", None)]
    assert rows[0]["latitude"] == 35.1 and rows[0]["longitude"] == 127.1
    assert rows[1]["latitude"] is None and rows[1]["longitude"] is None
    assert all(r["station_code"] is None and not r["code_active"] for r in rows)
    assert c.get(PATH, headers={**HEADERS, "If-None-Match": response.headers["etag"]}, params={"limit": 10}).status_code == 304
    previous = c.get(PATH, headers=HEADERS, params={"limit": 1, "cursor": old["next_cursor"]}).json()
    assert previous["snapshot_id"] == old["snapshot_id"] and previous["total_count"] == 2
    assert _run(c, collector.collect)["status"] == "skipped" and len(train.calls) == 2


@pytest.mark.parametrize("problem", ["partial", "empty", "duplicate", "conflicting_name", "provider_error"])
def test_incomplete_nationwide_walk_never_changes_published_rows(export_client, problem):
    c = export_client
    collector, train = service(c)
    _run(c, seed)
    _run(c, collector.collect)
    async def make_due(s):
        head = await s.get(ReferenceExportState, ("rail-station", "kric-general"))
        before = head.generation
        # 원본 row 시각도 같이 과거로 맞춰 stale 입력의 membership 계약을 유지한다.
        when = now_utc() - timedelta(days=3)
        head.confirmed_at = when
        await s.execute(update(RailStationReference).where(RailStationReference.source == KRIC_GENERAL_SOURCE).values(last_seen_at=when))
        return before
    before = _run(c, make_due)
    if problem == "partial": train.incomplete = True
    elif problem == "empty": train.rows = []
    elif problem == "duplicate": train.rows *= 2
    elif problem == "conflicting_name": train.rows[1] = replace(train.rows[0], station_name="다른역")
    else: train.failure = ValueError("provider URL and secret must not be stored")
    async def fail(s):
        with pytest.raises(ValueError): await collector.collect(s)
        head = await s.get(ReferenceExportState, ("rail-station", "kric-general"))
        assert head.generation == before and head.last_error == "ValueError"
        rows = list((await s.scalars(select(RailStationReference).where(RailStationReference.source == KRIC_GENERAL_SOURCE))).all())
        assert [r.station_name for r in sorted(rows, key=lambda r: r.id)] == ["전주", "순천"]
        run = await s.scalar(select(CollectionRun).where(CollectionRun.trigger == TRIGGER).order_by(CollectionRun.id.desc()).limit(1))
        assert run.status == "failed" and run.error_message == "ValueError"
    _run(c, fail)
    result = c.get(PATH, headers=HEADERS).json()
    assert result["total_count"] == 4 and result["meta"]["source_status"] == "stale"


def test_same_name_different_official_ids_survive(export_client):
    c = export_client
    collector, train = service(c)
    train.rows = [station("0001", "중앙"), station("0002", "중앙")]
    _run(c, seed)
    assert _run(c, collector.collect)["station_count"] == 2
    assert c.get(PATH, headers=HEADERS).json()["total_count"] == 4
    async def check(s):
        row = await s.scalar(select(RailStationReference).where(RailStationReference.identity_key == "kric_general_portal:korail:0001"))
        assert row.raw_item_json["station_sequence"] == "0001"
    _run(c, check)


def test_general_head_cannot_claim_a_kric_member(export_client):
    c = export_client
    collector, _ = service(c)
    _run(c, seed)
    _run(c, collector.collect)
    async def corrupt(s):
        kric = await s.get(ReferenceExportState, ("rail-station", "nationwide"))
        general = await s.get(ReferenceExportState, ("rail-station", "kric-general"))
        general.member_ids = [kric.member_ids[0]]
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


def test_revoked_owner_never_starts_the_next_request_or_marks_a_source_failure(export_client, monkeypatch):
    from app.dagster.recovery import (
        OWNER_LEASE,
        CollectionLeaseLost,
        collection_owner,
        owned_session_factory,
    )
    c = export_client
    collector, train = service(c)
    def revoke(): OWNER_LEASE.get().revoked = True
    train.revoke = revoke
    async def cannot_mark(*args, **kwargs):
        pytest.fail("회수된 owner로 source 실패를 기록하면 안 된다")
    monkeypatch.setattr("app.services.general_rail_reference.mark_reference_failure", cannot_mark)
    async def owned(_):
        with collection_owner("fixture-owner"):
            async with owned_session_factory(c.app.state.engine, "fixture-owner")() as s:
                with pytest.raises(CollectionLeaseLost): await collector.collect(s)
                assert await s.get(ReferenceExportState, ("rail-station", "kric-general")) is None
    _run(c, owned)
    assert train.calls == ["general"]
