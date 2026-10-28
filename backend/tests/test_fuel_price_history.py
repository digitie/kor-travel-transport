"""지도 ID의 다중유종 rolling168h 이력과 기존 service 인증 경계를 검증한다."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import hashlib
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.time_utils import now_utc
from app.main import create_app
from app.models import FuelPriceSnapshot, FuelStation
from app.services import export_price_history
from app.services.fuel_price_history import _price_item
from app.services.transport_collection import OPINET_SOURCE, upsert_latest_fuel_prices
from test_service_exports import HEADERS, _run, _seed_fuel_station, _set_state

NOW = datetime(2026, 10, 28, 15, tzinfo=UTC)  # KST 29일 자정; 창 시작은 KST22일 자정.


@pytest.mark.parametrize("price", [None, Decimal("0"), Decimal("1599.25")])
def test_price_item_preserves_missing_zero_and_kst_midnight_as_utc(price):
    local = datetime(2026, 10, 29, tzinfo=ZoneInfo("Asia/Seoul"))
    item = _price_item(SimpleNamespace(
        product_code="D047", price=price, observed_at=local, collected_at=local,
        provider_updated_at=local,
    ))
    assert item.price == (float(price) if price is not None else None)
    assert item.observed_at == item.collected_at == item.provider_updated_at == NOW


@pytest.fixture
def native_history(test_settings, monkeypatch):
    monkeypatch.setattr(export_price_history, "now_utc", lambda: NOW)
    test_settings.transport_service_export_token = "s" * 40
    test_settings.trusted_hosts_csv = "testserver,127.0.0.1"
    with TestClient(create_app(test_settings), client=("127.0.0.1", 50123)) as client:
        async def seed(session):
            await _seed_fuel_station(session, seen_at=NOW)
            station = await session.scalar(select(FuelStation).where(FuelStation.source_station_id == "A0000001"))
            station.brand_code, station.brand_name = "SKE", "SK에너지"
            start = NOW - timedelta(days=7)
            for product, price, observed in (
                ("B027", 1800, start), ("B027", 1900, start - timedelta(microseconds=1)),
                ("D047", 1600, NOW - timedelta(hours=1)), ("C004", 0, NOW - timedelta(hours=2)),
                ("B034", None, NOW - timedelta(hours=3)), ("K015", 2000, NOW - timedelta(days=8)),
                ("future", 999, NOW + timedelta(seconds=1)),
            ):
                session.add(FuelPriceSnapshot(
                    fuel_station_id=station.id, source=OPINET_SOURCE, product_code=product, price=price,
                    observed_at=observed, collected_at=min(observed, NOW), provider_updated_at=observed,
                    raw_item_json={"secret_raw": "never-public"},
                ))
            await session.flush()
            await upsert_latest_fuel_prices(session)
            await _set_state(session, OPINET_SOURCE, last_success_at=NOW, updated_at=NOW)
            return station.id
        station_id = _run(client, seed)
        yield client, f"/v1/transport/fuel/stations/{station_id}/price-history", station_id


def test_native_history_multifuel_actual_window_latest_and_no_token(native_history):
    client, path, station_id = native_history
    response = client.get(path, params={"source": OPINET_SOURCE})
    assert response.status_code == 200
    body = response.json()
    assert body["station_id"] == station_id and body["provider_id"] == "A0000001"
    assert body["source"] == OPINET_SOURCE and body["brand_code"] == "SKE"
    window = body["window"]
    start, end = (datetime.fromisoformat(window[k].replace("Z", "+00:00")) for k in ("from_at", "to_at"))
    assert end == NOW and end - start == timedelta(hours=168)
    assert start.astimezone(ZoneInfo("Asia/Seoul")).isoformat() == "2026-10-22T00:00:00+09:00"
    assert end.astimezone(ZoneInfo("Asia/Seoul")).isoformat() == "2026-10-29T00:00:00+09:00"
    assert window["mode"] == "rolling" and window["timezone"] == "Asia/Seoul"
    assert len(body["items"]) == 5 and body["meta"]["item_count"] == 5
    assert {r["product_code"] for r in body["items"]} == {"B027", "D047", "C004", "B034"}
    assert {r["price"] for r in body["items"]} == {1700, 1800, 1600, 0, None}
    assert all(r["observed_at"].endswith("Z") and r["collected_at"].endswith("Z") for r in body["items"])
    latest = {r["product_code"]: r for r in body["latest"]}
    assert latest["K015"]["observed_at"] < window["from_at"]  # 오래된 현재값은 그래프와 별도다.
    assert "future" not in latest
    assert body["source_last_success_at"] == "2026-10-28T15:00:00Z"
    assert len(body["source_revision"]) == 64
    assert "secret_raw" not in response.text and "never-public" not in response.text and "s" * 40 not in response.text
    # 같은 read라도 원 service route는 계속 토큰이 필요하다.
    assert client.get("/v1/service/exports/fuel-stations/A0000001/price-history").status_code == 404


def test_native_pagination_fixes_window_and_isolates_cursor_context(native_history):
    client, path, _ = native_history
    params = {"source": OPINET_SOURCE, "limit": 2}
    first = client.get(path, params=params).json()
    assert first["has_more"] and len(first["items"]) == 2
    page, items = first, first["items"]
    while page["next_cursor"]:
        response = client.get(path, params=params | {"cursor": page["next_cursor"]})
        assert response.status_code == 200
        page = response.json()
        assert page["window"] == first["window"] and page["source_revision"] == first["source_revision"]
        items += page["items"]
    assert len(items) == 5
    assert len({(r["product_code"], r["observed_at"]) for r in items}) == 5
    cursor = first["next_cursor"]
    assert client.get(path, params=params | {"days": 1, "cursor": cursor}).status_code == 422
    assert client.get(path, params=params | {"product": "D047", "cursor": cursor}).status_code == 422
    assert client.get(path.replace("/stations/", "/stations/9"), params=params | {"cursor": cursor}).status_code == 404
    # export/native 서명 namespace가 달라서 어느 쪽 cursor도 다른 route로 이식할 수 없다.
    export = "/v1/service/exports/fuel-stations/A0000001/price-history"
    assert client.get(export, headers=HEADERS, params={"cursor": cursor}).status_code == 422
    old = client.get(export, headers=HEADERS, params={"limit": 1}).json()["next_cursor"]
    assert client.get(path, params=params | {"cursor": old}).status_code == 422


def test_native_revision_failure_empty_products_and_unavailable(native_history):
    client, path, _ = native_history
    params = {"source": OPINET_SOURCE}
    cursor = client.get(path, params=params | {"limit": 1}).json()["next_cursor"]
    _run(client, lambda session: _set_state(session, OPINET_SOURCE, last_error="private-provider-failure", updated_at=NOW + timedelta(seconds=1)))
    assert client.get(path, params=params | {"cursor": cursor}).status_code == 409
    stale = client.get(path, params=params).json()
    assert stale["meta"]["source_status"] == "stale" and "private-provider-failure" not in str(stale)
    empty = client.get(path, params=params | {"product": "not-stocked"}).json()
    assert empty["items"] == [] and empty["latest"] == [] and not empty["has_more"]
    _run(client, lambda session: _set_state(session, OPINET_SOURCE, last_success_at=None))
    unavailable = client.get(path, params=params)
    assert unavailable.status_code == 503 and unavailable.json()["meta"]["source_status"] == "failed"


def test_native_cursor_cannot_move_its_recent_window_even_with_valid_signature(native_history):
    client, path, _ = native_history
    params = {"source": OPINET_SOURCE, "limit": 1}
    first = client.get(path, params=params).json()
    key = hashlib.sha256(("native-fuel-history:" + "s" * 40).encode()).digest()
    saved = export_price_history._decode_cursor(first["next_cursor"], key)
    saved["from"] = (NOW - timedelta(days=30)).isoformat()
    saved["to"] = (NOW - timedelta(days=23)).isoformat()
    cursor = export_price_history._encode_cursor(saved, key)
    assert client.get(path, params=params | {"cursor": cursor}).status_code == 422


def test_native_latest_does_not_mix_another_snapshot_source(native_history):
    client, path, station_id = native_history
    async def seed_foreign(session):
        session.add(FuelPriceSnapshot(
            fuel_station_id=station_id, source="other_source", product_code="foreign", price=123,
            observed_at=NOW, collected_at=NOW, raw_item_json={"private": "other-source"},
        ))
        await session.flush()
        await upsert_latest_fuel_prices(session)
    _run(client, seed_foreign)
    body = client.get(path, params={"source": OPINET_SOURCE}).json()
    assert "foreign" not in {r["product_code"] for r in body["items"]}
    assert "foreign" not in {r["product_code"] for r in body["latest"]}


@pytest.mark.parametrize("change", [{}, {"source": "krex_rest_area_fuel"}, {"source": ""}, {"source": OPINET_SOURCE, "days": 8}, {"source": OPINET_SOURCE, "days": 0}, {"source": OPINET_SOURCE, "limit": 5001}, {"source": OPINET_SOURCE, "cursor": "invalid"}])
def test_native_source_and_query_boundaries(native_history, change):
    client, path, _ = native_history
    response = client.get(path, params=change)
    assert response.status_code == (501 if change.get("source") == "krex_rest_area_fuel" else 422)


def test_native_missing_or_synthetic_station_ids_and_feature_brand(native_history):
    client, path, _ = native_history
    prefix = path.rsplit("/", 2)[0]
    assert client.get(prefix + "/-1/price-history", params={"source": OPINET_SOURCE}).status_code == 422
    assert client.get(prefix + "/2147483648/price-history", params={"source": OPINET_SOURCE}).status_code == 422
    assert client.get(prefix + "/999999/price-history", params={"source": OPINET_SOURCE}).status_code == 404
    places = client.get("/v1/transport/features/places", params={"kind": "fuel_station"}).json()["items"]
    assert len(places) == 1 and places[0]["brand_code"] == "SKE"
    assert places[0]["brand_name"] == "SK에너지" and places[0]["source"] == OPINET_SOURCE
