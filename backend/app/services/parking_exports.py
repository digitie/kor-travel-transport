"""주차장 Map 현재 상태의 검증·작은 typed pointer. provider 파싱을 복제하지 않는다."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from collections.abc import Sequence
from datetime import timedelta

from krairport import parse_parking_snapshot_values
from sqlalchemy import delete, select

from app.core.time_utils import now_utc, serialize_utc
from app.models import ParkingCurrent, ReferenceExportState
from app.services.parsers import parse_incheon_parking, parse_kac_parking
from app.services.reference_exports import promote_reference

KIND = "parking-current"
#: 한 주차 원천 응답에서 격리하고 나머지로 current를 승격할 수 있는 무효 행의 최대 비율.
#: 2026-11-09~13 운영에서 IIAC 관측시각 표기(`.000`) 하나로 그 원천의 모든 행이 거부되고 run이 실패했다(835건).
#: 행 단위 결함(용량 0으로 닫힌 주차장, 미매핑 공항, 한 행의 깨진 시각)은 나머지 정상 주차장의 현재값을 막지
#: 않게 격리한다. 원천 행 수가 작아(KAC 약 25, IIAC 약 20) 비율이 크면 응답 계약 변경으로 보고 지금처럼
#: 원천 전체를 거부한다. 20%(5행 중 1행)는 한두 행 결함은 받고 계약 변경은 거부하는 경계다.
PARKING_MAX_INVALID_RATIO = 0.2
#: 무효 행으로 이번 집합에서 빠진 직전 current 주차장을 유지하는 최대 관측 나이(값·관측시각은 그대로).
#: 한 주기 결함으로 소비자(Map)가 주차장을 삭제로 읽지 않게 하되, 계속 무효인 주차장을 오래된 값으로 남기지 않는다.
PARKING_CARRY_FORWARD_MAX_AGE = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ParkingPayload:
    """검증한 주차 원천 응답. `invalid_rows`는 격리한(current에서 뺀) 원천 행 수다."""

    history_rows: list
    current_rows: list
    received_rows: int
    invalid_rows: int


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


def validate_parking_payload(settings, source, response) -> ParkingPayload:
    """완결 receipt를 확인하고 행 단위로 검증한다. 무효 행은 격리하고 비율 초과만 원천 전체를 거부한다.

    집합 단위 결함(완결 증거 없음·건수 불일치·identity 중복·유효 행 0)은 지금처럼 전체 거부다. 행 단위 결함
    (필수 필드 결측, SDK 정본 시각·수치 거부, 기존 parser가 해석하지 못한 행, 용량 0, 미래 시각)은 그 행만
    current에서 빼고 `invalid_rows`로 센다. 이력 행은 기존 관대한 parser가 받은 행을 행 단위로 남긴다(한 행의
    parser 예외가 같은 원천의 다른 이력을 지우지 않는다).
    """
    import json
    proof = response.completion
    if not isinstance(proof, dict) or not proof.get("complete"):
        raise ValueError("주차장 원천 전체 수신 증거가 없습니다")
    raw_items = json.loads(response.body_text)
    if (not isinstance(raw_items, list) or not 0 < len(raw_items) <= 2000
            or proof.get("item_count") != len(raw_items)):
        raise ValueError("주차장 완결 집합 크기가 올바르지 않습니다")
    kac = source == "kac_parking"
    required = ("aprKor", "parkingAirportCodeName", "parkingGetdate", "parkingGettime", "parkingFullSpace", "parkingIstay") if kac else ("floor", "datetm", "parkingarea", "parking")
    legacy_parse = parse_kac_parking if kac else parse_incheon_parking
    history_rows = []
    current_rows = []
    invalid = 0
    for item in raw_items:
        try:
            # 기존 이력 parser를 행 하나에 적용한다(분 단위 이력 계약 그대로).
            parsed = legacy_parse([item]) if isinstance(item, dict) else []
        except Exception:  # noqa: BLE001 — 한 원천 행의 해석 실패는 그 행에만 국한한다.
            parsed = []
        legacy_row = parsed[0] if len(parsed) == 1 else None
        if legacy_row is not None:
            history_rows.append(legacy_row)
        try:
            if legacy_row is None or any(item.get(key) in (None, "") for key in required):
                raise ValueError("주차장 원천 필수 필드가 누락되었습니다")
            value = parse_parking_snapshot_values(item, provider="kac" if kac else "iiac")
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
        except Exception:  # noqa: BLE001 — SDK 정본 검증 오류 종류와 무관하게 그 행만 격리한다.
            invalid += 1
            continue
        current_rows.append(row)
    if not current_rows:
        raise ValueError(f"주차장 원천에 유효한 행이 없습니다(received_rows={len(raw_items)}, invalid_rows={invalid})")
    if invalid > len(raw_items) * PARKING_MAX_INVALID_RATIO:
        raise ValueError(f"주차장 원천 무효 행 비율이 상한을 넘었습니다(received_rows={len(raw_items)}, "
                         f"parsed_rows={len(raw_items) - invalid}, invalid_rows={invalid})")
    identities = [(row.airport_code, row.lot_id) for row in current_rows]
    if len(set(identities)) != len(current_rows):
        raise ValueError("주차장 원천 identity가 중복됩니다")

    def selected(values):
        return [row for row in values if source == "incheon_parking" or row.airport_code in settings.supported_airport_codes]
    return ParkingPayload(history_rows=selected(history_rows), current_rows=selected(current_rows),
                          received_rows=len(raw_items), invalid_rows=invalid)


async def store_parking_current(session, settings, *, source, run_id, observations: Sequence, proof, lot_ids,
                                carry_forward_limit: int = 0):
    """`carry_forward_limit`은 이번 원천 응답에서 격리한 무효 행 수다.

    current는 완결 집합 계약이다(빠진 주차장 = 소비자에서 삭제). 무효 행의 주차장은 알 수 없으므로 직전 head에
    있었는데 이번 집합에 없는 주차장이 그 수 이하일 때만, 관측이 `PARKING_CARRY_FORWARD_MAX_AGE` 안인 직전
    current 행을 값·관측시각 그대로 새 세대에 넣는다. 빠진 수가 더 많으면 실제 소멸이 섞인 것이라 넘기지 않는다.
    """
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
    if carry_forward_limit > 0 and old is not None:
        missing = [lot_id for lot_id in old.member_ids if lot_id not in set(ids)]
        if 0 < len(missing) <= carry_forward_limit:
            cutoff = now - PARKING_CARRY_FORWARD_MAX_AGE
            for lot_id in missing:
                row = await session.get(ParkingCurrent, (source, scope, lot_id))
                if (row is not None and row.generation == old.generation and row.observed_at is not None
                        and serialize_utc(row.observed_at) >= cutoff):
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
