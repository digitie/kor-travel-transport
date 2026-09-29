from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
from krairport import Flight, KrairportClient
from krairport.exceptions import KrairportError, KrairportRateLimitError

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc

KAC_FLIGHT_STATUS_ENDPOINT = "http://openapi.airport.co.kr/service/rest/FlightStatusList/getFlightStatusList"
KAC_FLIGHT_DETAIL_STATUS_ENDPOINT = "https://api.odcloud.kr/api/FlightStatusListDTL/v1/getFlightStatusListDetail"
KAC_FLIGHT_GATEWAY_ENDPOINT = "https://apis.data.go.kr/B551178/flight-status"
INCHEON_FLIGHT_ARRIVALS_ENDPOINT = "http://apis.data.go.kr/B551177/StatusOfPassengerFlightsDeOdp/getPassengerArrivalsDeOdp"
INCHEON_FLIGHT_DEPARTURES_ENDPOINT = "http://apis.data.go.kr/B551177/StatusOfPassengerFlightsDeOdp/getPassengerDeparturesDeOdp"
SUCCESS_RESULT_CODES = {"00", "0"}
SERVICE_KEY_PATTERN = re.compile(r"(serviceKey=)[^&'\"\s]+", re.IGNORECASE)

SAMPLE_FLIGHT_ITEMS: dict[str, list[dict[str, str]]] = {
    "GMP": [
        {
            "airFln": "KE1101",
            "airlineKorean": "대한항공",
            "boardingKor": "김포",
            "arrivedKor": "제주",
            "io": "O",
            "line": "국내",
            "std": "0830",
            "etd": "0840",
            "rmkKor": "출발",
        },
        {
            "airFln": "OZ8922",
            "airlineKorean": "아시아나항공",
            "boardingKor": "제주",
            "arrivedKor": "김포",
            "io": "I",
            "line": "국내",
            "std": "1015",
            "etd": "1020",
            "rmkKor": "도착",
        },
    ],
    "PUS": [
        {
            "airFln": "BX8804",
            "airlineKorean": "에어부산",
            "boardingKor": "김해",
            "arrivedKor": "김포",
            "io": "O",
            "line": "국내",
            "std": "0910",
            "etd": "0910",
            "rmkKor": "출발",
        },
        {
            "airFln": "7C505",
            "airlineKorean": "제주항공",
            "boardingKor": "제주",
            "arrivedKor": "김해",
            "io": "I",
            "line": "국내",
            "std": "1125",
            "etd": "1128",
            "rmkKor": "도착",
        },
    ],
    "CJU": [
        {
            "airFln": "LJ501",
            "airlineKorean": "진에어",
            "boardingKor": "제주",
            "arrivedKor": "김포",
            "io": "O",
            "line": "국내",
            "std": "0745",
            "etd": "0745",
            "rmkKor": "출발",
        },
        {
            "airFln": "KE1207",
            "airlineKorean": "대한항공",
            "boardingKor": "김포",
            "arrivedKor": "제주",
            "io": "I",
            "line": "국내",
            "std": "1240",
            "etd": "1247",
            "rmkKor": "도착",
        },
    ],
    "ICN": [
        {
            "direction": "departure",
            "airline": "대한항공",
            "flightId": "KE901",
            "scheduleDateTime": "202604250930",
            "estimatedDateTime": "202604250945",
            "airport": "파리/샤를드골",
            "remark": "출발",
            "typeOfFlight": "I",
        },
        {
            "direction": "arrival",
            "airline": "아시아나항공",
            "flightId": "OZ202",
            "scheduleDateTime": "202604251120",
            "estimatedDateTime": "202604251128",
            "airport": "로스앤젤레스",
            "remark": "도착",
            "typeOfFlight": "I",
        },
    ],
}


@dataclass(slots=True)
class FlightSourceResponse:
    source: str
    endpoint: str
    request_params: dict[str, Any]
    status_code: int
    body_text: str
    flights: tuple[Flight, ...] | None = None


class FlightStatusClient:
    async def fetch_status(self, airport_code: str, local_date: date) -> FlightSourceResponse:
        raise NotImplementedError


class FlightStatusUpstreamError(RuntimeError):
    pass


class FixtureFlightStatusClient(FlightStatusClient):
    async def fetch_status(self, airport_code: str, local_date: date) -> FlightSourceResponse:
        if airport_code.upper() == "ICN":
            return FlightSourceResponse(
                source="sample_incheon_flight_status",
                endpoint=INCHEON_FLIGHT_DEPARTURES_ENDPOINT,
                request_params={"airport_code": airport_code, "local_date": local_date.isoformat()},
                status_code=200,
                body_text=_build_sample_incheon_flight_json(),
            )

        return FlightSourceResponse(
            source="sample_flight_status",
            endpoint=KAC_FLIGHT_STATUS_ENDPOINT,
            request_params={"schAirCode": airport_code},
            status_code=200,
            body_text=_build_sample_flight_xml(airport_code),
        )


class KrairportFlightStatusClient(FlightStatusClient):
    """KAC는 provider의 typed GW 조회, IIAC는 기존 raw 조회를 사용한다.

    GW 필드/시각/페이지 해석은 형제 라이브러리에 맡긴다(ADR-004).
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.data_go_kr_service_key:
            raise ValueError("공공데이터 서비스 키가 필요합니다.")
        self.settings = settings

    async def fetch_status(self, airport_code: str, local_date: date) -> FlightSourceResponse:
        if airport_code.upper() == "ICN":
            return await self._fetch_incheon_status(local_date)
        return await self._fetch_kac_status(airport_code, local_date)

    async def _fetch_kac_status(self, airport_code: str, local_date: date) -> FlightSourceResponse:
        async with KrairportClient(
            kac_service_key=self.settings.data_go_kr_service_key,
            iiac_service_key=self.settings.data_go_kr_service_key,
            timeout=self.settings.api_timeout_seconds,
            retries=0,
        ) as client:
            flights = await client.kac.flight_status(
                airport_code=airport_code,
                searchday=local_date.strftime("%Y%m%d"),
                num_of_rows=100,
                max_pages=20,
            )
        return FlightSourceResponse(
            source="kac_flight_status_gateway",
            endpoint=KAC_FLIGHT_GATEWAY_ENDPOINT,
            request_params={"airport_code": airport_code.upper(), "local_date": local_date.isoformat()},
            status_code=200,
            body_text="",
            flights=tuple(flights),
        )

    async def _fetch_incheon_status(self, local_date: date) -> FlightSourceResponse:
        request_date = local_date.strftime("%Y%m%d")
        base_params = {
            "pageNo": 1,
            "numOfRows": 500,
            "searchday": request_date,
            "from_time": "0000",
            "to_time": "2400",
            "lang": "K",
            "inqtimechcd": "E",
        }
        async with KrairportClient(
            kac_service_key=self.settings.data_go_kr_service_key,
            iiac_service_key=self.settings.data_go_kr_service_key,
            timeout=self.settings.api_timeout_seconds,
        ) as client:
            departures = await client.iiac_raw_items(
                "StatusOfPassengerFlightsDeOdp", "getPassengerDeparturesDeOdp", base_params
            )
            arrivals = await client.iiac_raw_items(
                "StatusOfPassengerFlightsDeOdp", "getPassengerArrivalsDeOdp", base_params
            )
        return FlightSourceResponse(
            source="incheon_flight_status",
            endpoint=INCHEON_FLIGHT_DEPARTURES_ENDPOINT,
            request_params={**base_params, "endpoints": ["arrivals", "departures"]},
            status_code=200,
            body_text=json.dumps({"departures": departures, "arrivals": arrivals}, ensure_ascii=False),
        )


class FlightStatusService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = _build_client(settings)
        self._cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}

    async def get_status(self, airport_code: str, local_date: date) -> dict[str, Any]:
        airport_code = airport_code.upper()
        cache_key = (airport_code, local_date.isoformat())
        cached = self._cache.get(cache_key)
        current_time = now_utc()

        if cached and cached[0] > current_time:
            return cached[1]

        payload = await self._fetch_status(airport_code, local_date)
        status = payload.get("status")
        if status == "rate_limited":
            # Flight status is fetched on-demand per page view (no scheduler,
            # unlike CollectionService's DB-backed rate-limit tracking), so
            # without a longer backoff every visitor during a rate-limit
            # window would re-trigger another upstream call and keep
            # renewing it.
            backoff_seconds = self.settings.upstream_rate_limit_backoff_seconds
            expires_at = current_time + timedelta(seconds=max(backoff_seconds, 0))
            self._cache[cache_key] = (expires_at, payload)
        elif status != "upstream_error":
            expires_at = current_time + timedelta(seconds=max(self.settings.flight_status_cache_seconds, 0))
            self._cache[cache_key] = (expires_at, payload)
        return payload

    async def _fetch_status(self, airport_code: str, local_date: date) -> dict[str, Any]:
        base_payload = {
            "generated_at": now_utc(),
            "airport_code": airport_code,
            "local_date": local_date.isoformat(),
            "source": "kac_flight_status",
            "status": "success",
            "error_message": None,
            "items": [],
        }

        if not self.settings.enable_flight_status_markers:
            return {**base_payload, "source": "disabled", "status": "disabled"}

        if self.client is None:
            return {
                **base_payload,
                "status": "config_error",
                "error_message": "비행편 API 서비스 키가 설정되지 않았습니다.",
            }

        try:
            response = await self.client.fetch_status(airport_code, local_date)
            if response.source == "kac_flight_status_gateway":
                if response.flights is None:
                    raise FlightStatusUpstreamError("항공편 응답이 없습니다.")
                items = []
                for flight in response.flights:
                    if not flight.flight_id or flight.scheduled_at is None:
                        raise FlightStatusUpstreamError("항공편 예정시각 또는 편명이 없습니다.")
                    items.append({
                        "airport_code": flight.airport_code, "direction": str(flight.direction),
                        "flight_number": flight.flight_id, "airline": flight.airline_name,
                        "scheduled_at": serialize_utc(flight.scheduled_at),
                        "estimated_at": serialize_utc(flight.estimated_at) if flight.estimated_at else None,
                        "marker_at": serialize_utc(flight.estimated_at or flight.scheduled_at),
                        "origin_airport": flight.departure_airport_name or flight.departure_airport_code or "-",
                        "destination_airport": flight.arrival_airport_name or flight.arrival_airport_code or "-",
                        "status": flight.status_korean or flight.status_english,
                        "line_type": flight.line_type,
                        "_codeshare_identity": (
                            flight.airport_code, str(flight.direction),
                            serialize_utc(flight.scheduled_at),
                            flight.master_flight_id or flight.flight_id,
                        ),
                    })
                items = _deduplicate_codeshare_flights(items)
                items.sort(key=lambda flight: (flight["marker_at"], flight["flight_number"]))
                error_message = None
            elif response.source in {"incheon_flight_status", "sample_incheon_flight_status"}:
                items, error_message = parse_incheon_flight_status_json(response.body_text, local_date, self.settings.app_timezone)
            elif response.source == "kac_flight_detail_status":
                items, error_message = parse_kac_flight_detail_json(
                    response.body_text,
                    airport_code,
                    local_date,
                    self.settings.app_timezone,
                )
            else:
                items, error_message = parse_flight_status_xml(
                    response.body_text,
                    airport_code,
                    local_date,
                    self.settings.app_timezone,
                )
        except (
            FlightStatusUpstreamError,
            httpx.HTTPError,
            ElementTree.ParseError,
            ValueError,
            KrairportError,
        ) as exc:
            # KrairportRateLimitError gets its own status (see get_status's
            # longer backoff cache) instead of the generic upstream_error,
            # which is never cached and would let every page view re-trigger
            # another rate-limited upstream call.
            status = "rate_limited" if isinstance(exc, KrairportRateLimitError) else "upstream_error"
            return {
                **base_payload,
                "status": status,
                "error_message": _build_flight_api_error_message(
                    exc,
                    self.settings.data_go_kr_service_key,
                ),
            }

        status = "sample" if response.source in {"sample_flight_status", "sample_incheon_flight_status"} else "success"
        if error_message:
            status = "upstream_error"

        return {
            **base_payload,
            "source": response.source,
            "status": status,
            "error_message": error_message,
            "items": items,
        }


def parse_flight_status_xml(
    body_text: str,
    airport_code: str,
    local_date: date,
    tz_name: str = "Asia/Seoul",
) -> tuple[list[dict[str, Any]], str | None]:
    root = ElementTree.fromstring(body_text)
    result_code = _find_text(root, "resultCode")
    result_message = _find_text(root, "resultMsg")

    if result_code and result_code not in SUCCESS_RESULT_CODES:
        message = result_message or "UNKNOWN ERROR"
        return [], f"kac_flight_status API error {result_code}: {message}"

    items: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        parsed = _parse_flight_item(item, airport_code, local_date, tz_name)
        if parsed is not None:
            items.append(parsed)

    items = _deduplicate_codeshare_flights(items)
    items.sort(key=lambda flight: (flight["marker_at"], flight["flight_number"]))
    return items, None


def parse_kac_flight_detail_json(
    body_text: str,
    airport_code: str,
    local_date: date,
    tz_name: str = "Asia/Seoul",
) -> tuple[list[dict[str, Any]], str | None]:
    document = json.loads(body_text)
    data = document.get("data", [])
    if not isinstance(data, list):
        message = str(document.get("message") or document.get("error") or "UNKNOWN ERROR").strip()
        return [], f"kac_flight_detail_status API error: {message}"

    items: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        parsed = _parse_kac_detail_flight_item(item, airport_code, local_date, tz_name)
        if parsed is not None:
            items.append(parsed)

    items = _deduplicate_codeshare_flights(items)
    items.sort(key=lambda flight: (flight["marker_at"], flight["flight_number"]))
    return items, None


def parse_incheon_flight_status_json(
    body_text: str,
    local_date: date,
    tz_name: str = "Asia/Seoul",
) -> tuple[list[dict[str, Any]], str | None]:
    document = json.loads(body_text)
    items: list[dict[str, Any]] = []
    errors: list[str] = []

    for key, direction in (("departures", "departure"), ("arrivals", "arrival")):
        raw_items, error = _incheon_flight_section_items(document.get(key), key)
        if error:
            errors.append(error)
            continue

        for item in raw_items:
            parsed = _parse_incheon_flight_item(item, direction, local_date, tz_name)
            if parsed is not None:
                items.append(parsed)

    items = _deduplicate_codeshare_flights(items)
    items.sort(key=lambda flight: (flight["marker_at"], flight["flight_number"]))
    return items, "\n".join(errors) if errors else None


def _build_client(settings: Settings) -> FlightStatusClient | None:
    if settings.data_go_kr_service_key:
        return KrairportFlightStatusClient(settings)
    if settings.use_sample_client_when_no_key:
        return FixtureFlightStatusClient()
    return None


def _build_flight_api_error_message(exc: Exception, service_key: str | None) -> str:
    sanitized_error = _sanitize_upstream_error(exc, service_key)
    return f"비행편 API 응답을 읽지 못했습니다: {sanitized_error}"


def _sanitize_upstream_error(error: Exception | str, service_key: str | None) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        body = _sanitize_upstream_error(response.text, service_key) if response is not None else ""
        if body:
            return f"HTTP {response.status_code}: {body}"
        if response is not None:
            return f"HTTP {response.status_code}"

    message = str(error).strip() or error.__class__.__name__
    if service_key:
        message = message.replace(service_key, "<redacted>")
    message = SERVICE_KEY_PATTERN.sub(r"\1<redacted>", message)
    return " ".join(message.split())


def _deduplicate_codeshare_flights(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in items:
        key = item.get("_codeshare_identity") or (
            str(item.get("direction") or ""),
            item.get("marker_at"),
            str(item.get("origin_airport") or "").strip(),
            str(item.get("destination_airport") or "").strip(),
        )
        grouped.setdefault(key, []).append(item)

    deduplicated: list[dict[str, Any]] = []
    for group in grouped.values():
        if len(group) == 1:
            item = {**group[0]}
            item.pop("_codeshare_identity", None)
            item["codeshare_flight_numbers"] = [str(item.get("flight_number") or "").strip()]
            deduplicated.append(item)
            continue

        ordered_group = sorted(group, key=lambda flight: str(flight.get("flight_number") or ""))
        representative = {**next((flight for flight in ordered_group
            if flight.get("_codeshare_identity")
            and flight["flight_number"] == flight["_codeshare_identity"][-1]), ordered_group[0])}
        representative.pop("_codeshare_identity", None)
        flight_numbers = _unique_text_values(ordered_group, "flight_number")
        airlines = _unique_text_values(ordered_group, "airline")
        representative["flight_number"] = " / ".join(flight_numbers)
        representative["codeshare_flight_numbers"] = flight_numbers
        representative["airline"] = " / ".join(airlines) if airlines else None
        deduplicated.append(representative)

    return deduplicated


def _unique_text_values(items: list[dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item.get(key) or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _build_sample_flight_xml(airport_code: str) -> str:
    items = SAMPLE_FLIGHT_ITEMS.get(airport_code.upper(), SAMPLE_FLIGHT_ITEMS["GMP"])
    item_xml = []
    for item in items:
        item_xml.append("<item>" + "".join(f"<{key}>{value}</{key}>" for key, value in item.items()) + "</item>")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>NORMAL SERVICE</resultMsg>
  </header>
  <body>
    <items>
      {"".join(item_xml)}
    </items>
  </body>
</response>
"""


def _build_sample_incheon_flight_json() -> str:
    items = SAMPLE_FLIGHT_ITEMS["ICN"]
    arrivals = [item for item in items if item["direction"] == "arrival"]
    departures = [item for item in items if item["direction"] == "departure"]
    return json.dumps(
        {
            "arrivals": {
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                    "body": {"items": arrivals},
                }
            },
            "departures": {
                "response": {
                    "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                    "body": {"items": departures},
                }
            },
        },
        ensure_ascii=False,
    )


def _parse_flight_item(
    item: ElementTree.Element,
    airport_code: str,
    local_date: date,
    tz_name: str,
) -> dict[str, Any] | None:
    flight_number = _text(item, "airFln")
    scheduled_time = _text(item, "std")
    if not flight_number or not scheduled_time:
        return None

    scheduled_at = _combine_local_time(local_date, scheduled_time, tz_name)
    if scheduled_at is None:
        return None

    estimated_at = _combine_local_time(local_date, _text(item, "etd"), tz_name)
    marker_at = estimated_at or scheduled_at
    direction = _normalize_direction(_text(item, "io"), _text(item, "rmkKor"), _text(item, "rmkEng"))
    origin, destination = _build_route_labels(item, direction, airport_code)

    return {
        "airport_code": airport_code,
        "direction": direction,
        "flight_number": flight_number,
        "airline": _text(item, "airlineKorean") or _text(item, "airlineEnglish") or None,
        "scheduled_at": serialize_utc(scheduled_at),
        "estimated_at": serialize_utc(estimated_at) if estimated_at else None,
        "marker_at": serialize_utc(marker_at),
        "origin_airport": origin,
        "destination_airport": destination,
        "status": _text(item, "rmkKor") or _text(item, "rmkEng") or None,
        "line_type": _text(item, "line") or None,
    }


def _parse_kac_detail_flight_item(
    item: dict[str, Any],
    airport_code: str,
    local_date: date,
    tz_name: str,
) -> dict[str, Any] | None:
    flight_number = _dict_text(item, "AIR_FLN", "airFln", "flightid")
    flight_date = _parse_yyyymmdd(_dict_text(item, "FLIGHT_DATE", "flightDate")) or local_date
    scheduled_at = _combine_local_time(flight_date, _dict_text(item, "STD", "std", "scheduledatetime"), tz_name)
    if not flight_number or scheduled_at is None:
        return None

    estimated_at = _combine_local_time(flight_date, _dict_text(item, "ETD", "etd", "estimateddatetime"), tz_name)
    marker_at = estimated_at or scheduled_at
    direction = _normalize_direction(
        _dict_text(item, "IO", "io"),
        _dict_text(item, "RMK_KOR", "rmkKor"),
        _dict_text(item, "RMK_ENG", "rmkEng"),
    )
    origin = _dict_text(item, "BOARDING_KOR", "BOARDING_ENG", "depAirport")
    destination = _dict_text(item, "ARRIVED_KOR", "ARRIVED_ENG", "arrAirport")

    return {
        "airport_code": airport_code.upper(),
        "direction": direction,
        "flight_number": flight_number,
        "airline": _dict_text(item, "AIRLINE_KOREAN", "AIRLINE_ENGLISH") or None,
        "scheduled_at": serialize_utc(scheduled_at),
        "estimated_at": serialize_utc(estimated_at) if estimated_at else None,
        "marker_at": serialize_utc(marker_at),
        "origin_airport": origin or (airport_code.upper() if direction == "departure" else "-"),
        "destination_airport": destination or (airport_code.upper() if direction == "arrival" else "-"),
        "status": _dict_text(item, "RMK_KOR", "RMK_ENG") or None,
        "line_type": _dict_text(item, "LINE", "LINE_CODE") or None,
    }


def _parse_incheon_flight_item(
    item: dict[str, Any],
    direction: str,
    local_date: date,
    tz_name: str,
) -> dict[str, Any] | None:
    flight_number = str(item.get("flightId") or "").strip()
    scheduled_at = _combine_local_datetime_text(str(item.get("scheduleDateTime") or ""), local_date, tz_name)
    if not flight_number or scheduled_at is None:
        return None

    estimated_at = _combine_local_datetime_text(str(item.get("estimatedDateTime") or ""), local_date, tz_name)
    marker_at = estimated_at or scheduled_at
    remote_airport = str(item.get("airport") or "").strip() or "-"

    if direction == "departure":
        origin_airport = "인천"
        destination_airport = remote_airport
    else:
        origin_airport = remote_airport
        destination_airport = "인천"

    return {
        "airport_code": "ICN",
        "direction": direction,
        "flight_number": flight_number,
        "airline": str(item.get("airline") or "").strip() or None,
        "scheduled_at": serialize_utc(scheduled_at),
        "estimated_at": serialize_utc(estimated_at) if estimated_at else None,
        "marker_at": serialize_utc(marker_at),
        "origin_airport": origin_airport,
        "destination_airport": destination_airport,
        "status": str(item.get("remark") or "").strip() or None,
        "line_type": str(item.get("typeOfFlight") or "").strip() or None,
    }


def _find_text(root: ElementTree.Element, tag_name: str) -> str | None:
    element = root.find(f".//{tag_name}")
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _text(item: ElementTree.Element, tag_name: str) -> str:
    return _find_text(item, tag_name) or ""


def _incheon_flight_section_items(
    section: Any,
    key: str,
) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(section, list):
        # krairport's iiac_raw_items() escape hatch already validated the
        # envelope (raises KrairportError on a bad result code) and returns
        # a flat item list, not the {"response": {...}} wrapper.
        return [item for item in section if isinstance(item, dict)], None

    section = section or {}
    header = section.get("response", {}).get("header", {})
    result_code = str(header.get("resultCode") or "").strip()
    result_message = str(header.get("resultMsg") or "").strip()
    if result_code and result_code not in SUCCESS_RESULT_CODES:
        return [], f"incheon_flight_status {key} API error {result_code}: {result_message}"
    return _json_items(section), None


def _json_items(document: dict[str, Any]) -> list[dict[str, Any]]:
    items = document.get("response", {}).get("body", {}).get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _dict_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _parse_yyyymmdd(value: str) -> date | None:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    except ValueError:
        return None


def _combine_local_time(local_date: date, time_text: str, tz_name: str) -> datetime | None:
    hour_minute = _parse_hhmm(time_text)
    if hour_minute is None:
        return None
    hour, minute = hour_minute
    return datetime(
        local_date.year,
        local_date.month,
        local_date.day,
        hour,
        minute,
        tzinfo=ZoneInfo(tz_name),
    )


def _combine_local_datetime_text(value: str, local_date: date, tz_name: str) -> datetime | None:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) >= 12:
        try:
            return datetime.strptime(digits[:12], "%Y%m%d%H%M").replace(tzinfo=ZoneInfo(tz_name))
        except ValueError:
            return None
    if len(digits) >= 4:
        return _combine_local_time(local_date, digits[-4:], tz_name)
    return None


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 4:
        return None
    hour = int(digits[-4:-2])
    minute = int(digits[-2:])
    if hour > 23 or minute > 59:
        return None
    return hour, minute


def _normalize_direction(io_value: str, status_ko: str, status_en: str) -> str:
    normalized = io_value.strip().upper()
    status_text = f"{status_ko} {status_en}".upper()

    if normalized.startswith("O") or "출발" in status_text or "DEPART" in status_text:
        return "departure"
    if normalized.startswith("I") or "도착" in status_text or "ARRIV" in status_text:
        return "arrival"
    return "unknown"


def _build_route_labels(item: ElementTree.Element, direction: str, airport_code: str) -> tuple[str, str]:
    boarding = _text(item, "boardingKor") or _text(item, "boardingEng")
    arrived = _text(item, "arrivedKor") or _text(item, "arrivedEng")
    city = _text(item, "city")

    if direction == "departure":
        return boarding or airport_code, arrived or city or "-"
    if direction == "arrival":
        return boarding or city or "-", arrived or airport_code
    return boarding or airport_code, arrived or city or "-"
