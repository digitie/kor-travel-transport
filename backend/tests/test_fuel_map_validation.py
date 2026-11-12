"""지도 검증 결과는 TTL 없이 전체 입력 바이트 일치 때만 재사용한다."""

import json

import pytest
from app.schemas import TransportPlaceMapResponse
from app.services import fuel_map_validation as module
from pydantic import ValidationError


def _raw(price=1700, **extra):
    return json.dumps(
        [
            {
                "id": 1,
                "kind": "fuel_station",
                "source": "opinet",
                "name": "검산 주유소",
                "longitude": 127,
                "latitude": 37,
                "prices": [
                    {
                        "product_code": "B027",
                        "price": price,
                        "observed_at": "2026-11-07T12:34:56.123456Z",
                        "collected_at": "2026-11-07T12:34:56.123456Z",
                    }
                ],
                "updated_at": "2026-11-07T12:34:56Z",
                **extra,
            }
        ],
        ensure_ascii=False,
    )


def test_fuel_item_cache_matches_whole_dto_and_revalidates_changed_input():
    cache = module.ValidatedFuelMapItems()
    raw = _raw()
    payload, count = cache.read(raw)
    expected = TransportPlaceMapResponse.model_validate_json(
        '{"generated_at":"2026-11-07T13:00:00Z","items":' + raw + "}",
    )
    assert (
        json.loads(payload) == expected.model_dump(mode="json")["items"] and count == 1
    )
    assert cache.read(raw)[0] is payload
    changed = cache.read(_raw(1800, longitude=None))[0]
    assert changed != payload
    assert json.loads(changed)[0]["prices"][0]["price"] == 1800
    assert json.loads(changed)[0]["latitude"] is None
    bad = _raw().replace("2026-11-07T12:34:56.123456Z", "invalid-date")
    with pytest.raises(ValidationError):
        cache.read(bad)


def test_fuel_item_cache_checks_source_bytes_even_on_digest_collision(monkeypatch):
    class Digest:
        def digest(self):
            return b"same-test-digest"

    monkeypatch.setattr(module.hashlib, "sha256", lambda _: Digest())
    cache = module.ValidatedFuelMapItems()
    a, b = _raw(1700), _raw(1800)
    assert len(a.encode()) == len(b.encode())
    assert json.loads(cache.read(a)[0])[0]["prices"][0]["price"] == 1700
    assert json.loads(cache.read(b)[0])[0]["prices"][0]["price"] == 1800
    assert json.loads(cache.read(a)[0])[0]["prices"][0]["price"] == 1700


def test_fuel_item_cache_keeps_lru_capacity_and_handles_empty_and_oversize(monkeypatch):
    monkeypatch.setattr(module, "_MAX_ENTRIES", 2)
    cache = module.ValidatedFuelMapItems()
    for price in (1700, 1800, 1900):
        cache.read(_raw(price))
    assert len(cache.entries) == 2 and 0 < cache.bytes <= module._MAX_BYTES
    assert cache.read("[]") == (b"[]", 0)
    monkeypatch.setattr(module, "_MAX_BYTES", 1)
    assert json.loads(cache.read(_raw(2000))[0])[0]["prices"][0]["price"] == 2000


def test_fuel_item_cache_does_not_hold_lru_lock_while_validating(monkeypatch):
    cache = module.ValidatedFuelMapItems()
    adapter = module._ITEMS

    class CheckedAdapter:
        def validate_json(self, raw):
            assert cache.lock.acquire(blocking=False)
            cache.lock.release()
            return adapter.validate_json(raw)

        def dump_json(self, value):
            assert cache.lock.acquire(blocking=False)
            cache.lock.release()
            return adapter.dump_json(value)

    monkeypatch.setattr(module, "_ITEMS", CheckedAdapter())
    assert cache.read(_raw())[1] == 1
