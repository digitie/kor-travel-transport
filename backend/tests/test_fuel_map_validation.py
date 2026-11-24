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


def test_validated_items_and_revision_pages_never_evict_each_other():
    """공개 유가 검증 항목이 아무리 많아도 관리 /map의 revision 증명 페이지를 밀어내지 않는다(그 반대도)."""
    from datetime import UTC, datetime, timedelta

    cache = module.ValidatedFuelMapItems()
    now = datetime(2026, 11, 24, tzinfo=UTC)
    cache.put_page("admin-map", b'{"items":[]}', now, now + timedelta(minutes=5))
    for price in range(1000, 1000 + module._MAX_ENTRIES * 3):
        cache.read(_raw(price))
    assert cache.get_page("admin-map", now) == b'{"items":[]}'
    assert len(cache.entries) == module._MAX_ENTRIES
    for index in range(module._MAX_PAGE_ENTRIES * 2):
        cache.put_page(("page", index), b"{}", now, None)
    assert len(cache.entries) == module._MAX_ENTRIES and len(cache.pages) == module._MAX_PAGE_ENTRIES
    assert cache.get_page("admin-map", now) is None  # 페이지는 페이지끼리만 LRU로 밀린다.


def test_validated_items_over_their_budget_are_returned_but_not_stored(monkeypatch):
    raw = _raw()
    monkeypatch.setattr(module, "_MAX_BYTES", len(raw.encode()))  # 원문만 들어가고 원문+결과는 넘친다.
    cache = module.ValidatedFuelMapItems()
    cache.read(_raw(1800))
    payload, count = cache.read(raw)
    assert count == 1 and json.loads(payload)[0]["prices"][0]["price"] == 1700
    assert not cache.entries and cache.bytes == 0
