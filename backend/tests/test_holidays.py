from __future__ import annotations

import json
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from kasi.exceptions import KasiRateLimitError

from app.core.config import Settings
from app.services.holidays import (
    HolidayItem,
    KasiHolidayClient,
    collapse_holidays_by_date,
    format_holiday_sentence,
    parse_holiday_response,
)


def _mock_kasi_client(**method_results: object) -> AsyncMock:
    """Build a mock standing in for `async with KasiClient(...) as client`."""

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


def test_parse_holiday_xml_normalizes_public_holiday_items() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>NORMAL SERVICE.</resultMsg>
  </header>
  <body>
    <items>
      <item>
        <dateName>어린이날</dateName>
        <isHoliday>Y</isHoliday>
        <locdate>20260505</locdate>
      </item>
      <item>
        <dateName>기념일</dateName>
        <isHoliday>N</isHoliday>
        <locdate>20260509</locdate>
      </item>
    </items>
  </body>
</response>
"""

    items, error_message = parse_holiday_response(body)

    assert error_message is None
    assert len(items) == 2
    assert items[0].local_date == date(2026, 5, 5)
    assert items[0].name == "어린이날"
    assert items[0].is_holiday is True
    assert items[1].is_holiday is False


def test_parse_holiday_json_reports_upstream_error() -> None:
    body = """{
      "response": {
        "header": {
          "resultCode": "99",
          "resultMsg": "SERVICE ACCESS DENIED ERROR."
        }
      }
    }"""

    items, error_message = parse_holiday_response(body)

    assert items == []
    assert error_message == "holiday API error 99: SERVICE ACCESS DENIED ERROR."


def test_parse_holiday_response_accepts_raw_item_list() -> None:
    body = json.dumps(
        [
            {"dateName": "어린이날", "isHoliday": "Y", "locdate": "20260505"},
            {"dateName": "기념일", "isHoliday": "N", "locdate": "20260509"},
        ]
    )

    items, error_message = parse_holiday_response(body)

    assert error_message is None
    assert len(items) == 2
    assert items[0].local_date == date(2026, 5, 5)
    assert items[0].name == "어린이날"
    assert items[0].is_holiday is True
    assert items[1].is_holiday is False


class _FakeSpecialDay:
    def __init__(self, raw: dict[str, object]) -> None:
        self.raw = raw


class _FakePage:
    def __init__(self, items: list[_FakeSpecialDay]) -> None:
        self.items = items
        self.total_count = len(items)


@pytest.mark.asyncio
async def test_kasi_holiday_client_fetch_month_builds_json_source_response() -> None:
    settings = Settings(data_go_kr_service_key="test-key")
    page = _FakePage(
        [_FakeSpecialDay({"dateName": "어린이날", "isHoliday": "Y", "locdate": "20260505"})]
    )
    mock_client = _mock_kasi_client(holidays=page)

    with patch("app.services.holidays.KasiClient", return_value=mock_client):
        client = KasiHolidayClient(settings)
        response = await client.fetch_month(2026, 5)

    assert response.source == "kasi_holiday_info"
    items, error_message = parse_holiday_response(response.body_text)
    assert error_message is None
    assert items == [HolidayItem(local_date=date(2026, 5, 5), name="어린이날")]


@pytest.mark.asyncio
async def test_kasi_holiday_client_rate_limit_error_propagates() -> None:
    settings = Settings(data_go_kr_service_key="test-key")
    mock_client = _mock_kasi_client(holidays=KasiRateLimitError("LIMITED"))

    with patch("app.services.holidays.KasiClient", return_value=mock_client):
        client = KasiHolidayClient(settings)
        with pytest.raises(KasiRateLimitError):
            await client.fetch_month(2026, 5)


def test_format_holiday_sentence_collapses_same_date_names() -> None:
    items = collapse_holidays_by_date(
        [
            HolidayItem(local_date=date(2026, 5, 5), name="어린이날"),
            HolidayItem(local_date=date(2026, 5, 5), name="부처님오신 날"),
        ]
    )

    assert format_holiday_sentence(items) == "5/5 (화) 부처님오신 날 / 어린이날 입니다."


@pytest.mark.parametrize("row", [
    {"locdate": "20260928", "isHoliday": "Y"},
    {"locdate": "20260928", "dateName": "휴일"},
    {"locdate": "20260928", "dateName": "휴일", "isHoliday": "unknown"},
    {"locdate": "20260999", "dateName": "휴일", "isHoliday": "Y"},
    None,
])
def test_incomplete_rows_are_not_a_successful_empty_calendar(row):
    items, error = parse_holiday_response(json.dumps([row]))
    assert items == []
    assert error == "holiday API error: incomplete calendar rows"
    assert parse_holiday_response("[]") == ([], None)


@pytest.mark.asyncio
@pytest.mark.parametrize("total", [None, 51])
async def test_kasi_calendar_requires_complete_month_metadata(total):
    page = _FakePage([])
    page.total_count = total
    with patch("app.services.holidays.KasiClient", return_value=_mock_kasi_client(holidays=page)):
        with pytest.raises(ValueError, match="완전성"):
            await KasiHolidayClient(Settings(data_go_kr_service_key="fake")).fetch_month(2026, 9)
