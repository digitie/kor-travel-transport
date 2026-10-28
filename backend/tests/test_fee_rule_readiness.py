from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory
from app.models import Airport, Base, CollectionRun, ParkingFeeRule, ParkingLot, ParkingSnapshot, RawApiResponse
from app.services.collection import CollectionService, FixturePublicDataClient, SourceResponse
from app.services.fee_rules import select_fee_rules
from app.services.parsers import ParsedFeeRule, parse_incheon_fee


def _selection_rule(lot_id, day_type="weekday", raw=None):
    return SimpleNamespace(parking_lot_id=lot_id, day_type=day_type, raw_item_json=raw)


def test_selection_never_uses_an_arbitrary_lot() -> None:
    selected, reason = select_fee_rules([_selection_rule(1), _selection_rule(2)], None)
    assert selected == []
    assert reason == "parking_lot_required"
    generic = _selection_rule(None)
    exact = _selection_rule(1)
    assert select_fee_rules([generic, exact, _selection_rule(2)], 1) == ([exact], None)


def test_legacy_unmatched_named_rule_is_not_a_generic_fallback() -> None:
    unsafe = _selection_rule(None, raw={"parkingParkingName": "매칭하지 못한 주차장"})
    assert select_fee_rules([unsafe], 2) == ([], None)
    assert select_fee_rules([_selection_rule(None, raw={"fee_id": "FB00000001"})], 2) == ([], None)


def _scope(client, airport_code="GMP"):
    async def read():
        async with client.app.state.session_factory() as session:
            airport = await session.scalar(select(Airport).where(Airport.code == airport_code))
            lots = list((await session.execute(select(ParkingLot).where(ParkingLot.airport_id == airport.id).order_by(ParkingLot.id))).scalars())
            return airport.id, [(lot.id, lot.name) for lot in lots]
    return asyncio.run(read())


def _payload(lot_id, **changes):
    payload = {"airport_code": "GMP", "parking_lot_id": lot_id, "vehicle_size": "small",
        "entry_at": "2026-04-24T09:00:00+09:00", "exit_at": "2026-04-24T11:00:00+09:00"}
    return payload | changes


def test_fee_api_requires_a_lot_when_prices_are_lot_specific(client) -> None:
    response = client.post("/v1/fees/calculate", json=_payload(None))
    assert response.status_code == 200
    assert response.json()["reason_code"] == "parking_lot_required"
    assert response.json()["total_fee"] is None


def test_fee_api_friday_has_rule_provenance(client) -> None:
    _, lots = _scope(client)
    response = client.post("/v1/fees/calculate", json=_payload(lots[0][0]))
    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is True
    assert body["breakdown"][0]["day_type"] == "holiday"
    assert body["rule_updated_at"]
    assert body["official_url"].startswith("https://www.airport.co.kr/gimpo/")
    assert "할인은 반영하지" in body["message"]


def test_fee_api_incomplete_rules_and_disabled_collection_are_explained(client) -> None:
    airport_id, lots = _scope(client)
    async def remove(day_type=None):
        async with client.app.state.session_factory() as session:
            query = delete(ParkingFeeRule).where(ParkingFeeRule.airport_id == airport_id)
            if day_type:
                query = query.where(ParkingFeeRule.day_type == day_type)
            await session.execute(query)
            await session.commit()
    asyncio.run(remove("holiday"))
    body = client.post("/v1/fees/calculate", json=_payload(lots[0][0])).json()
    assert body["supported"] is False
    assert body["reason_code"] == "incomplete_rules"
    asyncio.run(remove())
    body = client.post("/v1/fees/calculate", json=_payload(lots[0][0])).json()
    assert body["reason_code"] == "collection_disabled"


def test_fee_api_rejects_naive_time_and_wrong_airport_lot(client) -> None:
    _, lots = _scope(client, "ICN")
    assert client.post("/v1/fees/calculate", json=_payload(lots[0][0])).status_code == 404
    assert client.post("/v1/fees/calculate", json=_payload(None,
        entry_at="2026-04-24T09:00:00", exit_at="2026-04-24T11:00:00")).status_code == 422


def test_icn_large_tariff_is_not_fabricated_from_small_car_fee(client) -> None:
    _, lots = _scope(client, "ICN")
    response = client.post("/v1/fees/calculate", json=_payload(lots[0][0], airport_code="ICN", vehicle_size="large"))
    assert response.status_code == 200
    assert response.json()["supported"] is False
    assert response.json()["total_fee"] is None


def test_named_fee_storage_does_not_pollute_airport_generic_rules(client) -> None:
    airport_id, lots = _scope(client)
    async def store():
        async with client.app.state.session_factory() as session:
            await session.execute(delete(ParkingFeeRule).where(ParkingFeeRule.airport_id == airport_id))
            now = datetime.now(timezone.utc)
            rule = ParsedFeeRule("GMP", "김포국제공항", "없는 주차장", "small", "weekday",
                10, 30, 1000, 15, 500, 20000, now, {})
            service = CollectionService(Settings(use_sample_client_when_no_key=True), client=FixturePublicDataClient())
            assert await service._store_fee_rules(session, [rule]) == 0
            rule.parking_lot_name = None
            assert await service._store_fee_rules(session, [rule]) == 1
            rows = list((await session.execute(select(ParkingFeeRule).where(ParkingFeeRule.airport_id == airport_id))).scalars())
            assert len(rows) == 1 and rows[0].parking_lot_id is None
    asyncio.run(store())


def test_gmp_live_fee_names_attach_to_the_correct_current_lots(client) -> None:
    airport_id, lots = _scope(client)
    async def store():
        async with client.app.state.session_factory() as session:
            await session.execute(delete(ParkingFeeRule).where(ParkingFeeRule.airport_id == airport_id))
            rule = ParsedFeeRule("GMP", "김포국제공항", "국제선 주차장", "small", "weekday",
                10, 30, 1000, 15, 500, 20000, datetime.now(timezone.utc), {})
            service = CollectionService(Settings(use_sample_client_when_no_key=True), client=FixturePublicDataClient())
            assert await service._store_fee_rules(session, [rule]) == 2
            rows = list((await session.execute(select(ParkingFeeRule).where(ParkingFeeRule.airport_id == airport_id))).scalars())
            assert {row.parking_lot_id for row in rows} == {lot_id for lot_id, name in lots if name.startswith("국제선")}
            assert all(row.parking_lot_id is not None for row in rows)
    asyncio.run(store())


def test_icn_tariff_uses_terminal_and_category_for_live_long_and_reserved_names(client) -> None:
    airport_id, _ = _scope(client, "ICN")
    async def store():
        async with client.app.state.session_factory() as session:
            await session.execute(delete(ParkingFeeRule).where(ParkingFeeRule.airport_id == airport_id))
            now = datetime.now(timezone.utc)
            lots = [ParkingLot(airport_id=airport_id, source_lot_id=f"icn-fee-test-{index}", name=name,
                terminal=terminal, category=category, is_active=True, created_at=now, updated_at=now)
                for index, (name, terminal, category) in enumerate([
                    ("T1 장기 P1 주차장", "T1", "long"),
                    ("T1 장기 P2 주차타워", "T1", "long"),
                    ("T1 P5 예약주차장", "T1", "reserved"),
                    ("T2 P1 장기주차타워", "T2", "long"),
                ])]
            session.add_all(lots)
            await session.flush()
            service = CollectionService(Settings(use_sample_client_when_no_key=True), client=FixturePublicDataClient())
            rules = [ParsedFeeRule("ICN", "인천국제공항", name, "small", "weekday",
                10, 60, 1000, 60, 1000, 9000, now, {"fee_id": "test"})
                for name in ("T1 장기주차장", "T1 예약주차장")]
            stored = await service._store_fee_rules(session, rules)
            rows = list((await session.execute(select(ParkingFeeRule).where(ParkingFeeRule.airport_id == airport_id))).scalars())
            # seed에 있던 같은 터미널·종류의 lot도 올바르게 함께 연결한다.
            actual_ids = {row.parking_lot_id for row in rows}
            assert {lot.id for lot in lots[:3]} <= actual_ids
            assert lots[3].id not in actual_ids
            assert stored == len(actual_ids)
            assert all(row.parking_lot_id is not None for row in rows)
    asyncio.run(store())


@pytest.mark.parametrize("include_matched", [False, True])
def test_collection_reports_all_or_partial_unmatched_fee_rules(client, include_matched) -> None:
    airport_id, lots = _scope(client)
    now = datetime.now(timezone.utc)
    names = ["연결되지 않은 주차장"] + ([lots[0][1]] if include_matched else [])
    rules = [ParsedFeeRule("GMP", "김포국제공항", name, "small", day,
        10, 30, 1000, 15, 500, 20000, now, {"parkingParkingName": name})
        for name in names for day in ("weekday", "holiday")]

    class FeeClient(FixturePublicDataClient):
        async def fetch_kac_fee(self, airport_code):
            return SourceResponse("kac_fee", "http://openapi.airport.co.kr/service/rest/AirportParkingFee/parkingfee",
                {"schAirportCode": airport_code}, 200, "[]", fee_rules=rules)

    async def collect():
        service = CollectionService(Settings(data_go_kr_service_key=None, use_sample_client_when_no_key=True,
            enable_scheduler=False, enable_fee_collection=True, enable_incheon_collection=False,
            enable_incheon_fee_collection=False, airport_codes_csv="GMP"), client=FeeClient())
        async with client.app.state.session_factory() as session:
            summary = await service.collect(session, trigger="test")
        async with client.app.state.session_factory() as session:
            run = await session.get(CollectionRun, summary["collection_run_id"])
            assert run.status == summary["status"]
            assert run.error_message and "주차장에 연결하지 못해" in run.error_message
            assert not list((await session.execute(select(ParkingFeeRule).where(
                ParkingFeeRule.airport_id == airport_id, ParkingFeeRule.parking_lot_id.is_(None),
            ))).scalars())
        return summary

    summary = asyncio.run(collect())
    assert summary["status"] == "partial_success"
    assert summary["snapshot_count"] > 0
    assert summary["fee_rule_count"] == (2 if include_matched else 0)
    assert len(summary["errors"]) == 1
    assert "GMP" in summary["errors"][0] and "2개" in summary["errors"][0]


def test_fee_updates_count_applied_rules_without_duplicate_rows(client) -> None:
    airport_id, lots = _scope(client)
    async def update():
        async with client.app.state.session_factory() as session:
            rule = ParsedFeeRule("GMP", "김포국제공항", lots[0][1], "small", "weekday",
                10, 30, 1100, 15, 500, 20000, datetime.now(timezone.utc), {})
            errors: list[str] = []
            service = CollectionService(Settings(use_sample_client_when_no_key=True), client=FixturePublicDataClient())
            assert await service._store_fee_rules(session, [rule], errors=errors) == 1
            assert await service._store_fee_rules(session, [rule], errors=errors) == 1
            rows = list((await session.execute(select(ParkingFeeRule).where(
                ParkingFeeRule.airport_id == airport_id, ParkingFeeRule.parking_lot_id == lots[0][0],
                ParkingFeeRule.vehicle_size == "small", ParkingFeeRule.day_type == "weekday",
            ))).scalars())
            assert len(rows) == 1 and rows[0].basic_fee == 1100
            assert errors == []
    asyncio.run(update())


def test_legacy_icn_zero_cap_is_unavailable_instead_of_an_uncapped_quote(client) -> None:
    airport_id, lots = _scope(client, "ICN")
    lot_id = next(lot_id for lot_id, name in lots if "장기" in name)
    async def damage():
        async with client.app.state.session_factory() as session:
            rules = list((await session.execute(select(ParkingFeeRule).where(
                ParkingFeeRule.airport_id == airport_id, ParkingFeeRule.parking_lot_id == lot_id,
                ParkingFeeRule.vehicle_size == "small",
            ))).scalars())
            assert len(rules) == 2
            for rule in rules:
                rule.daily_max_fee = 0
                rule.raw_item_json = {"fee_id": "FB00000002", "max_id": "NF00000002", "max_items": []}
            await session.commit()
    asyncio.run(damage())
    response = client.post("/v1/fees/calculate", json=_payload(lot_id, airport_code="ICN",
        entry_at="2026-11-05T09:00:00+09:00", exit_at="2026-11-06T09:00:00+09:00"))
    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is False and body["total_fee"] is None
    assert body["reason_code"] == "incomplete_rules"
    assert "일 최대요금" in body["message"]


def test_observed_gmp_four_tariff_names_cover_all_five_public_lots(tmp_path) -> None:
    """기존 공개 DTO의 실제 다섯 lot를 격리 DB에만 재현한다."""
    async def store():
        engine, factory = create_engine_and_session_factory(f"sqlite+aiosqlite:///{tmp_path / 'gmp.sqlite3'}")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[
                    Airport.__table__, ParkingLot.__table__, ParkingFeeRule.__table__,
                ]))
            async with factory() as session:
                now = datetime.now(timezone.utc)
                airport = Airport(code="GMP", name_ko="김포국제공항", source="kac", created_at=now, updated_at=now)
                session.add(airport)
                await session.flush()
                lots = [ParkingLot(airport_id=airport.id, source_lot_id=source_id, name=name,
                    is_active=True, created_at=now, updated_at=now) for source_id, name in [
                        ("gmp-domestic-1", "국내선 제1주차장"), ("gmp-domestic-2", "국내선 제2주차장"),
                        ("gmp-international-underground", "국제선 지하주차장"),
                        ("gmp-international-building", "국제선 주차빌딩"), ("gmp-cargo", "화물청사주차장"),
                    ]]
                session.add_all(lots)
                await session.flush()
                rules = [ParsedFeeRule("GMP", "김포국제공항", name, "small", day,
                    10, 30, 1000, 15, 500, 20000 if day == "weekday" else 30000, now,
                    {"parkingParkingName": name}) for name in [
                        "국내선 제1주차장", "국제선 주차장", "화물청사 주차장", "국내선 제2주차장(일반/예약)",
                    ] for day in ("weekday", "holiday")]
                service = CollectionService(Settings(use_sample_client_when_no_key=True), client=FixturePublicDataClient())
                errors: list[str] = []
                assert await service._store_fee_rules(session, rules, errors=errors) == 10
                assert await service._store_fee_rules(session, rules, errors=errors) == 10
                rows = list((await session.execute(select(ParkingFeeRule))).scalars())
                assert len(rows) == 10 and errors == []
                assert {row.parking_lot_id for row in rows} == {lot.id for lot in lots}
                assert all({row.day_type for row in rows if row.parking_lot_id == lot.id}
                    == {"weekday", "holiday"} for lot in lots)
        finally:
            await engine.dispose()
    asyncio.run(store())


@pytest.mark.parametrize("valid_maximum", [False, True])
def test_incheon_fee_parse_is_source_isolated_and_not_repeated(client, valid_maximum) -> None:
    items = [{"charid": "FB00000002", "chardesc": "01:00 초과 시 1000원 부과"}]
    if valid_maximum:
        items.append({"charid": "NF00000002", "chardesc": "일일 최대 9000원 적용"})
    body = json.dumps(items)

    class IncheonFeeClient(FixturePublicDataClient):
        async def fetch_incheon_fee(self):
            response = await super().fetch_incheon_fee()
            response.body_text = body
            return response

    settings = Settings(data_go_kr_service_key=None, use_sample_client_when_no_key=True,
        enable_scheduler=False, enable_fee_collection=False, enable_incheon_collection=False,
        enable_incheon_fee_collection=True, airport_codes_csv="GMP,ICN")

    async def collect():
        async with client.app.state.session_factory() as session:
            summary = await CollectionService(settings, client=IncheonFeeClient()).collect(session, trigger="test")
        async with client.app.state.session_factory() as session:
            run_id = summary["collection_run_id"]
            raw = await session.scalar(select(RawApiResponse).where(
                RawApiResponse.collection_run_id == run_id, RawApiResponse.source == "incheon_fee",
            ))
            assert raw is not None and raw.body_text == body
            run = await session.get(CollectionRun, run_id)
            assert run.status == summary["status"]
            stored_snapshots = await session.scalar(select(func.count()).select_from(ParkingSnapshot).where(
                ParkingSnapshot.collection_run_id == run_id,
            ))
            assert stored_snapshots == summary["snapshot_count"] > 0
            if valid_maximum:
                assert raw.parse_status != "failed" and raw.parse_error is None
                airport = await session.scalar(select(Airport).where(Airport.code == "ICN"))
                long_lot_ids = set((await session.execute(select(ParkingLot.id).where(
                    ParkingLot.airport_id == airport.id, ParkingLot.category == "long",
                ))).scalars())
                rules = list((await session.execute(select(ParkingFeeRule).where(
                    ParkingFeeRule.parking_lot_id.in_(long_lot_ids), ParkingFeeRule.vehicle_size == "small",
                ))).scalars())
                assert summary["fee_rule_count"] == len(rules) == len(long_lot_ids) * 2 > 0
                assert all(rule.daily_max_fee == 9000 for rule in rules)
            else:
                assert raw.parse_status == "failed" and "일 최대요금" in raw.parse_error
                assert "일 최대요금" in run.error_message
        return summary

    with patch("app.services.collection.parse_incheon_fee", wraps=parse_incheon_fee) as parser:
        summary = asyncio.run(collect())
    assert parser.call_count == 1
    assert summary["status"] == ("success" if valid_maximum else "partial_success")
    assert bool(summary["errors"]) is not valid_maximum
    if not valid_maximum:
        assert summary["fee_rule_count"] == 0


def test_fee_database_write_failure_still_rolls_back_collection(client) -> None:
    settings = Settings(data_go_kr_service_key=None, use_sample_client_when_no_key=True,
        enable_scheduler=False, enable_fee_collection=False, enable_incheon_collection=False,
        enable_incheon_fee_collection=True, airport_codes_csv="GMP,ICN")
    service = CollectionService(settings, client=FixturePublicDataClient())

    async def collect():
        async with client.app.state.session_factory() as session:
            before = await session.scalar(select(func.count()).select_from(ParkingSnapshot))
        async with client.app.state.session_factory() as session:
            with patch.object(service, "_store_fee_rules", side_effect=IntegrityError("fee update", {}, RuntimeError("test write failure"))):
                with pytest.raises(IntegrityError):
                    await service.collect(session, trigger="test")
        async with client.app.state.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == before
            run = await session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
            assert run.status == "failed" and "test write failure" in run.error_message
    asyncio.run(collect())
