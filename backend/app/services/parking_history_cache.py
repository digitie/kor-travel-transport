"""PostgreSQL 전체 주차 이력의 재생성 가능한 읽기 캐시."""

from __future__ import annotations

import asyncio
import gzip
import logging
from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic

import brotli
from pydantic_core import to_json
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import StreamingResponse

from app.core.time_utils import now_utc, serialize_utc
from app.models import Airport, ParkingSnapshot

logger = logging.getLogger(__name__)
POLL_SECONDS = 5
MAX_UNCHECKED_SECONDS = 30
MAX_PREPARED_RESPONSES = 8


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


@dataclass(frozen=True, slots=True)
class ParkingHistorySnapshot:
    earliest_observed_at: datetime
    max_snapshot_id: int
    items: tuple[CachedHistoryItem, ...]
    times: tuple[datetime, ...]

    @classmethod
    def from_rows(cls, earliest_observed_at: datetime, max_snapshot_id: int, rows: list) -> ParkingHistorySnapshot:
        items = tuple(CachedHistoryItem(
            observed_at=serialize_utc(row.observed_at),
            airport_code=row.code,
            parking_lot_id=row.parking_lot_id,
            encoded=to_json({
                "airport_code": row.code,
                "parking_lot_id": row.parking_lot_id,
                "observed_at": serialize_utc(row.observed_at),
                "occupied_spaces": row.occupied_spaces,
                "total_spaces": row.total_spaces,
                "available_spaces": row.available_spaces,
            }),
        ) for row in rows)
        return cls(earliest_observed_at, max_snapshot_id, items, tuple(item.observed_at for item in items))

    def render(self, cutoff: datetime, airport_code: str | None, parking_lot_id: int | None) -> bytes:
        start = bisect_left(self.times, cutoff)
        if parking_lot_id:
            payload = b",".join(item.encoded for item in self.items[start:]
                                if item.parking_lot_id == parking_lot_id)
        elif airport_code:
            payload = b",".join(item.encoded for item in self.items[start:]
                                if item.airport_code == airport_code)
        else:
            payload = b",".join(item.encoded for item in self.items[start:])
        return b'{"items":[' + payload + b'],"next_cursor":null}'


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


async def load_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    earliest_observed_at: datetime | None = None,
) -> ParkingHistorySnapshot:
    earliest = earliest_observed_at or now_utc() - timedelta(days=30)
    async with session_factory() as session:
        max_id = await session.scalar(select(func.max(ParkingSnapshot.id))) or 0
        ranked = (select(
            ParkingSnapshot.observed_at.label("observed_at"),
            ParkingSnapshot.parking_lot_id.label("parking_lot_id"),
            ParkingSnapshot.airport_id.label("airport_id"),
            ParkingSnapshot.occupied_spaces.label("occupied_spaces"),
            ParkingSnapshot.total_spaces.label("total_spaces"),
            ParkingSnapshot.available_spaces.label("available_spaces"),
        ).where(ParkingSnapshot.observed_at >= earliest, ParkingSnapshot.id <= max_id)
            .distinct(ParkingSnapshot.observed_at, ParkingSnapshot.parking_lot_id)
            .order_by(
                ParkingSnapshot.observed_at, ParkingSnapshot.parking_lot_id,
                case((func.left(ParkingSnapshot.source, 10) == "migration_", 1), else_=0),
                ParkingSnapshot.collected_at.desc(), ParkingSnapshot.id.desc(),
            ).subquery("history_rows"))
        rows = (await session.execute(select(
            ranked.c.observed_at, ranked.c.parking_lot_id, Airport.code,
            ranked.c.occupied_spaces, ranked.c.total_spaces, ranked.c.available_spaces,
        ).join(Airport, Airport.id == ranked.c.airport_id)
            .order_by(ranked.c.observed_at, ranked.c.parking_lot_id))).all()
    return await asyncio.to_thread(ParkingHistorySnapshot.from_rows, earliest, max_id, rows)


class ParkingHistoryReadCache:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory
        # 응답 전송이 끝날 때까지 점유한다. 압축하지 않은 전체 이력 요청도
        # 요청 수만큼 75MB 본문을 동시에 보유하지 않게 한다.
        self.delivery_semaphore = asyncio.Semaphore(2)
        self.snapshot: ParkingHistorySnapshot | None = None
        self.validated_at = 0.0
        self.validated_at_utc: datetime | None = None
        self.last_fingerprint: tuple[int, int, int, int] | None = None
        self.prepared_responses: OrderedDict[tuple[int, str | None, int | None, str], bytes] = OrderedDict()

    async def response_body(
        self, snapshot: ParkingHistorySnapshot, cutoff: datetime,
        airport_code: str | None, parking_lot_id: int | None, accept_encoding: str,
    ) -> tuple[bytes, dict[str, str]]:
        encoding = response_encoding(accept_encoding)
        key = (bisect_left(snapshot.times, cutoff), airport_code, parking_lot_id, encoding)
        if encoding != "identity" and snapshot is self.snapshot and key in self.prepared_responses:
            self.prepared_responses.move_to_end(key)
            return self.prepared_responses[key], response_headers(encoding)
        body = await run_history_cpu(snapshot.render, cutoff, airport_code, parking_lot_id)
        prepared, headers = await run_history_cpu(encode_response, body, accept_encoding)
        if encoding != "identity" and snapshot is self.snapshot:
            self.prepared_responses[key] = prepared
            self.prepared_responses.move_to_end(key)
            while len(self.prepared_responses) > MAX_PREPARED_RESPONSES:
                self.prepared_responses.popitem(last=False)
        return prepared, headers

    async def source_fingerprint(self) -> tuple[int, int, int, int]:
        async with self.session_factory() as session:
            current_max_id = await session.scalar(select(func.max(ParkingSnapshot.id))) or 0
            counters = (await session.execute(text(
                "SELECT n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables "
                "WHERE relid = 'parking_snapshots'::regclass"
            ))).one()
        return current_max_id, *(int(value) for value in counters)

    async def refresh_once(self) -> None:
        fingerprint = await self.source_fingerprint()
        if self.snapshot is None or self.last_fingerprint != fingerprint:
            refreshed = await load_snapshot(self.session_factory)
            # 자주 쓰는 30일 전체 결과를 게시 전에 압축한다. 요청 경로에서는
            # 동일한 시작 행 번호 동안 이 바이트를 재사용한다.
            cutoff = now_utc() - timedelta(days=30)
            prepared: OrderedDict[tuple[int, str | None, int | None, str], bytes] = OrderedDict()
            body = await asyncio.to_thread(refreshed.render, cutoff, None, None)
            start = bisect_left(refreshed.times, cutoff)
            for encoding in ("br", "gzip"):
                prepared[(start, None, None, encoding)] = await asyncio.to_thread(compress_body, body, encoding)
            # 준비 중 원본이 바뀌었다면 오래된 스냅샷에 새 확인 시각을 찍지 않는다.
            if await self.source_fingerprint() != fingerprint:
                logger.info("parking history cache source changed during preparation; retrying")
                return
            self.prepared_responses = prepared
            self.snapshot = refreshed
            logger.info("parking history cache refreshed rows=%s max_id=%s", len(refreshed.items), refreshed.max_snapshot_id)
        self.last_fingerprint = fingerprint
        self.validated_at = monotonic()
        self.validated_at_utc = now_utc()

    def usable_snapshot(self, cutoff: datetime) -> ParkingHistorySnapshot | None:
        snapshot = self.snapshot
        if (snapshot is None or cutoff < snapshot.earliest_observed_at
                or monotonic() - self.validated_at > MAX_UNCHECKED_SECONDS):
            return None
        return snapshot

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
