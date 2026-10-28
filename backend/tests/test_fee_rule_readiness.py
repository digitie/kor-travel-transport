from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import delete, select

from app.core.config import Settings
from app.models import Airport, ParkingFeeRule, ParkingLot
from app.services.collection import CollectionService, FixturePublicDataClient
from app.services.fee_rules import select_fee_rules
from app.services.parsers import ParsedFeeRule


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
