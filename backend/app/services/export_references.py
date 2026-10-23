"""Map 저변동 기준정보: source별 성공 membership + 고정 DTO 페이지."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from time import monotonic
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.models import BusTerminalReference, FerryPort, ReferenceExportState, ServiceExportSnapshot, ServiceExportSnapshotItem
from app.schemas import BusTerminalExportPage, FerryPortExportPage, ServiceExportMeta
from app.services.bus_collection import TAGO_BUS_SOURCE
from app.services.rail_maritime_collection import MARITIME_SOURCE, PORT_GUIDELINE_SOURCE
from app.services.export_addresses import export_admin_addresses
from app.services.export_current import BATCH_SIZE, MAX_SNAPSHOT_BYTES, MAX_SNAPSHOT_ITEMS, SNAPSHOT_TTL, SnapshotRace, cache_generation, _snapshot_transaction, expire_snapshots
from app.services.export_price_history import _decode_cursor, _encode_cursor, _response

@dataclass(frozen=True)
class ReferenceSpec:
    path: str
    kind: str
    reference_kind: str
    scope: str
    scope_keys: tuple[str, ...]
    max_age: timedelta
    page_model: type
    payload_batches: Callable


_FIELDS = ("id", "source", "service_type", "terminal_id", "terminal_name", "city_name", "latitude", "longitude", "location_source")


async def _reference_heads(session, spec):
    heads = list((await session.scalars(select(ReferenceExportState).where(
        ReferenceExportState.kind == spec.reference_kind,
        ReferenceExportState.scope_key.in_(spec.scope_keys),
    ).order_by(ReferenceExportState.scope_key))).all())
    return heads


def _valid_heads(heads, spec):
    return (len(heads) == len(spec.scope_keys) and {h.scope_key for h in heads} == set(spec.scope_keys)
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
                    BusTerminalReference.service_type == head.scope_key,
                    BusTerminalReference.last_seen_at == head.confirmed_at).order_by(BusTerminalReference.id))).mappings())
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


async def _ferry_payload_batches(session, heads):
    head = heads[0]
    ids = sorted(head.member_ids)
    fields = ("id", "source", "port_id", "port_name", "latitude", "longitude", "location_source", "location_point_count")
    for offset in range(0, len(ids), BATCH_SIZE):
        selected = ids[offset:offset + BATCH_SIZE]
        rows = list((await session.execute(select(
            *(getattr(FerryPort, field) for field in fields),
            FerryPort.raw_item_json["_manual_location"]["revision"].as_string().label("manual_revision"),
        ).where(FerryPort.id.in_(selected), FerryPort.source == MARITIME_SOURCE,
                FerryPort.last_seen_at == head.confirmed_at).order_by(FerryPort.id))).mappings())
        if len(rows) != len(selected):
            raise HTTPException(503, "항구 source 성공 membership이 일치하지 않습니다.")
        projected = []
        for row in rows:
            item = dict(row)
            lon, lat = item["longitude"], item["latitude"]
            valid = (item["location_source"] != PORT_GUIDELINE_SOURCE and lon is not None and lat is not None
                     and math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90)
            if not valid:
                item.update(longitude=None, latitude=None, location_point_count=0)
            projected.append(SimpleNamespace(**item))
        addresses = await export_admin_addresses(session, "ferry_port", projected)
        payloads = []
        for row in projected:
            if not row.port_id or not row.port_name:
                raise HTTPException(503, "확인된 항구 이름·코드가 없습니다.")
            address = addresses.get(row.id)
            payloads.append({
                "natural_key": f"{row.source}:{row.port_id}", "source": row.source,
                "port_id": row.port_id, "name": row.port_name, "latitude": row.latitude, "longitude": row.longitude,
                "location_source": row.location_source, "location_point_count": row.location_point_count,
                "manual_location_revision": row.manual_revision if row.location_source == "admin_manual" else None,
                "admin": address.model_dump(mode="json") if address else None,
            })
        yield payloads


async def _freeze_reference(session, heads, spec):
    started = monotonic()
    size = count = 0
    digest = hashlib.sha256()
    async for batch in spec.payload_batches(session, heads):
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
    generation = cache_generation(hashlib.sha256(namespace.encode()).hexdigest())
    cached = await session.scalar(select(ServiceExportSnapshot).where(
        ServiceExportSnapshot.kind == spec.kind, ServiceExportSnapshot.scope_key == spec.scope,
        ServiceExportSnapshot.generation == generation,
        ServiceExportSnapshot.expires_at > now_utc(),
    ).order_by(ServiceExportSnapshot.created_at.desc()).limit(1))
    if cached:
        return cached
    await expire_snapshots(session)
    now = now_utc()
    table = ServiceExportSnapshot.__table__
    factory = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    snapshot_id = str(uuid4())
    admitted = await session.scalar(factory(table).values(
        id=snapshot_id, kind=spec.kind, scope_key=spec.scope, generation=generation,
        source_collected_at=min(serialize_utc(h.confirmed_at) for h in heads),
        created_at=now, expires_at=now + SNAPSHOT_TTL, item_count=count, content_digest=content,
    ).on_conflict_do_nothing(index_elements=["kind", "scope_key", "generation"]).returning(table.c.id))
    if admitted is None:
        raise SnapshotRace()
    snapshot = await session.get(ServiceExportSnapshot, snapshot_id)
    ordinal = 0
    async for batch in spec.payload_batches(session, heads):
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

    def endpoint_for(spec):
        async def endpoint(request: Request, limit: int = Query(default=1000, ge=1, le=5000),
                                cursor: str | None = Query(default=None, min_length=1, max_length=4096),
                                session: AsyncSession = Depends(get_db)) -> Response:
            if not settings.transport_map_current_enabled:
                raise HTTPException(503, "터미널 export가 활성화되지 않았습니다.")
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
            heads = await _reference_heads(session, spec)
            after = 0
            if cursor:
                value = _decode_cursor(cursor, key)
                try:
                    snapshot_id = str(UUID(value["snapshot"]))
                    after = value["after"]
                    if (value.get("kind") != spec.kind or value.get("scope") != spec.scope or value.get("limit") != limit
                            or type(after) is not int or after < 0):
                        raise ValueError("scope")
                except (KeyError, ValueError, TypeError, AttributeError) as exc:
                    raise HTTPException(422, "cursor 범위가 일치하지 않습니다.") from exc
                snapshot = await session.get(ServiceExportSnapshot, snapshot_id)
                if snapshot is None or serialize_utc(snapshot.expires_at) <= now_utc():
                    raise HTTPException(410, "snapshot이 만료되었습니다. 첫 페이지부터 다시 요청하세요.")
                if snapshot.kind != spec.kind or snapshot.scope_key != spec.scope or after >= snapshot.item_count:
                    raise HTTPException(422, "cursor snapshot 범위가 일치하지 않습니다.")
            else:
                if not _valid_heads(heads, spec):
                    raise HTTPException(503, "기준정보 source의 완결 성공 집합이 없습니다.")
                snapshot = await _freeze_reference(session, heads, spec)
            stale = (not _valid_heads(heads, spec) or any(h.last_error is not None for h in heads)
                     or now_utc() - serialize_utc(snapshot.source_collected_at) > spec.max_age)
            rows = list((await session.execute(select(ServiceExportSnapshotItem.ordinal, ServiceExportSnapshotItem.payload).where(
                ServiceExportSnapshotItem.snapshot_id == snapshot.id, ServiceExportSnapshotItem.ordinal > after,
            ).order_by(ServiceExportSnapshotItem.ordinal).limit(limit + 1))).all())
            if (len(rows) != min(limit + 1, snapshot.item_count - after)
                    or any(row.ordinal != after + i + 1 for i, row in enumerate(rows))):
                raise HTTPException(503, "snapshot membership이 일치하지 않습니다.")
            items, has_more = [row.payload for row in rows[:limit]], len(rows) > limit
            next_cursor = _encode_cursor({"v": 1, "kind": spec.kind, "scope": spec.scope, "snapshot": snapshot.id,
                                          "after": after + len(items), "limit": limit}, key) if has_more else None
            page = spec.page_model(
                meta=ServiceExportMeta(generated_at=now_utc(), source_collected_at=serialize_utc(snapshot.source_collected_at),
                                       source_status="stale" if stale else "ok", item_count=len(items)),
                snapshot_id=snapshot.id, snapshot_expires_at=serialize_utc(snapshot.expires_at),
                total_count=snapshot.item_count, items=items, next_cursor=next_cursor, has_more=has_more,
            )
            revision = snapshot.content_digest
            await session.commit()
            return page, revision

        return endpoint

    specs = (
        ReferenceSpec("/bus-terminals", "bus-terminals-v1", "bus-terminal",
                      hashlib.sha256(b"bus-terminals:express+intercity:v1").hexdigest(),
                      ("express", "intercity"), timedelta(days=9), BusTerminalExportPage, _bus_payload_batches),
        ReferenceSpec("/ferry-ports", "ferry-ports-v1", "ferry-port",
                      hashlib.sha256(b"ferry-ports:all:v1").hexdigest(),
                      ("ports",), timedelta(days=9), FerryPortExportPage, _ferry_payload_batches),
    )
    for spec in specs:
        router.add_api_route(spec.path, endpoint_for(spec), methods=["GET"], response_model=spec.page_model,
                             name=spec.path.strip("/").replace("-", "_"), responses={304: {}, 404: {}, 410: {}, 422: {}, 503: {}})
    return router
