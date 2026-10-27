"""Map current의 고정 DTO snapshot. history/raw/provider를 읽지 않는다."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import Settings
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


async def _snapshot_transaction(session: AsyncSession) -> None:
    if session.bind.dialect.name == "postgresql":
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        await session.execute(text("SET LOCAL lock_timeout = '2s'"))
        await session.execute(text("SET LOCAL statement_timeout = '10s'"))


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
        raise HTTPException(503, "확인된 교통 집합의 크기가 export 상한을 벗어났습니다.")
    await expire_snapshots(session)
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
    started = monotonic()
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
            if monotonic() - started > 15:
                raise HTTPException(503, "snapshot 준비 시간 상한을 초과했습니다.")
            items = []
            for row in partition:
                payload = dict(row)
                for field in ("observed_at", "collected_at"):
                    payload[field] = serialize_utc(payload[field]).isoformat()
                body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                count += 1
                size += len(body)
                if count > MAX_SNAPSHOT_ITEMS or size > MAX_SNAPSHOT_BYTES:
                    raise HTTPException(503, "교통 snapshot 크기 상한을 초과했습니다.")
                digest.update(body + b"\n")
                items.append({"snapshot_id": snapshot_id, "ordinal": count, "payload": payload})
            await session.execute(insert(ServiceExportSnapshotItem), items)
    finally:
        await stream.close()
    if count != head.member_count:
        raise HTTPException(503, "교통 성공 집합의 membership이 일치하지 않습니다.")
    snapshot.content_digest = digest.hexdigest()
    await session.flush()
    return snapshot


def build_current_export_router(
    settings: Settings, get_db: Callable[..., AsyncIterator[AsyncSession]],
) -> APIRouter:
    router = APIRouter()
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
            raise HTTPException(503, "교통 current export가 활성화되지 않았습니다.")
        for attempt in range(2):
            try:
                page, revision = await read_page(session, limit, cursor)
                break
            except (SnapshotRace, DBAPIError) as exc:
                await session.rollback()
                code = getattr(getattr(exc, "orig", None), "sqlstate", None)
                if isinstance(exc, DBAPIError) and code not in {"40001", "55P03"}:
                    raise
                if attempt or code == "55P03":
                    raise HTTPException(503, "snapshot 준비가 겹쳤습니다. 잠시 후 다시 요청하세요.") from exc
        return _response(page, request, cursor_epoch=None, cursor_revision=revision)

    async def read_page(session, limit, cursor):
        await _snapshot_transaction(session)
        scope = highway_scope_key(settings, TRAFFIC_SOURCE)
        head = await session.get(HighwayTrafficCurrentState, (TRAFFIC_SOURCE, scope))
        if head is None:
            raise HTTPException(503, "확인된 교통 current 성공 집합이 없습니다.")
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
            raise HTTPException(503, "snapshot 항목의 순서·개수가 일치하지 않습니다.")
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
