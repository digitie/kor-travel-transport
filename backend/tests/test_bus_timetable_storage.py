"""저장 시간표는 제공기관 호출 보호·프로세스 캐시와 독립해서 읽는다."""
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from datagokr.models import TagoBusTimetable

from app.core.time_utils import now_utc, to_seoul
from app.models import BusTerminalReference
from app.schemas import BusTimetableResponse
from app.services.bus_timetable_storage import save_bus_timetable, stored_bus_timetable


def test_bus_saved_only_and_stale_fallback_never_call_provider(client):
    today = to_seoul(now_utc()).date()
    async def seed():
        async with client.app.state.session_factory() as session:
            for terminal in ["A", "B", "C"]:
                session.add(BusTerminalReference(source="data_go_kr_tago", service_type="express",
                    terminal_id=terminal, terminal_name=terminal, first_seen_at=now_utc(), last_seen_at=now_utc()))
            await session.commit()
    asyncio.run(seed())
    path = "/v1/transport/bus/timetable"
    params = dict(service_type="express", departure_terminal_id="A", arrival_terminal_id="B", date=today.isoformat())
    with patch("app.main.DataGoKrClient", side_effect=AssertionError("저장 조회에서 외부 요청 금지")):
        assert client.get(path, params={**params, "stored_only": True}).status_code == 404
        assert client.app.state.bus_timetable_last_provider_call_at is None

    class FakeClient:
        calls = 0
        def __init__(self, **_kwargs): self.express_bus = self
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def timetable_list(self, **_kwargs):
            type(self).calls += 1
            return SimpleNamespace(total_count=0, items=[])
    client.app.state.settings.data_go_kr_service_key = "test-key"
    with patch("app.main.DataGoKrClient", FakeClient):
        first = client.get(path, params=params)
        assert first.status_code == 200
        assert first.json()["stored"] is True
        assert first.json()["items"] == []  # 정상 빈 응답도 저장됨
        assert FakeClient.calls == 1
    client.app.state.bus_timetable_cache.clear()
    with patch("app.main.DataGoKrClient", side_effect=AssertionError("신선한 DB 저장본 재호출 금지")):
        assert client.get(path, params=params).json()["stale"] is False
    future = now_utc() + timedelta(hours=1)
    client.app.state.bus_timetable_rate_limited_until = future + timedelta(hours=1)
    with patch("app.main.now_utc", return_value=future), patch("app.main.DataGoKrClient", side_effect=AssertionError("호출 보호 우회 금지")):
        for stored_only in [False, True]:
            response = client.get(path, params={**params, "stored_only": stored_only})
            assert response.status_code == 200
            assert response.json()["stale"] is True
            assert response.json()["refresh_status"] == ("stored_only" if stored_only else "rate_limited")
            assert response.json()["fetched_at"] == first.json()["fetched_at"]
        assert client.get(path, params={**params, "arrival_terminal_id": "C"}).status_code == 429
        assert client.get(path, params={**params, "bus_grade_id": "1", "stored_only": True}).status_code == 404
        client.app.state.settings.data_go_kr_service_key = None
        assert client.get(path, params={**params, "stored_only": True}).status_code == 200
        assert client.get(path, params=params).json()["refresh_status"] == "not_configured"

    client.app.state.settings.data_go_kr_service_key = "test-key"
    client.app.state.bus_timetable_rate_limited_until = None
    client.app.state.bus_timetable_last_provider_call_at = None
    with patch("app.main.now_utc", return_value=future), patch("app.main.DataGoKrClient", side_effect=RuntimeError("secret-error")):
        failed_refresh = client.get(path, params=params)
        assert failed_refresh.status_code == 200
        assert failed_refresh.json()["refresh_status"] == "upstream_error"
        assert failed_refresh.json()["fetched_at"] == first.json()["fetched_at"]
        assert "secret-error" not in failed_refresh.text
        client.app.state.bus_timetable_last_provider_call_at = None
        assert client.get(path, params={**params, "arrival_terminal_id": "C"}).status_code == 502
        assert client.get(path, params={**params, "arrival_terminal_id": "C", "stored_only": True}).status_code == 404
    assert client.get(path, params={**params, "bus_grade_id": " ", "stored_only": True}).status_code == 422


def test_bus_cache_does_not_overwrite_newer_response(client):
    async def run():
        now = now_utc()
        latest = BusTimetableResponse(service_type="express", departure_terminal_id="A", arrival_terminal_id="B",
            service_date=to_seoul(now).date(), fetched_at=now, total=123, truncated=True, stored=True, items=[])
        async with client.app.state.session_factory() as session:
            await save_bus_timetable(session, latest, None)
            await save_bus_timetable(session, latest.model_copy(update={"fetched_at": now - timedelta(hours=1), "total": 0}), None)
        async with client.app.state.session_factory() as session:
            saved = await stored_bus_timetable(session, ("express", "A", "B", latest.service_date, None))
            assert saved is not None and saved.total == 123 and saved.truncated
            assert await stored_bus_timetable(session, ("express", "A", "B", latest.service_date, "1")) is None
    asyncio.run(run())


@pytest.mark.parametrize("has_saved", [True, False])
@pytest.mark.parametrize("failure", ["validation", "json", "unicode", "value"])
def test_bus_provider_validation_error_uses_saved_data_or_sanitized_502(client, has_saved, failure):
    now = now_utc()
    today = to_seoul(now).date()
    saved_at = now - timedelta(hours=1)

    async def seed():
        async with client.app.state.session_factory() as session:
            for terminal in ["A", "B"]:
                session.add(BusTerminalReference(source="data_go_kr_tago", service_type="express",
                    terminal_id=terminal, terminal_name=terminal, first_seen_at=now, last_seen_at=now))
            await session.commit()
            if has_saved:
                await save_bus_timetable(session, BusTimetableResponse(service_type="express",
                    departure_terminal_id="A", arrival_terminal_id="B", service_date=today,
                    fetched_at=saved_at, total=0, stored=True, items=[]), None)

    asyncio.run(seed())

    class MalformedProvider:
        calls = 0
        def __init__(self, **_kwargs): self.express_bus = self
        async def __aenter__(self): return self
        async def __aexit__(self, *_args): pass
        async def timetable_list(self, **_kwargs):
            type(self).calls += 1
            if failure == "json":
                json.loads(b'{"response":')
            if failure == "unicode":
                b'\xffprivate-value'.decode("utf-8")
            if failure == "value":
                raise ValueError("not-a-number-private-value")
            return TagoBusTimetable.model_validate({"charge": "not-a-number-private-value"})

    client.app.state.settings.data_go_kr_service_key = "test-key"
    params = dict(service_type="express", departure_terminal_id="A", arrival_terminal_id="B", date=today.isoformat())
    with patch("app.main.DataGoKrClient", MalformedProvider):
        response = client.get("/v1/transport/bus/timetable", params=params)
    assert MalformedProvider.calls == 1
    assert response.status_code == (200 if has_saved else 502)
    assert "not-a-number-private-value" not in response.text
    if has_saved:
        payload = response.json()
        assert payload["stored"] and payload["stale"]
        assert payload["refresh_status"] == "upstream_error"
        assert BusTimetableResponse.model_validate(payload).fetched_at == saved_at
    stored = client.get("/v1/transport/bus/timetable", params={**params, "stored_only": True})
    assert stored.status_code == (200 if has_saved else 404)
