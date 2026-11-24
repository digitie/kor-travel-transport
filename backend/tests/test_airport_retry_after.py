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


class FeeCountingFixture(RetryAfterFixture):
    fee_calls: list[str]
    fee_limited = False

    async def fetch_kac_fee(self, airport_code: str):
        self.fee_calls.append(airport_code)
        if self.fee_limited:
            raise KrairportRateLimitError("HTTP 429: too many requests", retry_after=None)
        return await super().fetch_kac_fee(airport_code)


@pytest.mark.parametrize("map_mode", [False, True])
def test_parking_429_stops_the_fee_calls_of_the_same_run(export_client, map_mode):
    """사후 리뷰 P1: 주차 429(Retry-After 없음)를 받은 실행이 요금 공항별 호출을 이어 가지 않는다."""
    c = export_client
    client = FeeCountingFixture()
    client.fee_calls = []
    client.retry_after = None
    collector = service(c, client)
    collector.settings.transport_map_current_enabled = map_mode
    collector.settings.enable_fee_collection = True
    _run(c, lambda s: collector.collect(s))
    assert client.calls == 1 and client.fee_calls == []


def test_first_fee_429_stops_the_remaining_fee_airports(export_client):
    c = export_client
    client = FeeCountingFixture()
    client.fee_calls = []
    client.limited = False
    client.fee_limited = True
    collector = service(c, client)
    collector.settings.enable_fee_collection = True
    _run(c, lambda s: collector.collect(s))
    assert len(client.fee_calls) == 1  # 남은 공항(최대 13곳)을 같은 실행에서 부르지 않는다


def test_public_incheon_flight_lookup_does_not_wait_minutes_on_429(monkeypatch):
    """공개 인천 조회는 SDK 재시도를 짧게 쓰고, 짧은 Retry-After의 rate_limited는 그 시간만큼만 캐시한다."""
    import asyncio
    from datetime import date

    from app.core.config import Settings
    from app.services import flight_status

    seen: dict = {}

    class Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def iiac_raw_items(self, *args, **kwargs):
            raise KrairportRateLimitError("HTTP 429", retry_after=7)

    monkeypatch.setattr(flight_status, "KrairportClient", Client)
    settings = Settings(data_go_kr_service_key="k", use_sample_client_when_no_key=False,
                        upstream_rate_limit_backoff_seconds=3600)
    service = flight_status.FlightStatusService(settings)
    origin = now_utc()
    monkeypatch.setattr(flight_status, "now_utc", lambda: origin)
    payload = asyncio.run(service.get_status("ICN", date.today()))
    assert payload["status"] == "rate_limited" and "_retry_after_seconds" not in payload
    assert seen["retries"] == flight_status.PUBLIC_REQUEST_RETRIES <= 1
    assert seen["max_retry_after"] == flight_status.PUBLIC_REQUEST_MAX_RETRY_AFTER_SECONDS <= 5
    expires_at, _ = next(iter(service._cache.values()))
    assert expires_at == origin + timedelta(seconds=flight_status.RATE_LIMITED_MIN_CACHE_SECONDS)
