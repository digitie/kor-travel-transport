from __future__ import annotations

import json

import pytest

from app.services.parsers import (
    parse_incheon_fee,
    parse_incheon_parking,
    parse_kac_congestion,
    parse_kac_fee,
    parse_kac_parking,
)


def test_parse_kac_congestion(fixtures_dir) -> None:
    xml_text = (fixtures_dir / "kac_congestion_gmp.xml").read_text(encoding="utf-8")
    parsed = parse_kac_congestion(xml_text, "GMP")

    assert len(parsed) == 2
    assert parsed[0].airport_code == "GMP"
    assert parsed[0].lot_name == "국내선 제1주차장"
    assert parsed[0].occupied_spaces == 482
    assert parsed[0].total_spaces == 510


def test_parse_kac_parking(fixtures_dir) -> None:
    xml_text = (fixtures_dir / "kac_parking_rt.xml").read_text(encoding="utf-8")
    parsed = parse_kac_parking(xml_text, allowed_airport_codes=["PUS", "CJU"])

    assert len(parsed) == 2
    assert {item.airport_code for item in parsed} == {"PUS", "CJU"}
    assert next(item for item in parsed if item.airport_code == "PUS").lot_name == "P3 여객(화물)주차장"
    assert next(item for item in parsed if item.airport_code == "PUS").lot_id == "pus-p3"
    assert next(item for item in parsed if item.airport_code == "CJU").lot_name == "P1 주차장"
    assert next(item for item in parsed if item.airport_code == "CJU").lot_id == "cju-p1"
    assert next(item for item in parsed if item.airport_code == "PUS").congestion_ratio == 92.1


def test_parse_incheon_parking(fixtures_dir) -> None:
    payload = json.loads((fixtures_dir / "incheon_parking.json").read_text(encoding="utf-8"))
    parsed = parse_incheon_parking(payload)

    assert len(parsed) == 2
    assert parsed[0].airport_code == "ICN"
    assert parsed[0].lot_name == "T1 단기주차장"
    assert parsed[1].total_spaces == 910


def test_parse_incheon_parking_accepts_live_timestamp_shape() -> None:
    parsed = parse_incheon_parking(
        {
            "response": {
                "body": {
                    "items": [
                        {
                            "floor": "T1 단기주차장지하1층",
                            "parking": "276",
                            "parkingarea": "378",
                            "datetm": "20260509060956.000",
                        }
                    ]
                }
            }
        }
    )

    assert parsed[0].lot_name == "T1 단기주차장지하1층"
    assert parsed[0].category == "short"
    assert parsed[0].observed_at.isoformat() == "2026-05-08T21:09:00+00:00"


def test_parse_incheon_fee_builds_short_and_long_rules() -> None:
    parsed = parse_incheon_fee(
        {
            "response": {
                "body": {
                    "items": [
                        {"charid": "FB00000001", "chardesc": "최초 00:30 에 한해 1200원 적용", "datetime": "202605080630"},
                        {"charid": "FB00000001", "chardesc": "00:15 초과 시 600원 부과", "datetime": "202605080630"},
                        {"charid": "FB00000002", "chardesc": "01:00 초과 시 1000원 부과", "datetime": "202605080630"},
                        {"charid": "NF00000001", "chardesc": "일일 최대 24000원 적용", "datetime": "202605080630"},
                        {"charid": "NF00000002", "chardesc": "일일 최대 9000원 적용", "datetime": "202605080630"},
                    ]
                }
            }
        }
    )

    short_rule = next(rule for rule in parsed if rule.parking_lot_name == "T1 단기주차장" and rule.day_type == "weekday")
    long_rule = next(rule for rule in parsed if rule.parking_lot_name == "T1 장기주차장" and rule.day_type == "weekday")
    assert short_rule.basic_minutes == 30
    assert short_rule.basic_fee == 1200
    assert short_rule.unit_minutes == 15
    assert short_rule.unit_fee == 600
    assert short_rule.daily_max_fee == 24000
    assert long_rule.basic_minutes == 60
    assert long_rule.basic_fee == 1000
    assert long_rule.daily_max_fee == 9000
    assert {rule.vehicle_size for rule in parsed} == {"small"}


def test_parse_kac_fee(fixtures_dir) -> None:
    xml_text = (fixtures_dir / "kac_fee_gmp.xml").read_text(encoding="utf-8")
    parsed = parse_kac_fee(xml_text, "GMP")

    assert len(parsed) == 4
    assert {rule.day_type for rule in parsed} == {"weekday", "holiday"}
    assert {rule.vehicle_size for rule in parsed} == {"small", "large"}
    assert next(rule for rule in parsed if rule.vehicle_size == "small" and rule.day_type == "weekday").basic_fee == 1000


# The following list-input tests exercise the path `KrairportPublicDataClient`
# actually uses in production: krairport's `kac_raw_items()`/`iiac_raw_items()`
# already extract items into a `list[dict]`, so `SourceResponse.body_text` is a
# JSON-serialized list rather than literal upstream XML/JSON envelope text.
# Field shapes below are taken from a live smoke test against the real KAC/IIAC
# APIs (T-030) -- not invented.


def test_parse_kac_parking_accepts_pre_extracted_item_list() -> None:
    items = [
        {
            "aprEng": "GIMPO INTERNATIONAL AIRPORT",
            "aprKor": "김포국제공항",
            "parkingAirportCodeName": "국내선 제1주차장",
            "parkingFullSpace": "2279",
            "parkingGetdate": "2026-04-25",
            "parkingGettime": "09:20:03",
            "parkingIincnt": "1813",
            "parkingIoutcnt": "1507",
            "parkingIstay": "2046",
        }
    ]

    parsed = parse_kac_parking(items, allowed_airport_codes=["GMP"])

    assert len(parsed) == 1
    assert parsed[0].airport_code == "GMP"
    assert parsed[0].lot_name == "국내선 제1주차장"
    assert parsed[0].total_spaces == 2279
    assert parsed[0].occupied_spaces == 2046

    assert parse_kac_parking(json.dumps(items), allowed_airport_codes=["GMP"]) == parsed


def test_parse_kac_fee_accepts_pre_extracted_item_list() -> None:
    items = [
        {
            "siteName": "김포국제공항",
            "parkingParkingName": "국내선 제1주차장",
            "parkingBasicAccount": "1000",
            "parkingBasicM": "30",
            "parkingFreeM": "30",
            "parkingMinuteAccount": "500",
            "parkingMinuteM": "15",
            "parkingMaxAccount": "20000",
            "parkingHoliBasicAccount": "1500",
            "parkingHoliBasicM": "30",
            "parkingHoliFreeM": "30",
            "parkingHoliMinuteAccount": "700",
            "parkingHoliMinuteM": "15",
            "parkingHoliMaxAccount": "25000",
            "parkingBasicAccountd": "1200",
            "parkingBasicMd": "30",
            "parkingFreeMd": "30",
            "parkingMinuteAccountd": "600",
            "parkingMinuteMd": "15",
            "parkingMaxAccountd": "25000",
            "parkingHoliBasicAccountd": "1800",
            "parkingHoliBasicMd": "30",
            "parkingHoliFreeMd": "30",
            "parkingHoliMinuteAccountd": "800",
            "parkingHoliMinuteMd": "15",
            "parkingHoliMaxAccountd": "30000",
        }
    ]

    parsed = parse_kac_fee(items, "GMP")

    assert len(parsed) == 4
    small_weekday = next(rule for rule in parsed if rule.vehicle_size == "small" and rule.day_type == "weekday")
    assert small_weekday.airport_name == "김포국제공항"
    assert small_weekday.parking_lot_name == "국내선 제1주차장"
    assert small_weekday.basic_fee == 1000
    assert small_weekday.unit_fee == 500
    assert small_weekday.daily_max_fee == 20000

    # `source_updated_at` is `now_utc()` at parse time for KAC fee rules, so
    # compare everything except that field rather than full dataclass equality.
    from_json = parse_kac_fee(json.dumps(items), "GMP")
    assert [(r.airport_code, r.vehicle_size, r.day_type, r.basic_fee, r.unit_fee, r.daily_max_fee) for r in from_json] == [
        (r.airport_code, r.vehicle_size, r.day_type, r.basic_fee, r.unit_fee, r.daily_max_fee) for r in parsed
    ]


def test_parse_incheon_parking_accepts_pre_extracted_item_list() -> None:
    items = [
        {"floor": "T1 단기주차장", "parking": "575", "parkingarea": "640", "datetm": "2026-04-25 09:20"},
    ]

    parsed = parse_incheon_parking(items)

    assert len(parsed) == 1
    assert parsed[0].lot_name == "T1 단기주차장"
    assert parsed[0].occupied_spaces == 575
    assert parsed[0].total_spaces == 640

    assert parse_incheon_parking(json.dumps(items)) == parsed


def test_parse_incheon_fee_accepts_pre_extracted_item_list() -> None:
    items = [
        {"charid": "FB00000001", "chardesc": "최초 00:30 에 한해 1200원 적용", "datetime": "202605080630"},
        {"charid": "FB00000001", "chardesc": "00:15 초과 시 600원 부과", "datetime": "202605080630"},
        {"charid": "NF00000001", "chardesc": "일일 최대 24000원 적용", "datetime": "202605080630"},
    ]

    parsed = parse_incheon_fee(items)

    short_rule = next(rule for rule in parsed if rule.parking_lot_name == "T1 단기주차장" and rule.day_type == "weekday")
    assert short_rule.basic_fee == 1200
    assert short_rule.unit_fee == 600
    assert short_rule.daily_max_fee == 24000

    assert parse_incheon_fee(json.dumps(items)) == parsed


@pytest.mark.parametrize("maximum", [None, "요금 안내 확인", "일일 최대 0원 적용"])
def test_parse_incheon_fee_rejects_missing_or_invalid_daily_cap(maximum) -> None:
    items = [{"charid": "FB00000002", "chardesc": "01:00 초과 시 1000원 부과"}]
    if maximum is not None:
        items.append({"charid": "NF00000002", "chardesc": maximum})
    with pytest.raises(ValueError, match="일 최대요금"):
        parse_incheon_fee(items)


def test_parse_incheon_fee_rejects_missing_unit_instead_of_a_flat_basic_fee() -> None:
    with pytest.raises(ValueError, match="추가 단위"):
        parse_incheon_fee([
            {"charid": "FB00000001", "chardesc": "최초 00:30 에 한해 1200원 적용"},
            {"charid": "NF00000001", "chardesc": "일일 최대 24000원 적용"},
        ])
