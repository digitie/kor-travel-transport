"""T4 이력은 시간·역키·수집 revision을 한정하고 외부 provider를 호출하지 않는다."""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import FuelPriceSnapshot, FuelStation
from app.core.time_utils import now_utc
from app.services.transport_collection import OPINET_SOURCE
from test_service_exports import HEADERS, _run, _seed_fuel_station, _set_state

PATH = "/v1/service/exports/fuel-stations/A0000001/price-history"
REST = "/v1/service/exports/rest-area-fuel-prices/test/price-history"


@pytest.fixture
def history_client(test_settings):
    test_settings.transport_service_export_token = "s" * 40
    test_settings.trusted_hosts_csv = "testserver,127.0.0.1"
    with TestClient(create_app(test_settings), client=("127.0.0.1", 50123)) as client:
        async def seed(session):
            now = now_utc()
            await _seed_fuel_station(session, seen_at=now)
            station = await session.scalar(select(FuelStation).where(
                FuelStation.source_station_id == "A0000001",
            ))
            for index in range(1, 6):
                session.add(FuelPriceSnapshot(
                    fuel_station_id=station.id, source=OPINET_SOURCE,
                    product_code="B027" if index % 2 else "D047",
                    price=1700 - index if index != 4 else None,
                    observed_at=now - timedelta(days=index), collected_at=now,
                    raw_item_json={"private_raw": "must-not-export"},
                ))
            await _set_state(session, OPINET_SOURCE, last_success_at=now)
        _run(client, seed)
        yield client


def test_history_defaults_and_product_filter(history_client):
    response = history_client.get(PATH, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["station_key"] == "A0000001"
    assert body["meta"]["item_count"] == 6 and body["meta"]["source_status"] == "ok"
    assert body["meta"]["source_collected_at"].endswith("Z")
    assert len(body["items"]) == 6 and not body["has_more"]
    assert body["items"][0]["price"] == 1700
    assert body["items"] == sorted(body["items"], key=lambda row: row["observed_at"], reverse=True)
    assert "private_raw" not in response.text
    filtered = history_client.get(PATH, headers=HEADERS, params={"product": "D047"}).json()
    assert len(filtered["items"]) == 2
    assert {row["product_code"] for row in filtered["items"]} == {"D047"}
    assert any(row["price"] is None for row in filtered["items"])


def test_history_pages_are_bounded_and_unchanged_first_page_revalidates(history_client):
    first = history_client.get(PATH, headers=HEADERS, params={"limit": 2})
    body = first.json()
    assert len(body["items"]) == 2 and body["has_more"] and body["next_cursor"]
    cached = history_client.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]}, params={"limit": 2})
    assert cached.status_code == 304 and not cached.content
    assert cached.headers["etag"] == first.headers["etag"]
    items = body["items"]
    while body["next_cursor"]:
        response = history_client.get(PATH, headers=HEADERS, params={"limit": 2, "cursor": body["next_cursor"]})
        assert response.status_code == 200
        body = response.json()
        items += body["items"]
    assert len(items) == 6
    assert len({(row["product_code"], row["observed_at"]) for row in items}) == 6


def test_history_gzip_and_identity_share_weak_etag(history_client):
    zipped = history_client.get(PATH, headers={**HEADERS, "Accept-Encoding": "gzip"})
    assert zipped.headers["content-encoding"] == "gzip"
    plain = history_client.get(PATH, headers={**HEADERS, "Accept-Encoding": "gzip;q=0"})
    assert "content-encoding" not in plain.headers
    assert plain.json()["items"] == zipped.json()["items"]
    assert plain.headers["etag"] == zipped.headers["etag"]
    assert "accept-encoding" in {value.strip().lower() for value in plain.headers["vary"].split(",")}
    assert plain.headers["cache-control"] == "private, no-cache"
    conditional = history_client.get(PATH, headers={**HEADERS, "If-None-Match": '"other", '+plain.headers["etag"][2:]})
    assert conditional.status_code == 304


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 5001}, {"cursor": ""}, {"cursor": "invalid"},
    {"from": "2026-01-01T00:00:00"},
    {"from": "2020-01-01T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
    {"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"},
    {"to": "2099-01-01T00:00:00Z"}, {"product": ""},
])
def test_history_invalid_bounds_fail(history_client, params):
    response = history_client.get(PATH, headers=HEADERS, params=params)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_history_cursor_filters_and_collection_revision_are_checked(history_client):
    first = history_client.get(PATH, headers=HEADERS, params={"limit": 1}).json()
    cursor = first["next_cursor"]
    assert history_client.get(PATH, headers=HEADERS, params={"product": "D047", "cursor": cursor}).status_code == 422
    changed = cursor[:-5] + ("aaaaa" if not cursor.endswith("aaaaa") else "bbbbb")
    assert history_client.get(PATH, headers=HEADERS, params={"cursor": changed}).status_code == 422
    _run(history_client, lambda session: _set_state(session, OPINET_SOURCE, last_error="provider failed"))
    assert history_client.get(PATH, headers=HEADERS, params={"cursor": cursor}).status_code == 409


def test_history_empty_filter_is_not_a_full_source_empty_snapshot(history_client):
    result = history_client.get(PATH, headers=HEADERS, params={"product": "no-such-product"})
    assert result.status_code == 200
    assert result.json()["items"] == [] and result.json()["meta"]["item_count"] == 0
    assert result.json()["meta"]["source_status"] == "ok"


def test_history_failure_revalidates_as_stale_instead_of_304(history_client):
    first = history_client.get(PATH, headers=HEADERS)
    _run(history_client, lambda session: _set_state(session, OPINET_SOURCE, last_error="provider failed"))
    stale = history_client.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]})
    assert stale.status_code == 200 and stale.json()["meta"]["source_status"] == "stale"
    assert stale.json()["items"] == first.json()["items"]
    _run(history_client, lambda session: _set_state(session, OPINET_SOURCE, last_success_at=None))
    unavailable = history_client.get(PATH, headers={**HEADERS, "If-None-Match": "*"})
    assert unavailable.status_code == 503 and "etag" not in unavailable.headers
    assert unavailable.json()["meta"]["source_status"] == "failed"
    assert unavailable.json()["meta"]["source_collected_at"] is None
    assert unavailable.json()["meta"]["item_count"] == 0


@pytest.mark.parametrize("path", [PATH, REST])
def test_history_existing_service_auth_cannot_be_bypassed(history_client, path):
    assert history_client.get(path).status_code == 404
    assert history_client.get(path, headers={"X-Kor-Travel-Transport-Service-Token": "x" * 40}).status_code == 404


def test_history_missing_station_and_unsupported_rest_area_are_problems(history_client):
    missing = history_client.get(PATH.replace("A0000001", "missing"), headers=HEADERS)
    assert missing.status_code == 404
    rest = history_client.get(REST, headers=HEADERS)
    assert rest.status_code == 501
    assert rest.headers["content-type"].startswith("application/problem+json")
    assert "이력" in rest.json()["detail"]



def test_history_revalidation_renews_cursor_before_expiry(history_client, monkeypatch):
    from app.services import export_price_history

    first_time = now_utc().replace(minute=2, second=0, microsecond=0) + timedelta(hours=1)
    clock = [first_time]
    monkeypatch.setattr(export_price_history, "now_utc", lambda: clock[0])
    first = history_client.get(PATH, headers=HEADERS, params={"limit": 1})
    assert first.status_code == 200 and first.json()["has_more"]
    clock[0] += timedelta(minutes=16)
    refreshed = history_client.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]}, params={"limit": 1})
    assert refreshed.status_code == 200
    assert refreshed.headers["etag"] != first.headers["etag"]
    old = history_client.get(PATH, headers=HEADERS, params={"cursor": first.json()["next_cursor"]})
    assert old.status_code == 409
    fresh = history_client.get(PATH, headers=HEADERS, params={"cursor": refreshed.json()["next_cursor"]})
    assert fresh.status_code == 200


@pytest.mark.parametrize("change", ["new_success", "same_clock_correction"])
def test_history_mutation_invalidates_old_cursor_and_revalidation(history_client, change):
    from app.models import TransportCollectionState

    first = history_client.get(PATH, headers=HEADERS, params={"limit": 1})
    async def mutate(session):
        state = await session.scalar(select(TransportCollectionState).where(
            TransportCollectionState.source == OPINET_SOURCE,
        ))
        if change == "new_success":
            state.last_success_at = now_utc()
        else:
            # 첫 페이지 밖의 row 교정: 첫 페이지 값과 원천 시각만으로는 잡을 수 없다.
            row = await session.scalar(select(FuelPriceSnapshot).order_by(
                FuelPriceSnapshot.observed_at.asc(),
            ).limit(1))
            row.price = 1501
        state.updated_at = now_utc() + timedelta(microseconds=1)
    _run(history_client, mutate)
    refreshed = history_client.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]}, params={"limit": 1})
    assert refreshed.status_code == 200
    assert refreshed.headers["etag"] != first.headers["etag"]
    assert refreshed.json()["items"] == first.json()["items"]
    old = history_client.get(PATH, headers=HEADERS, params={"cursor": first.json()["next_cursor"]})
    assert old.status_code == 409
    fresh = history_client.get(PATH, headers=HEADERS, params={"cursor": refreshed.json()["next_cursor"]})
    assert fresh.status_code == 200
