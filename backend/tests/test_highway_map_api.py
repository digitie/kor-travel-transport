import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.time_utils import now_utc
from app.highway_map_routes import build_highway_map_router


def make_client(monkeypatch):
    state = SimpleNamespace(now=now_utc(), calls=[], failure=False, links=1, delay=0, limiters=[], paths=[])

    class Client:
        def __init__(self, **kwargs):
            state.limiters.append(kwargs["rate_limiter"])
            state.paths.append(kwargs["executable_path"])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            state.calls.append("closed")

        async def list_roads(self, **kwargs):
            state.calls.append("catalog")
            if state.failure:
                raise RuntimeError("private diagnostic must not reach callers")
            return SimpleNamespace(collected_at=state.now, source_url="https://www.its.go.kr/map/traffic",
                items=[SimpleNamespace(road_id="0010", road_number="1", name="경부고속도로")])

        async def get_traffic(self, road_id, **kwargs):
            state.calls.append((road_id, kwargs["direction"]))
            if state.delay:
                await asyncio.sleep(state.delay)
            if state.failure:
                raise RuntimeError("private diagnostic must not reach callers")
            link = SimpleNamespace(link_id="L1", direction=kwargs["direction"], speed_kmh=0, length_m=200,
                path=((127.0, 37.0), (127.1, 37.1)))
            return SimpleNamespace(collected_at=state.now, source_url="https://www.its.go.kr/map/traffic",
                items=[SimpleNamespace(section_id="S1", name="첫 구간", links=[link] * state.links)])

    monkeypatch.setattr("app.highway_map_routes.KritsClient", Client)
    monkeypatch.setattr("app.highway_map_routes.now_utc", lambda: state.now)
    app = FastAPI()
    app.state.settings = SimpleNamespace(its_chromium_executable_path=None)
    app.include_router(build_highway_map_router(), prefix="/v1")
    return TestClient(app), state


def test_typed_geometry_cache_same_limiter_and_road_membership(monkeypatch):
    client, state = make_client(monkeypatch)
    assert client.get("/v1/transport/highways/roads").status_code == 200
    url = "/v1/transport/highways/road-traffic?road_id=0010&direction=1"
    result = client.get(url)
    assert result.status_code == 200
    body = result.json()
    assert body["road_id"] == "0010" and body["road_number"] == "1"
    assert body["complete"] is False and body["stale"] is False
    assert body["items"][0]["speed_kmh"] == 0
    assert body["items"][0]["path"] == [[127.0, 37.0], [127.1, 37.1]]
    assert client.get(url).json() == body
    assert client.get("/v1/transport/highways/road-traffic?road_id=9999").status_code == 422
    assert client.get("/v1/transport/highways/road-traffic?road_id=0010&direction=3").status_code == 422
    assert state.calls == ["catalog", "closed", ("0010", "1"), "closed"]
    assert len(state.limiters) == 2 and state.limiters[0] is state.limiters[1]


def test_blank_optional_chromium_path_uses_sdk_default(monkeypatch):
    client, state = make_client(monkeypatch)
    client.app.state.settings.its_chromium_executable_path = ""
    assert client.get("/v1/transport/highways/roads").status_code == 200
    assert state.paths == [None]


def test_failed_refresh_preserves_stale_geometry_and_backs_off(monkeypatch):
    client, state = make_client(monkeypatch)
    url = "/v1/transport/highways/road-traffic?road_id=0010&direction=1"
    saved = client.get(url).json()
    state.now += timedelta(minutes=6)
    state.failure = True
    stale = client.get(url)
    assert stale.status_code == 200 and stale.json()["stale"] is True
    assert stale.json()["fetched_at"] == saved["fetched_at"]
    assert stale.json()["items"] == saved["items"]
    attempts = len(state.calls)
    assert client.get(url).json()["stale"] is True
    blocked = client.get(url.replace("direction=1", "direction=2"))
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0
    assert len(state.calls) == attempts
    assert "private" not in blocked.text


def test_oversize_response_is_not_cached_or_returned_as_empty(monkeypatch):
    client, state = make_client(monkeypatch)
    state.links = 5001
    failed = client.get("/v1/transport/highways/road-traffic?road_id=0010")
    assert failed.status_code == 502
    assert "private" not in failed.text and "items" not in failed.json()
    assert state.calls[-1] == "closed"
    assert client.get("/v1/transport/highways/road-traffic?road_id=0010").status_code == 429


def test_lookup_timeout_closes_owned_client_and_backs_off(monkeypatch):
    client, state = make_client(monkeypatch)
    assert client.get("/v1/transport/highways/roads").status_code == 200
    original_timeout = asyncio.timeout
    monkeypatch.setattr("app.highway_map_routes.asyncio.timeout", lambda _: original_timeout(.01))
    state.delay = .05
    assert client.get("/v1/transport/highways/road-traffic?road_id=0010").status_code == 504
    assert state.calls[-1] == "closed"
    assert client.get("/v1/transport/highways/road-traffic?road_id=0010").status_code == 429


def test_worker_daily_miss_budget_resets_on_korean_calendar_day(monkeypatch):
    client, state = make_client(monkeypatch)
    state.now = datetime(2026, 10, 23, 15, tzinfo=timezone.utc)
    url = "/v1/transport/highways/road-traffic?road_id=0010"
    for _ in range(95):  # catalog 1회 + 소통 95회
        assert client.get(url).status_code == 200
        state.now += timedelta(minutes=6)
    attempts = len(state.calls)
    stale = client.get(url)
    assert stale.status_code == 200 and stale.json()["stale"] is True
    assert len(state.calls) == attempts
    assert client.get(url + "&direction=2").status_code == 429
    state.now = datetime(2026, 10, 24, 15, tzinfo=timezone.utc)
    assert client.get(url + "&direction=2").status_code == 200
    assert state.calls[-2] == ("0010", "2")
