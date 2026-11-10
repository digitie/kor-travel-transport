"""같은 RR에서 읽은 기준정보 입력의 작은 지문. 상태 TTL이나 수정 시각에 의존하지 않는다."""

from __future__ import annotations

import hashlib
import json

from kortravelcommon.reverse_address import reverse_address_tables
from kortravelcommon.address_providers import VworldKakaoAddressResolver
from sqlalchemy import DateTime, Float, Text, any_, bindparam, cast, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by

from app.models import (
    Base, BusTerminalReference, FerryPort, KricStationCode, KricStationMappingRegistry,
    ParkingCurrent, RailStationReference,
)


def _members(column, values):
    # 여러 source의 합계가 커도 asyncpg의 bind 개수 상한을 넘지 않는다.
    return column == any_(bindparam(None, value=values, type_=ARRAY(column.type)))


def _sha(value):
    return func.encode(func.sha256(func.convert_to(value, "UTF8")), "hex")


def _part(tag, table, fields, conditions):
    values = []
    for column in fields:
        if isinstance(column.type, DateTime) and column.type.timezone:
            values.append(func.timezone("UTC", column))
        elif isinstance(column.type, Float):
            # JSONB는 -0.0과0.0을 같게 저장하므로 원래 float 비트를 지문에 넣는다.
            values.append(func.encode(func.pg_catalog.float8send(column), "hex"))
        else:
            values.append(column)
    row = _sha(cast(func.jsonb_build_array(*values), Text))
    joined = func.string_agg(row, aggregate_order_by(literal(""), *table.primary_key.columns))
    return select(literal(tag).label("part"), func.count().label("rows"),
                  _sha(func.coalesce(joined, "")).label("digest")).select_from(table).where(*conditions)


async def reference_payload_revision(session, heads, kind: str, revision: str | None) -> str | None:
    """DB 값·주소·저장 매핑을 모두 확인한다. 미지원/개발 환경은 기존 완전 구성 경로다."""
    if session.bind.dialect.name != "postgresql" or not revision or revision == "unknown":
        return None
    ids = sorted({member for head in heads for member in head.member_ids})
    options = {
        "rail-stations-v1": (RailStationReference.__table__, "rail_station", "id"),
        "bus-terminals-v1": (BusTerminalReference.__table__, "bus_terminal", "id"),
        "ferry-ports-v1": (FerryPort.__table__, "ferry_port", "id"),
        "parking-current-v1": (ParkingCurrent.__table__, None, "parking_lot_id"),
    }
    if kind not in options:
        return None
    table, address_kind, identity = options[kind]
    fields = [column for column in table.columns if column.name != "raw_item_json"]
    if address_kind in {"bus_terminal", "ferry_port"}:
        fields.append(table.c.raw_item_json["_manual_location"]["revision"].as_string())
    parts = [_part("source", table, fields, [_members(table.c[identity], ids)])]
    if address_kind:
        entries, _ = reverse_address_tables(Base.metadata)
        keys = [f"{address_kind}:{row_id}" for row_id in ids]
        parts.append(_part("address", entries, [entries.c.provider_id, entries.c.target_key,
                           entries.c.coordinate_key, entries.c.status, entries.c.payload, entries.c.resolved_at],
                           [_members(entries.c.target_key, keys),
                            entries.c.provider_id == VworldKakaoAddressResolver.provider_id,
                            entries.c.status.in_(("ok", "error"))]))
    if address_kind == "rail_station":
        codes = KricStationCode.__table__
        parts.append(_part("codes", codes, list(codes.columns),
                           [_members(codes.c.rail_station_id, ids), codes.c.active.is_(True)]))
        registry = KricStationMappingRegistry.__table__
        parts.append(_part("registry", registry, [registry.c.id, registry.c.catalog_sha256,
                          registry.c.automatic_mappings_json, registry.c.manual_mappings_json], [registry.c.id == 1]))
    rows = (await session.execute(union_all(*parts))).all()
    namespace = ["reference-input-v1", revision, kind,
                 [[head.scope_key, head.generation, head.confirmed_at.isoformat(), head.member_ids, head.proof] for head in heads],
                 [tuple(row) for row in rows]]
    return hashlib.sha256(json.dumps(namespace, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
