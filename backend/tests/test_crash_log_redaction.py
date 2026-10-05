"""예외 경로 로그의 키 가림(적대 리뷰 LOW, 2026-10-05).

scheduler tick이나 `/v1/admin/collect` route가 예외를 내면 traceback이 `str(exc)` 원문을 싣는다.
원문에는 serviceKey가 들어갈 수 있다(httpx 오류의 URL 등). route 예외는 Starlette
ServerErrorMiddleware가 다시 던지고 uvicorn이 `uvicorn.error` logger로 남긴다 — 그래서 검사는
그 logger와 scheduler의 logger에 실제로 남는 글자를 본다.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings
from app.main import _run_scheduler, _run_transport_scheduler, create_app

_SECRET_KEY = "RAW+KEY/abc=="
_LEAKY = f"401 for url 'https://apis.data.go.kr/x?serviceKey=RAW%2BKEY%2Fabc%3D%3D&a=1' key={_SECRET_KEY}"


def _secret_free(text: str) -> bool:
    return "RAW+KEY" not in text and "RAW%2BKEY" not in text


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'crash.sqlite3'}",
        seed_sample_data=False,
        enable_scheduler=False,
        data_go_kr_service_key=_SECRET_KEY,
    )


class _StopLoop(BaseException):
    """scheduler 루프를 첫 tick 뒤에 끝낸다(`except Exception`에 걸리지 않게 BaseException)."""


@pytest.mark.parametrize(
    ("runner", "service_attr", "message"),
    [
        (_run_scheduler, "collection_service", "scheduler tick failed"),
        (_run_transport_scheduler, "transport_collection_service", "transport scheduler tick failed"),
    ],
)
def test_scheduler_tick_failure_log_is_redacted(tmp_path, caplog, runner, service_attr, message) -> None:
    settings = _settings(tmp_path)
    create_app(settings)
    session = SimpleNamespace(rollback=AsyncMock())

    @asynccontextmanager
    async def session_factory():
        yield session

    service = SimpleNamespace(collect=AsyncMock(side_effect=RuntimeError(_LEAKY)))
    app = SimpleNamespace(
        state=SimpleNamespace(session_factory=session_factory, settings=settings, **{service_attr: service})
    )

    with patch("app.main.asyncio.sleep", AsyncMock(side_effect=_StopLoop)):
        with caplog.at_level(logging.ERROR, logger="app.main"):
            with pytest.raises(_StopLoop):
                asyncio.run(runner(app))

    text = caplog.text
    assert message in text, text
    assert "RuntimeError" in text and "serviceKey=<redacted>" in text, text
    assert _secret_free(text), text


def test_uncaught_route_exception_log_is_redacted(tmp_path, caplog) -> None:
    """route 예외(`/v1/admin/collect` 포함 모든 route)가 uvicorn 앞까지 다시 던져지는 것을 확인하고,
    uvicorn이 남기는 그대로 남긴다."""
    from fastapi.testclient import TestClient

    from app.main import create_app as build

    settings = _settings(tmp_path)
    app = build(settings)

    @app.get("/__leak_probe")
    async def leak_probe() -> None:
        raise RuntimeError(_LEAKY)

    with TestClient(app) as client:
        with pytest.raises(RuntimeError) as exc_info:
            client.get("/__leak_probe")

    # uvicorn(protocols/http/*_impl.py)의 `self.logger.error("Exception in ASGI application\n", exc_info=exc)`와 같다.
    uvicorn_logger = logging.getLogger("uvicorn.error")
    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        uvicorn_logger.error("Exception in ASGI application\n", exc_info=exc_info.value)

    text = caplog.text
    assert "Exception in ASGI application" in text and "RuntimeError" in text, text
    assert "serviceKey=<redacted>" in text, text
    assert _secret_free(text), text
