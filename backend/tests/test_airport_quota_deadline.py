"""ICN 병행 관찰 run이 KAC quota 원래 until을 밀어 영구 중지시키지 않는다."""
# ruff: noqa: F811

from datetime import timedelta

import pytest

from krairport import KrairportRateLimitError
from sqlalchemy import select

from app.core.time_utils import now_utc
from app.models import CollectionRun, TransportCollectionState
from app.services.collection import KAC_QUOTA_SOURCE, UPSTREAM_RATE_LIMIT_MARKER, KrairportPublicDataClient
from test_parking_export import Fixture, service
from test_service_exports import _run, export_client  # noqa: F401


class LiveQuotaFixture(Fixture, KrairportPublicDataClient):
    quota = True
    icn_calls = 0

    async def fetch_kac_parking(self):
        if self.quota:
            self.calls += 1
            raise KrairportRateLimitError(UPSTREAM_RATE_LIMIT_MARKER)
        return await super().fetch_kac_parking()

    async def fetch_incheon_parking(self):
        self.icn_calls += 1
        return await super().fetch_incheon_parking()


@pytest.mark.parametrize("map_mode", [False, True])
def test_actual_quota_origin_survives_icn_runs_then_expires(export_client, monkeypatch, map_mode):
    c = export_client
    client = LiveQuotaFixture()
    collector = service(c, client)
    collector.settings.transport_map_current_enabled = map_mode
    collector.settings.upstream_rate_limit_backoff_seconds = 60
    origin = now_utc()
    clock = [origin]
    monkeypatch.setattr("app.services.collection.now_utc", lambda: clock[0])
    result = _run(c, lambda s: collector.collect(s))
    assert result["status"] == "partial_success" and client.calls == 1
    async def deadline(s):
        row = await s.scalar(select(TransportCollectionState).where(TransportCollectionState.source == KAC_QUOTA_SOURCE))
        from app.core.time_utils import serialize_utc
        return serialize_utc(row.next_due_at) if row.next_due_at else None
    original_due = _run(c, deadline)
    assert original_due == origin + timedelta(seconds=60)
    for seconds in (10, 20, 59):
        clock[0] = origin + timedelta(seconds=seconds)
        assert _run(c, lambda s: collector.collect(s))["status"] == "partial_success"
        assert _run(c, deadline) == original_due
        assert client.calls == 1
    assert client.icn_calls == 4
    clock[0] = origin + timedelta(seconds=61)
    client.quota = False
    assert _run(c, lambda s: collector.collect(s))["status"] == "success"
    assert client.calls == 2 and client.icn_calls == 5
    assert _run(c, deadline) is None
    async def unblocked(s):
        return not (await collector.get_upstream_rate_limit_state(s)).is_blocked
    assert _run(c, unblocked)


@pytest.mark.parametrize("map_mode", [False, True])
def test_legacy_native_error_is_adopted_once_without_sliding(export_client, monkeypatch, map_mode):
    c = export_client
    client = LiveQuotaFixture()
    client.quota = False
    collector = service(c, client)
    collector.settings.transport_map_current_enabled = map_mode
    collector.settings.upstream_rate_limit_backoff_seconds = 60
    origin = now_utc()
    clock = [origin + timedelta(seconds=10)]
    monkeypatch.setattr("app.services.collection.now_utc", lambda: clock[0])
    async def seed(s):
        s.add(CollectionRun(started_at=origin, finished_at=origin, status="partial_success", trigger="fixture",
                            error_message=UPSTREAM_RATE_LIMIT_MARKER))
    _run(c, seed)
    for seconds in (10, 45):
        clock[0] = origin + timedelta(seconds=seconds)
        assert _run(c, lambda s: collector.collect(s))["status"] == "partial_success"
        assert client.calls == 0
    clock[0] = origin + timedelta(seconds=61)
    assert _run(c, lambda s: collector.collect(s))["status"] == "success"
    assert client.calls == 1


def test_old_outcome_cannot_clear_newer_quota_deadline(export_client):
    c = export_client
    collector = service(c, LiveQuotaFixture())
    origin = now_utc()
    async def check(s):
        await collector._record_quota_outcome(s, started_at=origin, was_blocked=False,
                                              messages=[UPSTREAM_RATE_LIMIT_MARKER])
        await s.flush()
        await collector._record_quota_outcome(s, started_at=origin - timedelta(seconds=1), was_blocked=False, messages=[])
        row = await s.scalar(select(TransportCollectionState).where(TransportCollectionState.source == KAC_QUOTA_SOURCE))
        from app.core.time_utils import serialize_utc
        return serialize_utc(row.next_due_at)
    assert _run(c, check) == origin + timedelta(seconds=collector.settings.upstream_rate_limit_backoff_seconds)


@pytest.mark.parametrize("prior_failure", [False, True])
def test_new_success_fence_rejects_old_quota_failure(export_client, prior_failure):
    c = export_client
    collector = service(c, LiveQuotaFixture())
    collector.settings.upstream_rate_limit_backoff_seconds = 60
    origin = now_utc()
    async def check(s):
        if prior_failure:
            await collector._record_quota_outcome(s, started_at=origin, was_blocked=False,
                                                  messages=[UPSTREAM_RATE_LIMIT_MARKER])
            await s.flush()
        await collector._record_quota_outcome(s, started_at=origin + timedelta(seconds=80),
                                              was_blocked=False, messages=[])
        await s.flush()
        await collector._record_quota_outcome(s, started_at=origin + timedelta(seconds=70),
                                              was_blocked=False, messages=[UPSTREAM_RATE_LIMIT_MARKER])
        await s.flush()
        row = await s.scalar(select(TransportCollectionState).where(TransportCollectionState.source == KAC_QUOTA_SOURCE))
        from app.core.time_utils import serialize_utc
        assert row.next_due_at is None and row.last_error is None
        assert serialize_utc(row.last_started_at) == origin + timedelta(seconds=80)
    _run(c, check)


def test_expired_quota_deadline_reports_no_until_and_future_deadline_still_blocks(export_client):
    """지난 deadline은 차단이 아니다 — admin collector-status가 false와 과거 until을 함께 내지 않는다."""
    from app.core.time_utils import serialize_utc
    c = export_client
    client = LiveQuotaFixture()
    client.quota = False
    collector = c.app.state.collection_service
    collector.client = client  # admin collector-status도 같은 live 판정을 쓴다.
    past = now_utc() - timedelta(minutes=5)
    async def seed(s):
        s.add(TransportCollectionState(source=KAC_QUOTA_SOURCE, next_due_at=past,
                                       last_started_at=past - timedelta(hours=1), updated_at=past,
                                       last_error=f"kac_parking API error 99: {UPSTREAM_RATE_LIMIT_MARKER}"))
    _run(c, seed)
    async def state(s):
        return await collector.get_upstream_rate_limit_state(s)
    expired = _run(c, state)
    assert (expired.is_blocked, expired.blocked_until, expired.error_message) == (False, None, None)
    payload = c.get("/v1/admin/collector-status").json()
    assert payload["upstream_rate_limited"] is False and payload["upstream_rate_limited_until"] is None
    future = now_utc() + timedelta(minutes=5)
    async def extend(s):
        row = await s.scalar(select(TransportCollectionState).where(TransportCollectionState.source == KAC_QUOTA_SOURCE))
        row.next_due_at = future
    _run(c, extend)
    blocked = _run(c, state)
    assert blocked.is_blocked and serialize_utc(blocked.blocked_until) == future
    assert UPSTREAM_RATE_LIMIT_MARKER in blocked.error_message
    payload = c.get("/v1/admin/collector-status").json()
    assert payload["upstream_rate_limited"] is True and payload["upstream_rate_limited_until"] is not None


def test_transport_collector_status_hides_the_airport_quota_ledger(export_client):
    """성공 run도 만드는 공항 KAC quota 원장은 교통 collector-status의 원천 목록에 섞이지 않는다."""
    c = export_client
    client = LiveQuotaFixture()
    client.quota = False
    collector = service(c, client)
    assert _run(c, lambda s: collector.collect(s))["status"] == "success"
    async def ledger(s):
        return await s.scalar(select(TransportCollectionState.source).where(TransportCollectionState.source == KAC_QUOTA_SOURCE))
    assert _run(c, ledger) == KAC_QUOTA_SOURCE
    response = c.get("/v1/transport/collector-status")
    assert response.status_code == 200, response.text
    assert KAC_QUOTA_SOURCE not in [item["source"] for item in response.json()["sources"]]


def test_legacy_private_error_is_redacted_before_source_state_copy(export_client):
    from app.services.collection import UpstreamRateLimitState
    c = export_client
    collector = service(c, LiveQuotaFixture())
    collector.settings.data_go_kr_service_key = "private-fixture-key"
    async def check(s):
        await collector._retain_quota_deadline(s, UpstreamRateLimitState(
            is_blocked=True, blocked_until=now_utc() + timedelta(seconds=60), source="kac_parking",
            error_message=f"{UPSTREAM_RATE_LIMIT_MARKER} https://fixture.invalid?serviceKey=private-fixture-key",
        ))
        await s.flush()
        row = await s.scalar(select(TransportCollectionState).where(TransportCollectionState.source == KAC_QUOTA_SOURCE))
        assert "private-fixture-key" not in row.last_error
        assert UPSTREAM_RATE_LIMIT_MARKER in row.last_error
    _run(c, check)
