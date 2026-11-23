"""KAC HTTP 429의 Retry-After를 quota 예약에 쓰고, SDK가 이미 기다린 429를 곧바로 다시 부르지 않는다.

python-krairport-api #15부터 SDK는 짧은 Retry-After는 스스로 기다려 재시도하고, 상한(30초)을 넘는 요구는
기다리지 않고 `KrairportRateLimitError(retry_after=초)`로 돌려준다(수집 실패 감사 2026-11-23 §2.5 P2).
"""
# ruff: noqa: F811

from datetime import timedelta

import pytest
from krairport import KrairportRateLimitError
from sqlalchemy import select

from app.core.time_utils import now_utc, serialize_utc
from app.models import TransportCollectionState
from app.services.collection import (
    KAC_QUOTA_SOURCE, UPSTREAM_RATE_LIMIT_MARKER, KrairportPublicDataClient, rate_limit_retry_after,
)
from test_parking_export import Fixture, service
from test_service_exports import _run, export_client  # noqa: F401


class RetryAfterFixture(Fixture, KrairportPublicDataClient):
    retry_after: float | None = 3600
    marker = False
    limited = True

    async def fetch_kac_parking(self):
        if self.limited:
            self.calls += 1
            message = UPSTREAM_RATE_LIMIT_MARKER if self.marker else "HTTP 429: too many requests"
            raise KrairportRateLimitError(message, retry_after=self.retry_after)
        return await super().fetch_kac_parking()


async def _quota(s):
    row = await s.scalar(select(TransportCollectionState).where(TransportCollectionState.source == KAC_QUOTA_SOURCE))
    return (serialize_utc(row.next_due_at) if row and row.next_due_at else None, row.last_error if row else None)


@pytest.mark.parametrize("map_mode", [False, True])
def test_retry_after_blocks_kac_until_the_provider_deadline(export_client, monkeypatch, map_mode):
    c = export_client
    client = RetryAfterFixture()
    collector = service(c, client)
    collector.settings.transport_map_current_enabled = map_mode
    collector.settings.upstream_rate_limit_backoff_seconds = 60
    origin = now_utc()
    clock = [origin]
    monkeypatch.setattr("app.services.collection.now_utc", lambda: clock[0])

    assert _run(c, lambda s: collector.collect(s))["status"] == "partial_success"
    # SDK가 이미 기다렸다가 포기한 429를 같은 수집에서 다시 부르지 않는다.
    assert client.calls == 1
    due, error = _run(c, _quota)
    # quota 표지가 없는 HTTP 429는 설정 backoff(60초)가 아니라 공급자가 요구한 3600초를 쓴다.
    assert due == origin + timedelta(seconds=3600)
    assert error == "kac_parking HTTP 429: Retry-After 3600s"

    clock[0] = origin + timedelta(seconds=1800)
    _run(c, lambda s: collector.collect(s))
    assert client.calls == 1  # 예약 안에서는 KAC를 부르지 않는다.

    clock[0] = origin + timedelta(seconds=3601)
    client.limited = False
    assert _run(c, lambda s: collector.collect(s))["status"] == "success"
    assert client.calls == 2
    assert _run(c, _quota)[0] is None


@pytest.mark.parametrize(("retry_after", "expected"), [(None, 60), (30, 60), (7200, 7200)])
def test_quota_marker_uses_longer_of_backoff_and_retry_after(export_client, monkeypatch, retry_after, expected):
    c = export_client
    client = RetryAfterFixture()
    client.marker = True
    client.retry_after = retry_after
    collector = service(c, client)
    collector.settings.upstream_rate_limit_backoff_seconds = 60
    origin = now_utc()
    monkeypatch.setattr("app.services.collection.now_utc", lambda: origin)

    _run(c, lambda s: collector.collect(s))
    due, error = _run(c, _quota)
    assert due == origin + timedelta(seconds=expected)
    assert UPSTREAM_RATE_LIMIT_MARKER in error


def test_plain_429_without_retry_after_keeps_old_behaviour(export_client, monkeypatch):
    """Retry-After가 없는 HTTP 429는 예전처럼 quota 예약을 만들지 않는다(다음 tick에 다시 본다)."""
    c = export_client
    client = RetryAfterFixture()
    client.retry_after = None
    collector = service(c, client)
    origin = now_utc()
    monkeypatch.setattr("app.services.collection.now_utc", lambda: origin)

    _run(c, lambda s: collector.collect(s))
    assert client.calls == 1
    assert _run(c, _quota)[0] is None


@pytest.mark.parametrize(("error", "expected"), [
    (KrairportRateLimitError("x", retry_after=1.2), 2),
    (KrairportRateLimitError("x", retry_after=0), None),
    (KrairportRateLimitError("x", retry_after=float("inf")), None),
    (KrairportRateLimitError("x", retry_after=float("nan")), None),
    (KrairportRateLimitError("x"), None),
    (KrairportRateLimitError("x", retry_after=10**9), 7 * 24 * 3600),
    (RuntimeError("HTTP 429"), None),
])
def test_retry_after_hint_is_bounded(error, expected):
    assert rate_limit_retry_after(error) == expected
