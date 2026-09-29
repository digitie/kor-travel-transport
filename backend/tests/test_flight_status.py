from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from krairport import Flight
from krairport.exceptions import KrairportRateLimitError

from app.core.config import Settings
from app.services.flight_status import (
    FlightSourceResponse,
    FlightStatusService,
    KrairportFlightStatusClient,
    parse_flight_status_xml,
    parse_incheon_flight_status_json,
    parse_kac_flight_detail_json,
)


def _mock_krairport_client(**method_results: object) -> AsyncMock:
    """Build a mock standing in for `async with KrairportClient(...) as client`."""

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


class _FlakyFlightStatusClient:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch_status(self, airport_code: str, local_date: date) -> FlightSourceResponse:
        self.calls += 1
        if self.calls == 1:
            request = httpx.Request(
                "GET",
                "https://api.odcloud.kr/api/FlightStatusListDTL/v1/getFlightStatusListDetail?serviceKey=secret-key&page=1",
            )
            response = httpx.Response(400, request=request, text='{"message":"bad condition"}')
            raise httpx.HTTPStatusError(
                "Client error '400 Bad Request' for url "
                "'https://api.odcloud.kr/api/FlightStatusListDTL/v1/getFlightStatusListDetail?serviceKey=secret-key&page=1'",
                request=request,
                response=response,
            )

        body = json.dumps(
            {
                "data": [
                    {
                        "AIRLINE_ENGLISH": "AIR BUSAN",
                        "AIRPORT": airport_code,
                        "AIR_FLN": "BX8804",
                        "ARRIVED_ENG": "GIMPO",
                        "BOARDING_ENG": "GIMHAE",
                        "ETD": "0915",
                        "FLIGHT_DATE": local_date.strftime("%Y%m%d"),
                        "IO": "O",
                        "LINE": "DOMESTIC",
                        "RMK_ENG": "DEPARTED",
                        "STD": "0910",
                    }
                ]
            }
        )
        return FlightSourceResponse(
            source="kac_flight_detail_status",
            endpoint="https://api.odcloud.kr/api/FlightStatusListDTL/v1/getFlightStatusListDetail",
            request_params={"airport_code": airport_code},
            status_code=200,
            body_text=body,
        )


def test_flight_status_does_not_cache_or_leak_upstream_http_errors() -> None:
    service = FlightStatusService(
        Settings(
            data_go_kr_service_key=None,
            use_sample_client_when_no_key=False,
            flight_status_cache_seconds=300,
        )
    )
    flaky_client = _FlakyFlightStatusClient()
    service.client = flaky_client

    async def fetch_twice() -> tuple[dict, dict, dict]:
        first = await service.get_status("PUS", date(2026, 5, 17))
        second = await service.get_status("PUS", date(2026, 5, 17))
        third = await service.get_status("PUS", date(2026, 5, 17))
        return first, second, third

    first_payload, second_payload, third_payload = asyncio.run(fetch_twice())

    assert first_payload["status"] == "upstream_error"
    assert "secret-key" not in (first_payload["error_message"] or "")
    assert "serviceKey=" not in (first_payload["error_message"] or "")
    assert second_payload["status"] == "success"
    assert len(second_payload["items"]) == 1
    assert third_payload == second_payload
    assert flaky_client.calls == 2


class _RateLimitedFlightStatusClient:
    def __init__(self) -> None:
        self.calls = 0

    async def fetch_status(self, airport_code: str, local_date: date) -> FlightSourceResponse:
        self.calls += 1
        raise KrairportRateLimitError("LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.")


def test_flight_status_caches_rate_limited_response_for_the_backoff_window() -> None:
    service = FlightStatusService(
        Settings(
            data_go_kr_service_key=None,
            use_sample_client_when_no_key=False,
            flight_status_cache_seconds=300,
            upstream_rate_limit_backoff_seconds=3600,
        )
    )
    rate_limited_client = _RateLimitedFlightStatusClient()
    service.client = rate_limited_client

    async def fetch_twice() -> tuple[dict, dict]:
        first = await service.get_status("PUS", date(2026, 5, 17))
        second = await service.get_status("PUS", date(2026, 5, 17))
        return first, second

    first_payload, second_payload = asyncio.run(fetch_twice())

    assert first_payload["status"] == "rate_limited"
    assert second_payload == first_payload
    # Cached under the longer backoff window -- the second call must not
    # re-trigger another upstream request.
    assert rate_limited_client.calls == 1


def test_parse_flight_status_xml_reports_upstream_error() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>99</resultCode>
    <resultMsg>SERVICE ACCESS DENIED ERROR.</resultMsg>
  </header>
</response>
"""

    items, error_message = parse_flight_status_xml(body, "GMP", date(2026, 4, 25))

    assert items == []
    assert error_message == "kac_flight_status API error 99: SERVICE ACCESS DENIED ERROR."


def test_parse_flight_status_xml_normalizes_route_and_times() -> None:
    body = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>NORMAL SERVICE</resultMsg>
  </header>
  <body>
    <items>
      <item>
        <airFln>KE1101</airFln>
        <airlineKorean>대한항공</airlineKorean>
        <boardingKor>김포</boardingKor>
        <arrivedKor>제주</arrivedKor>
        <io>O</io>
        <line>국내</line>
        <std>0830</std>
        <etd>0840</etd>
        <rmkKor>출발</rmkKor>
      </item>
    </items>
  </body>
</response>
"""

    items, error_message = parse_flight_status_xml(body, "GMP", date(2026, 4, 25))

    assert error_message is None
    assert len(items) == 1
    assert items[0]["direction"] == "departure"
    assert items[0]["flight_number"] == "KE1101"
    assert items[0]["origin_airport"] == "김포"
    assert items[0]["destination_airport"] == "제주"
    assert items[0]["marker_at"].isoformat() == "2026-04-24T23:40:00+00:00"


def test_parse_kac_flight_detail_json_normalizes_odcloud_response() -> None:
    body = """{
      "page": 1,
      "perPage": 2,
      "totalCount": 1751281,
      "currentCount": 2,
      "matchCount": 2,
      "data": [
        {
          "AIRLINE_KOREAN": "제주항공",
          "AIRLINE_ENGLISH": "JEJU AIR",
          "AIRPORT": "GMP",
          "AIR_FLN": "7C104",
          "ARRIVED_KOR": "김포",
          "BOARDING_KOR": "제주",
          "CITY": "CJU",
          "ETD": "1032",
          "FLIGHT_DATE": "20260509",
          "IO": "I",
          "LINE": "국내",
          "RMK_KOR": "도착",
          "STD": "1040",
          "UFID": "20260509GMPI7C104"
        },
        {
          "AIRLINE_KOREAN": "대한항공",
          "AIRLINE_ENGLISH": "KOREAN AIR",
          "AIRPORT": "GMP",
          "AIR_FLN": "KE1101",
          "ARRIVED_KOR": "제주",
          "BOARDING_KOR": "김포",
          "CITY": "CJU",
          "ETD": "0840",
          "FLIGHT_DATE": "20260509",
          "IO": "O",
          "LINE": "국내",
          "RMK_KOR": "출발",
          "STD": "0830",
          "UFID": "20260509GMPOKE1101"
        }
      ]
    }"""

    items, error_message = parse_kac_flight_detail_json(body, "GMP", date(2026, 5, 9))

    assert error_message is None
    assert len(items) == 2
    assert items[0]["direction"] == "departure"
    assert items[0]["flight_number"] == "KE1101"
    assert items[0]["origin_airport"] == "김포"
    assert items[0]["destination_airport"] == "제주"
    assert items[0]["marker_at"].isoformat() == "2026-05-08T23:40:00+00:00"
    assert items[1]["direction"] == "arrival"
    assert items[1]["origin_airport"] == "제주"
    assert items[1]["destination_airport"] == "김포"


def test_parse_kac_flight_detail_json_groups_codeshare_markers() -> None:
    body = """{
      "data": [
        {
          "AIRLINE_KOREAN": "대한항공",
          "AIRPORT": "GMP",
          "AIR_FLN": "KE123",
          "ARRIVED_KOR": "제주",
          "BOARDING_KOR": "김포",
          "ETD": "0840",
          "FLIGHT_DATE": "20260509",
          "IO": "O",
          "LINE": "국내",
          "RMK_KOR": "출발",
          "STD": "0830"
        },
        {
          "AIRLINE_KOREAN": "델타항공",
          "AIRPORT": "GMP",
          "AIR_FLN": "DL9123",
          "ARRIVED_KOR": "제주",
          "BOARDING_KOR": "김포",
          "ETD": "0840",
          "FLIGHT_DATE": "20260509",
          "IO": "O",
          "LINE": "국내",
          "RMK_KOR": "출발",
          "STD": "0830"
        }
      ]
    }"""

    items, error_message = parse_kac_flight_detail_json(body, "GMP", date(2026, 5, 9))

    assert error_message is None
    assert len(items) == 1
    assert items[0]["flight_number"] == "DL9123 / KE123"
    assert items[0]["codeshare_flight_numbers"] == ["DL9123", "KE123"]
    assert items[0]["origin_airport"] == "김포"
    assert items[0]["destination_airport"] == "제주"


def test_parse_incheon_flight_status_json_accepts_pre_extracted_item_lists() -> None:
    body = json.dumps(
        {
            "departures": [
                {
                    "airline": "에티오피아항공",
                    "flightId": "ET673",
                    "scheduleDateTime": "202605090020",
                    "estimatedDateTime": "202605090043",
                    "airport": "아디스아바바/볼레",
                    "remark": "출발",
                    "typeOfFlight": "I",
                }
            ],
            "arrivals": [
                {
                    "airline": "에어로케이항공",
                    "flightId": "RF313",
                    "scheduleDateTime": "202605090005",
                    "estimatedDateTime": "202605090011",
                    "airport": "오사카/ 간사이",
                    "remark": "도착",
                    "typeOfFlight": "I",
                }
            ],
        }
    )

    items, error_message = parse_incheon_flight_status_json(body, date(2026, 5, 9))

    assert error_message is None
    assert len(items) == 2
    assert items[0]["direction"] == "arrival"
    assert items[1]["direction"] == "departure"


def test_krairport_flight_status_client_fetch_kac_status_uses_typed_gateway() -> None:
    settings = Settings(data_go_kr_service_key="test-key")
    items = [Flight(provider="kac", airport_code="GMP", direction="departure", flight_id="KE1101",
        scheduled_at=datetime.fromisoformat("2026-05-09T08:30:00+09:00"),
        estimated_at=datetime.fromisoformat("2026-05-09T08:40:00+09:00"),
        departure_airport_name="김포", arrival_airport_name="제주", airline_name="대한항공",
        flight_unique_id="0001", airline_code="KE", departure_airport_code="GMP", arrival_airport_code="CJU",
        status_korean=None, status_english=None, terminal=None, gate=None, codeshare=None)]
    mock_client = _mock_krairport_client()
    provider = mock_client.__aenter__.return_value.kac
    provider.flight_status.return_value = items

    with patch("app.services.flight_status.KrairportClient", return_value=mock_client) as factory:
        client = KrairportFlightStatusClient(settings)
        response = asyncio.run(client.fetch_status("GMP", date(2026, 5, 9)))

    assert response.source == "kac_flight_status_gateway"
    assert response.flights == tuple(items)
    assert response.body_text == ""
    assert factory.call_args.kwargs["retries"] == 0
    provider.flight_status.assert_awaited_once_with(airport_code="GMP", searchday="20260509", num_of_rows=100, max_pages=20)
    service = FlightStatusService(settings)
    service.client = AsyncMock()
    service.client.fetch_status.return_value = response
    payload = asyncio.run(service.get_status("GMP", date(2026, 5, 9)))
    assert payload["status"] == "success"
    assert payload["items"][0]["flight_number"] == "KE1101"
    assert payload["items"][0]["destination_airport"] == "제주"
    assert payload["items"][0]["marker_at"].isoformat() == "2026-05-08T23:40:00+00:00"


def test_krairport_flight_status_client_fetch_incheon_status_calls_both_directions() -> None:
    settings = Settings(data_go_kr_service_key="test-key")
    departure_item = {
        "airline": "대한항공",
        "flightId": "KE901",
        "scheduleDateTime": "202605090930",
        "airport": "파리",
        "remark": "출발",
        "typeOfFlight": "I",
    }
    arrival_item = {
        "airline": "아시아나항공",
        "flightId": "OZ202",
        "scheduleDateTime": "202605091120",
        "airport": "로스앤젤레스",
        "remark": "도착",
        "typeOfFlight": "I",
    }
    mock_client = _mock_krairport_client()
    # side_effect (not a shared return_value) so departures/arrivals can't
    # silently return the same items if the two calls' operation names or
    # order get swapped.
    mock_client.__aenter__.return_value.iiac_raw_items.side_effect = [[departure_item], [arrival_item]]

    with patch("app.services.flight_status.KrairportClient", return_value=mock_client):
        client = KrairportFlightStatusClient(settings)
        response = asyncio.run(client.fetch_status("ICN", date(2026, 5, 9)))

    assert response.source == "incheon_flight_status"
    document = json.loads(response.body_text)
    assert document["departures"] == [departure_item]
    assert document["arrivals"] == [arrival_item]

    calls = mock_client.__aenter__.return_value.iiac_raw_items.call_args_list
    assert calls[0].args[:2] == ("StatusOfPassengerFlightsDeOdp", "getPassengerDeparturesDeOdp")
    assert calls[1].args[:2] == ("StatusOfPassengerFlightsDeOdp", "getPassengerArrivalsDeOdp")


def test_gateway_groups_explicit_codeshares_without_merging_unrelated_flights() -> None:
    base = dict(provider="kac", airport_code="GMP", direction="departure",
        scheduled_at=datetime.fromisoformat("2026-05-09T08:30:00+09:00"),
        estimated_at=None, departure_airport_name="김포", arrival_airport_name="제주",
        flight_unique_id=None, airline_code=None, airline_name=None,
        departure_airport_code="GMP", arrival_airport_code="CJU",
        status_korean=None, status_english=None, terminal=None, gate=None, codeshare=None)
    flights = [Flight(**base, flight_id="KE123", master_flight_id="KE123"),
        Flight(**{**base, "estimated_at": datetime.fromisoformat("2026-05-09T08:45:00+09:00")},
            flight_id="DL9123", master_flight_id="KE123"),
        Flight(**base, flight_id="7C123"),
        Flight(**{**base, "direction": "arrival"}, flight_id="KE123", master_flight_id="KE123"),
        Flight(**{**base, "scheduled_at": datetime.fromisoformat("2026-05-10T08:30:00+09:00")},
            flight_id="KE123", master_flight_id="KE123")]
    service = FlightStatusService(Settings(data_go_kr_service_key=None, use_sample_client_when_no_key=False))
    service.client = AsyncMock()
    service.client.fetch_status.return_value = FlightSourceResponse(
        source="kac_flight_status_gateway", endpoint="fixture", request_params={},
        status_code=200, body_text="", flights=tuple(flights))
    payload = asyncio.run(service.get_status("GMP", date(2026, 5, 9)))
    assert payload["status"] == "success"
    assert len(payload["items"]) == 4
    grouped = next(item for item in payload["items"] if item["flight_number"] == "DL9123 / KE123")
    assert grouped["codeshare_flight_numbers"] == ["DL9123", "KE123"]
    assert grouped["marker_at"] == base["scheduled_at"]
    assert all("_codeshare_identity" not in item for item in payload["items"])


def test_krairport_flight_status_client_rate_limit_error_propagates() -> None:
    settings = Settings(data_go_kr_service_key="test-key")
    mock_client = _mock_krairport_client()
    mock_client.__aenter__.return_value.kac.flight_status.side_effect = KrairportRateLimitError("LIMITED")

    with patch("app.services.flight_status.KrairportClient", return_value=mock_client):
        client = KrairportFlightStatusClient(settings)
        with pytest.raises(KrairportRateLimitError):
            asyncio.run(client.fetch_status("GMP", date(2026, 5, 9)))


def test_parse_incheon_flight_status_json_normalizes_departures_and_arrivals() -> None:
    body = """{
      "departures": {
        "response": {
          "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
          "body": {
            "items": [
              {
                "airline": "에티오피아항공",
                "flightId": "ET673",
                "scheduleDateTime": "202605090020",
                "estimatedDateTime": "202605090043",
                "airport": "아디스아바바/볼레",
                "remark": "출발",
                "typeOfFlight": "I"
              }
            ]
          }
        }
      },
      "arrivals": {
        "response": {
          "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
          "body": {
            "items": [
              {
                "airline": "에어로케이항공",
                "flightId": "RF313",
                "scheduleDateTime": "202605090005",
                "estimatedDateTime": "202605090011",
                "airport": "오사카/ 간사이",
                "remark": "도착",
                "typeOfFlight": "I"
              }
            ]
          }
        }
      }
    }"""

    items, error_message = parse_incheon_flight_status_json(body, date(2026, 5, 9))

    assert error_message is None
    assert len(items) == 2
    assert items[0]["direction"] == "arrival"
    assert items[0]["origin_airport"] == "오사카/ 간사이"
    assert items[0]["destination_airport"] == "인천"
    assert items[1]["direction"] == "departure"
    assert items[1]["origin_airport"] == "인천"
    assert items[1]["destination_airport"] == "아디스아바바/볼레"
