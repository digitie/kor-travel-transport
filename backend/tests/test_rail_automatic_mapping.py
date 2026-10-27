"""자동 재계산의 순수 후보. DB·provider·수집 실행은 사용하지 않는다."""
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas import KricAutomaticMappingApplyRequest
from app.services.rail_station_mapping import (
    AutomaticMappingInputError,
    build_automatic_mapping_plan,
    catalog_digest,
    station_catalog,
)

NOW = datetime(2026, 10, 27, 9, tzinfo=UTC)


def code(number, name, *, key=("OP", "L1"), operator="운영사", line="노선", place_id=None):
    return SimpleNamespace(operator_code=key[0], line_code=key[1], station_code=number,
        operator_name=operator, line_name=line, station_name=name, active=True, rail_station_id=place_id)


def place(row_id, identity, number, name, *, operator="운영사", line="노선"):
    return SimpleNamespace(id=row_id, identity_key=identity, station_number=number, station_name=name,
        rail_operator_name=operator, operating_line_name=line)


def mapping(station, target, *, method="exact_identity"):
    return {"operator_code": station.operator_code, "line_code": station.line_code,
        "station_code": station.station_code, "rail_station_identity_key": target,
        "match_method": method}


def registry(codes, *, automatic=None, manual=None):
    catalog = station_catalog(codes)
    return SimpleNamespace(catalog_json=catalog, catalog_sha256=catalog_digest(catalog),
        automatic_mappings_json=automatic or [], manual_mappings_json=manual or [])


def plan(source, codes, places):
    return build_automatic_mapping_plan(source, codes, places, generated_at=NOW)


def test_preview_recalculates_cached_array_without_changing_raw_manual_or_fk():
    seoul = code("P313", "서울역", key=("KR", "K4"), operator="한국철도공사", line="경의중앙")
    manual_code = code("M1", "수동 코드", place_id=2)
    refs = [place(823, "코레일|경의중앙선|1251|서울역", "1251", "서울역", operator="코레일", line="경의중앙선"),
        place(2, "manual|station", "999", "수동 기준 역"),
        place(99, "unused", "900", "장소만 있는 역", operator="별도 기관", line="다른 노선")]
    raw_manual = [{**mapping(manual_code, "manual|station"), "note": "  원문\n보존 🙂  ",
        "legacy_metadata": {"source": "기존 항목"}}]
    source = registry([seoul, manual_code], manual=raw_manual)
    before = deepcopy((vars(source), [vars(row) for row in [seoul, manual_code]], [vars(row) for row in refs]))

    result = plan(source, [seoul, manual_code], refs)

    assert result.preview.before.station_count == 2  # 장소 수가 아닌 공식 코드 수다.
    assert result.preview.before.manual_mapped_count == result.preview.after.manual_mapped_count == 1
    assert result.preview.before.automatic_mapped_count == 0
    assert result.preview.after.automatic_mapped_count == 1
    assert result.preview.before.unmatched_count == 1 and result.preview.after.unmatched_count == 0
    assert result.preview.can_apply and result.preview.has_changes
    assert result.link_updates == {("KR", "K4", "P313"): 823}
    assert result.preview.changes[0].change_type == "added"
    assert result.preview.expected_revision != result.preview.candidate_revision
    assert (vars(source), [vars(row) for row in [seoul, manual_code]], [vars(row) for row in refs]) == before


def test_preview_reports_removal_retarget_and_preserves_unrelated_links_outside_alias():
    moved = code("001", "새역", place_id=1)
    removed = code("002", "자동 불가", place_id=3)
    retained = code("003", "보존역", place_id=4)
    codes = [moved, removed, retained]
    refs = [place(1, "old", "900", "이전역"), place(2, "new", "901", "새역"),
        place(3, "removed", "902", "이전 연결"), place(4, "retained", "903", "보존역")]
    source = registry(codes, automatic=[mapping(moved, "old"), mapping(removed, "removed"), mapping(retained, "retained")])

    result = plan(source, codes, refs)

    assert result.preview.can_apply  # KR/K4 밖 변경을 영구 차단하지 않는다.
    assert result.link_updates == {("OP", "L1", "001"): 2, ("OP", "L1", "002"): None}
    assert [row.change_type for row in result.preview.changes] == ["retargeted", "removed"]
    assert result.preview.before.mapped_count == 3 and result.preview.after.mapped_count == 2
    assert all(row.station_code != "003" for row in result.preview.changes)


def test_preview_keeps_manual_target_priority_and_exposes_suppressed_candidate():
    automatic_code = code("001", "자동역")
    manual_code = code("M1", "수동역", place_id=1)
    refs = [place(1, "reserved", "001", "자동역")]
    source = registry([automatic_code, manual_code], manual=[{**mapping(manual_code, "reserved"), "note": "근거"}])

    result = plan(source, [automatic_code, manual_code], refs)

    assert result.preview.can_apply and result.preview.has_changes
    assert result.preview.before.manual_mapped_count == result.preview.after.manual_mapped_count == 1
    assert result.preview.after.automatic_mapped_count == 0 and result.preview.after.unmatched_count == 1
    assert result.link_updates == {}
    assert result.preview.manual_conflicts[0].reason == "manual_target_reserved"
    assert result.preview.manual_conflicts[0].reserved_by.station_code == "M1"


def test_noop_and_row_order_preserve_revisions_and_write_set():
    first, second = code("001", "하나", place_id=1), code("002", "둘", place_id=2)
    refs = [place(1, "one", "001", "하나"), place(2, "two", "002", "둘")]
    source = registry([first, second], automatic=[mapping(first, "one"), mapping(second, "two")])
    result = plan(source, [first, second], refs)
    reversed_result = plan(source, [second, first], list(reversed(refs)))

    assert result.preview == reversed_result.preview
    assert result.preview.can_apply and not result.preview.has_changes
    assert result.preview.expected_revision == result.preview.candidate_revision
    assert not result.link_updates and not result.preview.changes


def test_actual_fk_disagreement_is_visible_and_not_silently_repaired():
    station = code("001", "역", place_id=None)
    refs = [place(1, "one", "001", "역")]
    source = registry([station], automatic=[mapping(station, "one")])

    result = plan(source, [station], refs)

    assert not result.preview.can_apply
    assert result.preview.blockers[0].code == "persisted_link_mismatch"
    assert station.rail_station_id is None


def test_raw_note_is_part_of_both_revision_fingerprints_without_normalization():
    station = code("M1", "수동", place_id=1)
    refs = [place(1, "one", "999", "기준")]
    first = registry([station], manual=[{**mapping(station, "one"), "note": " 근거 "}])
    second = registry([station], manual=[{**mapping(station, "one"), "note": "근거"}])
    before, after = plan(first, [station], refs), plan(second, [station], refs)
    assert before.preview.expected_revision != after.preview.expected_revision
    assert before.preview.candidate_revision != after.preview.candidate_revision
    assert first.manual_mappings_json[0]["note"] == " 근거 "


def test_stored_catalog_mismatch_is_rejected_without_fetching_anything():
    station = code("001", "역")
    source = registry([station])
    source.catalog_json[0]["station_name"] = "다른 catalog"
    with pytest.raises(AutomaticMappingInputError, match="catalog"):
        plan(source, [station], [place(1, "one", "001", "역")])


def test_apply_wire_accepts_only_two_hashes_and_rejects_manual_round_trip():
    payload = {"expected_revision": "a" * 64, "candidate_revision": "b" * 64}
    assert KricAutomaticMappingApplyRequest(**payload).model_dump() == payload
    with pytest.raises(ValidationError):
        KricAutomaticMappingApplyRequest(**payload, mappings=[])


def test_match_method_change_updates_registry_without_rewriting_the_same_fk():
    station = code("001", "역", place_id=1)
    refs = [place(1, "one", "001", "역")]
    source = registry([station], automatic=[mapping(station, "one", method="station_number_and_name")])
    result = plan(source, [station], refs)
    assert result.preview.has_changes and result.preview.can_apply
    assert result.preview.changes[0].change_type == "method_changed"
    assert result.preview.before == result.preview.after
    assert not result.link_updates


def test_swap_is_planned_as_two_changed_pairs_without_mutating_either_fk():
    first, second = code("001", "역B", place_id=1), code("002", "역A", place_id=2)
    refs = [place(1, "a", "900", "역A"), place(2, "b", "901", "역B")]
    source = registry([first, second], automatic=[mapping(first, "a"), mapping(second, "b")])
    result = plan(source, [first, second], refs)
    assert result.preview.can_apply
    assert result.link_updates == {("OP", "L1", "001"): 2, ("OP", "L1", "002"): 1}
    assert first.rail_station_id == 1 and second.rail_station_id == 2


def test_inactive_code_cannot_silently_surrender_a_candidate_target():
    active, inactive = code("001", "역"), code("old", "퇴역", place_id=1)
    inactive.active = False
    refs = [place(1, "one", "001", "역")]
    result = plan(registry([active]), [active, inactive], refs)
    assert result.preview.before.station_count == result.preview.after.station_count == 1
    assert not result.preview.can_apply
    assert result.preview.blockers[0].code == "inactive_target_occupied"
