"""같은 RR에서 읽은 기준정보 입력의 작은 지문. 상태 TTL이나 수정 시각에 의존하지 않는다."""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from weakref import WeakKeyDictionary

from kortravelcommon.address_providers import VworldKakaoAddressResolver
from kortravelcommon.reverse_address import reverse_address_tables
from sqlalchemy import (
    DateTime,
    Float,
    Text,
    any_,
    bindparam,
    cast,
    func,
    literal,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by

from app.core.read_timing import observe_fingerprint
from app.models import (
    Base,
    BusTerminalReference,
    FerryPort,
    KricStationCode,
    KricStationMappingRegistry,
    ParkingCurrent,
    RailStationReference,
    ReferenceExportInputRevision,
)

_REVISION_CACHE = WeakKeyDictionary()
_MAX_REVISIONS = 64


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
    components = {
        "bus-terminals-v1": ("bus_source", "address_bus_terminal"),
        "ferry-ports-v1": ("ferry_source", "address_ferry_port"),
        "rail-stations-v1": ("rail_source", "address_rail_station", "rail_codes", "rail_registry"),
        "parking-current-v1": ("parking_source",),
    }.get(kind)
    if components is None:
        return None
    # 같은 RR에서 실제 입력별 transactional counter만 읽는다. 다른 DB/표의 commit은 키와 무관하다.
    records = (await session.execute(select(
        ReferenceExportInputRevision.component, ReferenceExportInputRevision.epoch, ReferenceExportInputRevision.revision,
        func.pg_current_xact_id_if_assigned().cast(Text).label("own_xid"),
        func.current_setting("transaction_isolation").label("isolation"),
    ).where(ReferenceExportInputRevision.component.in_(components))
      .order_by(ReferenceExportInputRevision.component))).all()
    if len(records) != len(components):
        from fastapi import HTTPException
        raise HTTPException(503, "참조 입력 revision 구성이 완전하지 않습니다.")
    own_xid, isolation = records[0].own_xid, records[0].isolation
    input_versions = tuple((row.component, row.epoch, row.revision) for row in records)
    can_memo = isolation in {"repeatable read", "serializable"} and own_xid is None and not (
        session.new or session.dirty or session.deleted
    )
    cache = _REVISION_CACHE.setdefault(session.bind, OrderedDict())
    head_key = json.dumps([[h.scope_key, h.generation, h.confirmed_at.isoformat(), h.member_ids, h.proof]
                           for h in heads], sort_keys=True, separators=(",", ":"))
    cache_key = (input_versions, revision, kind, head_key)
    if can_memo and cache_key in cache:
        cache.move_to_end(cache_key)
        return cache[cache_key]
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
    observe_fingerprint()
    rows = (await session.execute(union_all(*parts))).all()
    namespace = ["reference-input-v1", revision, kind,
                 [[head.scope_key, head.generation, head.confirmed_at.isoformat(), head.member_ids, head.proof] for head in heads],
                 [tuple(row) for row in rows]]
    result = hashlib.sha256(json.dumps(namespace, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if can_memo:
        cache[cache_key] = result
        while len(cache) > _MAX_REVISIONS:
            cache.popitem(last=False)
    return result
