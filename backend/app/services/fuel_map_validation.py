"""실제 DB JSON 전체가 같은 경우에만 완료한 지도 항목 검증·직렬화를 재사용한다.

매 요청 DB 조회를 유지하므로 TTL/가격 반영 지연은 없다. digest가 같아도 원문 바이트를
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
        self.lock = threading.Lock()

    def read(self, raw: str) -> tuple[bytes, int]:
        source = raw.encode("utf-8")
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
                while self.bytes > _MAX_BYTES or len(self.entries) > _MAX_ENTRIES:
                    old = self.entries.popitem(last=False)[1]
                    self.bytes -= len(old[0]) + len(old[1])
        return payload, count


_validated_items = ValidatedFuelMapItems()


def validated_fuel_map_items(raw: str) -> tuple[bytes, int]:
    return _validated_items.read(raw)
