"""Transport 소유 전국주차장 기준정보. 요청 중 제공기관을 호출하지 않는다."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import defer

from app.core.time_utils import now_utc, serialize_utc
from app.models import PublicParkingLot, TransportCollectionState
from app.schemas import (
    ExportCollectionState, PublicParkingExportItem, PublicParkingExportPage,
    PublicParkingItem, PublicParkingPage,
)
from app.services.public_parking_collection import SOURCE

STALE_AFTER = timedelta(days=90)  # 월간 기준정보. 기준일은 별도 reference_date로 보존한다.


def current_parking_conditions() -> list[Any]:
    generation = select(TransportCollectionState.last_success_at).where(
        TransportCollectionState.source == SOURCE,
    ).scalar_subquery()
    return [PublicParkingLot.source == SOURCE, PublicParkingLot.last_seen_at == generation]


def parking_item(row: PublicParkingLot, generation, *, export: bool = False):
    fields = {name: getattr(row, name) for name in PublicParkingItem.model_fields
              if name not in {"opening_hours", "collected_at", "is_current"}}
    fields.update(opening_hours=row.opening_hours_json, collected_at=serialize_utc(row.last_seen_at),
                  is_current=generation is not None and serialize_utc(row.last_seen_at) == serialize_utc(generation))
    if export:
        return PublicParkingExportItem(**fields, source_key=row.source_key, raw=row.raw_json)
    return PublicParkingItem(**fields)


async def parking_state(session):
    if session.bind.dialect.name == "postgresql":
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == SOURCE))
    generation = state.last_success_at if state else None
    return state, generation, ExportCollectionState(
        source=SOURCE, last_success_at=serialize_utc(generation) if generation else None,
        failed=False, stale=generation is None or now_utc() - serialize_utc(generation) > STALE_AFTER,
        last_attempt_failed=bool(state and state.last_error),
    )


def _cursor(cursor: str | None, generation, query: str) -> int:
    if not cursor:
        return 0
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if (not isinstance(payload, dict) or set(payload) != {"g", "q", "id"}
                or type(payload["id"]) is not int or not 0 < payload["id"] <= 9223372036854775807
                or payload["q"] != hashlib.sha256(query.encode()).hexdigest()):
            raise ValueError
    except (ValueError, TypeError, UnicodeError, KeyError):
        raise HTTPException(422, "유효한 주차장 페이지 커서가 아닙니다.") from None
    current = serialize_utc(generation).isoformat() if generation else None
    if payload["g"] != current:
        raise HTTPException(409, "주차장 기준정보가 갱신됐습니다. 첫 페이지부터 다시 조회해 주세요.")
    return payload["id"]


async def parking_page(session, limit: int, cursor: str | None, q: str | None, *, export: bool = False):
    _, generation, collection = await parking_state(session)
    if export and collection.stale:
        raise HTTPException(503, "완료된 최신 주차장 기준정보가 없습니다.")
    query = (q or "").strip()
    after = _cursor(cursor, generation, query)
    statement = select(PublicParkingLot).where(*current_parking_conditions(), PublicParkingLot.id > after)
    if query:
        statement = statement.where(or_(*(field.icontains(query, autoescape=True) for field in (
            PublicParkingLot.name, PublicParkingLot.road_address, PublicParkingLot.land_address,
        ))))
    if not export:
        statement = statement.options(defer(PublicParkingLot.raw_json))
    rows = list((await session.scalars(statement.order_by(PublicParkingLot.id).limit(limit + 1))).all())
    has_more, rows = len(rows) > limit, rows[:limit]
    next_cursor = None
    if has_more:
        payload = {"g": serialize_utc(generation).isoformat(), "q": hashlib.sha256(query.encode()).hexdigest(), "id": rows[-1].id}
        next_cursor = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    model = PublicParkingExportPage if export else PublicParkingPage
    return model(generated_at=now_utc(), collection=collection, items=[parking_item(row, generation, export=export) for row in rows],
                 next_cursor=next_cursor, has_more=has_more)


def build_public_parking_router(get_db) -> APIRouter:
    router = APIRouter(prefix="/transport/parking-lots", tags=["parking-reference"])

    @router.get("", response_model=PublicParkingPage)
    async def list_parking(limit: int = Query(100, ge=1, le=1000), cursor: str | None = Query(None, max_length=500),
                           q: str | None = Query(None, max_length=100), session=Depends(get_db)):
        return await parking_page(session, limit, cursor, q)

    @router.get("/{parking_id}", response_model=PublicParkingItem)
    async def detail_parking(parking_id: int = Path(ge=1, le=9223372036854775807), session=Depends(get_db)):
        _, generation, _ = await parking_state(session)
        row = await session.scalar(select(PublicParkingLot).options(defer(PublicParkingLot.raw_json)).where(
            PublicParkingLot.id == parking_id, PublicParkingLot.source == SOURCE,
        ))
        if row is None:
            raise HTTPException(404, "저장된 주차장이 없습니다.")
        return parking_item(row, generation)

    return router


def build_public_parking_export_router(get_db) -> APIRouter:
    router = APIRouter()

    @router.get("/parking-lots", response_model=PublicParkingExportPage)
    async def export_parking(limit: int = Query(500, ge=1, le=1000), cursor: str | None = Query(None, max_length=500),
                             session=Depends(get_db)):
        return await parking_page(session, limit, cursor, None, export=True)

    return router
