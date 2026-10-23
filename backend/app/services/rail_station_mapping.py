"""KRIC 역 코드 카탈로그와 이름 차이 연결 규칙."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select, text
from app.models import KricStationCode, KricStationMappingRegistry, RailStationReference

RAIL_STATION_REFERENCE_LOCK_KEY = 420054


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
    code_name_counts = Counter(source_key(row) for row in code_rows)
    code_number_name_counts = Counter(
        (str(row.station_code).strip(), normalized_station_name(row.station_name))
        for row in code_rows
    )
    places_by_source_name: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    places_by_number_name: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for place in place_rows:
        places_by_source_name[source_key(place)].append(place)
        number = str(place.station_number or "").strip()
        name = normalized_station_name(place.station_name)
        if number and name:
            places_by_number_name[(number, name)].append(place)

    exact: dict[tuple[str, str, str], Any] = {}
    for row in code_rows:
        key = source_key(row)
        candidates = places_by_source_name.get(key, [])
        if code_name_counts[key] == 1 and len(candidates) == 1:
            exact[provider_key(row)] = candidates[0]
    exact_targets = {str(place.identity_key) for place in exact.values()}

    by_number: dict[tuple[str, str, str], Any] = {}
    for row in code_rows:
        code = provider_key(row)
        if code in exact:
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
