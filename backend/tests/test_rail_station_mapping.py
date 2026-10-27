import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.services.rail_station_mapping import (
    automatic_station_mappings,
    catalog_digest,
    effective_station_mappings,
    lock_rail_station_reference_catalog,
    mapping_revision,
    normalized_station_name,
    reference_catalog_digest,
    station_catalog,
    validate_manual_mappings,
)


def test_reference_catalog_lock_is_postgresql_transaction_scoped_and_shared():
    async def exercise():
        postgres = SimpleNamespace(
            bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
            execute=AsyncMock(),
        )
        await lock_rail_station_reference_catalog(postgres)
        statement, params = postgres.execute.await_args.args
        assert str(statement) == "SELECT pg_advisory_xact_lock(:lock_key)"
        assert params == {"lock_key": 420054}

        sqlite = SimpleNamespace(
            bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
            execute=AsyncMock(),
        )
        await lock_rail_station_reference_catalog(sqlite)
        sqlite.execute.assert_not_awaited()

    asyncio.run(exercise())


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


def test_mapping_revision_does_not_depend_on_provider_row_order():
    first = {"operator_code": "O1", "line_code": "L1", "station_code": "S1",
        "rail_station_identity_key": "line|one", "match_method": "exact_identity"}
    second = {"operator_code": "O2", "line_code": "L2", "station_code": "S2",
        "rail_station_identity_key": "line|two", "match_method": "station_number_and_name"}
    assert mapping_revision("a" * 64, [first, second], []) == mapping_revision("a" * 64, [second, first], [])


def test_reference_catalog_digest_is_order_independent_and_tracks_mapping_identity():
    first = place("rail|first", "001", "서울역")
    second = place("rail|second", "002", "시청역")
    assert reference_catalog_digest([first, second]) == reference_catalog_digest([second, first])
    renamed = place("rail|second", "002", "시청역(개명)")
    assert reference_catalog_digest([first, second]) != reference_catalog_digest([first, renamed])


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


def test_gyeongui_jungang_composite_alias_preserves_observed_number_and_source():
    official = code("KR", "K4", "P313", "서울역", line_name="경의중앙")
    official.rail_operator_name = "한국철도공사"
    reference = place("코레일|경의중앙선|1251|서울역", "1251", "서울역",
        line="경의중앙선", operator="코레일")
    official.raw = {"RAIL_OPR_ISTT_NM": "한국철도공사", "LN_NM": "경의중앙", "STIN_CD": "P313"}
    reference.raw_item_json = {"철도운영기관명": "코레일", "운영노선": "경의중앙선", "역 번호": "1251"}
    before = deepcopy((vars(official), vars(reference)))

    assert automatic_station_mappings([official], [reference]) == [{
        "operator_code": "KR", "line_code": "K4", "station_code": "P313",
        "rail_station_identity_key": reference.identity_key, "match_method": "exact_identity",
    }]
    assert (vars(official), vars(reference)) == before


@pytest.mark.parametrize(("operator_code", "line_code"), [("S1", "K4"), ("KR", "1"), ("AR", "A1")])
@pytest.mark.parametrize(("operator_name", "line_name"), [("한국철도공사", "경의중앙"), ("코레일", "경의중앙선")])
def test_gyeongui_jungang_alias_does_not_expand_to_other_official_code_lines(
    operator_code, line_code, operator_name, line_name,
):
    official = code(operator_code, line_code, "P313", "서울역", line_name=line_name)
    official.rail_operator_name = operator_name
    reference = place("rail|gyeongui-seoul", "1251", "서울역", line="경의중앙선", operator="코레일")
    assert automatic_station_mappings([official], [reference]) == []


@pytest.mark.parametrize("duplicate_side", ["code", "place"])
@pytest.mark.parametrize("reverse", [False, True])
def test_gyeongui_jungang_alias_rejects_duplicates_after_normalization(duplicate_side, reverse):
    first = code("KR", "K4", "P313", "서울역", line_name="경의중앙")
    first.rail_operator_name = "한국철도공사"
    codes = [first]
    places = [place("rail|one", "1251", "서울역", line="경의중앙선", operator="코레일")]
    if duplicate_side == "code":
        second = code("KR", "K4", "P314", "서울역", line_name="경의중앙선")
        second.rail_operator_name = "코레일"
        codes.append(second)
    else:
        places.append(place("rail|two", "9999", "서울역", line="경의중앙", operator="한국철도공사"))
    if reverse:
        codes.reverse()
        places.reverse()
    assert automatic_station_mappings(codes, places) == []


@pytest.mark.parametrize("duplicate_side", ["code", "place"])
def test_gyeongui_jungang_ambiguous_alias_cannot_fall_back_to_matching_number(duplicate_side):
    first = code("KR", "K4", "P313", "서울역", line_name="경의중앙")
    first.rail_operator_name = "한국철도공사"
    codes = [first]
    places = [place("rail|one", "P313", "서울역", line="경의중앙선", operator="코레일")]
    if duplicate_side == "code":
        second = code("KR", "K4", "P314", "서울역", line_name="경의중앙선")
        second.rail_operator_name = "코레일"
        codes.append(second)
    else:
        places.append(place("rail|two", "1251", "서울역", line="경의중앙", operator="한국철도공사"))
    assert automatic_station_mappings(codes, places) == []


def test_number_fallback_for_unaliased_composites_remains_available():
    codes = [code("OP", "L1", "001", "서울역"), code("OP", "L1", "002", "서울역")]
    reference = place("rail|one", "001", "서울역")
    assert automatic_station_mappings(codes, [reference]) == [{
        "operator_code": "OP", "line_code": "L1", "station_code": "001",
        "rail_station_identity_key": reference.identity_key, "match_method": "station_number_and_name",
    }]


def test_gyeongui_jungang_alias_keeps_other_lines_name_number_and_manual_guards():
    official = code("KR", "K4", "P313", "서울역", line_name="경의중앙")
    official.rail_operator_name = "한국철도공사"
    reference = place("rail|gyeongui-seoul", "1251", "서울역", line="경의중앙선", operator="코레일")
    airport = code("AR", "A1", "A01", "서울역(공항철도)", line_name="공항")
    airport.rail_operator_name = "공항철도주식회사"
    airport_place = place("rail|airport-seoul", "A01", "서울역", line="공항철도선", operator="공항철도")
    codes, places = [official, airport], [reference, airport_place]
    automatic = automatic_station_mappings(codes, places)
    assert [(row["station_code"], row["rail_station_identity_key"], row["match_method"]) for row in automatic] == [
        ("P313", "rail|gyeongui-seoul", "exact_identity"),
        ("A01", "rail|airport-seoul", "station_number_and_name"),
    ]
    manual = validate_manual_mappings([{
        "operator_code": "AR", "line_code": "A1", "station_code": "A01",
        "rail_station_identity_key": reference.identity_key,
    }], {("KR", "K4", "P313"), ("AR", "A1", "A01")})
    assert effective_station_mappings(codes, places, automatic, manual) == {
        ("AR", "A1", "A01"): (reference.identity_key, "manual"),
    }
    # 역명 정규화는 기존 번호 분기에서만 허용한다. 별칭이 역명만으로 연결을 늘리지 않는다.
    different_name = place("rail|different-name", "1251", "서울", line="경의중앙선", operator="코레일")
    other_line = place("rail|other-line", "1251", "서울역", line="경부선", operator="코레일")
    assert automatic_station_mappings([official], [different_name, other_line]) == []


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
