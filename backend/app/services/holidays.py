from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree

import httpx
from kasi import KasiClient
from kasi.exceptions import KasiError

from app.core.config import Settings
from app.core.time_utils import now_utc

HOLIDAY_ENDPOINT = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"
SUCCESS_RESULT_CODES = {"00", "0"}
WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]

SAMPLE_HOLIDAYS = [
    (date(2025, 5, 5), "어린이날"),
    (date(2025, 6, 6), "현충일"),
    (date(2025, 8, 15), "광복절"),
    (date(2025, 10, 3), "개천절"),
    (date(2025, 10, 9), "한글날"),
    (date(2025, 12, 25), "기독탄신일"),
    (date(2026, 1, 1), "신정"),
    (date(2026, 2, 16), "설날"),
    (date(2026, 2, 17), "설날"),
    (date(2026, 2, 18), "설날"),
    (date(2026, 3, 2), "삼일절 대체공휴일"),
    (date(2026, 5, 5), "어린이날"),
    (date(2026, 5, 25), "부처님오신 날"),
]


@dataclass(frozen=True, slots=True)
class HolidayItem:
    local_date: date
    name: str
    is_holiday: bool = True


@dataclass(frozen=True, slots=True)
class HolidaySourceResponse:
    source: str
    endpoint: str
    request_params: dict[str, Any]
    status_code: int
    body_text: str


@dataclass(frozen=True, slots=True)
class HolidayLookupResult:
    source: str
    status: str
    error_message: str | None
    items: list[HolidayItem]


class HolidayClient:
    async def fetch_month(self, year: int, month: int) -> HolidaySourceResponse:
        raise NotImplementedError


class FixtureHolidayClient(HolidayClient):
    async def fetch_month(self, year: int, month: int) -> HolidaySourceResponse:
        return HolidaySourceResponse(
            source="sample_holiday_info",
            endpoint=HOLIDAY_ENDPOINT,
            request_params={"solYear": year, "solMonth": f"{month:02d}"},
            status_code=200,
            body_text=_build_sample_holiday_xml(year, month),
        )


class KasiHolidayClient(HolidayClient):
    """`python-kasi-api`(`kasi`)의 `holidays()`(`SpcdeInfoService/getRestDeInfo`)를
    통해 공휴일을 조회한다. HTTP 호출과 응답 파싱은 kasi가 대신하고, 이 클라이언트는
    kasi의 정규화된 `raw` item mapping을 기존 `parse_holiday_response` 경로로 넘긴다
    (ADR-004의 provider 라이브러리 원칙 적용)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.data_go_kr_service_key:
            raise ValueError("공공데이터 서비스키가 필요합니다.")
        self.settings = settings

    async def fetch_month(self, year: int, month: int) -> HolidaySourceResponse:
        params = {"solYear": str(year), "solMonth": f"{month:02d}"}
        async with KasiClient(
            service_key=self.settings.data_go_kr_service_key,
            timeout=self.settings.api_timeout_seconds,
        ) as client:
            page = await client.holidays(sol_year=year, sol_month=month, num_of_rows=50)
        if page.total_count is None or page.total_count != len(page.items):
            raise ValueError("공휴일 월별 응답의 완전성을 확인할 수 없습니다.")
        raw_items = [dict(item.raw) for item in page.items]
        return HolidaySourceResponse(
            source="kasi_holiday_info",
            endpoint=HOLIDAY_ENDPOINT,
            request_params=params,
            status_code=200,
            body_text=json.dumps(raw_items, ensure_ascii=False),
        )


class HolidayService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = _build_client(settings)
        self._cache: dict[tuple[int, int], tuple[datetime, HolidayLookupResult]] = {}

    async def get_holidays(self, start_date: date, end_date: date) -> HolidayLookupResult:
        if end_date < start_date:
            return HolidayLookupResult(source="none", status="success", error_message=None, items=[])
        if self.client is None:
            return HolidayLookupResult(
                source="disabled",
                status="config_error",
                error_message="공휴일 API 서비스키가 설정되지 않았습니다.",
                items=[],
            )

        items: list[HolidayItem] = []
        errors: list[str] = []
        sources: set[str] = set()

        for year, month in _iter_months(start_date, end_date):
            result = await self._get_month(year, month)
            sources.add(result.source)
            if result.error_message:
                errors.append(result.error_message)
            items.extend(
                item
                for item in result.items
                if item.is_holiday and start_date <= item.local_date <= end_date
            )

        unique_items = _deduplicate_holidays(items)
        status = "success"
        if errors:
            status = "upstream_error"
        elif sources == {"sample_holiday_info"}:
            status = "sample"

        return HolidayLookupResult(
            source=",".join(sorted(sources)) or "none",
            status=status,
            error_message="\n".join(errors) if errors else None,
            items=unique_items,
        )

    async def get_recent_holidays(self, end_date: date, limit: int = 8) -> HolidayLookupResult:
        start_date = end_date - timedelta(days=730)
        result = await self.get_holidays(start_date, end_date)
        by_date = collapse_holidays_by_date(result.items)
        return HolidayLookupResult(
            source=result.source,
            status=result.status,
            error_message=result.error_message,
            items=sorted(by_date, key=lambda item: item.local_date, reverse=True)[:limit],
        )

    async def _get_month(self, year: int, month: int) -> HolidayLookupResult:
        cache_key = (year, month)
        current_time = now_utc()
        cached = self._cache.get(cache_key)
        if cached and cached[0] > current_time:
            return cached[1]

        try:
            response = await self.client.fetch_month(year, month) if self.client else None
            if response is None:
                raise ValueError("공휴일 API 클라이언트가 설정되지 않았습니다.")
            items, error_message = parse_holiday_response(response.body_text)
            if any((item.local_date.year, item.local_date.month) != (year, month) for item in items):
                error_message = "holiday API error: response month mismatch"
            result = HolidayLookupResult(
                source=response.source,
                status="upstream_error" if error_message else "success",
                error_message=error_message,
                items=items,
            )
        except (httpx.HTTPError, ElementTree.ParseError, ValueError, json.JSONDecodeError, KasiError) as exc:
            result = HolidayLookupResult(
                source="kasi_holiday_info",
                status="upstream_error",
                error_message=f"공휴일 API 응답을 읽지 못했습니다. {type(exc).__name__}",
                items=[],
            )

        expires_at = current_time + timedelta(seconds=max(self.settings.holiday_cache_seconds, 0))
        self._cache[cache_key] = (expires_at, result)
        return result


def parse_holiday_response(body_text: str) -> tuple[list[HolidayItem], str | None]:
    stripped = body_text.strip()
    if not stripped:
        return [], "holiday API error: empty response"
    if stripped.startswith("["):
        return _parse_holiday_raw_items(stripped)
    if stripped.startswith("{"):
        return _parse_holiday_json(stripped)
    return _parse_holiday_xml(stripped)


def _parse_holiday_raw_items(body_text: str) -> tuple[list[HolidayItem], str | None]:
    # kasi already validated the response envelope (result code, auth, rate
    # limit) and raises KasiError on failure, so a raw item list here is
    # already a success response — no envelope/result_code check needed.
    raw_items = json.loads(body_text)
    items = []
    incomplete = False
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            incomplete = True
            continue
        parsed = _parse_holiday_fields(raw_item)
        if parsed is not None:
            items.append(parsed)
        else:
            incomplete = True
    return _deduplicate_holidays(items), "holiday API error: incomplete calendar rows" if incomplete else None


def collapse_holidays_by_date(items: list[HolidayItem]) -> list[HolidayItem]:
    names_by_date: dict[date, set[str]] = {}
    for item in items:
        names_by_date.setdefault(item.local_date, set()).add(item.name)
    return [
        HolidayItem(local_date=local_date, name=" / ".join(sorted(names)))
        for local_date, names in names_by_date.items()
    ]


def format_holiday_sentence(items: list[HolidayItem]) -> str:
    if not items:
        return "지난주, 이번주, 다음주에는 공휴일이 없습니다."
    labels = [
        f"{item.local_date.month}/{item.local_date.day} ({WEEKDAY_LABELS[item.local_date.weekday()]}) {item.name}"
        for item in items
    ]
    return f"{', '.join(labels)} 입니다."


def _parse_holiday_xml(body_text: str) -> tuple[list[HolidayItem], str | None]:
    root = ElementTree.fromstring(body_text)
    result_code = _find_text(root, "resultCode")
    result_message = _find_text(root, "resultMsg")
    if result_code and result_code not in SUCCESS_RESULT_CODES:
        return [], f"holiday API error {result_code}: {result_message or 'UNKNOWN ERROR'}"

    items: list[HolidayItem] = []
    incomplete = False
    for element in root.findall(".//item"):
        parsed = _parse_holiday_fields(
            {
                "dateName": _find_text(element, "dateName"),
                "isHoliday": _find_text(element, "isHoliday"),
                "locdate": _find_text(element, "locdate"),
            }
        )
        if parsed is not None:
            items.append(parsed)
        else:
            incomplete = True
    return _deduplicate_holidays(items), "holiday API error: incomplete calendar rows" if incomplete else None


def _parse_holiday_json(body_text: str) -> tuple[list[HolidayItem], str | None]:
    document = json.loads(body_text)
    response = document.get("response", {})
    header = response.get("header", {})
    result_code = str(header.get("resultCode") or "").strip()
    result_message = str(header.get("resultMsg") or "").strip()
    if result_code and result_code not in SUCCESS_RESULT_CODES:
        return [], f"holiday API error {result_code}: {result_message or 'UNKNOWN ERROR'}"

    raw_items = response.get("body", {}).get("items", {})
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("item", [])
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        raw_items = []

    items = []
    incomplete = False
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            incomplete = True
            continue
        parsed = _parse_holiday_fields(raw_item)
        if parsed is not None:
            items.append(parsed)
        else:
            incomplete = True
    return _deduplicate_holidays(items), "holiday API error: incomplete calendar rows" if incomplete else None


def _parse_holiday_fields(item: dict[str, Any]) -> HolidayItem | None:
    name = str(item.get("dateName") or item.get("date_name") or "").strip()
    locdate = str(item.get("locdate") or "").strip()
    holiday_flag = str(item.get("isHoliday") or "").strip().upper()
    is_holiday = holiday_flag == "Y"
    if not name or len(locdate) != 8 or not locdate.isascii() or not locdate.isdecimal() or holiday_flag not in {"Y", "N"}:
        return None
    try:
        local_date = datetime.strptime(locdate, "%Y%m%d").date()
    except ValueError:
        return None
    return HolidayItem(local_date=local_date, name=name, is_holiday=is_holiday)


def _find_text(root: ElementTree.Element, tag_name: str) -> str | None:
    element = root.find(f".//{tag_name}")
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _iter_months(start_date: date, end_date: date) -> list[tuple[int, int]]:
    cursor = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)
    months: list[tuple[int, int]] = []
    while cursor <= end_month:
        months.append((cursor.year, cursor.month))
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def _deduplicate_holidays(items: list[HolidayItem]) -> list[HolidayItem]:
    seen: set[tuple[date, str]] = set()
    unique: list[HolidayItem] = []
    for item in sorted(items, key=lambda holiday: (holiday.local_date, holiday.name)):
        key = (item.local_date, item.name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _build_client(settings: Settings) -> HolidayClient | None:
    if settings.data_go_kr_service_key:
        return KasiHolidayClient(settings)
    if settings.use_sample_client_when_no_key:
        return FixtureHolidayClient()
    return None


def _build_sample_holiday_xml(year: int, month: int) -> str:
    item_xml = []
    for local_date, name in SAMPLE_HOLIDAYS:
        if local_date.year == year and local_date.month == month:
            item_xml.append(
                "<item>"
                f"<dateName>{name}</dateName>"
                "<isHoliday>Y</isHoliday>"
                f"<locdate>{local_date:%Y%m%d}</locdate>"
                "</item>"
            )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>NORMAL SERVICE.</resultMsg>
  </header>
  <body>
    <items>
      {"".join(item_xml)}
    </items>
  </body>
</response>
"""
