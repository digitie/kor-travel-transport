"""PostgreSQL 전체 주차 이력의 재생성 가능한 읽기 캐시.

원본(`parking_snapshots`)은 삽입 전용이다. 그래서 처음(기동)과 드문 예외에만 30일 전체를 다시 만들고,
수집마다는 직전 읽기의 최대 id 이후 새 행이 닿은 (관측 시각, 주차장) 키만 다시 골라 끼워 넣는다(증분).
기간(30일) 밖 앞부분은 갱신 때마다 잘라 낸다. 증분 결과는 같은 시점의 전체 재생성과 bytes 단위로 같다.
항목은 범위마다 UTC 하루 단위 불변 조각으로 나눠 두고, 바뀐 날짜 조각만 새로 만든다. gzip 본문은 조각마다 보관한
deflate를 이어 붙여 만든다(갱신 뒤 다시 압축하는 것은 바뀐 날짜와 첫 날짜뿐).
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import struct
import sys
import threading
import zlib
from bisect import bisect_left
from collections import OrderedDict, defaultdict
from collections.abc import Mapping
from contextlib import suppress
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic, process_time, sleep, thread_time
from types import MappingProxyType
from typing import NamedTuple
from weakref import WeakValueDictionary
from uuid import uuid4
from zoneinfo import ZoneInfo

import brotli
from pydantic_core import to_json
from sqlalchemy import case, func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import StreamingResponse

from app.core.time_utils import now_utc, serialize_utc
from app.models import Airport, ParkingSnapshot

try:  # POSIX 전용이다. Windows 개발 환경에서는 최대 RSS를 null로 기록한다.
    import resource
except ImportError:  # pragma: no cover - 운영(Linux)에는 항상 있다.
    resource = None

logger = logging.getLogger(__name__)
POLL_SECONDS = 5
MAX_UNCHECKED_SECONDS = 30
MAX_PREPARED_RESPONSES = 8
# 500k 행/rail 간섭 교대 측정으로 선택한 협력 단위다. TTL·폴링 주기와 독립이다.
HISTORY_ENCODING_YIELD_ROWS = 400
# DB 결과 변환이 API event loop를 한 번에 오래 점유하지 않게 한다.
HISTORY_FETCH_ROWS = 2048
#: 증분 갱신 한 번이 다룰 (관측 시각, 주차장) 키 상한. 넘으면(대량 이관·복원) 전체 재생성으로 간다.
INCREMENTAL_MAX_KEYS = 50_000
#: 증분의 안전망. 마지막 전체 재생성이 이보다 오래되면 이용이 적은 새벽(KST)에 한 번 전체 재생성한다.
FULL_REBUILD_MAX_AGE = timedelta(hours=20)
FULL_REBUILD_LOCAL_HOURS = range(3, 5)
#: 전체 재생성 중 원본이 바뀌었을 때 결과를 버리지 않고 증분 기준으로 채택한 뒤 따라잡는 증분 횟수 상한.
#: 따라잡는 사이에도 수집이 계속 끼면 마지막 결과를 검증 전 기준(`pending_base`)으로 두고 다음 확인이 이어 간다.
ADOPT_MAX_CATCHUPS = 3
#: 캐시가 보관하는 기간. 전체 이력 요청(최대 30일) + 여유. 여유가 없으면 갱신 직전에 시각을 정하고 전송 슬롯을
#: 기다리던 30일 요청이, 갱신으로 앞부분이 잘린 snapshot(`cutoff < earliest`)을 못 쓰고 직접 SQL로 떨어진다.
HISTORY_WINDOW = timedelta(days=30)
HISTORY_WINDOW_MARGIN = timedelta(minutes=15)
_KST = ZoneInfo("Asia/Seoul")
# 캐시를 쓸 수 없을 때 직접 조회를 한 번에 하나로 묶는 범위. 주차장 하나는 30일이어도 약
# 8,640행이라 묶지 않는다. 공항·전체 범위도 7일 이하(기본 3일, 전체 7일 약 12만 행)는 기존처럼
# 전송 슬롯 안에서 바로 돈다. 그보다 긴 공항·전체 범위(전체 30일 약 52만 행·75MB)만 묶는다.
DIRECT_FALLBACK_SERIAL_MIN_DAYS = 8
# 차례를 기다리는 요청이 깨움 신호를 놓쳐도 다시 확인하는 간격(초).
DIRECT_FALLBACK_RECHECK_SECONDS = 1.0
# 직접 조회 응답을 요청마다 압축하는 수준(캐시의 요청 시 압축 부분과 같다).
DIRECT_FALLBACK_BROTLI_QUALITY = 6


def direct_fallback_is_heavy(parking_lot_id: int | None, days: int) -> bool:
    """직접 조회를 프로세스당 한 번에 하나로 묶을 범위인지(`DIRECT_FALLBACK_SERIAL_MIN_DAYS` 참고)."""
    return not parking_lot_id and days >= DIRECT_FALLBACK_SERIAL_MIN_DAYS


class BoundedHistoryResponse(StreamingResponse):
    """대량 본문을 backpressure 단위로 보내고 실패해도 점유 슬롯을 돌려준다."""

    def __init__(self, content: bytes, *, delivery_semaphore: asyncio.Semaphore, **kwargs) -> None:
        async def chunks():
            for start in range(0, len(content), 64 * 1024):
                yield content[start:start + 64 * 1024]

        super().__init__(chunks(), **kwargs)
        self.body = content
        self.delivery_semaphore = delivery_semaphore

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.delivery_semaphore.release()


class WorkerCpuMeter:
    """갱신 worker thread 안에서 잰 thread CPU 합계.

    `thread_time()`은 호출한 thread의 CPU만 센다. 그래서 같은 프로세스의 요청 처리와
    섞이지 않는다. event loop 위의 DB 행 수신은 여기에 들어가지 않는다.
    """

    def __init__(self) -> None:
        self.seconds = 0.0
        self._lock = threading.Lock()

    def call(self, fn, *args):
        started = thread_time()
        try:
            return fn(*args)
        finally:
            elapsed = thread_time() - started
            with self._lock:
                self.seconds += elapsed


#: 진행 중인 갱신의 CPU 계측기. `refresh_once`가 정하고 적재·조각·압축 thread 호출(`_run_worker`)이 읽는다.
#: 함수 인자로 넘기지 않아 `load_snapshot`·`load_changes`의 호출 모양이 그대로다.
_WORKER_CPU: ContextVar[WorkerCpuMeter | None] = ContextVar("parking_history_worker_cpu", default=None)


async def _run_worker(fn, *args):
    meter = _WORKER_CPU.get()
    if meter is None:
        return await asyncio.to_thread(fn, *args)
    return await asyncio.to_thread(meter.call, fn, *args)


def peak_rss_kib() -> int | None:
    """프로세스 시작 이후 최대 RSS(KiB). 갱신 전후 값이 다르면 그 갱신이 최고점을 올린 것이다."""
    if resource is None:
        return None
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux는 KiB, macOS는 byte 단위다.
    return value // 1024 if sys.platform == "darwin" else int(value)


async def run_history_cpu(fn, *args):
    """요청 취소 뒤에도 실행 중인 CPU 작업이 끝나기 전에는 슬롯을 반환하지 않는다."""
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        raise


@dataclass(frozen=True, slots=True)
class CachedHistoryItem:
    observed_at: datetime
    airport_code: str
    parking_lot_id: int
    encoded: bytes


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_DAY = timedelta(days=1)
_GZIP_HEADER = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"  # mtime 0, 최대 압축, OS 미상(gzip.compress와 같은 꼴)
_DEFLATE_FINAL = b"\x03\x00"  # 빈 마지막 고정 Huffman 블록
_BODY_PREFIX = b'{"items":['
_BODY_SUFFIX = b'],"next_cursor":null}'
#: 날짜 조각 gzip 수준. 조각은 한 번 압축해 보관하므로 크기를 우선해 9다(합성 55만 행 30일: 9는 2.0MB, 6은 2.5MB).
#: 요청마다 새로 압축하는 첫 날짜(부분)·머리말·꼬리는 6이다. 압축을 푼 본문은 수준과 무관하게 같다.
HISTORY_GZIP_SEGMENT_LEVEL = 9
HISTORY_GZIP_HEAD_LEVEL = 6


def _day_of(value: datetime) -> int:
    return (value - _EPOCH) // _DAY


def _day_start(day: int) -> datetime:
    return _EPOCH + day * _DAY


# --- gzip 조각 이어 붙이기 -------------------------------------------------------------
# 날짜 조각마다 독립 deflate 스트림(Z_FULL_FLUSH로 바이트 정렬, 마지막 블록 아님)을 만들어 두고, 요청 때 gzip 머리말 +
# 조각들 + 빈 마지막 블록 + CRC32·길이 꼬리로 한 member의 정상 gzip을 조립한다. 조각은 서로를 참조하지 않으므로
# 이어 붙인 스트림은 표준 inflate로 그대로 풀린다. CRC32는 zlib의 crc32_combine(GF(2) 곱)으로 조각 CRC를 합친다.
_CRC_POLY = 0xEDB88320


def _multmodp(a: int, b: int) -> int:
    m, p = 1 << 31, 0
    while True:
        if a & m:
            p ^= b
            if (a & (m - 1)) == 0:
                return p
        m >>= 1
        b = (b >> 1) ^ _CRC_POLY if b & 1 else b >> 1


def _x2n_table() -> tuple[int, ...]:
    table, p = [], 1 << 30  # x^1
    for _ in range(32):
        table.append(p)
        p = _multmodp(p, p)
    return tuple(table)


_X2N = _x2n_table()


def crc32_combine(crc1: int, crc2: int, len2: int) -> int:
    """`zlib.crc32(a + b) == crc32_combine(zlib.crc32(a), zlib.crc32(b), len(b))`(zlib 1.2.12 알고리즘)."""
    p, k, n = 1 << 31, 3, len2
    while n:
        if n & 1:
            p = _multmodp(_X2N[k & 31], p)
        n >>= 1
        k += 1
    return _multmodp(p, crc1) ^ crc2


class DeflatedSegment(NamedTuple):
    data: bytes
    crc: int
    length: int


def deflate_segment(raw: bytes, level: int = HISTORY_GZIP_SEGMENT_LEVEL) -> DeflatedSegment:
    compressor = zlib.compressobj(level, zlib.DEFLATED, -15)
    return DeflatedSegment(compressor.compress(raw) + compressor.flush(zlib.Z_FULL_FLUSH), zlib.crc32(raw), len(raw))


def assemble_gzip(segments: list[DeflatedSegment]) -> bytes:
    crc = length = 0
    for segment in segments:
        crc = crc32_combine(crc, segment.crc, segment.length)
        length += segment.length
    return b"".join((_GZIP_HEADER, *(segment.data for segment in segments), _DEFLATE_FINAL,
                     struct.pack("<II", crc, length & 0xFFFFFFFF)))


class HistoryChunk:
    """한 범위의 UTC 하루치 항목(불변). 앞에 쉼표를 붙인 본문 조각의 deflate는 처음 쓸 때 한 번 만들어 둔다.

    증분 갱신은 바뀐 날짜의 조각만 새로 만들고 나머지 조각 객체는 그대로 넘긴다. 그래서 압축 조각도 그대로 재사용된다.
    """

    __slots__ = ("day", "items", "times", "_deflated")

    def __init__(self, day: int, items: tuple[CachedHistoryItem, ...], times: tuple[datetime, ...]) -> None:
        self.day, self.items, self.times = day, items, times
        self._deflated: DeflatedSegment | None = None

    def deflated(self) -> DeflatedSegment:
        segment = self._deflated
        if segment is None:
            segment = deflate_segment(b"," + b",".join(item.encoded for item in self.items))
            self._deflated = segment
        return segment


def _chunks(items, times) -> tuple[HistoryChunk, ...]:
    """정렬된 항목을 UTC 날짜 경계로 나눈다(경계는 bisect로 찾는다)."""
    chunks, pos, size = [], 0, len(items)
    while pos < size:
        day = _day_of(times[pos])
        end = bisect_left(times, _day_start(day + 1), pos)
        chunks.append(HistoryChunk(day, tuple(items[pos:end]), tuple(times[pos:end])))
        pos = end
    return tuple(chunks)


@dataclass(frozen=True, slots=True)
class HistoryScopeIndex:
    """한 범위(전체·공항·주차장)의 오래된 순서 항목. 날짜 조각의 나열이다."""

    chunks: tuple[HistoryChunk, ...]
    days: tuple[int, ...]
    offsets: tuple[int, ...]  # 조각마다 범위 안 시작 순번
    size: int

    @classmethod
    def of(cls, chunks: tuple[HistoryChunk, ...]) -> HistoryScopeIndex:
        offsets, total = [], 0
        for chunk in chunks:
            offsets.append(total)
            total += len(chunk.items)
        return cls(chunks, tuple(chunk.day for chunk in chunks), tuple(offsets), total)

    @property
    def items(self) -> tuple[CachedHistoryItem, ...]:
        return tuple(item for chunk in self.chunks for item in chunk.items)

    @property
    def times(self) -> tuple[datetime, ...]:
        return tuple(value for chunk in self.chunks for value in chunk.times)

    def locate(self, cutoff: datetime) -> tuple[int, int]:
        """(조각 번호, 조각 안 순번): `cutoff` 이상인 첫 항목."""
        index = bisect_left(self.days, _day_of(cutoff))
        if index < len(self.chunks) and self.days[index] == _day_of(cutoff):
            within = bisect_left(self.chunks[index].times, cutoff)
            if within < len(self.chunks[index].items):
                return index, within
            return index + 1, 0
        return index, 0

    def start_index(self, cutoff: datetime) -> int:
        index, within = self.locate(cutoff)
        return self.size if index >= len(self.chunks) else self.offsets[index] + within

    def splice(
        self, earliest: datetime, changed_days: frozenset[int],
        changed_keys: frozenset[tuple[datetime, int]], winners: list[CachedHistoryItem],
    ) -> HistoryScopeIndex:
        """증분 반영: 기간 밖 앞 조각을 버리고(첫 조각은 잘라 새로 만든다), 바뀐 키가 있는 날짜의 조각만 다시 만든다.
        나머지 조각 객체(와 압축 조각)는 그대로 재사용한다. 늦게 들어온 옛 관측 하나가 그 뒤 날짜를 모두 다시 만들지 않는다."""
        chunks = list(self.chunks)
        first_day = _day_of(earliest)
        keep_from = bisect_left(self.days, first_day)
        chunks = chunks[keep_from:]
        if chunks and chunks[0].day == first_day:
            head = chunks[0]
            trim = bisect_left(head.times, earliest)
            if trim:
                chunks[0] = HistoryChunk(head.day, head.items[trim:], head.times[trim:])
                if not chunks[0].items:
                    chunks.pop(0)
        if changed_days:
            added: dict[int, list[CachedHistoryItem]] = defaultdict(list)
            for item in winners:
                added[_day_of(item.observed_at)].append(item)
            rebuilt = []
            for chunk in chunks:
                if chunk.day in changed_days:
                    kept = [item for item in chunk.items if _history_key(item) not in changed_keys]
                    extra = added.pop(chunk.day, [])
                    # 이 범위의 키가 바뀌지 않았으면(다른 공항·주차장의 새 행) 조각을 그대로 둔다(압축 조각 재사용).
                    if extra or len(kept) != len(chunk.items):
                        kept.extend(extra)
                        kept.sort(key=_history_key)
                        if kept:
                            rebuilt.append(HistoryChunk(chunk.day, tuple(kept), tuple(item.observed_at for item in kept)))
                        continue
                rebuilt.append(chunk)
            for day, extra in added.items():  # 이 범위에 아직 없던 날짜
                extra.sort(key=_history_key)
                rebuilt.append(HistoryChunk(day, tuple(extra), tuple(item.observed_at for item in extra)))
            rebuilt.sort(key=lambda chunk: chunk.day)
            chunks = rebuilt
        if len(chunks) == len(self.chunks) and all(new is old for new, old in zip(chunks, self.chunks, strict=True)):
            return self
        return HistoryScopeIndex.of(tuple(chunks))


_EMPTY_SCOPE = HistoryScopeIndex((), (), (), 0)


def _cached_item(row) -> CachedHistoryItem:
    # 인덱스와 JSON에 같은 UTC 값을 쓰고 대량 행의 중복 변환을 피한다.
    # 전체 재생성과 증분이 이 한 함수로 인코딩하므로 같은 행은 같은 bytes가 된다.
    observed_at = serialize_utc(row.observed_at)
    airport_code, parking_lot_id = row.code, row.parking_lot_id
    return CachedHistoryItem(
        observed_at=observed_at,
        airport_code=airport_code,
        parking_lot_id=parking_lot_id,
        encoded=to_json({
            "airport_code": airport_code,
            "parking_lot_id": parking_lot_id,
            "observed_at": observed_at,
            "occupied_spaces": row.occupied_spaces,
            "total_spaces": row.total_spaces,
            "available_spaces": row.available_spaces,
        }),
    )


def _encode_rows(rows) -> list[CachedHistoryItem]:
    prepared = []
    for index, row in enumerate(rows, 1):
        prepared.append(_cached_item(row))
        # 긴 변환 중에도 API thread가 GIL을 다시 얻을 기회를 작은 묶음마다 준다.
        if index % HISTORY_ENCODING_YIELD_ROWS == 0:
            sleep(0)
    return prepared


def _history_key(item: CachedHistoryItem) -> tuple[datetime, int]:
    # 원본 SQL의 `ORDER BY observed_at, parking_lot_id`와 같은 전순서다(DISTINCT ON 키라 중복이 없다).
    return item.observed_at, item.parking_lot_id


@dataclass(frozen=True, slots=True)
class ParkingHistorySnapshot:
    earliest_observed_at: datetime
    max_snapshot_id: int
    everything: HistoryScopeIndex
    airport_indexes: Mapping[str, HistoryScopeIndex]
    lot_indexes: Mapping[int, HistoryScopeIndex]
    #: 같은 읽기 시점의 원본 전체 `count(*)`(= `id <= max_snapshot_id` 행 수, 기간과 무관).
    #: 다음 증분에서 `id <= max_snapshot_id` 행 수가 그대로여야 늦게 commit된 낮은 id·삭제가 없다고 본다.
    #: None이면 증분하지 않고 전체 재생성한다.
    source_row_count: int | None = None
    #: 마지막 전체 재생성의 읽기 시각(UTC). 증분은 물려받는다.
    full_built_at: datetime | None = None

    @property
    def items(self) -> tuple[CachedHistoryItem, ...]:
        return self.everything.items

    @property
    def times(self) -> tuple[datetime, ...]:
        return self.everything.times

    @property
    def size(self) -> int:
        return self.everything.size

    @classmethod
    def from_rows(
        cls, earliest_observed_at: datetime, max_snapshot_id: int, rows: list,
        source_row_count: int | None = None, full_built_at: datetime | None = None,
    ) -> ParkingHistorySnapshot:
        items = _encode_rows(rows)
        airports: dict[str, list[CachedHistoryItem]] = defaultdict(list)
        lots: dict[int, list[CachedHistoryItem]] = defaultdict(list)
        for item in items:
            airports[item.airport_code].append(item)
            lots[item.parking_lot_id].append(item)
        # 같은 인코딩 객체의 참조만 분할한다. 원본 순서·동일 시각 순서를 그대로 유지한다.
        def scope(group):
            return HistoryScopeIndex.of(_chunks(group, [item.observed_at for item in group]))
        return cls(earliest_observed_at, max_snapshot_id, scope(items),
                   MappingProxyType({key: scope(group) for key, group in airports.items()}),
                   MappingProxyType({key: scope(group) for key, group in lots.items()}),
                   source_row_count, full_built_at)

    def with_changes(
        self, earliest_observed_at: datetime, max_snapshot_id: int, source_row_count: int,
        changed_keys: frozenset[tuple[datetime, int]], rows: list,
    ) -> ParkingHistorySnapshot:
        """새 적재분만 반영한 다음 snapshot. 같은 읽기 시점의 전체 재생성과 결과가 같다.

        `changed_keys`는 새 행이 닿은 (UTC 관측 시각, 주차장) 키이고, `rows`는 그 키마다 전체 재생성과 같은
        규칙(DISTINCT ON, live 우선, 최신 수집·id)으로 고른 행이다. 그 키의 기존 항목을 고른 행으로 바꾸고,
        `earliest_observed_at`보다 이른 앞부분을 버린다. 바뀐 날짜 조각만 새로 만들고, 나머지 조각(인코딩 bytes·
        압축 조각 포함)은 그대로 재사용한다.
        """
        earliest = max(earliest_observed_at, self.earliest_observed_at)
        winners = sorted((item for item in _encode_rows(rows) if item.observed_at >= earliest), key=_history_key)
        keys = frozenset(key for key in changed_keys if key[0] >= earliest)
        changed_days = frozenset(_day_of(key[0]) for key in keys)

        def scopes(existing: Mapping, key_of) -> Mapping:
            grouped: dict = defaultdict(list)
            for item in winners:
                grouped[key_of(item)].append(item)
            result = {}
            for scope_key in (*existing, *(key for key in grouped if key not in existing)):
                spliced = existing.get(scope_key, _EMPTY_SCOPE).splice(
                    earliest, changed_days, keys, grouped.get(scope_key, []))
                if spliced.size:
                    result[scope_key] = spliced
            return MappingProxyType(result)

        return ParkingHistorySnapshot(
            earliest, max_snapshot_id, self.everything.splice(earliest, changed_days, keys, winners),
            scopes(self.airport_indexes, lambda item: item.airport_code),
            scopes(self.lot_indexes, lambda item: item.parking_lot_id),
            source_row_count, self.full_built_at,
        )

    def scope_index(self, airport_code: str | None, parking_lot_id: int | None) -> HistoryScopeIndex:
        if parking_lot_id:
            return self.lot_indexes.get(parking_lot_id, _EMPTY_SCOPE)
        if airport_code:
            return self.airport_indexes.get(airport_code, _EMPTY_SCOPE)
        return self.everything

    def start_index(self, cutoff: datetime, airport_code: str | None, parking_lot_id: int | None) -> int:
        return self.scope_index(airport_code, parking_lot_id).start_index(cutoff)

    def render(self, cutoff: datetime, airport_code: str | None, parking_lot_id: int | None) -> bytes:
        scope = self.scope_index(airport_code, parking_lot_id)
        index, within = scope.locate(cutoff)
        # 타 공항 전체 순회 없이 선택된 범위의 항목만 읽는다.
        chunks = scope.chunks[index:]
        parts = [b",".join([item.encoded for item in (chunk.items[within:] if position == 0 else chunk.items)])
                 for position, chunk in enumerate(chunks)]
        return _BODY_PREFIX + b",".join(parts) + _BODY_SUFFIX

    def render_gzip(self, cutoff: datetime, airport_code: str | None, parking_lot_id: int | None) -> bytes:
        """`gzip.decompress(render_gzip(...)) == render(...)`. 첫 날짜(부분)와 머리·꼬리만 새로 압축하고,
        나머지 날짜는 조각에 보관한 압축을 이어 붙인다. 30일 전체도 갱신 뒤 첫 요청에 하루치만 압축한다."""
        scope = self.scope_index(airport_code, parking_lot_id)
        index, within = scope.locate(cutoff)
        chunks = scope.chunks[index:]
        if not chunks:
            return assemble_gzip([deflate_segment(_BODY_PREFIX + _BODY_SUFFIX, HISTORY_GZIP_HEAD_LEVEL)])
        head = chunks[0]
        segments = [deflate_segment(_BODY_PREFIX + b",".join(item.encoded for item in head.items[within:]),
                                    HISTORY_GZIP_HEAD_LEVEL)]
        segments.extend(chunk.deflated() for chunk in chunks[1:])
        segments.append(deflate_segment(_BODY_SUFFIX, HISTORY_GZIP_HEAD_LEVEL))
        return assemble_gzip(segments)


def accepts_gzip(header: str) -> bool:
    for value in header.split(","):
        parts = [part.strip().lower() for part in value.split(";")]
        if parts[0] != "gzip":
            continue
        for part in parts[1:]:
            if part.startswith("q="):
                try:
                    return float(part[2:]) > 0
                except ValueError:
                    return False
        return True
    return False


class _HistorySourceRow(NamedTuple):
    """드라이버의 무거운 Row 대신 변환 때까지 필요한 여섯 값만 보관한다."""

    observed_at: datetime
    parking_lot_id: int
    code: str
    occupied_spaces: int
    total_spaces: int
    available_spaces: int


def history_rows_statement(*conditions):
    """관측 시각·주차장마다 live 우선, 최신 수집 행 하나를 오래된 순서로 고르는 SQL.

    전체 재생성과 증분이 같은 문장을 쓴다(증분은 바뀐 키로만 좁힌다). 그래서 고르는 규칙이 하나다.
    """
    ranked = (select(
        ParkingSnapshot.observed_at.label("observed_at"),
        ParkingSnapshot.parking_lot_id.label("parking_lot_id"),
        ParkingSnapshot.airport_id.label("airport_id"),
        ParkingSnapshot.occupied_spaces.label("occupied_spaces"),
        ParkingSnapshot.total_spaces.label("total_spaces"),
        ParkingSnapshot.available_spaces.label("available_spaces"),
    ).where(*conditions)
        .distinct(ParkingSnapshot.observed_at, ParkingSnapshot.parking_lot_id)
        .order_by(
            ParkingSnapshot.observed_at, ParkingSnapshot.parking_lot_id,
            case((func.left(ParkingSnapshot.source, 10) == "migration_", 1), else_=0),
            ParkingSnapshot.collected_at.desc(), ParkingSnapshot.id.desc(),
        ).subquery("history_rows"))
    return (select(
        ranked.c.observed_at, ranked.c.parking_lot_id, Airport.code,
        ranked.c.occupied_spaces, ranked.c.total_spaces, ranked.c.available_spaces,
    ).join(Airport, Airport.id == ranked.c.airport_id)
        .order_by(ranked.c.observed_at, ranked.c.parking_lot_id))


# 한 읽기 transaction 안의 모든 문장이 같은 시점을 본다. 최대 id·행 수·본문이 서로 어긋나지 않는다.
_CONSISTENT_READ = {"isolation_level": "REPEATABLE READ"}


async def _stream_history_rows(session: AsyncSession, statement) -> list[_HistorySourceRow]:
    connection = await session.connection()
    result = await connection.stream(statement.execution_options(yield_per=HISTORY_FETCH_ROWS))
    rows, codes = [], {}
    try:
        async for batch in result.partitions(HISTORY_FETCH_ROWS):
            for observed, lot, code, occupied, total, available in batch:
                rows.append(_HistorySourceRow(
                    observed, lot, codes.setdefault(code, code), occupied, total, available,
                ))
            await asyncio.sleep(0)
    finally:
        await result.close()
    return rows


async def load_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    earliest_observed_at: datetime | None = None,
) -> ParkingHistorySnapshot:
    built_at = now_utc()
    earliest = earliest_observed_at or built_at - HISTORY_WINDOW - HISTORY_WINDOW_MARGIN
    async with session_factory() as session:
        await session.connection(execution_options=_CONSISTENT_READ)
        max_id, row_count = (await session.execute(select(
            func.coalesce(func.max(ParkingSnapshot.id), 0), func.count(),
        ).select_from(ParkingSnapshot))).one()
        rows = await _stream_history_rows(session, history_rows_statement(
            ParkingSnapshot.observed_at >= earliest, ParkingSnapshot.id <= max_id,
        ))
    return await _run_worker(
        ParkingHistorySnapshot.from_rows, earliest, int(max_id), rows, int(row_count), built_at,
    )


def _encode_history_batch(batch) -> bytes:
    # 캐시 항목 JSON(`_cached_item`)과 같은 키 순서·UTC 직렬화다.
    return b",".join(to_json({
        "airport_code": code,
        "parking_lot_id": lot,
        "observed_at": serialize_utc(observed),
        "occupied_spaces": occupied,
        "total_spaces": total,
        "available_spaces": available,
    }) for observed, lot, code, occupied, total, available in batch)


class _StreamingBodyEncoder:
    """직접 조회 본문을 조각마다 바로 압축한다.

    br/gzip 요청은 75MB 비압축 본문을 한 번도 메모리에 모으지 않고 압축본(수 MB)만 보유한다.
    압축 bytes는 한 번에 압축한 값과 다를 수 있지만 압축을 푼 본문은 같다. 조각은 한 번에
    하나씩 순서대로 넣는다(동시 호출 없음).
    """

    def __init__(self, encoding: str) -> None:
        self.parts: list[bytes] = []
        if encoding == "br":
            compressor = brotli.Compressor(quality=DIRECT_FALLBACK_BROTLI_QUALITY)
            self._process, self._finish = compressor.process, compressor.finish
        elif encoding == "gzip":
            compressor = zlib.compressobj(HISTORY_GZIP_HEAD_LEVEL, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
            self._process, self._finish = compressor.compress, compressor.flush
        else:
            self._process, self._finish = None, None

    def write(self, data: bytes) -> None:
        output = data if self._process is None else self._process(data)
        if output:
            self.parts.append(output)

    def finish(self) -> bytes:
        if self._finish is not None:
            self.parts.append(self._finish())
        body = b"".join(self.parts)
        self.parts = []
        return body


async def render_direct_history(
    session: AsyncSession, *conditions, accept_encoding: str = "",
) -> tuple[bytes, dict[str, str]]:
    """캐시를 쓸 수 없을 때 DB에서 전체·오래된 순서 본문을 직접 만든다.

    2048행씩 받아 바로 행 JSON으로 바꾸고 압축한다. 52만 행의 Row·dict 목록을 만들지 않고,
    br/gzip 요청은 비압축 본문도 모으지 않는다(identity는 행 조각과 최종 본문 한 벌). 압축을
    푼 bytes는 기존 전체 `to_json` 직렬화·캐시 본문과 같다.
    """
    encoding = response_encoding(accept_encoding)
    encoder = _StreamingBodyEncoder(encoding)

    def write_batch(batch, first: bool) -> None:
        if not first:
            encoder.write(b",")
        encoder.write(_encode_history_batch(batch))

    connection = await session.connection()
    result = await connection.stream(
        history_rows_statement(*conditions).execution_options(yield_per=HISTORY_FETCH_ROWS)
    )
    encoder.write(_BODY_PREFIX)
    first = True
    try:
        async for batch in result.partitions(HISTORY_FETCH_ROWS):
            if batch:
                # 행 변환과 수신은 둘 다 GIL을 쥐는 Python 작업이라 겹쳐도 빨라지지 않는다(측정).
                # 묶음마다 순서대로 처리하고, 취소돼도 실행 중인 thread가 끝난 뒤에 돌아간다.
                await run_history_cpu(write_batch, batch, first)
                first = False
    finally:
        await result.close()
    encoder.write(_BODY_SUFFIX)
    return await run_history_cpu(encoder.finish), response_headers(encoding)


class IncrementalUnavailable(Exception):
    """증분으로 맞출 수 없는 원본 변화(늦은 commit·삭제·대량 적재). 전체 재생성으로 간다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def load_changes(
    session_factory: async_sessionmaker[AsyncSession],
    base: ParkingHistorySnapshot,
    *,
    earliest_observed_at: datetime | None = None,
    timings: dict[str, float] | None = None,
) -> tuple[ParkingHistorySnapshot, int]:
    """`base` 이후 새로 commit된 행만 읽어 다음 snapshot을 만든다. (snapshot, 바뀐 키 수)를 돌려준다.

    정확성 조건(하나라도 어긋나면 `IncrementalUnavailable`):
    - `id <= base.max_snapshot_id` 행 수가 `base.source_row_count`와 같다. 시퀀스는 commit 순서가 아니므로
      직전 읽기 때 진행 중이던 transaction이 낮은 id로 늦게 commit하면 이 수가 늘고, 삭제면 준다.
    - 새 행이 닿은 키 수가 `INCREMENTAL_MAX_KEYS` 이하다.
    갱신(update)은 호출자가 `pg_stat` 지문으로 걸러 전체 재생성한다(운영 코드에는 이 쓰기 경로가 없다).
    """
    if base.source_row_count is None:
        raise IncrementalUnavailable("no_row_count")
    earliest = earliest_observed_at or now_utc() - HISTORY_WINDOW - HISTORY_WINDOW_MARGIN
    watermark = base.max_snapshot_id
    timings = timings if timings is not None else {}
    started = monotonic()
    async with session_factory() as session:
        await session.connection(execution_options=_CONSISTENT_READ)
        max_id, unchanged_count, row_count = (await session.execute(select(
            func.coalesce(func.max(ParkingSnapshot.id), 0),
            func.count().filter(ParkingSnapshot.id <= watermark),
            func.count(),
        ).select_from(ParkingSnapshot))).one()
        timings["count_ms"] = round((monotonic() - started) * 1000, 1)
        if int(max_id) < watermark or int(unchanged_count) != base.source_row_count:
            raise IncrementalUnavailable("late_commit_or_delete")
        keys: frozenset[tuple[datetime, int]] = frozenset()
        rows: list[_HistorySourceRow] = []
        if int(max_id) > watermark:
            touched = select(ParkingSnapshot.parking_lot_id, ParkingSnapshot.observed_at).where(
                ParkingSnapshot.id > watermark, ParkingSnapshot.id <= max_id,
                ParkingSnapshot.observed_at >= earliest,
            ).distinct()
            touched_rows = (await session.execute(touched.limit(INCREMENTAL_MAX_KEYS + 1))).all()
            if len(touched_rows) > INCREMENTAL_MAX_KEYS:
                raise IncrementalUnavailable("too_many_changes")
            keys = frozenset((serialize_utc(observed), lot) for lot, observed in touched_rows)
            if keys:
                # 바뀐 키의 옛 행·새 행을 모두 다시 보고 전체 재생성과 같은 규칙으로 하나를 고른다
                # (같은 관측의 다른 source, 이관 행 우선순위, 늦게 들어온 옛 관측 모두 같은 결과).
                rows = await _stream_history_rows(session, history_rows_statement(
                    ParkingSnapshot.id <= max_id,
                    tuple_(ParkingSnapshot.parking_lot_id, ParkingSnapshot.observed_at).in_(touched),
                ))
    timings["changes_ms"] = round((monotonic() - started) * 1000, 1)
    splice_started = monotonic()
    snapshot = await _run_worker(
        base.with_changes, earliest, int(max_id), int(row_count), keys, rows,
    )
    timings["splice_ms"] = round((monotonic() - splice_started) * 1000, 1)
    return snapshot, len(keys)


class ParkingHistoryReadCache:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        # 응답 전송이 끝날 때까지 점유한다. 압축하지 않은 전체 이력 요청도
        # 요청 수만큼 75MB 본문을 동시에 보유하지 않게 한다.
        self.delivery_semaphore = asyncio.Semaphore(2)
        # 캐시를 쓸 수 없을 때(기동 직후·전체 재생성이 30초를 넘는 구간) 긴 범위를 직접 SQL로
        # 만드는 작업은 한 번에 하나만 한다. 전체 재생성 peak와 직접 조회 여러 개가 겹치지 않게 한다.
        # `acquire_direct_fallback`/`release_direct_fallback`으로만 쓴다.
        self.direct_fallback_lock = asyncio.Lock()
        # 캐시 확인·직접 조회 종료 때 교체하며 set한다. 차례를 기다리는 요청을 깨운다.
        self._state_changed = asyncio.Event()
        # 진행 중인 갱신의 시작 monotonic 시각. 없으면 None이다.
        self.rebuild_started_at: float | None = None
        self.snapshot: ParkingHistorySnapshot | None = None
        self.validated_at = 0.0
        self.validated_at_utc: datetime | None = None
        self.last_fingerprint: tuple[int, int, int, int] | None = None
        self.prepared_responses: OrderedDict[tuple[int, str | None, int | None, str], bytes] = OrderedDict()
        #: 검증하지 못한(요청에 쓰지 않는) 증분 기준과 그 읽기 직전 지문. 전체 재생성 결과를 채택했지만 따라잡는
        #: 동안에도 원본이 계속 바뀌었을 때만 생긴다. 다음 확인이 이 기준에서 증분하고, 게시되면 비운다.
        self.pending_base: tuple[ParkingHistorySnapshot, tuple[int, int, int, int]] | None = None
        #: 연속 증분 오류 수(경보용, finish 로그 `incremental_errors`). 증분이 한 번 성공하면 0.
        self.incremental_errors = 0
        # 같은 불변 snapshot/범위만 합친다. 대기자가 사라지면 lock도 남기지 않는다.
        self.preparation_locks: WeakValueDictionary[tuple, asyncio.Lock] = WeakValueDictionary()

    @property
    def rebuild_active(self) -> bool:
        """갱신(증분·전체)이 진행 중인지. 다른 작업이 무거운 일을 미룰 때 읽는다."""
        return self.rebuild_started_at is not None

    async def response_body(
        self, snapshot: ParkingHistorySnapshot, cutoff: datetime,
        airport_code: str | None, parking_lot_id: int | None, accept_encoding: str,
    ) -> tuple[bytes, dict[str, str]]:
        encoding = cached_response_encoding(accept_encoding)
        key = (snapshot.start_index(cutoff, airport_code, parking_lot_id), airport_code, parking_lot_id, encoding)
        async def prepare():
            if encoding != "identity" and snapshot is self.snapshot and key in self.prepared_responses:
                self.prepared_responses.move_to_end(key)
                return self.prepared_responses[key], response_headers(encoding)
            if encoding == "gzip":
                # 날짜 조각 압축을 이어 붙인다(바뀐 날짜만 새로 압축). 본문 전체를 다시 압축하지 않는다.
                prepared = await run_history_cpu(snapshot.render_gzip, cutoff, airport_code, parking_lot_id)
                headers = response_headers(encoding)
            else:
                body = await run_history_cpu(snapshot.render, cutoff, airport_code, parking_lot_id)
                prepared, headers = await run_history_cpu(encode_response, body, accept_encoding)
            if encoding != "identity" and snapshot is self.snapshot:
                self.prepared_responses[key] = prepared
                self.prepared_responses.move_to_end(key)
                while len(self.prepared_responses) > MAX_PREPARED_RESPONSES:
                    self.prepared_responses.popitem(last=False)
            return prepared, headers
        if encoding == "identity":
            return await prepare()
        lock_key = (id(snapshot), key)
        lock = self.preparation_locks.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            self.preparation_locks[lock_key] = lock
        async with lock:
            return await prepare()

    async def source_fingerprint(self) -> tuple[int, int, int, int]:
        async with self.session_factory() as session:
            current_max_id = await session.scalar(select(func.max(ParkingSnapshot.id))) or 0
            counters = (await session.execute(text(
                "SELECT n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables "
                "WHERE relid = 'parking_snapshots'::regclass"
            ))).one()
        return current_max_id, *(int(value) for value in counters)

    def refresh_mode(self, fingerprint: tuple[int, int, int, int]) -> tuple[str, str]:
        """(mode, reason). mode는 `incremental` 또는 `full`이다.

        `pending_base`가 있으면 게시된 snapshot 대신 그 기준과 그 읽기 직전 지문으로 판단한다.
        """
        snapshot, last = self.pending_base or (self.snapshot, self.last_fingerprint)
        if snapshot is None or last is None:
            return "full", "cold"
        if snapshot.source_row_count is None:
            return "full", "no_row_count"
        if fingerprint[2:] != last[2:]:
            # update·delete 통계가 움직였다. 삽입 전용 가정이 깨졌으니 처음부터 다시 만든다.
            return "full", "update_or_delete"
        if fingerprint[0] < snapshot.max_snapshot_id:
            return "full", "max_id_decreased"
        built_at = snapshot.full_built_at
        now = now_utc()
        if (built_at is not None and now - built_at >= FULL_REBUILD_MAX_AGE
                and now.astimezone(_KST).hour in FULL_REBUILD_LOCAL_HOURS):
            return "full", "periodic"
        return "incremental", "adopted_base" if self.pending_base is not None else "new_rows"

    async def prepare_full_window(
        self, snapshot: ParkingHistorySnapshot,
    ) -> OrderedDict[tuple[int, str | None, int | None, str], bytes]:
        # 자주 쓰는 30일 전체 gzip 본문을 게시 전에 만든다(#270 공개 전체 이력 경로가 그대로 넘긴다).
        # 날짜 조각 압축을 재사용하므로 증분 뒤에는 바뀐 날짜와 첫 날짜(부분)만 새로 압축한다(zlib은 GIL을 놓는다).
        # 요청 경로에서는 동일한 시작 행 번호 동안 이 바이트를 재사용한다.
        cutoff = now_utc() - timedelta(days=30)
        prepared: OrderedDict[tuple[int, str | None, int | None, str], bytes] = OrderedDict()
        start = snapshot.start_index(cutoff, None, None)
        prepared[(start, None, None, "gzip")] = await _run_worker(snapshot.render_gzip, cutoff, None, None)
        return prepared

    async def adopt_full_rebuild(
        self, full: ParkingHistorySnapshot, before: tuple[int, int, int, int],
        after: tuple[int, int, int, int], phases: dict[str, float],
    ) -> tuple[str, ParkingHistorySnapshot | None, tuple[int, int, int, int] | None, OrderedDict | None, int]:
        """전체 재생성 중 원본이 바뀌었을 때 결과를 버리지 않고 증분 기준으로 채택해 따라잡는다.

        `full`은 REPEATABLE READ 한 시점의 (최대 id, 행 수, 본문)이라 기동 직후 전체 적재와 똑같이 증분 기준이 된다.
        `before`는 그 읽기 직전 지문, `after`는 준비 뒤 지문이다. 돌려주는 값은
        (판정, snapshot, 지문, 사전 압축 본문, 따라잡은 증분 횟수)다.

        - `published`: 따라잡은 결과를 읽은 뒤 지문이 그 읽기 직전 지문 그대로다. 그 지문으로 게시·검증한다
          (일반 증분 게시와 같은 신선도 근거).
        - `pending`: 상한만큼 따라잡는 동안에도 수집이 끼었다. 마지막 결과를 검증 없이 기준으로만 둔다(요청에 안 쓴다).
        - 그 밖(`update_or_delete`·`max_id_decreased`·`late_commit_or_delete`·`too_many_changes`·`catchup_error:*`):
          채택하면 정확성이 깨질 수 있다. 예전처럼 버린다(`source_changed`, 다음 확인이 전체 재생성).

        채택 조건은 일반 증분과 같다. update·delete 통계는 전체 적재 직전 지문부터 줄곧 그대로여야 하고(읽은 뒤의
        update는 행 수 검사가 못 본다), 늦게 commit된 낮은 id·삭제는 `load_changes`의 `count(*) WHERE id <= W`
        검사가 거른다. rollback된 행은 어느 읽기 시점에도 보이지 않아 최대 id·행 수·본문 어디에도 들지 않는다.
        """
        base, base_before, current = full, before, after
        for catchups in range(1, ADOPT_MAX_CATCHUPS + 1):
            if current[2:] != base_before[2:]:
                return "update_or_delete", None, None, None, catchups - 1
            if current[0] < base.max_snapshot_id:
                return "max_id_decreased", None, None, None, catchups - 1
            # `current`는 다음 읽기 직전 지문이다. 따라잡은 결과를 게시할 때 이 지문으로 검증한다.
            catchup_started = monotonic()
            try:
                caught, _ = await load_changes(self.session_factory, base, timings={})
            except IncrementalUnavailable as exc:
                return exc.reason, None, None, None, catchups - 1
            except Exception as exc:  # noqa: BLE001 — 채택은 최적화다. 실패하면 예전처럼 버린다.
                logger.exception("parking history full-rebuild adoption failed; discarding")
                return f"catchup_error:{type(exc).__name__}", None, None, None, catchups - 1
            prepared = await self.prepare_full_window(caught)
            phases["catchup_ms"] = round(phases.get("catchup_ms", 0) + (monotonic() - catchup_started) * 1000, 1)
            latest = await self.source_fingerprint()
            if latest == current:
                return "published", caught, current, prepared, catchups
            base, base_before, current = caught, current, latest
        # 따라잡는 사이에도 계속 바뀌었다. 마지막 결과와 그 읽기 직전 지문을 기준으로 남긴다. 그 뒤의
        # update·delete는 다음 확인의 `refresh_mode`가 이 지문과 비교해 전체 재생성으로 보낸다.
        if current[2:] != base_before[2:]:
            return "update_or_delete", None, None, None, ADOPT_MAX_CATCHUPS
        return "pending", base, base_before, None, ADOPT_MAX_CATCHUPS

    async def refresh_once(self) -> None:
        fingerprint = await self.source_fingerprint()
        if self.snapshot is None or self.last_fingerprint != fingerprint or self.pending_base is not None:
            # 수집마다는 새 행만 끼워 넣는다(증분, 수 초). 처음·삽입 전용이 깨진 드문 경우만 전체 재생성.
            mode, reason = self.refresh_mode(fingerprint)
            rebuild_id = uuid4().hex
            started = monotonic()
            row_count = changed_keys = adoption = None
            catchups = 0
            phases: dict[str, float] = {}
            outcome = "failed"
            process_started = process_time()
            worker_cpu = WorkerCpuMeter()
            meter_token = _WORKER_CPU.set(worker_cpu)
            self.rebuild_started_at = started
            logger.warning(json.dumps({"event": "parking_history_rebuild", "phase": "start",
                "rebuild_id": rebuild_id, "at": now_utc().isoformat(), "duration_ms": 0,
                "row_count": row_count, "mode": mode, "reason": reason,
                "peak_rss_kib": peak_rss_kib()}, separators=(",", ":")))
            try:
                refreshed = None
                if mode == "incremental":
                    try:
                        base = self.pending_base[0] if self.pending_base is not None else self.snapshot
                        refreshed, changed_keys = await load_changes(self.session_factory, base, timings=phases)
                    except IncrementalUnavailable as exc:
                        mode, reason = "full", exc.reason
                    except Exception as exc:  # noqa: BLE001 — 증분 고장으로 캐시가 다음 새벽까지 꺼지지 않게 전체로 회복한다.
                        self.incremental_errors += 1
                        logger.exception("parking history incremental refresh failed (consecutive=%s); rebuilding in full",
                                         self.incremental_errors)
                        mode, reason = "full", f"incremental_error:{type(exc).__name__}"
                if refreshed is None:
                    # 전체 재생성은 기준을 처음부터 다시 만든다. 검증 전 기준은 버린다.
                    self.pending_base = None
                    load_started = monotonic()
                    refreshed = await load_snapshot(self.session_factory)
                    phases["full_load_ms"] = round((monotonic() - load_started) * 1000, 1)
                row_count = refreshed.size
                if mode == "incremental":
                    self.incremental_errors = 0
                gzip_started = monotonic()
                prepared = await self.prepare_full_window(refreshed)
                phases["gzip_ms"] = round((monotonic() - gzip_started) * 1000, 1)
                # 준비 중 원본이 바뀌었다면 오래된 스냅샷에 새 확인 시각을 찍지 않는다.
                # 증분이면 다음 확인(POLL_SECONDS 뒤)이 같은 기준에서 다시 증분하므로 비용이 작다.
                after = await self.source_fingerprint()
                if after != fingerprint:
                    if mode != "full" or refreshed.source_row_count is None:
                        logger.info("parking history cache source changed during preparation; retrying")
                        outcome = "source_changed"
                        return
                    # 전체 재생성(운영 ARM 수십 초)을 버리면 다음 확인이 또 전체 재생성이다. 증분 기준으로 채택하고
                    # 그 뒤 행만 따라잡는다. 정확성 조건이 깨질 수 있는 경우만 예전처럼 버린다.
                    adoption, caught, caught_fingerprint, caught_prepared, catchups = await self.adopt_full_rebuild(
                        refreshed, fingerprint, after, phases)
                    if adoption == "pending":
                        self.pending_base = (caught, caught_fingerprint)
                        logger.info("parking history full rebuild adopted as base; source still changing")
                        outcome = "adopted_base"
                        return
                    if adoption != "published":
                        logger.info("parking history cache source changed during full rebuild (%s); retrying", adoption)
                        outcome = "source_changed"
                        return
                    refreshed, fingerprint, prepared = caught, caught_fingerprint, caught_prepared
                    row_count = refreshed.size
                self.pending_base = None
                self.prepared_responses = prepared
                self.snapshot = refreshed
                logger.info("parking history cache refreshed rows=%s max_id=%s", refreshed.size, refreshed.max_snapshot_id)
                outcome = "published"
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            finally:
                _WORKER_CPU.reset(meter_token)
                self.rebuild_started_at = None
                logger.warning(json.dumps({"event": "parking_history_rebuild", "phase": "finish",
                    "rebuild_id": rebuild_id, "at": now_utc().isoformat(),
                    "duration_ms": round((monotonic() - started) * 1000, 3),
                    "row_count": row_count, "outcome": outcome, "mode": mode, "reason": reason,
                    "changed_keys": changed_keys, "phases_ms": phases,
                    "adoption": adoption, "catchups": catchups,
                    "incremental_errors": self.incremental_errors,
                    "peak_rss_kib": peak_rss_kib(),
                    "worker_cpu_ms": round(worker_cpu.seconds * 1000, 3),
                    "process_cpu_ms": round((process_time() - process_started) * 1000, 3)},
                    separators=(",", ":")))
        self.last_fingerprint = fingerprint
        self.validated_at = monotonic()
        self.validated_at_utc = now_utc()
        # 직접 조회 차례를 기다리던 요청이 새로 확인된 캐시로 바로 응답하게 깨운다.
        self._notify_state_changed()

    def usable_snapshot(self, cutoff: datetime) -> ParkingHistorySnapshot | None:
        snapshot = self.snapshot
        if (snapshot is None or cutoff < snapshot.earliest_observed_at
                or monotonic() - self.validated_at > MAX_UNCHECKED_SECONDS):
            return None
        return snapshot

    def _notify_state_changed(self) -> None:
        event, self._state_changed = self._state_changed, asyncio.Event()
        event.set()

    async def acquire_direct_fallback(self, cutoff: datetime) -> ParkingHistorySnapshot | None:
        """긴 범위 직접 조회의 차례를 기다린다.

        기다리는 동안 캐시를 쓸 수 있게 되면(새 snapshot 게시·무변경 재확인) 잠금 없이 그
        snapshot을 돌려준다. None이면 호출자가 차례를 얻었으므로 끝나면
        `release_direct_fallback`을 불러야 한다. 기다림은 앞선 직접 조회 1건이 끝날 때까지다.
        """
        while True:
            cached = self.usable_snapshot(cutoff)
            if cached is not None:
                return cached
            if not self.direct_fallback_lock.locked():
                # 잠금이 비어 있으면 대기 없이 바로 얻는다(사이에 다른 코루틴이 끼지 않는다).
                await self.direct_fallback_lock.acquire()
                return None
            changed = self._state_changed
            with suppress(TimeoutError):
                await asyncio.wait_for(changed.wait(), DIRECT_FALLBACK_RECHECK_SECONDS)

    def release_direct_fallback(self) -> None:
        self.direct_fallback_lock.release()
        self._notify_state_changed()

    async def run(self) -> None:
        while True:
            try:
                await self.refresh_once()
            except Exception:
                logger.exception("parking history cache refresh failed")
            await asyncio.sleep(POLL_SECONDS)


def accepts_br(header: str) -> bool:
    for value in header.split(","):
        parts = [part.strip().lower() for part in value.split(";")]
        if parts[0] != "br":
            continue
        for part in parts[1:]:
            if part.startswith("q="):
                try:
                    return float(part[2:]) > 0
                except ValueError:
                    return False
        return True
    return False


def response_encoding(accept_encoding: str) -> str:
    if accepts_br(accept_encoding):
        return "br"
    if accepts_gzip(accept_encoding):
        return "gzip"
    return "identity"


def cached_response_encoding(accept_encoding: str) -> str:
    """캐시 적중 응답의 인코딩. gzip을 받으면 gzip이다(날짜 조각 압축을 재사용해 갱신마다 본문 전체를 압축하지 않는다).

    br은 매번 본문 전체를 압축해야 해서(운영 ARM 수 초) gzip을 받지 않는 클라이언트에만 쓴다. 공개 전체 이력(#270)은
    브라우저의 `br, gzip`을 그대로 넘기므로 gzip 본문(약 2배 크기)을 받고 브라우저가 푼다.
    """
    if accepts_gzip(accept_encoding):
        return "gzip"
    return response_encoding(accept_encoding)


def response_headers(encoding: str) -> dict[str, str]:
    headers = {"Vary": "Accept-Encoding", "Cache-Control": "private, no-store"}
    if encoding != "identity":
        headers["Content-Encoding"] = encoding
    return headers


def compress_body(body: bytes, encoding: str) -> bytes:
    if encoding == "br":
        return brotli.compress(body, quality=6)
    if encoding == "gzip":
        return gzip.compress(body, compresslevel=9, mtime=0)
    return body


def encode_response(body: bytes, accept_encoding: str) -> tuple[bytes, dict[str, str]]:
    encoding = response_encoding(accept_encoding)
    return compress_body(body, encoding), response_headers(encoding)
