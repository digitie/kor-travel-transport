"""실제 장소 JSON 전체가 같은 경우에만 완료한 지도 항목 검증·직렬화를 재사용한다.

기본 경로는 매 요청 DB 조회를 유지한다. 완전한 transaction revision이 증명된
장소 페이지도 같은 메모리 상한을 공유하며 business 시간 경계까지만 재사용한다. digest가 같아도 원문 바이트를
대조한다. 변경된 가격·좌표·날짜·편의 정보는 반드시 같은 전체 DTO 검증을 다시 거친다.
"""

import hashlib
import threading
from collections import OrderedDict

from pydantic import TypeAdapter

from app.schemas import TransportPlaceMapItem

_ITEMS = TypeAdapter(list[TransportPlaceMapItem])
_MAX_BYTES = 32 * 1024 * 1024
_MAX_ENTRIES = 8


class ValidatedFuelMapItems:
    def __init__(self):
        self.entries = OrderedDict()
        self.bytes = 0
        self.pages = OrderedDict()
        self.page_bytes = 0
        self.lock = threading.Lock()

    def read(self, raw: str | bytes) -> tuple[bytes, int]:
        source = raw.encode("utf-8") if isinstance(raw, str) else raw
        key = hashlib.sha256(source).digest(), len(source)
        with self.lock:
            found = self.entries.get(key)
        # 큰 바이트 비교·Pydantic 검증·직렬화는 LRU 잠금 밖에서 한다.
        if found is not None and found[0] == source:
            with self.lock:
                if self.entries.get(key) is found:
                    self.entries.move_to_end(key)
            return found[1], found[2]
        validated = _ITEMS.validate_json(source)
        payload = _ITEMS.dump_json(validated)
        count = len(validated)
        size = len(source) + len(payload)
        if size <= _MAX_BYTES:
            with self.lock:
                previous = self.entries.pop(key, None)
                if previous is not None:
                    self.bytes -= len(previous[0]) + len(previous[1])
                self.entries[key] = source, payload, count
                self.bytes += size
                self._trim(prefer_pages=False)
        return payload, count

    def _trim(self, *, prefer_pages):
        while self.bytes + self.page_bytes > _MAX_BYTES or len(self.entries) + len(self.pages) > _MAX_ENTRIES:
            if self.entries and (prefer_pages or not self.pages):
                old = self.entries.popitem(last=False)[1]
                self.bytes -= len(old[0]) + len(old[1])
            else:
                old = self.pages.popitem(last=False)[1]
                self.page_bytes -= len(old[0])

    def get_page(self, key, at):
        with self.lock:
            found = self.pages.get(key)
            if found is None:
                return None
            body, since, until = found
            if at < since or (until is not None and at >= until):
                self.pages.pop(key)
                self.page_bytes -= len(body)
                return None
            self.pages.move_to_end(key)
            return body

    def put_page(self, key, body, at, boundary):
        if len(body) > _MAX_BYTES:
            return
        with self.lock:
            previous = self.pages.pop(key, None)
            if previous is not None:
                self.page_bytes -= len(previous[0])
            self.pages[key] = body, at, boundary
            self.page_bytes += len(body)
            self._trim(prefer_pages=True)


_validated_items = ValidatedFuelMapItems()


def validated_fuel_map_items(raw: str) -> tuple[bytes, int]:
    return _validated_items.read(raw)


def validated_place_map_items(raw: bytes) -> tuple[bytes, int]:
    """현재 DB에서 조립한 다중 종류 항목도 같은 DTO·바이트 검산으로 재사용한다."""
    return _validated_items.read(raw)
