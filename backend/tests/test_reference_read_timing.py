"""TRN03의 실제 요청별 페이지·큰 본문 지문 작업을 관측한다."""
# ruff: noqa: F811
import asyncio
import re

import pytest
from app.core import read_timing
from app.models import RailStationReference
from sqlalchemy import update
from starlette.responses import Response
from test_reference_export_reuse import HEADERS, _get, _prepare
from test_service_exports import _run, export_client  # noqa: F401


def _counts(response):
    timing = response.headers["server-timing"]
    return {key: int(re.search(rf'{key};desc="(\d+)"', timing).group(1))
            for key in ("page_builds", "fingerprint_calculations")}


def test_reference_counts_actual_build_and_fingerprint_but_not_304_etag(export_client):
    client = export_client
    _prepare(client)
    first = _get(client)
    assert first.status_code == 200, first.text
    assert _counts(first)["page_builds"] == 1
    assert _counts(first)["fingerprint_calculations"] > 0
    # A fresh 200 page builds a DTO; the unchanged input fingerprint is memoized.
    again = _get(client)
    assert again.status_code == 200
    assert _counts(again) == {"page_builds": 1, "fingerprint_calculations": 0}
    same = client.get("/v1/service/exports/rail-stations?limit=1", headers={
        **HEADERS, "If-None-Match": first.headers["ETag"],
    })
    assert same.status_code == 304 and same.content == b""
    assert _counts(same) == {"page_builds": 0, "fingerprint_calculations": 0}

    async def change(session):
        await session.execute(update(RailStationReference).values(station_name="즉시 변경 역"))
    _run(client, change)
    changed = client.get("/v1/service/exports/rail-stations?limit=1", headers={
        **HEADERS, "If-None-Match": first.headers["ETag"],
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["items"][0]["name"] == "즉시 변경 역"
    assert _counts(changed)["page_builds"] == 1
    assert _counts(changed)["fingerprint_calculations"] > 0


def test_legacy_fallback_counts_payload_hash_even_when_result_is_304(export_client):
    client = export_client
    _prepare(client)
    client.app.state.settings.release_sha = "unknown"
    first = _get(client)
    assert first.status_code == 200, first.text
    assert _counts(first) == {"page_builds": 1, "fingerprint_calculations": 1}
    same = client.get("/v1/service/exports/rail-stations?limit=1", headers={
        **HEADERS, "If-None-Match": first.headers["ETag"],
    })
    assert same.status_code == 304
    assert _counts(same) == {"page_builds": 0, "fingerprint_calculations": 1}


@pytest.mark.asyncio
async def test_concurrent_requests_keep_costs_local_and_ignore_outside_work():
    read_timing.observe_page_build()
    read_timing.observe_fingerprint()
    assert read_timing._current.get() is None
    ready = [asyncio.Event(), asyncio.Event()]

    async def endpoint(scope, receive, send):
        index = scope["index"]
        read_timing.observe_page_build()
        ready[index].set()
        await ready[1 - index].wait()
        for _ in range(index + 1):
            read_timing.observe_fingerprint()
            await asyncio.sleep(0)
        await Response("ok")(scope, receive, send)

    middleware = read_timing.ReadTimingMiddleware(endpoint)

    async def request(index):
        messages = []
        async def receive():
            return {"type": "http.request", "body": b""}
        async def send(message):
            messages.append(message)
        await middleware({"type": "http", "index": index}, receive, send)
        assert read_timing._current.get() is None
        headers = dict(messages[0]["headers"])
        timing = headers[b"server-timing"].decode()
        assert 'page_builds;desc="1"' in timing
        assert f'fingerprint_calculations;desc="{index + 1}"' in timing

    await asyncio.gather(request(0), request(1))
    assert read_timing._current.get() is None
