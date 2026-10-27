"""KRIC 역 코드 카탈로그와 이름 차이 연결 규칙."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from app.core.time_utils import now_utc
from app.models import KricStationCode, KricStationMappingRegistry, RailStationReference
from app.schemas import (
    KricAutomaticMappingBlocker, KricAutomaticMappingChange, KricAutomaticMappingCodeKey,
    KricAutomaticMappingConflict, KricAutomaticMappingCounts, KricAutomaticMappingPreview,
    KricAutomaticMappingTarget,
    KricAutomaticMappingApplyRequest, KricAutomaticMappingApplyResponse,
)

RAIL_STATION_REFERENCE_LOCK_KEY = 420054
KRIC_TIMETABLE_LEASE_NAME = "transport:kric_timetable"


class AutomaticMappingInputError(ValueError):
    """저장된 입력이 미준비·불일치 상태다. provider 조회로 보충하지 않는다."""


class AutomaticMappingConflict(ValueError):
    """별도 writer·수집·이전 미리보기와 충돌했다. API는 문자열 detail의409로 변환한다."""


@dataclass(frozen=True)
class AutomaticMappingPlan:
    preview: KricAutomaticMappingPreview
    automatic: list[dict[str, str]]
    link_updates: dict[tuple[str, str, str], int | None]


async def lock_rail_station_reference_catalog(session: Any) -> None:
    """기준 역 수집과 관리자 매핑 저장을 하나의 PostgreSQL 트랜잭션 잠금으로 직렬화한다."""
    bind = getattr(session, "bind", None)
    if getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": RAIL_STATION_REFERENCE_LOCK_KEY},
    )


def provider_key(row: Any) -> tuple[str, str, str]:
    return (
        str(getattr(row, "operator_code", getattr(row, "rail_operator_code", ""))).strip(),
        str(row.line_code).strip(),
        str(row.station_code).strip(),
    )


def source_key(row: Any) -> tuple[str, str, str]:
    return (
        str(getattr(row, "operator_name", getattr(row, "rail_operator_name", "")) or "").strip(),
        str(getattr(row, "line_name", "") or getattr(row, "operating_line_name", "") or "").strip(),
        str(row.station_name or "").strip(),
    )


def _composite_match_key(row: Any, *, official: bool) -> tuple[str, str, str, str]:
    """원문과 별개인 비교키. 코레일 경의중앙 표기는 공식 KR/K4 안에서만 묶는다."""
    operator, line, name = source_key(row)
    aliases = {("코레일", "경의중앙선"), ("한국철도공사", "경의중앙")}
    if (operator, line) in aliases:
        if not official or provider_key(row)[:2] == ("KR", "K4"):
            # 이름만 같은 다른 운영기관·노선의 원문 키와 충돌하지 않게 구분한다.
            return ("kric_code_line", "KR", "K4", name)
    return ("source_names", operator, line, name)


def catalog_record(row: Any) -> dict[str, str]:
    operator_code, line_code, station_code = provider_key(row)
    operator_name, line_name, station_name = source_key(row)
    return {
        "operator_code": operator_code,
        "operator_name": operator_name,
        "line_code": line_code,
        "line_name": line_name,
        "station_code": station_code,
        "station_name": station_name,
    }


def station_catalog(codes: Iterable[Any]) -> list[dict[str, str]]:
    return sorted(
        (catalog_record(row) for row in codes),
        key=lambda row: (row["operator_code"], row["line_code"], row["station_code"]),
    )


def catalog_digest(catalog: list[dict[str, str]]) -> str:
    encoded = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def reference_catalog_digest(places: Iterable[Any]) -> str:
    """수동 연결 대상의 식별·표시 필드만 정렬해 동시성 지문을 만든다."""
    catalog = sorted(
        ({
            "id": int(getattr(place, "id", 0) or 0),
            "identity_key": str(place.identity_key),
            "operator_name": getattr(place, "rail_operator_name", None),
            "line_name": getattr(place, "operating_line_name", None),
            "station_number": getattr(place, "station_number", None),
            "station_name": getattr(place, "station_name", None),
        } for place in places),
        key=lambda item: (item["identity_key"], item["id"]),
    )
    encoded = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def mapping_revision(
    catalog_sha256: str | None,
    automatic: list[dict[str, str]],
    manual: list[dict[str, str]],
    reference_sha256: str | None = None,
) -> str:
    def sort_by_code(item: dict[str, str]) -> tuple[str, str, str]:
        return item["operator_code"], item["line_code"], item["station_code"]

    document = {
        "catalog_sha256": catalog_sha256,
        "reference_sha256": reference_sha256,
        "automatic": sorted(automatic, key=sort_by_code),
        "manual": sorted(manual, key=sort_by_code),
    }
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_station_name(value: str | None) -> str:
    """역번이 같은 후보끼리만 비교할 보수적인 한글 표기 정규화."""
    name = unicodedata.normalize("NFKC", (value or "").strip())
    # 괄호 안 부역명·병기 시설명은 역 코드가 같은 후보를 좁히는 데만 제외한다.
    name = re.sub(r"[（(][^（）()]*[）)]", "", name).strip()
    name = name.removesuffix("역")
    return re.sub(r"\s+", "", name)


def automatic_station_mappings(
    codes: Iterable[Any], places: Iterable[Any],
) -> list[dict[str, str]]:
    """정확한 이름 일치 또는 동일 역번·정규 역명 유일 일치만 JSON으로 만든다."""
    code_rows = list(codes)
    place_rows = list(places)
    code_name_counts = Counter(_composite_match_key(row, official=True) for row in code_rows)
    code_number_name_counts = Counter(
        (str(row.station_code).strip(), normalized_station_name(row.station_name))
        for row in code_rows
    )
    places_by_source_name: dict[tuple[str, str, str, str], list[Any]] = defaultdict(list)
    places_by_number_name: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for place in place_rows:
        places_by_source_name[_composite_match_key(place, official=False)].append(place)
        number = str(place.station_number or "").strip()
        name = normalized_station_name(place.station_name)
        if number and name:
            places_by_number_name[(number, name)].append(place)

    exact: dict[tuple[str, str, str], Any] = {}
    ambiguous_alias_codes: set[tuple[str, str, str]] = set()
    for row in code_rows:
        key = _composite_match_key(row, official=True)
        candidates = places_by_source_name.get(key, [])
        if key[0] == "kric_code_line" and (code_name_counts[key] > 1 or len(candidates) > 1):
            # 별칭으로 합쳐진 복합 식별이 모호하면 번호 하나로 우회 확정하지 않는다.
            ambiguous_alias_codes.add(provider_key(row))
        if code_name_counts[key] == 1 and len(candidates) == 1:
            exact[provider_key(row)] = candidates[0]
    exact_targets = {str(place.identity_key) for place in exact.values()}

    by_number: dict[tuple[str, str, str], Any] = {}
    for row in code_rows:
        code = provider_key(row)
        if code in exact or code in ambiguous_alias_codes:
            continue
        number = str(row.station_code).strip()
        name = normalized_station_name(row.station_name)
        lookup = (number, name)
        candidates = places_by_number_name.get(lookup, [])
        if (
            number
            and name
            and code_number_name_counts[lookup] == 1
            and len(candidates) == 1
            and str(candidates[0].identity_key) not in exact_targets
        ):
            by_number[code] = candidates[0]

    target_counts = Counter(str(place.identity_key) for place in by_number.values())
    results: list[dict[str, str]] = []
    for row in code_rows:
        code = provider_key(row)
        place = exact.get(code)
        strategy = "exact_identity"
        if place is None:
            place = by_number.get(code)
            strategy = "station_number_and_name"
            if place is not None and target_counts[str(place.identity_key)] != 1:
                place = None
        if place is None:
            continue
        results.append({
            "operator_code": code[0],
            "line_code": code[1],
            "station_code": code[2],
            "rail_station_identity_key": str(place.identity_key),
            "match_method": strategy,
        })
    return results


def validate_manual_mappings(mappings: Any, catalog_keys: set[tuple[str, str, str]]) -> list[dict[str, str]]:
    if not isinstance(mappings, list):
        raise TypeError("매핑 JSON은 배열이어야 합니다.")
    validated: list[dict[str, str]] = []
    keys: set[tuple[str, str, str]] = set()
    targets: set[str] = set()
    for item in mappings:
        if not isinstance(item, Mapping):
            raise TypeError("매핑 항목은 JSON 객체여야 합니다.")
        code = tuple(str(item.get(field, "")).strip() for field in ("operator_code", "line_code", "station_code"))
        target = str(item.get("rail_station_identity_key", "")).strip()
        note = str(item.get("note", "")).strip()
        if not all(code) or not target or len(target) > 400:
            raise ValueError("코드 세 항목과 연결할 역 identity_key가 필요합니다.")
        if code not in catalog_keys:
            raise ValueError("현재 KRIC 카탈로그에 없는 역 코드입니다.")
        if code in keys:
            raise ValueError("같은 역 코드가 여러 번 매핑됐습니다.")
        if target in targets:
            raise ValueError("같은 역 기준정보를 여러 코드에 연결할 수 없습니다.")
        if len(note) > 500:
            raise ValueError("메모는 500자 이하여야 합니다.")
        keys.add(code)
        targets.add(target)
        validated.append({
            "operator_code": code[0],
            "line_code": code[1],
            "station_code": code[2],
            "rail_station_identity_key": target,
            "note": note,
        })
    return sorted(validated, key=lambda row: (row["operator_code"], row["line_code"], row["station_code"]))


def effective_station_mappings(
    codes: Iterable[Any],
    places: Iterable[Any],
    automatic: list[dict[str, str]],
    manual: list[dict[str, str]],
) -> dict[tuple[str, str, str], tuple[str, str]]:
    """수동 매핑을 먼저 예약하고 자동 매핑이 같은 장소를 중복 점유하지 않게 한다."""
    code_rows = list(codes)
    place_rows = list(places)
    places_by_identity: dict[str, list[Any]] = defaultdict(list)
    for place in place_rows:
        places_by_identity[str(place.identity_key)].append(place)
    active_keys = {provider_key(row) for row in code_rows}

    manual_by_key: dict[tuple[str, str, str], str] = {}
    reserved: set[str] = set()
    for item in manual:
        key = tuple(str(item.get(field, "")) for field in ("operator_code", "line_code", "station_code"))
        target = str(item.get("rail_station_identity_key", ""))
        if key not in active_keys or len(places_by_identity.get(target, [])) != 1 or target in reserved:
            continue
        manual_by_key[key] = target
        reserved.add(target)

    effective: dict[tuple[str, str, str], tuple[str, str]] = {}
    for key, target in manual_by_key.items():
        effective[key] = (target, "manual")

    automatic_by_key = {
        (item["operator_code"], item["line_code"], item["station_code"]): item["rail_station_identity_key"]
        for item in automatic
    }
    for key in active_keys:
        target = automatic_by_key.get(key)
        if key not in effective and target and target not in reserved:
            effective[key] = (target, "automatic")
            reserved.add(target)
    return effective


def _stored_mapping_records(value: Any) -> list[dict[str, Any]]:
    """원문 note·추가 필드를 정규화하거나 고치지 않고 식별자만 확인한다."""
    if not isinstance(value, list) or len(value) > 10000:
        raise AutomaticMappingInputError("저장된 매핑 배열을 확인해 주세요.")
    keys: set[tuple[str, str, str]] = set()
    targets: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or any(
            not isinstance(item.get(name), str) or not item[name]
            for name in ("operator_code", "line_code", "station_code", "rail_station_identity_key")
        ):
            raise AutomaticMappingInputError("저장된 매핑 식별자를 확인해 주세요.")
        key = tuple(item[name] for name in ("operator_code", "line_code", "station_code"))
        target = item["rail_station_identity_key"]
        if key in keys or target in targets:
            raise AutomaticMappingInputError("저장된 매핑 식별자가 중복됐습니다.")
        keys.add(key)
        targets.add(target)
    return value


def _mapping_counts(codes: list[Any], effective: dict) -> KricAutomaticMappingCounts:
    return KricAutomaticMappingCounts(
        station_count=len(codes), mapped_count=len(effective),
        automatic_mapped_count=sum(method == "automatic" for _, method in effective.values()),
        manual_mapped_count=sum(method == "manual" for _, method in effective.values()),
        unmatched_count=len(codes) - len(effective),
    )


def build_automatic_mapping_plan(
    registry: Any, codes: Iterable[Any], places: Iterable[Any], *, generated_at: datetime,
) -> AutomaticMappingPlan:
    """저장 입력만으로 후보와 실제 FK 변경 쌍을 만든다. 입력 객체는 바꾸지 않는다."""
    all_codes, place_rows = list(codes), list(places)
    code_rows = [row for row in all_codes if getattr(row, "active", True)]
    if not code_rows or not place_rows or max(len(all_codes), len(place_rows)) > 10000:
        raise AutomaticMappingInputError("공식 역 코드와 기준정보가 준비되지 않았습니다.")
    catalog = getattr(registry, "catalog_json", None)
    sha = getattr(registry, "catalog_sha256", None)
    if not isinstance(catalog, list) or not catalog or len(catalog) > 10000:
        raise AutomaticMappingInputError("저장된 공식 역 코드 catalog가 필요합니다.")
    if any(not isinstance(row, dict) or any(not isinstance(row.get(name), str) or not row[name].strip()
        for name in ("operator_code", "operator_name", "line_code", "line_name", "station_code", "station_name"))
        for row in catalog):
        raise AutomaticMappingInputError("저장된 공식 역 코드 catalog가 불완전합니다.")
    expected_catalog = station_catalog(code_rows)
    if (len({provider_key(row) for row in code_rows}) != len(code_rows)
            or sorted(catalog, key=lambda row: (row["operator_code"], row["line_code"], row["station_code"])) != expected_catalog
            or catalog_digest(catalog) != sha):
        raise AutomaticMappingInputError("저장 catalog와 active 공식 역 코드가 일치하지 않습니다.")
    identities = [str(row.identity_key) for row in place_rows]
    ids = [row.id for row in place_rows]
    if (len(set(identities)) != len(identities) or len(set(ids)) != len(ids)
            or any(not isinstance(row_id, int) or isinstance(row_id, bool) for row_id in ids)
            or any(not key for key in identities)):
        raise AutomaticMappingInputError("기준 역 식별자가 중복되거나 비어 있습니다.")
    old_auto = _stored_mapping_records(getattr(registry, "automatic_mappings_json", None))
    manual = _stored_mapping_records(getattr(registry, "manual_mappings_json", None))
    known_identities = set(identities)
    if any(item["rail_station_identity_key"] not in known_identities
            for records in (old_auto, manual) for item in records):
        raise AutomaticMappingInputError("저장 매핑이 현재 기준 역에 없는 대상을 참조합니다.")
    if any(item.get("match_method", "exact_identity") not in ("exact_identity", "station_number_and_name")
            for item in old_auto):
        raise AutomaticMappingInputError("저장된 자동 연결 방식이 유효하지 않습니다.")
    new_auto = sorted(automatic_station_mappings(code_rows, place_rows),
        key=lambda row: (row["operator_code"], row["line_code"], row["station_code"]))
    before = effective_station_mappings(code_rows, place_rows, old_auto, manual)
    after = effective_station_mappings(code_rows, place_rows, new_auto, manual)
    place_by_identity = {str(row.identity_key): row for row in place_rows}
    before_auto = {(row["operator_code"], row["line_code"], row["station_code"]): row for row in old_auto}
    after_auto = {(row["operator_code"], row["line_code"], row["station_code"]): row for row in new_auto}

    def target(key, effective, automatic) -> KricAutomaticMappingTarget:
        link = effective.get(key)
        if not link:
            return KricAutomaticMappingTarget(match_method="unmatched")
        identity, method = link
        place = place_by_identity.get(identity)
        match_method = "manual" if method == "manual" else automatic[key].get("match_method", "exact_identity")
        return KricAutomaticMappingTarget(rail_station_id=place.id if place else None,
            rail_station_identity_key=identity, match_method=match_method)

    changes: list[KricAutomaticMappingChange] = []
    blockers: list[KricAutomaticMappingBlocker] = []
    updates: dict[tuple[str, str, str], int | None] = {}
    for row in sorted(code_rows, key=provider_key):
        key = provider_key(row)
        old, new = target(key, before, before_auto), target(key, after, after_auto)
        fields = dict(zip(("operator_code", "line_code", "station_code"), key, strict=True))
        if row.rail_station_id != old.rail_station_id:
            blockers.append(KricAutomaticMappingBlocker(code="persisted_link_mismatch",
                message="실제 저장 연결과 기존 registry가 일치하지 않습니다.", **fields))
        if row.rail_station_id != new.rail_station_id:
            updates[key] = new.rail_station_id
        if old == new:
            continue
        kind = ("added" if old.rail_station_identity_key is None else
            "removed" if new.rail_station_identity_key is None else
            "retargeted" if old.rail_station_identity_key != new.rail_station_identity_key else "method_changed")
        changes.append(KricAutomaticMappingChange(**fields, operator_name=row.operator_name,
            line_name=row.line_name, station_name=row.station_name, change_type=kind, before=old, after=new))
    new_target_ids = {place_by_identity[identity].id for identity, _ in after.values()}
    for row in all_codes:
        if not getattr(row, "active", True) and row.rail_station_id in new_target_ids:
            fields = dict(zip(("operator_code", "line_code", "station_code"), provider_key(row), strict=True))
            blockers.append(KricAutomaticMappingBlocker(code="inactive_target_occupied",
                message="비활성 코드가 후보의 기준 역을 점유하고 있습니다.", **fields))
    manual_by_key = {key: identity for key, (identity, method) in before.items() if method == "manual"}
    if manual_by_key != {key: identity for key, (identity, method) in after.items() if method == "manual"}:
        blockers.append(KricAutomaticMappingBlocker(code="manual_link_changed", message="기존 수동 연결이 달라집니다."))
    manual_by_target = {identity: key for key, identity in manual_by_key.items()}
    conflicts: list[KricAutomaticMappingConflict] = []
    for key, item in after_auto.items():
        identity = item["rail_station_identity_key"]
        reason = None
        reserved = None
        if key in manual_by_key and manual_by_key[key] != identity:
            reason, reserved = "manual_code_override", key
        elif identity in manual_by_target and manual_by_target[identity] != key:
            reason, reserved = "manual_target_reserved", manual_by_target[identity]
        if reason and reserved:
            fields = dict(zip(("operator_code", "line_code", "station_code"), key, strict=True))
            reserved_fields = dict(zip(("operator_code", "line_code", "station_code"), reserved, strict=True))
            conflicts.append(KricAutomaticMappingConflict(**fields, rail_station_identity_key=identity,
                reason=reason, reserved_by=KricAutomaticMappingCodeKey(**reserved_fields)))
    reference_sha = reference_catalog_digest(place_rows)
    revision = mapping_revision(sha, old_auto, manual, reference_sha)
    candidate = mapping_revision(sha, new_auto, manual, reference_sha)
    blockers.sort(key=lambda row: (row.code, row.operator_code or "", row.line_code or "", row.station_code or ""))
    preview = KricAutomaticMappingPreview(generated_at=generated_at, expected_revision=revision,
        candidate_revision=candidate, catalog_sha256=sha, before=_mapping_counts(code_rows, before),
        after=_mapping_counts(code_rows, after), has_changes=revision != candidate,
        can_apply=not blockers, changes=changes, manual_conflicts=conflicts, blockers=blockers)
    return AutomaticMappingPlan(preview=preview, automatic=new_auto, link_updates=updates)


def _require_fresh_mapping_session(session: AsyncSession) -> None:
    if session.in_transaction() or session.new or session.dirty or session.deleted:
        raise AutomaticMappingInputError("자동 연결 작업에는 새 DB 세션이 필요합니다.")


async def _prepare_mapping_transaction(session: AsyncSession, *, read_only: bool) -> None:
    if session.bind.dialect.name == "postgresql":
        # POST의 잠금 SELECT가 오래된 RR snapshot을 먼저 고정하지 않게 RC로 시작한다.
        isolation = "REPEATABLE READ" if read_only else "READ COMMITTED"
        await session.connection(execution_options={"isolation_level": isolation})
        if read_only:
            await session.execute(text("SET TRANSACTION READ ONLY"))
        await session.execute(text("SET LOCAL lock_timeout = '2s'"))
        await session.execute(text("SET LOCAL statement_timeout = '10s'"))


async def _stored_mapping_inputs(session: AsyncSession, *, lock_registry: bool = False):
    query = select(KricStationMappingRegistry).where(KricStationMappingRegistry.id == 1)
    if lock_registry:
        query = query.with_for_update()
    registry = await session.scalar(query.execution_options(populate_existing=True))
    if registry is None:
        raise AutomaticMappingInputError("저장된 역 매핑 catalog가 아직 없습니다.")
    codes = (await session.scalars(select(KricStationCode)
        .options(load_only(KricStationCode.id, KricStationCode.operator_code, KricStationCode.operator_name,
            KricStationCode.line_code, KricStationCode.line_name, KricStationCode.station_code,
            KricStationCode.station_name, KricStationCode.rail_station_id, KricStationCode.active))
        .order_by(KricStationCode.operator_code, KricStationCode.line_code, KricStationCode.station_code)
        .execution_options(populate_existing=True))).all()
    places = (await session.scalars(select(RailStationReference)
        .options(load_only(RailStationReference.id, RailStationReference.identity_key,
            RailStationReference.rail_operator_name, RailStationReference.operating_line_name,
            RailStationReference.station_number, RailStationReference.station_name))
        .where(RailStationReference.source == "kric_public_file")
        .order_by(RailStationReference.identity_key, RailStationReference.id)
        .execution_options(populate_existing=True))).all()
    return registry, codes, places


async def preview_automatic_station_mappings(session: AsyncSession) -> KricAutomaticMappingPreview:
    """RR 읽기만 수행한다. 새 registry·원본파일·수집 run은 만들지 않는다."""
    _require_fresh_mapping_session(session)
    try:
        await _prepare_mapping_transaction(session, read_only=True)
        registry, codes, places = await _stored_mapping_inputs(session)
        return build_automatic_mapping_plan(registry, codes, places, generated_at=now_utc()).preview
    except DBAPIError as exc:
        if _mapping_conflict_sqlstate(exc):
            raise AutomaticMappingConflict("역정보를 변경 중입니다. 잠시 후 미리보기를 다시 열어 주세요.") from None
        raise
    finally:
        await session.rollback()


def _mapping_conflict_sqlstate(error: DBAPIError) -> bool:
    original = error.orig
    code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return isinstance(error, IntegrityError) or code in {"55P03", "57014", "40P01", "40001"}


async def apply_automatic_station_mappings(
    session: AsyncSession, payload: KricAutomaticMappingApplyRequest,
) -> KricAutomaticMappingApplyResponse:
    """저장 입력을 잠금 뒤 검산하고 변경 FK와 automatic만 한 번에 반영한다."""
    _require_fresh_mapping_session(session)
    try:
        await _prepare_mapping_transaction(session, read_only=False)
        if session.bind.dialect.name == "postgresql":
            acquired = await session.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext(:lease_name))"),
                {"lease_name": KRIC_TIMETABLE_LEASE_NAME})
            if not acquired:
                raise AutomaticMappingConflict("도시철도 수집이 진행 중입니다. 완료 후 다시 확인해 주세요.")
        await lock_rail_station_reference_catalog(session)
        registry, codes, places = await _stored_mapping_inputs(session, lock_registry=True)
        plan = build_automatic_mapping_plan(registry, codes, places, generated_at=now_utc())
        preview = plan.preview
        if payload.expected_revision != preview.expected_revision:
            raise AutomaticMappingConflict("역 코드나 매핑이 변경됐습니다. 미리보기를 새로 열어 주세요.")
        if payload.candidate_revision != preview.candidate_revision:
            raise AutomaticMappingConflict("자동 연결 후보가 변경됐습니다. 미리보기를 새로 열어 주세요.")
        if not preview.can_apply:
            raise AutomaticMappingConflict("저장된 역 연결의 무결성을 확인한 뒤 다시 시도해 주세요.")
        if not preview.has_changes:
            await session.rollback()
            return KricAutomaticMappingApplyResponse(status="unchanged", previous_revision=preview.expected_revision,
                revision=preview.candidate_revision, changed_link_count=0, summary=preview.after)
        rows = {provider_key(row): row for row in codes if row.active}
        for key in plan.link_updates:
            rows[key].rail_station_id = None
        await session.flush()  # 변경 쌍만 비워 교환 시 unique FK 충돌을 막는다.
        for key, place_id in plan.link_updates.items():
            rows[key].rail_station_id = place_id
        registry.automatic_mappings_json = plan.automatic
        registry.mappings_updated_at = registry.updated_at = now_utc()
        await session.commit()
        return KricAutomaticMappingApplyResponse(status="applied", previous_revision=preview.expected_revision,
            revision=preview.candidate_revision, changed_link_count=len(plan.link_updates), summary=preview.after)
    except DBAPIError as exc:
        await session.rollback()
        if _mapping_conflict_sqlstate(exc):
            raise AutomaticMappingConflict("다른 역정보 변경이 진행 중입니다. 미리보기를 새로 확인해 주세요.") from None
        raise
    except BaseException:
        await session.rollback()
        raise


async def load_kric_station_mapping(session: AsyncSession):
    registry = await session.get(KricStationMappingRegistry, 1)
    codes = (await session.scalars(
        select(KricStationCode)
        .where(KricStationCode.active.is_(True))
        .order_by(KricStationCode.operator_code, KricStationCode.line_code, KricStationCode.station_code)
    )).all()
    places = (await session.scalars(
        select(RailStationReference)
        .where(RailStationReference.source == "kric_public_file")
        .order_by(RailStationReference.rail_operator_name, RailStationReference.operating_line_name,
                  RailStationReference.station_name, RailStationReference.identity_key)
    )).all()
    catalog = (registry.catalog_json if registry and registry.catalog_json else station_catalog(codes))
    catalog_sha256 = (registry.catalog_sha256 if registry and registry.catalog_sha256 else catalog_digest(catalog))
    automatic = list(registry.automatic_mappings_json or []) if registry else []
    if codes and not automatic:
        from app.services.rail_station_mapping import automatic_station_mappings
        automatic = automatic_station_mappings(codes, places)
    manual_raw = list(registry.manual_mappings_json or []) if registry else []
    effective = effective_station_mappings(codes, places, automatic, manual_raw)
    return registry, codes, places, catalog_sha256, automatic, manual_raw, effective



async def persisted_mapping_context(session):
    """export는 저장된 registry만 읽고 자동 이름 매칭을 재실행하지 않는다."""
    row = (await session.execute(select(
        KricStationMappingRegistry.catalog_sha256,
        KricStationMappingRegistry.automatic_mappings_json,
        KricStationMappingRegistry.manual_mappings_json,
    ).where(KricStationMappingRegistry.id == 1))).one_or_none()
    automatic = list(row.automatic_mappings_json or []) if row else []
    manual = list(row.manual_mappings_json or []) if row else []
    if len(automatic) > 10000 or len(manual) > 10000:
        raise ValueError("저장된 mapping registry가 export 상한을 초과했습니다")
    def index(items):
        result = {}
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("저장된 mapping registry가 유효하지 않습니다")
            key = tuple(str(item.get(field, "")) for field in ("operator_code", "line_code", "station_code"))
            if not all(key) or key in result:
                raise ValueError("저장된 mapping code가 누락·중복되었습니다")
            result[key] = item
        return result
    return {"automatic": index(automatic), "manual": index(manual),
            "revision": mapping_revision(row.catalog_sha256 if row else None, automatic, manual)}


async def persisted_station_links(session, ids, context):
    """active FK와 registry를 같은 RR에서 검증한다. 시각표·provider는 읽지 않는다."""
    rows = (await session.execute(select(
        KricStationCode.rail_station_id, KricStationCode.operator_code, KricStationCode.line_code,
        KricStationCode.station_code, KricStationCode.station_name, KricStationCode.last_seen_at,
        RailStationReference.identity_key,
    ).join(RailStationReference, KricStationCode.rail_station_id == RailStationReference.id)
        .where(KricStationCode.active.is_(True), KricStationCode.rail_station_id.in_(ids)))).all()
    result = {}
    for row in rows:
        key = (row.operator_code, row.line_code, row.station_code)
        manual = context["manual"].get(key)
        automatic = context["automatic"].get(key)
        mapping = manual or automatic
        method = "persisted"
        if mapping:
            if mapping.get("rail_station_identity_key") != row.identity_key:
                raise ValueError("저장된 FK와 mapping registry 대상이 일치하지 않습니다")
            method = "manual" if manual else automatic.get("match_method", "automatic")
        if row.rail_station_id in result:
            raise ValueError("같은 역사에 active code가 중복되었습니다")
        result[row.rail_station_id] = {"operator_code": row.operator_code, "line_code": row.line_code,
                                      "station_code": row.station_code, "code_station_name": row.station_name,
                                      "code_collected_at": row.last_seen_at, "mapping_method": method}
    return result
