from __future__ import annotations

import json
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest
from krairport.exceptions import KrairportRateLimitError

from app.core.config import Settings
from app.services.collection import (
    CollectionService,
    FixturePublicDataClient,
    KrairportPublicDataClient,
    build_public_data_client,
    compute_upstream_rate_limit_retry_at,
    is_upstream_rate_limit_error,
    normalize_upstream_rate_limit_error,
    validate_source_response_body,
)


def _mock_krairport_client(**method_results: object) -> AsyncMock:
    """Build a mock standing in for `async with AsyncKrairportClient(...) as client`.

    `method_results` maps method name (`kac_raw_items`/`iiac_raw_items`) to
    either a return value or an exception instance to raise.
    """

    client = AsyncMock()
    for name, result in method_results.items():
        method = getattr(client, name)
        if isinstance(result, Exception):
            method.side_effect = result
        else:
            method.return_value = result

    context_manager = AsyncMock()
    context_manager.__aenter__.return_value = client
    context_manager.__aexit__.return_value = False
    return context_manager


def test_build_public_data_client_uses_fixture_without_key() -> None:
    settings = Settings(
        data_go_kr_service_key=None,
        use_sample_client_when_no_key=True,
    )

    client = build_public_data_client(settings)

    assert isinstance(client, FixturePublicDataClient)


def test_postgres_collection_lease_keeps_lock_on_dedicated_connection() -> None:
    class LockConnection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def scalar(self, statement):
            self.statements.append(str(statement))
            return True

    async def run() -> None:
        connection = LockConnection()
        engine = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"),
            connect=lambda: connection,
        )
        session = SimpleNamespace(bind=engine)
        service = CollectionService(Settings(use_sample_client_when_no_key=True), client=FixturePublicDataClient())

        async with service._postgres_collection_lease(session) as acquired:
            assert acquired is True
            # 수집 세션이 commit해도 lock owner인 connection은 context exit까지 유지된다.
            assert len(connection.statements) == 1

        assert len(connection.statements) == 2
        assert "pg_try_advisory_lock" in connection.statements[0]
        assert "pg_advisory_unlock" in connection.statements[1]

    asyncio.run(run())


def test_build_public_data_client_requires_key_when_sample_disabled() -> None:
    settings = Settings(
        data_go_kr_service_key=None,
        use_sample_client_when_no_key=False,
    )

    with pytest.raises(ValueError):
        build_public_data_client(settings)


def test_build_public_data_client_uses_live_client_with_key() -> None:
    settings = Settings(
        data_go_kr_service_key="test-key",
        use_sample_client_when_no_key=False,
    )

    client = build_public_data_client(settings)

    assert isinstance(client, KrairportPublicDataClient)


def test_collection_service_reports_enabled_sources() -> None:
    settings = Settings(
        use_sample_client_when_no_key=True,
        enable_incheon_collection=True,
        enable_fee_collection=True,
        enable_incheon_fee_collection=True,
    )

    service = CollectionService(settings, client=FixturePublicDataClient())

    assert service.enabled_sources == ["kac_parking", "incheon_parking", "kac_fee", "incheon_fee"]


def test_validate_source_response_body_detects_kac_access_denied() -> None:
    with pytest.raises(ValueError, match="SERVICE ACCESS DENIED ERROR"):
        validate_source_response_body(
            "kac_parking",
            """<?xml version="1.0" encoding="UTF-8"?>
            <response>
              <header>
                <resultCode>99</resultCode>
                <resultMsg>SERVICE ACCESS DENIED ERROR.</resultMsg>
              </header>
            </response>
            """,
        )


def test_validate_source_response_body_detects_incheon_error_payload() -> None:
    with pytest.raises(ValueError, match="INVALID REQUEST"):
        validate_source_response_body(
            "incheon_parking",
            """{
              "response": {
                "header": {
                  "resultCode": "99",
                  "resultMsg": "INVALID REQUEST"
                }
              }
            }""",
        )


def test_validate_source_response_body_detects_incheon_fee_error_payload() -> None:
    with pytest.raises(ValueError, match="SERVICE ACCESS DENIED"):
        validate_source_response_body(
            "incheon_fee",
            """{
              "response": {
                "header": {
                  "resultCode": "99",
                  "resultMsg": "SERVICE ACCESS DENIED"
                }
              }
            }""",
        )


def test_is_upstream_rate_limit_error_detects_quota_message() -> None:
    assert is_upstream_rate_limit_error("kac_parking API error 99: LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.")
    assert not is_upstream_rate_limit_error("kac_parking API error 99: SERVICE ACCESS DENIED ERROR.")


def test_compute_upstream_rate_limit_retry_at_uses_backoff_seconds() -> None:
    reference_at = datetime(2026, 4, 29, 8, 18, 2, tzinfo=ZoneInfo("UTC"))

    blocked_until = compute_upstream_rate_limit_retry_at(reference_at, 3600)

    assert blocked_until == datetime(2026, 4, 29, 9, 18, 2, tzinfo=ZoneInfo("UTC"))


def test_normalize_upstream_rate_limit_error_strips_nested_skip_prefix() -> None:
    normalized = normalize_upstream_rate_limit_error(
        "kac_parking upstream rate limit active until 2026-04-29T15:05:00Z: "
        "kac_parking API error 99: LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR."
    )

    assert normalized == "kac_parking API error 99: LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR."


async def test_krairport_client_fetch_kac_parking_builds_json_source_response() -> None:
    settings = Settings(data_go_kr_service_key="test-key")
    items = [{"aprKor": "김포국제공항", "parkingFullSpace": "2279"}]

    with patch(
        "app.services.collection.AsyncKrairportClient",
        return_value=_mock_krairport_client(kac_raw_items=items),
    ) as client_cls:
        response = await KrairportPublicDataClient(settings).fetch_kac_parking()

    client_cls.assert_called_once()
    assert response.source == "kac_parking"
    assert json.loads(response.body_text) == items
    # krairport already validated resultCode before returning -- the JSON-array
    # body must be recognized as pre-validated by validate_source_response_body.
    validate_source_response_body(response.source, response.body_text)


async def test_krairport_client_fetch_incheon_fee_calls_generic_raw_items_escape_hatch() -> None:
    settings = Settings(data_go_kr_service_key="test-key")
    items = [{"charid": "FB00000001", "chardesc": "최초 00:30 에 한해 1200원 적용"}]
    mock_client = _mock_krairport_client(iiac_raw_items=items)

    with patch("app.services.collection.AsyncKrairportClient", return_value=mock_client):
        response = await KrairportPublicDataClient(settings).fetch_incheon_fee()

    mock_client.__aenter__.return_value.iiac_raw_items.assert_called_once_with(
        "ParkingChargeInfo", "getParkingChargeInformation", {"pageNo": 1, "numOfRows": 100}
    )
    assert response.source == "incheon_fee"
    assert json.loads(response.body_text) == items


async def test_krairport_client_rate_limit_error_propagates_with_detectable_message() -> None:
    """`is_upstream_rate_limit_error` pattern-matches on the exception's `str()`.

    krairport raises `KrairportRateLimitError` with the upstream `resultMsg`
    verbatim as its message, so the marker text must survive unchanged
    through `KrairportPublicDataClient` for the existing backoff logic
    (`CollectionService._safe_fetch` -> `is_upstream_rate_limit_error`) to
    still trip correctly now that the fetch layer is krairport, not raw httpx.
    """

    settings = Settings(data_go_kr_service_key="test-key")
    upstream_error = KrairportRateLimitError("LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.")

    with patch(
        "app.services.collection.AsyncKrairportClient",
        return_value=_mock_krairport_client(kac_raw_items=upstream_error),
    ):
        with pytest.raises(KrairportRateLimitError) as exc_info:
            await KrairportPublicDataClient(settings).fetch_kac_parking()

    assert is_upstream_rate_limit_error(str(exc_info.value))
