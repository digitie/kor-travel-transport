"""Map current의 고정 DTO snapshot. history/raw/provider를 읽지 않는다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import Settings
from app.core.export_guard import ExportDeadlineRoute, mark_building
from app.core.problems import (
    FAST_SOURCE_RETRY_AFTER_SECONDS,
    CodedHTTPException,
    ProblemCode,
    database_sqlstate,
    unavailable,
)
from app.core.time_utils import now_utc, serialize_utc
from app.models import (
    HighwayTrafficCurrent, HighwayTrafficCurrentState, ServiceExportSnapshot,
    ServiceExportSnapshotItem, TransportCollectionState,
)
from app.schemas import HighwayTrafficCurrentExportPage, ServiceExportMeta
from app.services.export_price_history import _decode_cursor, _encode_cursor, _response
from app.services.transport_collection import TRAFFIC_SOURCE, highway_scope_key

SNAPSHOT_TTL = timedelta(minutes=15)
CURRENT_MAX_AGE = timedelta(minutes=30)
MAX_SNAPSHOT_ITEMS = 20000
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
BATCH_SIZE = 400
KIND = "highway-traffic-current-v1"


class SnapshotRace(Exception):
    """별도 reader가 같은 generation/TTL epoch를 먼저 확정했다. 새 RR로 한 번 재시도한다."""


#: snapshot 문장이 `SET LOCAL statement_timeout`에 걸린 SQLSTATE(query_canceled).
QUERY_CANCELED = "57014"
#: admission의 unique 대기·행 잠금이 `SET LOCAL lock_timeout`(2초)에 걸린 SQLSTATE(lock_not_available).
LOCK_NOT_AVAILABLE = "55P03"
#: 같은 입력의 두 builder가 서로의 잠금을 기다린 교착(deadlock_detected). 55P03과 같이 잠시 뒤 한 번 다시 시도한다.
DEADLOCK_DETECTED = "40P01"
#: 잠시 기다렸다 새 RR로 다시 시도하는 경합 SQLSTATE. 40001(이미 commit된 경쟁)은 곧바로 다시 시도한다.
CONTENTION_SQLSTATES = frozenset({LOCK_NOT_AVAILABLE, DEADLOCK_DETECTED})
RETRY_SQLSTATES = CONTENTION_SQLSTATES | {"40001"}
#: 55P03·40P01 뒤 새 RR로 다시 시도하기 전 대기(초, 균등 분포). 앞 builder의 COPY·commit이 끝나기를 기다린다.
LOCK_RETRY_DELAY_SECONDS = (0.3, 1.0)
#: 요청 경로 snapshot·본문 구성의 전체 예산(초). **첫 시도 시작**부터 재고 재시도도 같은 예산을 나눠 쓴다.
#: 시도마다 예산을 새로 주면 최악 (지문 + 15초 + admission 2초) x 2 = 약 36초로 Map read timeout(30초)을 넘는다.
BUILD_BUDGET_SECONDS = 15
#: snapshot transaction의 `SET LOCAL` 상한(초). 요청 경로의 statement_timeout은 남은 예산보다 길게 두지 않는다.
SNAPSHOT_STATEMENT_TIMEOUT_SECONDS = 10
SNAPSHOT_LOCK_TIMEOUT_SECONDS = 2
#: 경합 재시도를 시작할 최소 남은 예산 = 대기 + admission lock_timeout + 이 여유(초). 모자라면 곧바로 EXPORT_BUSY다.
RETRY_MARGIN_SECONDS = 3
BUSY_DETAIL = "snapshot 준비가 겹쳤습니다. 잠시 후 다시 요청하세요."
STATEMENT_TIMEOUT_DETAIL = "snapshot 준비 시간 상한을 초과했습니다."
_build_started: ContextVar[float | None] = ContextVar("transport_export_build_started", default=None)


def build_started() -> float:
    """요청 경로(`read_snapshot_with_retry` 안)면 첫 시도의 시작 시각, 그 밖(Dagster 준비 op 등)이면 지금.

    본문 구성이 시작됐다는 표시도 남긴다(handler 상한 초과를 EXPORT_PREPARE_TIMEOUT으로 가른다).
    """
    mark_building()
    started = _build_started.get()
    return monotonic() if started is None else started


def budget_exceeded(started: float) -> bool:
    return monotonic() - started > BUILD_BUDGET_SECONDS


def _remaining_budget() -> float | None:
    started = _build_started.get()
    return None if started is None else BUILD_BUDGET_SECONDS - (monotonic() - started)


def snapshot_statement_timeout_ms() -> int:
    """snapshot transaction의 statement_timeout(밀리초). 요청 경로의 재시도는 남은 예산을 넘기지 않는다."""
    remaining = _remaining_budget()
    seconds = SNAPSHOT_STATEMENT_TIMEOUT_SECONDS if remaining is None else min(
        SNAPSHOT_STATEMENT_TIMEOUT_SECONDS, max(remaining, 1.0))
    return int(seconds * 1000)


async def read_snapshot_with_retry(session: AsyncSession, read: Callable[[], Awaitable[Any]]) -> Any:
    """T2/T3 첫 고정·페이지 읽기를 새 REPEATABLE READ로 최대 두 번 시도한다(감사 T23-01·T23-10).

    - 이미 commit된 경쟁(40001)·handle/head 경합(`SnapshotRace`)은 곧바로 새 RR로 한 번 더 시도한다(기존 정책).
    - admission 대기 lock_timeout(55P03)·교착(40P01)은 같은 입력을 다른 builder가 먼저 구성하는 중이라는 뜻이다.
      예전에는 55P03이 곧바로 503이었다(2026-11-19 artifact COPY 보고서의 "55P03 즉시 503"). 그때는 503에 사유가
      없었고, 요청 안에서 다시 시도하면 시도마다 예산을 새로 받아 Map read timeout을 넘길 수 있었다. 이제 두
      시도가 예산 하나를 나눠 쓰고, 남은 예산이 `대기 + lock_timeout(2초) + 여유(3초)` 이상일 때만 0.3~1초 뒤 새
      RR로 한 번 더 시도해 앞 builder가 commit한 본문을 재사용한다. 모자라면 예전처럼 곧바로 503 `EXPORT_BUSY`다.
      advisory lock single-flight는 RR snapshot이 잡힌 뒤에 얻게 돼 상대의 commit을 보지 못하므로 쓰지 않는다.
    - 두 번째 시도의 statement_timeout은 남은 예산을 넘지 않는다(`snapshot_statement_timeout_ms`). 경합 뒤 재시도가
      예산·statement timeout에 걸리면 원인은 경합이므로 `EXPORT_PREPARE_TIMEOUT`이 아니라 `EXPORT_BUSY`다.
    - 두 번째도 경합이면 503 `EXPORT_BUSY`다.
    - 첫 시도 안의 statement timeout(57014)은 원인 불명 500이 아니라 503 `EXPORT_PREPARE_TIMEOUT`이다.
    그 밖의 DB 오류는 그대로 올린다(export 경로의 일시 DB 불가는 `ExportTransientDbMiddleware`가 503 TRANSIENT_DB로
    바꾼다). 요청 전체의 상한은 handler 상한(`ExportDeadlineRoute`, 25초)이다 — 재시도의 pool checkout 대기는
    이 예산이 아니라 그 상한이 덮는다.
    """
    started = monotonic()
    token = _build_started.set(started)
    try:
        retried = False
        for attempt in range(2):
            try:
                return await read()
            except CodedHTTPException as exc:
                if retried and exc.code == ProblemCode.EXPORT_PREPARE_TIMEOUT:
                    raise unavailable(ProblemCode.EXPORT_BUSY, BUSY_DETAIL) from exc
                raise
            except (SnapshotRace, DBAPIError) as exc:
                await session.rollback()
                code = database_sqlstate(exc) if isinstance(exc, DBAPIError) else None
                if code == QUERY_CANCELED:
                    raise unavailable(ProblemCode.EXPORT_BUSY if retried else ProblemCode.EXPORT_PREPARE_TIMEOUT,
                                      BUSY_DETAIL if retried else STATEMENT_TIMEOUT_DETAIL) from exc
                if isinstance(exc, DBAPIError) and code not in RETRY_SQLSTATES:
                    raise
                if attempt:
                    raise unavailable(ProblemCode.EXPORT_BUSY, BUSY_DETAIL) from exc
                delay = random.uniform(*LOCK_RETRY_DELAY_SECONDS) if code in CONTENTION_SQLSTATES else 0.0
                remaining = BUILD_BUDGET_SECONDS - (monotonic() - started)
                if remaining < delay + SNAPSHOT_LOCK_TIMEOUT_SECONDS + RETRY_MARGIN_SECONDS:
                    raise unavailable(ProblemCode.EXPORT_BUSY, BUSY_DETAIL) from exc
                retried = True
                if delay:
                    # rollback으로 pool 연결을 돌려준 뒤에 기다린다.
                    await asyncio.sleep(delay)
        raise AssertionError("unreachable")
    finally:
        _build_started.reset(token)


def _cache_epoch(now: datetime) -> int:
    return int(now.timestamp()) // int(SNAPSHOT_TTL.total_seconds())


def cache_generation(generation: str, now: datetime | None = None) -> str:
    epoch = _cache_epoch(now or now_utc())
    return hashlib.sha256(f"{generation}:{epoch}".encode()).hexdigest()[:32]


def snapshot_expires_at(now: datetime) -> datetime:
    """생성한 cache epoch의 끝 + TTL.

    같은 epoch 안에서는 같은 generation의 snapshot을 재사용하므로, 만료를 생성 시각+TTL로 두면 epoch 끝에
    재사용한 reader가 몇 초 만에 다음 페이지에서 410을 받는다. epoch 끝 기준이면 같은 epoch 안에서 건네는
    snapshot의 남은 수명이 항상 TTL(15분) 이상이고 최대 2×TTL(30분)이다.
    """
    seconds = int(SNAPSHOT_TTL.total_seconds())
    return datetime.fromtimestamp((_cache_epoch(now) + 1) * seconds, tz=UTC) + SNAPSHOT_TTL

_FIELDS = (
    "identity_key", "source", "route_no", "route_name", "conzone_id", "conzone_name",
    "direction", "speed", "free_flow_speed", "congestion_level", "observed_at", "collected_at",
)


def _timeout_literal(milliseconds: int) -> str:
    # SET은 bind 변수를 받지 않는다. 양의 정수만 문장에 넣는다.
    if type(milliseconds) is not int or milliseconds <= 0:
        raise ValueError("timeout은 양의 정수(밀리초)여야 합니다")
    return f"{milliseconds // 1000}s" if milliseconds % 1000 == 0 else f"{milliseconds}ms"


async def _snapshot_transaction(
    session: AsyncSession, *, lock_timeout_ms: int | None = None, statement_timeout_ms: int | None = None,
) -> None:
    if session.bind.dialect.name == "postgresql":
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        if lock_timeout_ms is None and statement_timeout_ms is None:
            # 요청 경로: 잠금 2초, 문장 상한은 남은 예산 이하(재시도와 예산 공유).
            await session.execute(text(f"SET LOCAL lock_timeout = '{SNAPSHOT_LOCK_TIMEOUT_SECONDS}s'"))
            await session.execute(text(f"SET LOCAL statement_timeout = {snapshot_statement_timeout_ms()}"))
        else:
            # 오프라인 준비(`reference_export_preparation`)가 자기 예산에 맞춘 상한을 넘긴다.
            lock_ms = SNAPSHOT_LOCK_TIMEOUT_SECONDS * 1000 if lock_timeout_ms is None else lock_timeout_ms
            statement_ms = snapshot_statement_timeout_ms() if statement_timeout_ms is None else statement_timeout_ms
            await session.execute(text(f"SET LOCAL lock_timeout = '{_timeout_literal(lock_ms)}'"))
            await session.execute(text(f"SET LOCAL statement_timeout = '{_timeout_literal(statement_ms)}'"))


#: 요청 경로 GC가 다른 정리(오프라인 준비의 대량 정리 등)와 겹칠 때의 신호.
_GC_CONTENTION_SQLSTATES = frozenset({"40001", "40P01", "55P03"})


async def gc_quietly(session: AsyncSession, action: Callable, *args, **kwargs) -> int:
    """요청 경로의 부가 정리(`expire_snapshots`·`collect_unused_artifact`)를 savepoint 안에서 한다.

    RR snapshot을 잡은 뒤 다른 transaction(준비의 대량 정리 등)이 같은 victim을 지우고 commit했으면 `FOR UPDATE`가
    40001을 낸다. 정리는 읽기를 실패시키면 안 되므로 경합(40001·40P01·55P03)이면 그 정리만 savepoint까지 되돌리고
    0을 돌려준다. 같은 transaction의 읽기·handle 발급은 그대로 이어 간다.
    """
    try:
        async with session.begin_nested():
            return await action(session, *args, **kwargs)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in _GC_CONTENTION_SQLSTATES:
            return 0
        raise


async def expire_snapshots(session: AsyncSession, *, limit: int = 1) -> int:
    """호출자 transaction의 만료 snapshot만 제한 삭제한다. 페이지 reader는 RR MVCC로 보호된다.

    PostgreSQL은 victim 부모 행을 먼저 잠그고(`FOR UPDATE SKIP LOCKED`) 다른 transaction이 지우는 중인
    victim은 건너뛴다. 다른 종류의 첫 페이지 freeze가 같은 victim의 행 잠금을 lock_timeout(2초)까지
    기다리다 55P03으로 503이 되지 않는다. 이미 commit된 삭제와 겹친 RR 직렬화 실패(40001)는 호출자가
    기존처럼 한 번 재시도한다.
    """
    if not 1 <= limit <= 2:
        raise ValueError("GC limit은 1~2입니다")
    query = select(ServiceExportSnapshot.id).where(
        ServiceExportSnapshot.expires_at <= now_utc(),
    ).order_by(ServiceExportSnapshot.expires_at).limit(limit)
    if session.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    ids = list((await session.scalars(query)).all())
    if not ids:
        return 0
    # SQLite FK 설정에도 독립적으로 자식부터 정리한다. 공개된 미만료 snapshot은 지우지 않는다.
    await session.execute(delete(ServiceExportSnapshotItem).where(ServiceExportSnapshotItem.snapshot_id.in_(ids)))
    await session.execute(delete(ServiceExportSnapshot).where(ServiceExportSnapshot.id.in_(ids)))
    return len(ids)


async def _freeze_traffic(
    session: AsyncSession, scope: str, head: HighwayTrafficCurrentState,
) -> ServiceExportSnapshot:
    now = now_utc()
    generation = cache_generation(head.generation, now)
    cached = await session.scalar(select(ServiceExportSnapshot).where(
        ServiceExportSnapshot.kind == KIND, ServiceExportSnapshot.scope_key == scope,
        ServiceExportSnapshot.generation == generation,
        ServiceExportSnapshot.expires_at > now,
    ).order_by(ServiceExportSnapshot.created_at.desc()).limit(1))
    if cached:
        return cached
    if not 0 <= head.member_count <= MAX_SNAPSHOT_ITEMS:
        raise unavailable(ProblemCode.EXPORT_TOO_LARGE, "확인된 교통 집합의 크기가 export 상한을 벗어났습니다.")
    await gc_quietly(session, expire_snapshots)
    snapshot_id = str(uuid4())
    table = ServiceExportSnapshot.__table__
    factory = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    admitted = await session.scalar(factory(table).values(
        id=snapshot_id, kind=KIND, scope_key=scope, generation=generation,
        source_collected_at=head.confirmed_at, created_at=now, expires_at=snapshot_expires_at(now),
        item_count=head.member_count, content_digest="pending",
    ).on_conflict_do_nothing(index_elements=["kind", "scope_key", "generation"]).returning(table.c.id))
    if admitted is None:
        raise SnapshotRace()
    snapshot = await session.get(ServiceExportSnapshot, snapshot_id)
    started = build_started()
    count = size = 0
    digest = hashlib.sha256()
    query = select(*(getattr(HighwayTrafficCurrent, field) for field in _FIELDS)).where(
        HighwayTrafficCurrent.source == TRAFFIC_SOURCE,
        HighwayTrafficCurrent.scope_key == scope,
        HighwayTrafficCurrent.generation == head.generation,
    ).order_by(HighwayTrafficCurrent.identity_key).limit(MAX_SNAPSHOT_ITEMS + 1)
    stream = await session.stream(query.execution_options(yield_per=BATCH_SIZE))
    try:
        async for partition in stream.mappings().partitions(BATCH_SIZE):
            if budget_exceeded(started):
                raise unavailable(ProblemCode.EXPORT_PREPARE_TIMEOUT, STATEMENT_TIMEOUT_DETAIL)
            items = []
            for row in partition:
                payload = dict(row)
                for field in ("observed_at", "collected_at"):
                    payload[field] = serialize_utc(payload[field]).isoformat()
                body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                count += 1
                size += len(body)
                if count > MAX_SNAPSHOT_ITEMS or size > MAX_SNAPSHOT_BYTES:
                    raise unavailable(ProblemCode.EXPORT_TOO_LARGE, "교통 snapshot 크기 상한을 초과했습니다.")
                digest.update(body + b"\n")
                items.append({"snapshot_id": snapshot_id, "ordinal": count, "payload": payload})
            await session.execute(insert(ServiceExportSnapshotItem), items)
    finally:
        await stream.close()
    if count != head.member_count:
        raise unavailable(ProblemCode.EXPORT_SOURCE_INCONSISTENT, "교통 성공 집합의 membership이 일치하지 않습니다.")
    snapshot.content_digest = digest.hexdigest()
    await session.flush()
    return snapshot


def build_current_export_router(
    settings: Settings, get_db: Callable[..., AsyncIterator[AsyncSession]],
) -> APIRouter:
    router = APIRouter(route_class=ExportDeadlineRoute)
    key = hashlib.sha256((settings.transport_service_export_token or "").encode()).digest()

    @router.get("/highway-traffic/current", response_model=HighwayTrafficCurrentExportPage,
                responses={304: {}, 404: {}, 410: {}, 422: {}, 503: {}})
    async def traffic_current(
        request: Request,
        limit: int = Query(default=1000, ge=1, le=5000),
        cursor: str | None = Query(default=None, min_length=1, max_length=4096),
        session: AsyncSession = Depends(get_db),
    ) -> Response:
        """완결 성공 current만 고정한다. 페이지 사이 재수집에도 최초 DTO는 만료까지 유지된다."""
        if not settings.transport_map_current_enabled:
            raise unavailable(ProblemCode.EXPORT_DISABLED, "교통 current export가 활성화되지 않았습니다.")
        page, revision = await read_snapshot_with_retry(session, lambda: read_page(session, limit, cursor))
        return _response(page, request, cursor_epoch=None, cursor_revision=revision)

    async def read_page(session, limit, cursor):
        await _snapshot_transaction(session)
        scope = highway_scope_key(settings, TRAFFIC_SOURCE)
        head = await session.get(HighwayTrafficCurrentState, (TRAFFIC_SOURCE, scope))
        if head is None:
            raise unavailable(ProblemCode.EXPORT_NO_HISTORY, "확인된 교통 current 성공 집합이 없습니다.",
                              retry_after=FAST_SOURCE_RETRY_AFTER_SECONDS)
        after = 0
        if cursor:
            value = _decode_cursor(cursor, key)
            try:
                snapshot_id = str(UUID(value["snapshot"]))
                after = value["after"]
                if (value.get("kind") != KIND or value.get("scope") != scope
                        or value.get("limit") != limit or type(after) is not int or after < 0):
                    raise ValueError("scope")
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                raise HTTPException(422, "cursor의 경로·범위·limit이 일치하지 않습니다.") from exc
            snapshot = await session.get(ServiceExportSnapshot, snapshot_id)
            if snapshot is None or serialize_utc(snapshot.expires_at) <= now_utc():
                raise HTTPException(410, "snapshot이 만료되었습니다. 첫 페이지부터 다시 요청하세요.")
            if snapshot.kind != KIND or snapshot.scope_key != scope or after >= snapshot.item_count:
                raise HTTPException(422, "cursor의 snapshot 범위가 일치하지 않습니다.")
        else:
            snapshot = await _freeze_traffic(session, scope, head)
        state = await session.scalar(select(TransportCollectionState).where(
            TransportCollectionState.source == TRAFFIC_SOURCE,
        ))
        source_status = "ok"
        if (state is None or state.last_error is not None
                or now_utc() - serialize_utc(snapshot.source_collected_at) > CURRENT_MAX_AGE):
            source_status = "stale"
        rows = list((await session.execute(select(ServiceExportSnapshotItem.ordinal, ServiceExportSnapshotItem.payload).where(
            ServiceExportSnapshotItem.snapshot_id == snapshot.id,
            ServiceExportSnapshotItem.ordinal > after,
        ).order_by(ServiceExportSnapshotItem.ordinal).limit(limit + 1))).all())
        expected = min(limit + 1, snapshot.item_count - after)
        if len(rows) != expected or any(row.ordinal != after + i + 1 for i, row in enumerate(rows)):
            raise unavailable(ProblemCode.EXPORT_SOURCE_INCONSISTENT, "snapshot 항목의 순서·개수가 일치하지 않습니다.")
        items, has_more = [row.payload for row in rows[:limit]], len(rows) > limit
        next_cursor = _encode_cursor({
            "v": 1, "kind": KIND, "scope": scope, "snapshot": snapshot.id,
            "after": after + len(items), "limit": limit,
        }, key) if has_more else None
        page = HighwayTrafficCurrentExportPage(
            meta=ServiceExportMeta(generated_at=now_utc(), source_collected_at=serialize_utc(snapshot.source_collected_at),
                                   source_status=source_status, item_count=len(items)),
            snapshot_id=snapshot.id, snapshot_expires_at=serialize_utc(snapshot.expires_at),
            total_count=snapshot.item_count, items=items, next_cursor=next_cursor, has_more=has_more,
        )
        revision = snapshot.content_digest
        # RR transaction/pool 연결을 반환한 다음에만 JSON/gzip을 만든다.
        await session.commit()
        return page, revision

    return router
