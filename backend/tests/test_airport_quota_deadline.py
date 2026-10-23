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
