"""Map 저변동 기준정보: source별 성공 membership + 고정 DTO 페이지."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from time import monotonic
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.models import BusTerminalReference, ReferenceExportState, ServiceExportSnapshot, ServiceExportSnapshotItem
from app.schemas import BusTerminalExportPage, ServiceExportMeta
from app.services.bus_collection import TAGO_BUS_SOURCE
from app.services.export_addresses import export_admin_addresses
from app.services.export_current import BATCH_SIZE, MAX_SNAPSHOT_BYTES, MAX_SNAPSHOT_ITEMS, SNAPSHOT_TTL, _snapshot_transaction, expire_snapshots
from app.services.export_price_history import _decode_cursor, _encode_cursor, _response

KIND = "bus-terminals-v1"
SCOPE = hashlib.sha256(b"bus-terminals:express+intercity:v1").hexdigest()
MAX_AGE = timedelta(days=9)
_FIELDS = ("id", "source", "service_type", "terminal_id", "terminal_name", "city_name", "latitude", "longitude", "location_source")


async def _bus_heads(session):
    heads = list((await session.scalars(select(ReferenceExportState).where(
        ReferenceExportState.kind == "bus-terminal",
        ReferenceExportState.scope_key.in_(("express", "intercity")),
    ).order_by(ReferenceExportState.scope_key))).all())
    return heads


def _valid_heads(heads):
    return (len(heads) == 2 and {h.scope_key for h in heads} == {"express", "intercity"}
            and all(h.proof.get("complete") and 0 < len(h.member_ids) <= 10000
                    and len(set(h.member_ids)) == len(h.member_ids) for h in heads))


async def _bus_payload_batches(session, heads):
    for head in heads:
        ids = sorted(head.member_ids)
        for offset in range(0, len(ids), BATCH_SIZE):
            selected = ids[offset:offset + BATCH_SIZE]
            rows = list((await session.execute(select(
                *(getattr(BusTerminalReference, field) for field in _FIELDS),
                BusTerminalReference.raw_item_json["_manual_location"]["revision"].as_string().label("manual_revision"),
            ).where(BusTerminalReference.id.in_(selected),
                    BusTerminalReference.source == TAGO_BUS_SOURCE,
                    BusTerminalReference.service_type == head.scope_key).order_by(BusTerminalReference.id))).mappings())
            if len(rows) != len(selected):
                raise HTTPException(503, "터미널 성공 membership이 일치하지 않습니다.")
            addresses = await export_admin_addresses(session, "bus_terminal", [SimpleNamespace(**row) for row in rows])
            payloads = []
            for row in rows:
                if not row["terminal_id"] or not row["terminal_name"]:
                    raise HTTPException(503, "확인된 터미널 이름·코드가 없습니다.")
                address = addresses.get(row["id"])
                payloads.append({
                    "natural_key": f"{row['source']}:{row['service_type']}:{row['terminal_id']}",
                    "source": row["source"], "service_type": row["service_type"], "terminal_id": row["terminal_id"],
                    "name": row["terminal_name"], "city_name": row["city_name"], "latitude": row["latitude"],
                    "longitude": row["longitude"], "location_source": row["location_source"],
                    "manual_location_revision": row["manual_revision"] if row["location_source"] == "admin_manual" else None,
                    "admin": address.model_dump(mode="json") if address else None,
                })
            yield payloads


async def _freeze_bus(session, heads):
    started = monotonic()
    size = count = 0
    digest = hashlib.sha256()
    async for batch in _bus_payload_batches(session, heads):
        if monotonic() - started > 15:
            raise HTTPException(503, "터미널 snapshot 준비 시간 상한을 초과했습니다.")
        for item in batch:
            body = json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            size += len(body)
            count += 1
            if size > MAX_SNAPSHOT_BYTES or count > MAX_SNAPSHOT_ITEMS:
                raise HTTPException(503, "터미널 snapshot 크기 상한을 초과했습니다.")
            digest.update(body + b"\n")
    content = digest.hexdigest()
    namespace = json.dumps([[h.generation, serialize_utc(h.confirmed_at).isoformat()] for h in heads]) + content
    generation = hashlib.sha256(namespace.encode()).hexdigest()[:32]
    cached = await session.scalar(select(ServiceExportSnapshot).where(
        ServiceExportSnapshot.kind == KIND, ServiceExportSnapshot.scope_key == SCOPE,
        ServiceExportSnapshot.generation == generation,
        ServiceExportSnapshot.expires_at > now_utc() + timedelta(minutes=1),
    ).order_by(ServiceExportSnapshot.created_at.desc()).limit(1))
    if cached:
        return cached
    if session.bind.dialect.name == "postgresql":
        lock_key = int.from_bytes(hashlib.sha256(KIND.encode()).digest()[:8], "big", signed=True)
        if not await session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock_key}):
            raise HTTPException(503, "터미널 snapshot을 준비 중입니다.")
    await expire_snapshots(session)
    now = now_utc()
    snapshot = ServiceExportSnapshot(
        id=str(uuid4()), kind=KIND, scope_key=SCOPE, generation=generation,
        source_collected_at=min(serialize_utc(h.confirmed_at) for h in heads),
        created_at=now, expires_at=now + SNAPSHOT_TTL, item_count=count, content_digest=content,
    )
    session.add(snapshot)
    await session.flush()
    ordinal = 0
    async for batch in _bus_payload_batches(session, heads):
        if monotonic() - started > 15:
            raise HTTPException(503, "터미널 snapshot 저장 시간 상한을 초과했습니다.")
        values = []
        for item in batch:
            ordinal += 1
            values.append({"snapshot_id": snapshot.id, "ordinal": ordinal, "payload": item})
        await session.execute(insert(ServiceExportSnapshotItem), values)
    if ordinal != count:
        raise HTTPException(503, "터미널 snapshot의 완결 수량이 달라졌습니다.")
    return snapshot


def build_reference_export_router(settings: Settings, get_db: Callable[..., AsyncIterator[AsyncSession]]) -> APIRouter:
    router = APIRouter()
    key = hashlib.sha256((settings.transport_service_export_token or "").encode()).digest()

    @router.get("/bus-terminals", response_model=BusTerminalExportPage,
                responses={304: {}, 404: {}, 410: {}, 422: {}, 503: {}})
    async def bus_terminals(request: Request, limit: int = Query(default=1000, ge=1, le=5000),
                            cursor: str | None = Query(default=None, min_length=1, max_length=4096),
                            session: AsyncSession = Depends(get_db)) -> Response:
        if not settings.transport_map_current_enabled:
            raise HTTPException(503, "터미널 export가 활성화되지 않았습니다.")
        await _snapshot_transaction(session)
        heads = await _bus_heads(session)
        after = 0
        if cursor:
            value = _decode_cursor(cursor, key)
            try:
                snapshot_id = str(UUID(value["snapshot"]))
                after = value["after"]
                if (value.get("kind") != KIND or value.get("scope") != SCOPE or value.get("limit") != limit
                        or type(after) is not int or after < 0):
                    raise ValueError("scope")
            except (KeyError, ValueError, TypeError, AttributeError) as exc:
                raise HTTPException(422, "cursor 범위가 일치하지 않습니다.") from exc
            snapshot = await session.get(ServiceExportSnapshot, snapshot_id)
            if snapshot is None or serialize_utc(snapshot.expires_at) <= now_utc():
                raise HTTPException(410, "snapshot이 만료되었습니다. 첫 페이지부터 다시 요청하세요.")
            if snapshot.kind != KIND or snapshot.scope_key != SCOPE or after >= snapshot.item_count:
                raise HTTPException(422, "cursor snapshot 범위가 일치하지 않습니다.")
        else:
            if not _valid_heads(heads):
                raise HTTPException(503, "고속·시외 터미널의 완결 성공 집합이 없습니다.")
            snapshot = await _freeze_bus(session, heads)
        stale = (not _valid_heads(heads) or any(h.last_error is not None for h in heads)
                 or now_utc() - serialize_utc(snapshot.source_collected_at) > MAX_AGE)
        rows = list((await session.execute(select(ServiceExportSnapshotItem.ordinal, ServiceExportSnapshotItem.payload).where(
            ServiceExportSnapshotItem.snapshot_id == snapshot.id, ServiceExportSnapshotItem.ordinal > after,
        ).order_by(ServiceExportSnapshotItem.ordinal).limit(limit + 1))).all())
        if (len(rows) != min(limit + 1, snapshot.item_count - after)
                or any(row.ordinal != after + i + 1 for i, row in enumerate(rows))):
            raise HTTPException(503, "snapshot membership이 일치하지 않습니다.")
        items, has_more = [row.payload for row in rows[:limit]], len(rows) > limit
        next_cursor = _encode_cursor({"v": 1, "kind": KIND, "scope": SCOPE, "snapshot": snapshot.id,
                                      "after": after + len(items), "limit": limit}, key) if has_more else None
        page = BusTerminalExportPage(
            meta=ServiceExportMeta(generated_at=now_utc(), source_collected_at=serialize_utc(snapshot.source_collected_at),
                                   source_status="stale" if stale else "ok", item_count=len(items)),
            snapshot_id=snapshot.id, snapshot_expires_at=serialize_utc(snapshot.expires_at),
            total_count=snapshot.item_count, items=items, next_cursor=next_cursor, has_more=has_more,
        )
        revision = snapshot.content_digest
        await session.commit()
        return _response(page, request, cursor_epoch=None, cursor_revision=revision)

    return router
