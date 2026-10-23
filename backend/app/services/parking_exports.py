"""주차장 Map 현재 상태의 검증·작은 typed pointer. provider 파싱을 복제하지 않는다."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from collections.abc import Sequence

from krairport import parse_parking_snapshot_values
from sqlalchemy import delete, select

from app.core.time_utils import now_utc, serialize_utc
from app.models import ParkingCurrent, ReferenceExportState
from app.services.parsers import parse_incheon_parking, parse_kac_parking
from app.services.reference_exports import promote_reference

KIND = "parking-current"


def parking_scope(settings, source):
    airports = ["ICN"] if source == "incheon_parking" else sorted(set(settings.supported_airport_codes) - {"ICN"})
    return hashlib.sha256((source + ":" + ",".join(airports)).encode()).hexdigest()


def parking_sources(settings):
    sources = []
    if set(settings.supported_airport_codes) - {"ICN"}:
        sources.append("kac_parking")
    if settings.enable_incheon_collection:
        sources.append("incheon_parking")
    return tuple(sources)


def validate_parking_payload(settings, source, response):
    import json
    proof = response.completion
    if not isinstance(proof, dict) or not proof.get("complete"):
        raise ValueError("주차장 원천 전체 수신 증거가 없습니다")
    raw_items = json.loads(response.body_text)
    if (not isinstance(raw_items, list) or not 0 < len(raw_items) <= 2000
            or proof.get("item_count") != len(raw_items)):
        raise ValueError("주차장 완결 집합 크기가 올바르지 않습니다")
    required = ("aprKor", "parkingAirportCodeName", "parkingGetdate", "parkingGettime", "parkingFullSpace", "parkingIstay") if source == "kac_parking" else ("floor", "datetm", "parkingarea", "parking")
    if any(not isinstance(item, dict) or any(item.get(key) in (None, "") for key in required) for item in raw_items):
        raise ValueError("주차장 원천 필수 필드가 누락되었습니다")
    canonical = [parse_parking_snapshot_values(item, provider="kac" if source == "kac_parking" else "iiac")
                 for item in raw_items]
    rows = parse_kac_parking(response.body_text) if source == "kac_parking" else parse_incheon_parking(response.body_text)
    if len(rows) != len(raw_items):
        raise ValueError("해석되지 않은 주차장 원천 행이 있습니다")
    identities = [(row.airport_code, row.lot_id) for row in rows]
    if len(set(identities)) != len(rows):
        raise ValueError("주차장 원천 identity가 중복됩니다")
    current_rows = []
    for legacy_row, value in zip(rows, canonical, strict=True):
        # 기존 이력 parser의 분 단위 변환은 그대로 보존하고 Map current는 SDK 정본을 직접 쓴다.
        row = replace(legacy_row, total_spaces=value.total_spaces,
                      occupied_spaces=value.occupied_spaces, observed_at=value.observed_at)
        if (row.source != source or not row.lot_name or not row.lot_id
                or row.total_spaces <= 0 or row.occupied_spaces < 0
                or row.observed_at.tzinfo is None):
            raise ValueError("주차장 원천 필수값이 올바르지 않습니다")
        # 현재 API가 미래 시각을 성공으로 승인하지 않는다. 기존 이력 parser는 변경하지 않는다.
        if (serialize_utc(row.observed_at) - now_utc()).total_seconds() > 300:
            raise ValueError("주차장 관측시각이 미래입니다")
        current_rows.append(row)
    def selected(values):
        return [row for row in values if source == "incheon_parking" or row.airport_code in settings.supported_airport_codes]
    return selected(rows), selected(current_rows)


async def store_parking_current(session, settings, *, source, run_id, observations: Sequence, proof, lot_ids):
    scope = parking_scope(settings, source)
    old = await session.scalar(select(ReferenceExportState).where(
        ReferenceExportState.kind == KIND, ReferenceExportState.scope_key == scope,
    ).with_for_update())
    if old and old.attempt_order > run_id:
        raise ValueError("옛 주차 수집은 새 성공집합을 덮을 수 없습니다")
    if not observations or (old and len(observations) * 4 < len(old.member_ids)):
        raise ValueError("주차장 빈/급감 집합은 이전 성공을 보존합니다")
    now = now_utc()
    ids = []
    pending = []
    for value in observations:
        lot_id = lot_ids.get((value.airport_code, value.lot_id))
        if lot_id is None:
            raise ValueError("주차장 이력 저장과 current membership이 일치하지 않습니다")
        row = await session.get(ParkingCurrent, (source, scope, lot_id))
        if row is None:
            row = ParkingCurrent(source=source, scope_key=scope, parking_lot_id=lot_id, generation="pending")
            session.add(row)
        # 원천 replay의 이력 INSERT skip과 무관하게 membership을 확정한다. 늦은 값은 최신 값을 덮지 않는다.
        if row.observed_at is None or serialize_utc(value.observed_at) >= serialize_utc(row.observed_at):
            row.airport_code = value.airport_code
            row.lot_code = value.lot_id
            row.name = value.lot_name
            row.total_spaces = value.total_spaces
            row.occupied_spaces = value.occupied_spaces
            row.available_spaces = max(value.total_spaces - value.occupied_spaces, 0)
            row.observed_at = value.observed_at
            row.collected_at = now
        ids.append(lot_id)
        pending.append(row)
    await promote_reference(session, kind=KIND, scope=scope, run_id=run_id,
                            confirmed_at=min(now, *(serialize_utc(v.observed_at) for v in observations)),
                            member_ids=ids, proof={**proof, "source": source})
    await session.flush()
    head = await session.get(ReferenceExportState, (KIND, scope))
    head.last_attempt_at = now
    for row in pending:
        row.generation = head.generation
    # 신규 행도 같은 transaction에서 확정한다. 이전 cursor는 별도 immutable DTO를 읽는다.
    await session.flush()
    await session.execute(delete(ParkingCurrent).where(
        ParkingCurrent.source == source, ParkingCurrent.scope_key == scope,
        ParkingCurrent.generation != head.generation,
    ))
