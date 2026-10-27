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
    bad_source = None
    bad_kind = None
    timestamp_variant = None
    kac_row_variant = None
    last_kac_body = None

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
        if self.bad_source == "kac_parking":
            rows[0]["parkingIstay" if self.bad_kind == "count" else "parkingGetdate"] = "upstream error"
        # 기존 이력 parser는 견디지만 Map current 엄격 검증은 거절하는 원천 행.
        if self.kac_row_variant == "zero_capacity":
            rows[0]["parkingFullSpace"] = "0"
        elif self.kac_row_variant == "unmapped_airport":
            rows[0]["aprKor"], rows[0]["aprEng"] = "미매핑공항", "UNMAPPED AIRPORT"
        if self.subset is not None:
            rows = rows[:self.subset]
        if self.empty_kac:
            rows = []
        self.last_kac_body = json.dumps(rows)
        return replace(response, body_text=self.last_kac_body,
                       completion=None if self.missing_proof else {"complete": True, "item_count": len(rows)})

    async def fetch_incheon_parking(self):
        response = await super().fetch_incheon_parking()
        rows = json.loads(response.body_text)
        now = self.moment
        for row in rows:
            row["datetm"] = now.strftime("%Y-%m-%d %H:%M")
            if self.timestamp_variant is not None:
                row["datetm"] = now.replace(second=20).strftime(self.timestamp_variant)
        if self.bad_source == "incheon_parking":
            rows[0]["parking" if self.bad_kind == "count" else "datetm"] = "upstream error"
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


def test_map_collector_consumes_public_sdk_complete_receipt(test_settings):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch
    from app.services.collection import KrairportPublicDataClient
    from test_collection_service import _mock_krairport_client
    test_settings.transport_map_current_enabled = True
    test_settings.data_go_kr_service_key = "fixture"
    mock = _mock_krairport_client(parking_raw_set=SimpleNamespace(
        items=({"floor": "시험"},), total_count=1, page_count=1,
        page_size=100, wire_page_metadata=True,
    ))
    with patch("app.services.collection.KrairportClient", return_value=mock):
        response = asyncio.run(KrairportPublicDataClient(test_settings).fetch_incheon_parking())
    assert response.completion["complete"] and response.completion["item_count"] == 1
    mock.__aenter__.return_value.parking_raw_set.assert_awaited_once_with(
        provider="iiac", page_size=100, max_pages=20,
    )


import pytest


@pytest.mark.parametrize("source", ["kac_parking", "incheon_parking"])
@pytest.mark.parametrize("kind", ["count", "timestamp"])
def test_bad_source_values_retry_then_preserve_head_and_failed_raw(export_client, source, kind):
    from app.models import RawApiResponse
    c = export_client
    client = Fixture()
    collector = service(c, client)
    _run(c, lambda s: collector.collect(s))
    async def head_generation(s):
        head = await s.get(ReferenceExportState, (KIND, parking_scope(c.app.state.settings, source)))
        return head.generation
    before = _run(c, head_generation)
    client.bad_source, client.bad_kind = source, kind
    result = _run(c, lambda s: collector.collect(s))
    assert result["status"] == "partial_success"
    assert _run(c, head_generation) == before
    page = c.get(PATH, headers=HEADERS)
    assert page.status_code == 200 and page.json()["total_count"] == 12
    assert page.json()["meta"]["source_status"] == "stale"
    async def raw_count(s):
        return await s.scalar(select(func.count()).select_from(RawApiResponse).where(
            RawApiResponse.source == source, RawApiResponse.parse_status == "failed"))
    assert _run(c, raw_count) == 2


def test_live_blocked_runs_keep_marker_and_never_call_kac_twice(export_client):
    from app.services.collection import KrairportPublicDataClient, UPSTREAM_RATE_LIMIT_MARKER
    class LiveFixture(Fixture, KrairportPublicDataClient):
        pass
    c = export_client
    client = LiveFixture()
    collector = service(c, client)
    assert collector.client_mode == "live"
    async def previous_failure(s):
        now = now_utc()
        s.add(CollectionRun(started_at=now, finished_at=now, status="partial_success", trigger="fixture",
                            error_message=f"kac_parking API error 99: {UPSTREAM_RATE_LIMIT_MARKER}"))
    _run(c, previous_failure)
    for _ in range(2):
        result = _run(c, lambda s: collector.collect(s))
        assert result["status"] == "partial_success"
        assert UPSTREAM_RATE_LIMIT_MARKER in " ".join(result["errors"])
        async def blocked(s):
            return (await collector.get_upstream_rate_limit_state(s)).is_blocked
        assert _run(c, blocked)
    assert client.calls == 0


@pytest.mark.parametrize("format", ["%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"])
def test_current_uses_canonical_seconds_while_legacy_history_stays_unchanged(export_client, format):
    c = export_client
    client = Fixture()
    client.timestamp_variant = format
    collector = service(c, client)
    result = _run(c, lambda s: collector.collect(s))
    assert result["status"] == "success", result
    async def clocks(s):
        current = list((await s.scalars(select(ParkingCurrent.observed_at).where(
            ParkingCurrent.source == "incheon_parking"))).all())
        history = list((await s.scalars(select(ParkingSnapshot.observed_at).where(
            ParkingSnapshot.collection_run_id == result["collection_run_id"],
            ParkingSnapshot.source == "incheon_parking"))).all())
        return current, history
    current, history = _run(c, clocks)
    assert len(current) == len(history) == 2
    assert all(value.second == 20 for value in current)
    assert all(value.second == 0 for value in history)
    page = c.get(PATH, headers=HEADERS)
    assert page.status_code == 200, page.text
    from datetime import datetime
    assert all(datetime.fromisoformat(item["observed_at"]).second == 20
               for item in page.json()["items"] if item["source"] == "incheon_parking")


@pytest.mark.parametrize("variant", ["zero_capacity", "unmapped_airport"])
def test_strict_current_rejection_still_stores_flag_off_history(export_client, variant):
    """엄격 검증은 current 승격에만 건다 — 거절된 원천의 이번 이력은 플래그 OFF parser 결과대로 남는다."""
    from app.services.parsers import parse_kac_parking
    c = export_client
    settings = c.app.state.settings
    client = Fixture()
    client.moment -= timedelta(minutes=10)  # 두 번째 수집의 이력이 중복 skip되지 않게 관측시각을 나눈다.
    collector = service(c, client)
    assert _run(c, lambda s: collector.collect(s))["status"] == "success"
    async def head_generation(s):
        head = await s.get(ReferenceExportState, (KIND, parking_scope(settings, "kac_parking")))
        return head.generation
    before = _run(c, head_generation)
    client.moment += timedelta(minutes=10)
    client.kac_row_variant = variant
    result = _run(c, lambda s: collector.collect(s))
    assert result["status"] == "partial_success", result
    assert client.calls == 3  # 엄격 거절 재시도만 있고 이력용 추가 호출은 없다.
    assert _run(c, head_generation) == before
    page = c.get(PATH, headers=HEADERS)
    assert page.status_code == 200 and page.json()["total_count"] == 12
    assert page.json()["meta"]["source_status"] == "stale"
    expected = len(parse_kac_parking(client.last_kac_body, allowed_airport_codes=settings.supported_airport_codes))
    async def stored(s):
        return await s.scalar(select(func.count()).select_from(ParkingSnapshot).where(
            ParkingSnapshot.collection_run_id == result["collection_run_id"],
            ParkingSnapshot.source == "kac_parking"))
    assert expected > 0 and _run(c, stored) == expected


def test_history_only_store_failure_does_not_abort_failure_marking(export_client):
    """거절 원천의 이력 전용 저장이 실패해도 수집은 이어지고 그 원천의 실패 기록은 남는다."""
    c = export_client
    settings = c.app.state.settings
    client = Fixture()
    client.moment -= timedelta(minutes=10)
    collector = service(c, client)
    assert _run(c, lambda s: collector.collect(s))["status"] == "success"
    client.moment += timedelta(minutes=10)
    client.kac_row_variant = "zero_capacity"
    original = collector._store_observations
    async def failing_history_only(session, run_id, rows, *, lot_ids=None):
        if lot_ids is None:
            raise RuntimeError("history store boom")
        return await original(session, run_id, rows, lot_ids=lot_ids)
    collector._store_observations = failing_history_only
    result = _run(c, lambda s: collector.collect(s))
    assert result["status"] == "partial_success", result
    async def state(s):
        head = await s.get(ReferenceExportState, (KIND, parking_scope(settings, "kac_parking")))
        stored = await s.scalar(select(func.count()).select_from(ParkingSnapshot).where(
            ParkingSnapshot.collection_run_id == result["collection_run_id"],
            ParkingSnapshot.source == "kac_parking"))
        return head.last_error, stored
    assert _run(c, state) == ("source_failed", 0)
