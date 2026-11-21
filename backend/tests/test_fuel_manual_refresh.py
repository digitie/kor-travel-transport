import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from opinet import OpinetRateLimitError
from sqlalchemy import func, select

from app import main
from app.core.time_utils import now_utc
from app.models import FuelPriceSnapshot, FuelStation, TransportCollectionState
from app.services import fuel_manual_refresh as refresh
from app.services.fuel_statistics import publish_fuel_statistics
from app.services.transport_collection import OPINET_SOURCE, upsert_latest_fuel_prices

PATH = "/v1/internal/fuel/refresh"
TOKEN = "only-for-fuel-refresh-fixtures-000"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
VIEWPORT = {"min_longitude": 127, "max_longitude": 128, "min_latitude": 37, "max_latitude": 38}


def run(client, work):
    async def in_session():
        async with client.app.state.session_factory.begin() as session:
            return await work(session)
    return asyncio.run(in_session())


@pytest.fixture
def provider(monkeypatch):
    calls, replies = [], {}

    class FakeCollector:
        def __init__(self, *, browser_channel, timeout_ms, throttle):
            assert browser_channel is None and timeout_ms == 8000
            assert throttle.max_search_requests == 18

        @asynccontextmanager
        async def open_region_search(self):
            async def search(region, kind):
                assert region.sido_value == "서울특별시" and kind in {"station", "lpg"}
                suffix = region.sigungu_value.removeprefix("시험구")
                ids = ["U0", "U1", "UNRELATED"] if suffix == "_shared" else [f"U{suffix}"]
                calls.append(f"U{suffix}" if kind == "station" else f"LPG:{suffix}")
                rows = []
                for station_id in ids:
                    reply = replies.get(station_id, (1712, now_utc() - timedelta(minutes=1)))
                    if callable(reply):
                        reply = await reply()
                    if isinstance(reply, Exception):
                        raise reply
                    price, observed = reply
                    rows.append(SimpleNamespace(station_id=station_id, prices=[
                        SimpleNamespace(product_code=SimpleNamespace(value="B027"), price=price, updated_at=observed),
                    ]))
                return tuple(rows)
            yield search

    monkeypatch.setattr(refresh, "OpinetBrowserCollector", FakeCollector)
    return calls, replies


@pytest.fixture
def api(test_settings, provider):
    def make(limit=10, *, peer="127.0.0.1", **overrides):
        values = dict(opinet_browser_enabled=True, fuel_refresh_internal_token=TOKEN,
                      fuel_refresh_daily_limit=limit, transport_admin_write_token="separate-test-secret",
                      release_sha="fixture-refresh")
        return TestClient(main.create_app(test_settings.model_copy(update={**values, **overrides})),
                          client=(peer, 50000))
    return make


def seed(client, count, at, *, unsupported=False, unpriced=(), shared_region=False, lpg=False):
    async def insert(session):
        ids = []
        for i in range(count):
            station = FuelStation(
                source=OPINET_SOURCE, identity_key=f"station:U{i}", source_station_id=None if unsupported else f"U{i}",
                name=f"주유소 {i}", query_level="sigungu", sido_value="서울특별시", sido_name="서울",
                sigungu_value="시험구_shared" if shared_region else f"시험구{i}", sigungu_name="구",
                source_kinds=["lpg"] if lpg else ["station"],
                latitude=37.5, longitude=127.1 + i / 100, first_seen_at=at, last_seen_at=at,
            )
            session.add(station)
            await session.flush()
            ids.append(station.id)
            session.add(snapshot(station.id, 1500 if i not in unpriced else None, at, at))
        await session.flush()
        await upsert_latest_fuel_prices(session)
        return ids
    return run(client, insert)


def snapshot(station_id, price, observed, collected):
    return FuelPriceSnapshot(fuel_station_id=station_id, source=OPINET_SOURCE, product_code="B027", price=price,
                             provider_updated_at=observed, observed_at=observed, collected_at=collected)


def post(client, body, expected=200):
    response = client.post(PATH, json=body, headers=AUTH)
    assert response.status_code == expected, response.text[:500]
    return response.json()


def map_get(client, **overrides):
    params = {**VIEWPORT, "kind": "fuel_station", "zoom": 14, "include_sources": "false", **overrides}
    response = client.get("/v1/transport/features/places", params={
        key: value for key, value in params.items() if value is not None
    })
    assert response.status_code == 200, response.text[:500]
    return response.json()


@pytest.mark.parametrize("overrides", [
    {"opinet_browser_enabled": False}, {"fuel_refresh_daily_limit": 0}, {"fuel_refresh_internal_token": "weak"},
    {"transport_admin_write_token": TOKEN},
])
def test_disabled_without_browser_separate_token_and_positive_limit(api, provider, overrides):
    with api(**overrides) as client:
        post(client, {"station_id": 1}, 404)
    assert provider[0] == []



def test_browser_prices_require_provider_timestamp():
    observed = datetime(2026, 11, 21, 6, 30, tzinfo=UTC)
    stations = [SimpleNamespace(prices=[
        SimpleNamespace(product_code=SimpleNamespace(value="B027"), price=1712, updated_at=observed),
        SimpleNamespace(product_code=SimpleNamespace(value="D047"), price=1500, updated_at=None),
        SimpleNamespace(product_code=SimpleNamespace(value="C004"), price=1400, updated_at=observed + timedelta(hours=2)),
    ])]
    assert refresh._observations(stations, observed + timedelta(minutes=30)) == {"B027": (observed, 1712)}


def test_two_stations_share_one_region_search_and_ignore_unrequested_rows(api, provider):
    with api() as client:
        ids = seed(client, 2, now_utc() - timedelta(hours=1), shared_region=True)
        one = post(client, {"station_id": ids[0]})["results"]
        assert [result["station_id"] for result in one] == ids[:1]
        together = post(client, {"viewport": VIEWPORT})["results"]
        assert [item["status"] for item in together] == ["cooldown", "updated"]
        assert provider[0] == ["U_shared", "U_shared"]


def test_lpg_stations_in_the_same_region_share_one_tab_search(api, provider):
    with api() as client:
        ids = seed(client, 2, now_utc() - timedelta(hours=1), shared_region=True, lpg=True)
        results = post(client, {"viewport": VIEWPORT})["results"]
        assert [item["station_id"] for item in results] == ids
        assert [item["status"] for item in results] == ["updated", "updated"]
        assert provider[0] == ["LPG:_shared"]


def test_auth_and_exact_target_schema(api, provider):
    with api() as client:
        assert client.post(PATH, json={"station_id": 1}).status_code == 401
        assert client.post(PATH, headers={"Authorization": "Bearer separate-test-secret"},
                           json={"station_id": 1}).status_code == 401
        for invalid in ({"station_id": 1, "viewport": VIEWPORT}, {"station_id": True},
                        {"viewport": {**VIEWPORT, "count": 9}}, {"viewport": {**VIEWPORT, "max_longitude": 126}}):
            post(client, invalid, 422)
        post(client, {"station_id": 1}, 404)
        assert post(client, {"viewport": VIEWPORT}) == {"status": "completed", "results": []}
    assert provider[0] == []


@pytest.mark.parametrize("peer,headers", [
    ("192.0.2.10", {}),
    ("192.0.2.10", {"X-Forwarded-For": "127.0.0.1"}),
    ("127.0.0.1", {"X-Forwarded-For": "127.0.0.1"}),
    ("127.0.0.1", {"Forwarded": "for=127.0.0.1"}),
])
def test_refresh_rejects_off_loopback_and_forwarded_peers(api, provider, peer, headers):
    with api(peer=peer) as client:
        response = client.post(PATH, json={"viewport": VIEWPORT}, headers={**AUTH, **headers})
        assert response.status_code == 404
    assert provider[0] == []


def test_refresh_accepts_direct_ipv6_loopback(api):
    with api(peer="::1") as client:
        assert post(client, {"viewport": VIEWPORT}) == {"status": "completed", "results": []}


def test_map_server_counts_tenth_ignores_null_price_and_deduplicates_products(api, provider):
    with api() as client:
        ids = seed(client, 10, now_utc() - timedelta(hours=1), unpriced={9})
        post(client, {"viewport": VIEWPORT}, 422)
        assert provider[0] == []
        assert map_get(client, product_codes="B027")["total"] == 9
        result = post(client, {"viewport": {**VIEWPORT, "product_codes": ["B027", "B027"]}})
        assert result["status"] == "completed"
        assert [row["station_id"] for row in result["results"]] == ids[:9]
        assert provider[0] == [f"U{i}" for i in range(9)]


def test_global_quota_rolls_at_seoul_midnight_and_station_cooldown(api, provider, monkeypatch):
    at = now_utc().replace(hour=14, minute=59, second=0, microsecond=0)
    clock = [at]
    monkeypatch.setattr(refresh, "now_utc", lambda: clock[0])
    provider[1].update({"U0": (1500, at - timedelta(minutes=1)), "U1": (1700, at - timedelta(minutes=1))})
    with api(limit=1) as client:
        first, second = seed(client, 2, at - timedelta(hours=1))
        result = post(client, {"viewport": VIEWPORT})
        assert result["status"] == "partial"
        assert [(r["status"], r["reason"]) for r in result["results"]] == [
            ("unchanged", None), ("rate_limited", "call_budget_exhausted"),
        ]
        assert post(client, {"station_id": first})["results"][0]["status"] == "cooldown"
        clock[0] += timedelta(minutes=2)
        assert post(client, {"station_id": second})["results"][0]["status"] == "updated"
        assert provider[0] == ["U0", "U1"]


def test_overlapping_requests_make_only_one_provider_call(api, provider):
    entered, release = Event(), Event()

    async def waiting():
        entered.set()
        assert await asyncio.to_thread(release.wait, 2)
        return 1777, now_utc() - timedelta(minutes=1)

    provider[1]["U0"] = waiting
    with api() as client, api() as other_client, ThreadPoolExecutor(max_workers=2) as workers:
        first, second = seed(client, 2, now_utc() - timedelta(hours=1))
        active = workers.submit(post, client, {"station_id": first})
        try:
            assert entered.wait(2)
            duplicate = post(other_client, {"station_id": first})["results"][0]
            other = post(other_client, {"station_id": second})["results"][0]
            assert duplicate["reason"] == other["reason"] == "refresh_busy"
        finally:
            release.set()
        assert active.result(3)["results"][0]["status"] == "updated"
    assert provider[0] == ["U0"]



def test_request_deadline_releases_the_lease_and_charges_only_started_calls(api, provider, monkeypatch):
    async def too_slow():
        await asyncio.sleep(10)
        raise AssertionError("the request deadline should cancel this call")

    provider[1]["U0"] = too_slow
    with api(limit=2) as client:
        ids = seed(client, 2, now_utc() - timedelta(hours=1))
        with monkeypatch.context() as local:
            local.setattr(refresh, "REQUEST_SECONDS", 1)
            result = post(client, {"viewport": VIEWPORT})
        assert result["status"] == "failed"
        assert [row["reason"] for row in result["results"]] == ["request_timeout", "request_timeout"]
        assert post(client, {"station_id": ids[1]})["results"][0]["status"] == "updated"
    assert provider[0] == ["U0", "U1"]

def test_upstream_throttle_aborts_remaining_work_and_blocks_other_requests(api, provider):
    provider[1]["U0"] = OpinetRateLimitError("private upstream detail")
    with api() as client:
        ids = seed(client, 2, now_utc() - timedelta(hours=1))
        result = post(client, {"viewport": VIEWPORT})
        assert [r["reason"] for r in result["results"]] == ["provider_rate_limited", "provider_backoff"]
        assert post(client, {"station_id": ids[1]})["results"][0]["reason"] == "refresh_busy"
    assert provider[0] == ["U0"]


def test_unsupported_source_id_never_calls_provider(api, provider):
    with api() as client:
        [station_id] = seed(client, 1, now_utc() - timedelta(hours=1), unsupported=True)
        assert post(client, {"station_id": station_id})["results"][0]["status"] == "unsupported"
    assert provider[0] == []


def test_overlay_map_cache_and_station_reads_preserve_history_and_stats(api, provider, monkeypatch):
    now = now_utc()
    stamp = now - timedelta(hours=1)
    provider[1]["U0"] = (1712, now - timedelta(minutes=1))
    with api() as client:
        [station_id] = seed(client, 1, stamp)

        async def publish(session):
            session.add(TransportCollectionState(source=OPINET_SOURCE, last_success_at=stamp, updated_at=stamp))
            await session.flush()
            await publish_fuel_statistics(session, OPINET_SOURCE, stamp)
        run(client, publish)

        history_url = f"/v1/transport/fuel/stations/{station_id}/price-history?source={OPINET_SOURCE}"
        stats_url = "/v1/transport/fuel/statistics"
        history_before = client.get(history_url)
        stats_before = client.get(stats_url).json()["items"]
        assert history_before.json()["latest"][0]["price"] == 1500
        assert stats_before
        assert map_get(client)["items"][0]["latest_price"] == 1500
        assert map_get(client)["items"][0]["latest_price"] == 1500
        result = post(client, {"station_id": station_id})["results"][0]
        assert result["status"] == "updated" and result["checked_at"]
        assert map_get(client)["items"][0]["latest_price"] == 1712
        assert map_get(client, kinds="fuel_station,rail_station", kind=None)["items"][0]["latest_price"] == 1712
        station = client.get("/v1/transport/fuel/stations").json()
        assert station["items"][0]["prices"][0]["price"] == 1712
        assert datetime.fromisoformat(station["fuel_prices_last_refreshed_at"]) == stamp
        assert client.get(history_url).json()["latest"][0]["price"] == 1500
        assert client.get(stats_url).json()["items"] == stats_before

        async def stored_count(session):
            return await session.scalar(select(func.count()).select_from(FuelPriceSnapshot))
        assert run(client, stored_count) == 1

        # Advance only the reader clock. The persisted revision is unchanged and a cached page must expire too.
        monkeypatch.setattr(main, "now_utc", lambda: now + timedelta(hours=25))
        assert map_get(client)["items"][0]["latest_price"] == 1500


@pytest.mark.parametrize("case", ["old", "conflict", "future", "baseline_wins_after_refresh"])
def test_manual_observation_never_rolls_back_price(api, provider, case):
    now = now_utc()
    stamp = now - timedelta(hours=1)
    observed = {"old": stamp - timedelta(seconds=1), "conflict": stamp, "future": now + timedelta(hours=1),
                "baseline_wins_after_refresh": now - timedelta(minutes=1)}[case]
    provider[1]["U0"] = (1100, observed)
    with api() as client:
        [station_id] = seed(client, 1, stamp)
        result = post(client, {"station_id": station_id})["results"][0]
        if case == "baseline_wins_after_refresh":
            assert result["status"] == "updated"
            assert map_get(client)["items"][0]["latest_price"] == 1100
            async def later_batch(session):
                session.add(snapshot(station_id, 1700, now, now))
                await session.flush()
                await upsert_latest_fuel_prices(session)
            run(client, later_batch)
            assert map_get(client)["items"][0]["latest_price"] == 1700
        else:
            assert result["status"] == "error"
            assert map_get(client)["items"][0]["latest_price"] == 1500
