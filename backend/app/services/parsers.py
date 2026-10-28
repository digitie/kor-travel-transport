from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from xml.etree import ElementTree

from app.core.time_utils import combine_korean_timestamp, now_utc, to_utc


KAC_AIRPORT_CODE_TO_NAMES = {
    "CJJ": {"청주국제공항", "CHEONGJU INTERNATIONAL AIRPORT"},
    "CJU": {"제주국제공항", "JEJU INTERNATIONAL AIRPORT"},
    "GMP": {"김포국제공항", "GIMPO INTERNATIONAL AIRPORT"},
    "HIN": {"사천공항", "SACHEON AIRPORT"},
    "KUV": {"군산공항", "GUNSAN AIRPORT"},
    "KWJ": {"광주공항", "GWANGJU AIRPORT"},
    "MWX": {"무안국제공항", "MUAN INTERNATIONAL AIRPORT"},
    "PUS": {"김해국제공항", "GIMHAE INTERNATIONAL AIRPORT"},
    "RSU": {"여수공항", "YEOSU AIRPORT"},
    "TAE": {"대구국제공항", "DAEGU INTERNATIONAL AIRPORT"},
    "USN": {"울산공항", "ULSAN AIRPORT"},
    "WJU": {"원주공항", "WONJU AIRPORT"},
    "YNY": {"양양국제공항", "YANGYANG INTERNATIONAL AIRPORT"},
}

KAC_AIRPORT_NAME_TO_CODE = {
    name.strip().upper(): code
    for code, names in KAC_AIRPORT_CODE_TO_NAMES.items()
    for name in names
}

KAC_LOT_NAME_NORMALIZATION = {
    "CJU": {
        "P1주차장": "P1 주차장",
        "P2장기주차장": "P2 장기주차장",
        "화물주차장": "화물터미널주차장",
    },
    "GMP": {
        "국제선 지하": "국제선 지하주차장",
        "화물청사": "화물청사주차장",
    },
    "PUS": {
        "P3 여객(화물)": "P3 여객(화물)주차장",
    },
}

KAC_LOT_SOURCE_IDS = {
    "CJU": {
        "P1 주차장": "cju-p1",
        "P2 장기주차장": "cju-p2",
        "화물터미널주차장": "cju-cargo",
    },
    "GMP": {
        "국내선 제1주차장": "gmp-domestic-1",
        "국내선 제2주차장": "gmp-domestic-2",
        "국제선 지하주차장": "gmp-international-underground",
        "국제선 주차빌딩": "gmp-international-building",
        "화물청사주차장": "gmp-cargo",
    },
    "PUS": {
        "P1 여객주차장": "pus-p1",
        "P2 여객주차장": "pus-p2",
        "P3 여객(화물)주차장": "pus-p3",
    },
}

INCHEON_FEE_PROFILES = [
    {
        "fee_id": "FB00000001",
        "max_id": "NF00000001",
        "lot_prefixes": ["T1 단기주차장", "T2 단기주차장"],
    },
    {
        "fee_id": "FB00000002",
        "max_id": "NF00000002",
        "lot_prefixes": ["T1 장기주차장", "T2 장기주차장"],
    },
    {
        "fee_id": "FB00000003",
        "max_id": "NF00000003",
        "lot_prefixes": ["T1 예약주차장", "T2 예약주차장"],
    },
]

TIME_AMOUNT_PATTERN = re.compile(r"(\d{2}):(\d{2})")
WON_AMOUNT_PATTERN = re.compile(r"([\d,]+)원")


@dataclass(slots=True)
class ParsedParkingObservation:
    source: str
    airport_code: str
    airport_name_ko: str
    airport_name_en: str | None
    lot_id: str
    lot_name: str
    terminal: str | None
    category: str | None
    observed_at: datetime
    occupied_spaces: int
    total_spaces: int
    congestion_label: str | None
    congestion_ratio: float | None
    raw_item: dict[str, Any]


@dataclass(slots=True)
class ParsedFeeRule:
    airport_code: str
    airport_name: str
    parking_lot_name: str | None
    vehicle_size: str
    day_type: str
    free_minutes: int
    basic_minutes: int
    basic_fee: int
    unit_minutes: int
    unit_fee: int
    daily_max_fee: int
    source_updated_at: datetime
    raw_item: dict[str, Any]


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip().replace(",", "")
    if text == "":
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace("%", "")
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _slug_lot_id(prefix: str, name: str) -> str:
    normalized = "".join(char.lower() if char.isalnum() else "-" for char in name)
    return f"{prefix}-{normalized}".strip("-")


def _json_items(document: dict[str, Any]) -> list[dict[str, Any]]:
    items = document.get("response", {}).get("body", {}).get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def _classify_incheon_lot_category(lot_name: str) -> str:
    if "예약" in lot_name:
        return "reserved"
    if "장기" in lot_name:
        return "long"
    if "화물" in lot_name:
        return "cargo"
    if "단기" in lot_name:
        return "short"
    return "incheon"


def _parse_hhmm_duration(text: str) -> int:
    match = TIME_AMOUNT_PATTERN.search(text)
    if match is None:
        return 0
    return int(match.group(1)) * 60 + int(match.group(2))


def _parse_won_amount(text: str) -> int:
    match = WON_AMOUNT_PATTERN.search(text)
    if match is None:
        return 0
    return _safe_int(match.group(1))


def _parse_incheon_fee_updated_at(items: list[dict[str, Any]]) -> datetime:
    for item in items:
        timestamp_text = str(item.get("datetime") or "").strip()
        if len(timestamp_text) >= 12:
            return to_utc(datetime.strptime(timestamp_text[:12], "%Y%m%d%H%M"))
    return now_utc()


def _xml_items(xml_text: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml_text)
    items: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        items.append({child.tag: (child.text or "").strip() for child in item})
    return items


def _resolve_kac_airport_code(name_ko: str | None, name_en: str | None) -> str | None:
    for candidate in (name_ko, name_en):
        normalized = (candidate or "").strip().upper()
        if normalized in KAC_AIRPORT_NAME_TO_CODE:
            return KAC_AIRPORT_NAME_TO_CODE[normalized]
    return None


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.split())


def normalize_kac_lot_name(airport_code: str, lot_name: str) -> str:
    normalized = _normalize_whitespace(lot_name)
    return KAC_LOT_NAME_NORMALIZATION.get(airport_code, {}).get(normalized, normalized)


def _kac_source_lot_id(airport_code: str, lot_name: str) -> str:
    return KAC_LOT_SOURCE_IDS.get(airport_code, {}).get(lot_name, _slug_lot_id(airport_code.lower(), lot_name))


def parse_kac_congestion(xml_text: str, airport_code: str) -> list[ParsedParkingObservation]:
    observations: list[ParsedParkingObservation] = []
    for item in _xml_items(xml_text):
        lot_name = item.get("parkingAirportCodeName") or item.get("parkingName") or "주차장"
        total_spaces = _safe_int(item.get("parkingTotalSpace"))
        occupied_spaces = _safe_int(item.get("parkingOccupiedSpace"))
        observations.append(
            ParsedParkingObservation(
                source="kac_congestion",
                airport_code=airport_code,
                airport_name_ko=item.get("airportKor") or airport_code,
                airport_name_en=item.get("airportEng"),
                lot_id=_slug_lot_id(airport_code.lower(), lot_name),
                lot_name=lot_name,
                terminal=None,
                category=None,
                observed_at=combine_korean_timestamp(item.get("sysGetdate"), item.get("sysGettime")),
                occupied_spaces=occupied_spaces,
                total_spaces=total_spaces,
                congestion_label=item.get("parkingCongestion"),
                congestion_ratio=_safe_float(item.get("parkingCongestionDegree")),
                raw_item=item,
            )
        )
    return observations


def _coerce_kac_items(payload: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept either literal upstream XML text or a pre-extracted item list.

    `python-krairport-api`'s `kac_raw_items()` already parses XML into flat
    `{tag: text}` dicts, so a krairport-backed fetch hands us
    `SourceResponse.body_text` as a JSON-serialized list instead of XML.
    """

    if isinstance(payload, list):
        return [
            {key: (value.strip() if isinstance(value, str) else value) for key, value in item.items()}
            for item in payload
        ]
    stripped = payload.strip()
    if stripped.startswith("["):
        return _coerce_kac_items(json.loads(payload))
    return _xml_items(payload)


def parse_kac_parking(
    payload: str | list[dict[str, Any]],
    allowed_airport_codes: list[str] | None = None,
) -> list[ParsedParkingObservation]:
    observations: list[ParsedParkingObservation] = []
    allowed = {code.upper() for code in allowed_airport_codes} if allowed_airport_codes else None
    for item in _coerce_kac_items(payload):
        airport_code = _resolve_kac_airport_code(item.get("aprKor"), item.get("aprEng"))
        if airport_code is None:
            continue
        if allowed is not None and airport_code not in allowed:
            continue

        lot_name = normalize_kac_lot_name(
            airport_code,
            item.get("parkingAirportCodeName") or item.get("parkingName") or "주차장",
        )
        total_spaces = _safe_int(item.get("parkingFullSpace"))
        occupied_spaces = _safe_int(item.get("parkingIstay"))
        congestion_ratio = round((occupied_spaces / total_spaces) * 100, 1) if total_spaces > 0 else None
        observations.append(
            ParsedParkingObservation(
                source="kac_parking",
                airport_code=airport_code,
                airport_name_ko=item.get("aprKor") or airport_code,
                airport_name_en=item.get("aprEng"),
                lot_id=_kac_source_lot_id(airport_code, lot_name),
                lot_name=lot_name,
                terminal=None,
                category=None,
                observed_at=combine_korean_timestamp(
                    (item.get("parkingGetdate") or "").replace("-", ""),
                    (item.get("parkingGettime") or "").replace(":", ""),
                ),
                occupied_spaces=occupied_spaces,
                total_spaces=total_spaces,
                congestion_label=None,
                congestion_ratio=congestion_ratio,
                raw_item=item,
            )
        )
    return observations


def _coerce_incheon_items(payload: str | dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Accept literal upstream JSON text/envelope, or a pre-extracted item list.

    `python-krairport-api`'s `iiac_raw_items()` already parses the JSON
    envelope into a flat item list, so a krairport-backed fetch hands us
    `SourceResponse.body_text` as a JSON-serialized list instead of the
    original `{"response": {"body": {"items": ...}}}` envelope.
    """

    document = json.loads(payload) if isinstance(payload, str) else payload
    return document if isinstance(document, list) else _json_items(document)


def parse_incheon_parking(
    payload: str | dict[str, Any] | list[dict[str, Any]],
) -> list[ParsedParkingObservation]:
    items = _coerce_incheon_items(payload)

    observations: list[ParsedParkingObservation] = []
    for item in items:
        lot_name = item.get("floor") or "인천공항 주차장"
        observed_text = str(item.get("datetm") or "")
        observed_at = now_utc()
        if observed_text:
            normalized = observed_text.replace("-", "").replace(":", "").replace(" ", "")
            if len(normalized) >= 12:
                observed_at = to_utc(datetime.strptime(normalized[:12], "%Y%m%d%H%M"))

        observations.append(
            ParsedParkingObservation(
                source="incheon_parking",
                airport_code="ICN",
                airport_name_ko="인천국제공항",
                airport_name_en="Incheon International Airport",
                lot_id=_slug_lot_id("icn", lot_name),
                lot_name=lot_name,
                terminal="T2" if "T2" in lot_name.upper() else "T1",
                category=_classify_incheon_lot_category(lot_name),
                observed_at=observed_at,
                occupied_spaces=_safe_int(item.get("parking")),
                total_spaces=_safe_int(item.get("parkingarea")),
                congestion_label=None,
                congestion_ratio=None,
                raw_item=item,
            )
        )
    return observations


def _build_incheon_fee_rule(
    profile: dict[str, Any],
    descriptions_by_id: dict[str, list[str]],
    source_updated_at: datetime,
    lot_prefix: str,
    vehicle_size: str,
    day_type: str,
    raw_item: dict[str, Any],
) -> ParsedFeeRule | None:
    fee_descriptions = descriptions_by_id.get(str(profile["fee_id"]), [])
    max_descriptions = descriptions_by_id.get(str(profile["max_id"]), [])
    if not fee_descriptions:
        return None

    basic_description = next((description for description in fee_descriptions if description.startswith("최초")), "")
    unit_description = next((description for description in fee_descriptions if "초과" in description), "")

    if basic_description:
        basic_minutes = _parse_hhmm_duration(basic_description)
        basic_fee = _parse_won_amount(basic_description)
        unit_minutes = _parse_hhmm_duration(unit_description) or basic_minutes
        unit_fee = _parse_won_amount(unit_description)
    else:
        unit_minutes = _parse_hhmm_duration(unit_description)
        unit_fee = _parse_won_amount(unit_description)
        basic_minutes = unit_minutes
        basic_fee = unit_fee

    if basic_minutes <= 0 or basic_fee <= 0:
        return None

    return ParsedFeeRule(
        airport_code="ICN",
        airport_name="인천국제공항",
        parking_lot_name=lot_prefix,
        vehicle_size=vehicle_size,
        day_type=day_type,
        free_minutes=0,
        basic_minutes=basic_minutes,
        basic_fee=basic_fee,
        unit_minutes=max(1, unit_minutes or basic_minutes),
        unit_fee=unit_fee,
        daily_max_fee=_parse_won_amount(max_descriptions[0]) if max_descriptions else 0,
        source_updated_at=source_updated_at,
        raw_item=raw_item,
    )


def parse_incheon_fee(payload: str | dict[str, Any] | list[dict[str, Any]]) -> list[ParsedFeeRule]:
    items = _coerce_incheon_items(payload)
    descriptions_by_id: dict[str, list[str]] = {}
    raw_by_id: dict[str, list[dict[str, Any]]] = {}

    for item in items:
        char_id = str(item.get("charid") or "").strip()
        description = str(item.get("chardesc") or "").strip()
        if not char_id or not description:
            continue
        descriptions_by_id.setdefault(char_id, []).append(description)
        raw_by_id.setdefault(char_id, []).append(item)

    source_updated_at = _parse_incheon_fee_updated_at(items)
    rules: list[ParsedFeeRule] = []
    for profile in INCHEON_FEE_PROFILES:
        raw_item = {
            "fee_id": profile["fee_id"],
            "max_id": profile["max_id"],
            "fee_items": raw_by_id.get(str(profile["fee_id"]), []),
            "max_items": raw_by_id.get(str(profile["max_id"]), []),
        }
        for lot_prefix in profile["lot_prefixes"]:
            # 이 charid 요금표는 소형 단기/장기/예약 주차장만 제공한다.
            # 같은 금액을 대형차 규칙으로 복제하지 않는다.
            for vehicle_size in ("small",):
                for day_type in ("weekday", "holiday"):
                    rule = _build_incheon_fee_rule(
                        profile,
                        descriptions_by_id,
                        source_updated_at,
                        lot_prefix,
                        vehicle_size,
                        day_type,
                        raw_item,
                    )
                    if rule is not None:
                        rules.append(rule)
    return rules


def _append_fee_rule(
    target: list[ParsedFeeRule],
    item: dict[str, str],
    airport_code: str,
    vehicle_size: str,
    day_type: str,
    basic_account_key: str,
    basic_minutes_key: str,
    free_minutes_key: str,
    unit_fee_key: str,
    unit_minutes_key: str,
    max_fee_key: str,
) -> None:
    if basic_account_key not in item and unit_fee_key not in item:
        return

    rule = ParsedFeeRule(
        airport_code=airport_code,
        airport_name=item.get("siteName", airport_code),
        parking_lot_name=item.get("parkingParkingName"),
        vehicle_size=vehicle_size,
        day_type=day_type,
        free_minutes=_safe_int(item.get(free_minutes_key)),
        basic_minutes=_safe_int(item.get(basic_minutes_key)),
        basic_fee=_safe_int(item.get(basic_account_key)),
        unit_minutes=max(1, _safe_int(item.get(unit_minutes_key), 1)),
        unit_fee=_safe_int(item.get(unit_fee_key)),
        daily_max_fee=_safe_int(item.get(max_fee_key)),
        source_updated_at=now_utc(),
        raw_item=item,
    )
    target.append(rule)


def parse_kac_fee(payload: str | list[dict[str, Any]], airport_code: str) -> list[ParsedFeeRule]:
    """Parse `AirportParkingFee/parkingfee` items.

    Field names below (`parkingBasicM`, `parkingMaxAccount`, `siteName`, ...)
    are camelCase as confirmed against the live endpoint. An earlier version
    of this parser assumed `PARKING_BASIC_M`-style SCREAMING_SNAKE_CASE names
    that never matched any real response, so KAC fee collection had always
    silently produced zero rules in `live` mode (`_append_fee_rule`'s
    early-return guard skips a rule when neither key is present).
    """

    rules: list[ParsedFeeRule] = []
    for item in _coerce_kac_items(payload):
        _append_fee_rule(
            rules,
            item,
            airport_code,
            "small",
            "weekday",
            "parkingBasicAccount",
            "parkingBasicM",
            "parkingFreeM",
            "parkingMinuteAccount",
            "parkingMinuteM",
            "parkingMaxAccount",
        )
        _append_fee_rule(
            rules,
            item,
            airport_code,
            "small",
            "holiday",
            "parkingHoliBasicAccount",
            "parkingHoliBasicM",
            "parkingHoliFreeM",
            "parkingHoliMinuteAccount",
            "parkingHoliMinuteM",
            "parkingHoliMaxAccount",
        )
        _append_fee_rule(
            rules,
            item,
            airport_code,
            "large",
            "weekday",
            "parkingBasicAccountd",
            "parkingBasicMd",
            "parkingFreeMd",
            "parkingMinuteAccountd",
            "parkingMinuteMd",
            "parkingMaxAccountd",
        )
        _append_fee_rule(
            rules,
            item,
            airport_code,
            "large",
            "holiday",
            "parkingHoliBasicAccountd",
            "parkingHoliBasicMd",
            "parkingHoliFreeMd",
            "parkingHoliMinuteAccountd",
            "parkingHoliMinuteMd",
            "parkingHoliMaxAccountd",
        )
    return rules
