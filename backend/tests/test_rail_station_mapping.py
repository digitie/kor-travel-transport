from types import SimpleNamespace

import pytest
from app.services.rail_station_mapping import (
    automatic_station_mappings,
    catalog_digest,
    effective_station_mappings,
    normalized_station_name,
    station_catalog,
    validate_manual_mappings,
)


def code(operator: str, line: str, station: str, name: str, *, line_name: str = "1호선"):
    return SimpleNamespace(rail_operator_code=operator, rail_operator_name="운영사", line_code=line,
        line_name=line_name, station_code=station, station_name=name)


def place(identity: str, number: str, name: str, *, line: str = "1호선", operator: str = "운영사"):
    return SimpleNamespace(identity_key=identity, station_number=number, station_name=name,
        operating_line_name=line, rail_operator_name=operator)


def test_catalog_serializes_complete_kric_code_identity_and_source_labels():
    rows = [code("OP", "L1", "A01", "서울역")]
    catalog = station_catalog(rows)
    assert catalog == [{"operator_code": "OP", "operator_name": "운영사", "line_code": "L1",
        "line_name": "1호선", "station_code": "A01", "station_name": "서울역"}]
    assert len(catalog_digest(catalog)) == 64


@pytest.mark.parametrize(("value", "expected"), [
    ("동대문역사문화공원역", "동대문역사문화공원"),
    ("서울역 (공항철도)", "서울"),
    ("  서울 역 ", "서울"),
])
def test_station_name_normalization_is_conservative_for_code_join(value, expected):
    assert normalized_station_name(value) == expected


def test_automatic_mapping_prefers_exact_then_unique_station_number_and_normalized_name():
    codes = [code("OP", "L1", "001", "서울역"), code("OP", "L2", "A01", "서울역(공항철도)", line_name="공항철도")]
    places = [place("rail|seoul", "001", "서울역"), place("rail|airport-seoul", "A01", "서울역", line="공항철도", operator="공항철도")]
    result = automatic_station_mappings(codes, places)
    assert result == [
        {"operator_code": "OP", "line_code": "L1", "station_code": "001",
         "rail_station_identity_key": "rail|seoul", "match_method": "exact_identity"},
        {"operator_code": "OP", "line_code": "L2", "station_code": "A01",
         "rail_station_identity_key": "rail|airport-seoul", "match_method": "station_number_and_name"},
    ]


def test_automatic_mapping_rejects_ambiguous_code_and_name_only_matches():
    codes = [code("OP1", "L1", "001", "검암역"), code("OP2", "L2", "001", "검암역")]
    places = [place("rail|incheon2", "999", "검암역", line="인천2호선", operator="인천교통공사")]
    assert automatic_station_mappings(codes, places) == []


def test_manual_mapping_is_validated_and_overrides_automatic_without_double_booking():
    codes = [code("OP", "L1", "001", "첫역"), code("OP", "L2", "002", "둘역")]
    places = [place("rail|one", "001", "첫역"), place("rail|two", "002", "둘역")]
    automatic = automatic_station_mappings(codes, places)
    manual = validate_manual_mappings([{
        "operator_code": "OP", "line_code": "L2", "station_code": "002",
        "rail_station_identity_key": "rail|one", "note": "노선 코드 차이를 운영기관 자료로 확인",
    }], {("OP", "L1", "001"), ("OP", "L2", "002")})
    effective = effective_station_mappings(codes, places, automatic, manual)
    assert effective == {("OP", "L2", "002"): ("rail|one", "manual")}
    with pytest.raises(ValueError, match="여러 코드"):
        validate_manual_mappings([
            {"operator_code": "OP", "line_code": "L1", "station_code": "001", "rail_station_identity_key": "rail|two"},
            {"operator_code": "OP", "line_code": "L2", "station_code": "002", "rail_station_identity_key": "rail|two"},
        ], {("OP", "L1", "001"), ("OP", "L2", "002")})
