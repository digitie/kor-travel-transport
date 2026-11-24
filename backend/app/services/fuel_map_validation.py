"""실제 장소 JSON 전체가 같은 경우에만 완료한 지도 항목 검증·직렬화를 재사용한다.

기본 경로는 매 요청 DB 조회를 유지한다. 완전한 transaction revision이 증명된
장소 페이지는 business 시간 경계까지만 재사용한다. digest가 같아도 원문 바이트를
대조한다. 변경된 가격·좌표·날짜·편의 정보는 반드시 같은 전체 DTO 검증을 다시 거친다.

페이지와 검증 항목은 슬롯·바이트 예산을 따로 갖는다(2026-11-24 감사). 예전에는 8개·32MiB를 함께 쓰고
항목을 넣을 때 페이지를 먼저 버려, 팬마다 bbox가 달라 재사용이 드문 공개 유가 검증 항목 8건이 관리 /map의
revision 증명 페이지를 모두 밀어냈다. 이제 항목은 항목끼리만, 페이지는 페이지끼리만 LRU로 밀어낸다.
항목 예산을 넘는 큰 입력(예: limit 5000 공개 유가는 본문만 약 7.4MB라 원문+결과가 두 배다)은 저장하지 않는다. 다시 나올 가능성이
낮은데 한 건이 예산 전체를 비우기 때문이다.
"""

import hashlib
import threading
from collections import OrderedDict

from pydantic import TypeAdapter

from app.schemas import TransportPlaceMapItem

_ITEMS = TypeAdapter(list[TransportPlaceMapItem])
# 검증 항목(원문+검증 결과). 공개 유가 limit 300 응답 본문이 약 0.44MB(감사 측정)라 한 건은 1MB 안팎이다.
_MAX_BYTES = 8 * 1024 * 1024
_MAX_ENTRIES = 8
# revision 증명 페이지 본문(관리 /map 한 화면은 최대 900곳). 두 예산 합계는 예전과 같은 32MiB다.
_MAX_PAGE_BYTES = 24 * 1024 * 1024
_MAX_PAGE_ENTRIES = 16


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
                self._trim_entries()
        return payload, count

    def _trim_entries(self):
        while self.entries and (self.bytes > _MAX_BYTES or len(self.entries) > _MAX_ENTRIES):
            old = self.entries.popitem(last=False)[1]
            self.bytes -= len(old[0]) + len(old[1])

    def _trim_pages(self):
        while self.pages and (self.page_bytes > _MAX_PAGE_BYTES or len(self.pages) > _MAX_PAGE_ENTRIES):
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
        if len(body) > _MAX_PAGE_BYTES:
            return
        with self.lock:
            previous = self.pages.pop(key, None)
            if previous is not None:
                self.page_bytes -= len(previous[0])
            self.pages[key] = body, at, boundary
            self.page_bytes += len(body)
            self._trim_pages()


_validated_items = ValidatedFuelMapItems()


def validated_fuel_map_items(raw: str) -> tuple[bytes, int]:
    return _validated_items.read(raw)


def validated_place_map_items(raw: bytes) -> tuple[bytes, int]:
    """현재 DB에서 조립한 다중 종류 항목도 같은 DTO·바이트 검산으로 재사용한다."""
    return _validated_items.read(raw)
