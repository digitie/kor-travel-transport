"""고정 SDK의 XML 조회부터 기존 출도착 API까지 공동운항을 검증한다."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import pytest
from krairport import KrairportClient

from app.core.config import Settings
from app.services.flight_status import FlightStatusService, KrairportFlightStatusClient

FIXTURE = Path(__file__).parent / "fixtures" / "kac_codeshare_public_20261025.json"


def _response_xml(rows: list[dict[str, str]]) -> str:
    root = ET.Element("response")
    ET.SubElement(ET.SubElement(root, "header"), "resultCode").text = "00"
    body = ET.SubElement(root, "body")
    for name, value in {"pageNo": 1, "numOfRows": 100, "totalCount": len(rows)}.items():
        ET.SubElement(body, name).text = str(value)
    items = ET.SubElement(body, "items")
    for row in rows:
        item = ET.SubElement(items, "item")
        for name, value in row.items():
            ET.SubElement(item, name).text = value
    return ET.tostring(root, encoding="unicode")


@pytest.fixture
def sdk_replay(monkeypatch):
    public = json.loads(FIXTURE.read_text(encoding="utf-8"))
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        operation = request.url.path.rsplit("/", 1)[-1]
        assert operation in {"depart", "arrival"}
        assert request.url.params["airport_code"] == "GMP"
        assert request.url.params["searchday"] == "20261025"
        assert request.url.params["numOfRows"] == "100"
        calls.append((operation, request.url.params["pageNo"]))
        rows = public["departure" if operation == "depart" else "arrival"]
        return httpx.Response(200, text=_response_xml(rows))

    @asynccontextmanager
    async def offline_client(**kwargs):
        assert kwargs["retries"] == 0
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as session:
            async with KrairportClient(**kwargs, session=session) as sdk:
                yield sdk

    monkeypatch.setattr("app.services.flight_status.KrairportClient", offline_client)
    return public, calls


def _settings() -> Settings:
    return Settings(data_go_kr_service_key="offline-only-key", flight_status_cache_seconds=300)


def _assert_markers(payload: dict) -> None:
    assert payload["status"] == "success"
    assert payload["source"] == "kac_flight_status_gateway"
    assert payload["error_message"] is None
    assert len(payload["items"]) == 4
    assert sorted(number for item in payload["items"] for number in item["codeshare_flight_numbers"]) == [
        "7C102", "7C904", "BX8032", "KE5153", "LJ3572", "LJ6301", "OZ8802",
    ]
    grouped = next(item for item in payload["items"] if "LJ6301" in item["codeshare_flight_numbers"])
    assert grouped["flight_number"] == "KE5153 / LJ6301"
    assert grouped["codeshare_flight_numbers"] == ["KE5153", "LJ6301"]
    assert grouped["origin_airport"] == "서울/김포"
    assert grouped["destination_airport"] == "제주"
    assert grouped["scheduled_at"].isoformat() == "2026-10-24T21:05:00+00:00"
    assert all("_codeshare_identity" not in item for item in payload["items"])


def test_real_sdk_preserves_seven_public_marketing_rows(sdk_replay) -> None:
    public, calls = sdk_replay
    response = asyncio.run(KrairportFlightStatusClient(_settings()).fetch_status("GMP", date(2026, 10, 25)))
    assert response.source == "kac_flight_status_gateway"
    assert response.flights is not None
    assert len(response.flights) == 7
    assert [flight.flight_id for flight in response.flights] == [
        row["flightid"] for row in public["departure"] + public["arrival"]
    ]
    pair = response.flights[:2]
    assert pair[0].flight_unique_id == pair[1].flight_unique_id == "0000000000000013491693"
    assert pair[0].master_flight_id == pair[1].master_flight_id == "LJ6301"
    assert pair[0].scheduled_at.isoformat() == "2026-10-25T06:05:00+09:00"
    assert calls == [("depart", "1"), ("arrival", "1")]


def test_real_sdk_normalization_preserves_marketing_ids_and_existing_marker_count(sdk_replay) -> None:
    _public, calls = sdk_replay
    service = FlightStatusService(_settings())

    async def fetch_twice():
        first = await service.get_status("GMP", date(2026, 10, 25))
        second = await service.get_status("GMP", date(2026, 10, 25))
        return first, second

    payload, cached = asyncio.run(fetch_twice())
    _assert_markers(payload)
    assert cached == payload
    assert calls == [("depart", "1"), ("arrival", "1")]


def test_existing_api_serializes_real_sdk_codeshare_without_new_contract(client, sdk_replay) -> None:
    _public, calls = sdk_replay
    client.app.state.flight_status_service = FlightStatusService(_settings())
    response = client.get("/v1/flights/status", params={"airport_code": "GMP", "local_date": "2026-10-25"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert len(payload["items"]) == 4
    assert sorted(number for item in payload["items"] for number in item["codeshare_flight_numbers"]) == [
        "7C102", "7C904", "BX8032", "KE5153", "LJ3572", "LJ6301", "OZ8802",
    ]
    grouped = next(item for item in payload["items"] if "LJ6301" in item["codeshare_flight_numbers"])
    assert grouped["scheduled_at"] in {"2026-10-24T21:05:00Z", "2026-10-24T21:05:00+00:00"}
    assert grouped["estimated_at"] in {"2026-10-24T21:19:00Z", "2026-10-24T21:19:00+00:00"}
    assert grouped["marker_at"] == grouped["estimated_at"]
    assert "offline-only-key" not in response.text
    assert "fid" not in grouped and "raw" not in grouped
    assert client.get("/v1/flights/status", params={"airport_code": "GMP", "local_date": "2026-10-25"}).json() == payload
    assert calls == [("depart", "1"), ("arrival", "1")]


@pytest.mark.parametrize("fault", ["duplicate", "invalid_master", "invalid_schedule"])
def test_sdk_integrity_errors_remain_upstream_errors_in_existing_api(client, sdk_replay, fault) -> None:
    public, calls = sdk_replay
    rows = public["departure"]
    if fault == "duplicate":
        rows[1] = deepcopy(rows[0])
    elif fault == "invalid_master":
        rows[1]["masterflightid"] = "conflicting-master"
    else:
        rows[1]["scheduledatetime"] = "202610250610"
    client.app.state.flight_status_service = FlightStatusService(_settings())
    response = client.get("/v1/flights/status", params={"airport_code": "GMP", "local_date": "2026-10-25"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "upstream_error"
    assert payload["items"] == []
    assert payload["error_message"]
    assert "conflicting-master" not in response.text
    assert "offline-only-key" not in response.text
    assert calls == [("depart", "1")]
