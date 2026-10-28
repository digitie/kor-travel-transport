from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import serialize_utc, to_seoul
from app.models import Airport, ParkingFeeRule, ParkingLot
from app.schemas import FeeCalculationRequest, FeeCalculationResponse
from app.services.fee_calculator import calculate_total_fee
from app.services.holidays import HolidayService


OFFICIAL_FEE_URLS = {
    "GMP": "https://www.airport.co.kr/gimpo/cms/frCon/index.do?CONTENTS_NO=2&MENU_ID=1360",
    "ICN": "https://www.airport.kr/ap_ko/969/subview.do",
    "PUS": "https://www.airport.co.kr/gimhae/cms/frCon/index.do?CONTENTS_NO=2&MENU_ID=190",
    "CJU": "https://www.airport.co.kr/jeju/cms/frCon/index.do?CONTENTS_NO=2&MENU_ID=120",
    "CJJ": "https://www.airport.co.kr/cheongju/cms/frCon/index.do?CONTENTS_NO=2&MENU_ID=170",
    "USN": "https://www.airport.co.kr/ulsan/cms/frCon/index.do?CONTENTS_NO=2&MENU_ID=180",
    "HIN": "https://www.airport.co.kr/sacheon/cms/frCon/index.do?CONTENTS_NO=2&MENU_ID=180",
    "RSU": "https://www.airport.co.kr/yeosu/cms/frCon/index.do?CONTENTS_NO=2&MENU_ID=180",
}


def select_fee_rules(rules: list[ParkingFeeRule], lot_id: int | None) -> tuple[list[ParkingFeeRule], str | None]:
    # 과거 수집기가 lot 이름 매칭 실패를 공통 규칙으로 저장한 행은 사용하지 않는다.
    generic = [rule for rule in rules if rule.parking_lot_id is None and not (
        (rule.raw_item_json or {}).get("parkingParkingName") or (rule.raw_item_json or {}).get("fee_id")
    )]
    if lot_id is not None:
        selected = generic + [rule for rule in rules if rule.parking_lot_id == lot_id]
    elif generic:
        selected = generic
    else:
        lots = {rule.parking_lot_id for rule in rules if rule.parking_lot_id is not None}
        if len(lots) > 1:
            return [], "parking_lot_required"
        selected = [rule for rule in rules if rule.parking_lot_id in lots]
    # lot별 규칙이 공통 규칙보다 우선한다.
    return list({rule.day_type: rule for rule in selected}.values()), None


async def quote_parking_fee(
    session: AsyncSession,
    airport: Airport,
    lot: ParkingLot | None,
    payload: FeeCalculationRequest,
    settings: Settings,
    holiday_service: HolidayService,
) -> FeeCalculationResponse:
    common = {
        "airport_code": airport.code,
        "parking_lot_id": payload.parking_lot_id,
        "vehicle_size": payload.vehicle_size,
        "official_url": OFFICIAL_FEE_URLS.get(airport.code),
    }

    def unavailable(code: str, message: str) -> FeeCalculationResponse:
        return FeeCalculationResponse(supported=False, reason_code=code, message=message, **common)

    if airport.code == "ICN" and payload.vehicle_size == "large":
        return unavailable("vehicle_unsupported", "인천 단기·장기·예약주차장의 대형차 요금은 제공되지 않습니다.")
    stored = list((await session.execute(select(ParkingFeeRule).where(
        ParkingFeeRule.airport_id == airport.id,
        ParkingFeeRule.vehicle_size == payload.vehicle_size,
    ).order_by(ParkingFeeRule.parking_lot_id.is_(None).desc(), ParkingFeeRule.id))).scalars().all())
    rules, selection_error = select_fee_rules(stored, payload.parking_lot_id)
    if selection_error:
        return unavailable(selection_error, "주차장별 요금이 다릅니다. 주차장을 선택해 주세요.")
    selected_lot_ids = {rule.parking_lot_id for rule in rules if rule.parking_lot_id is not None}
    if lot is None and len(selected_lot_ids) == 1:
        selected_lot_id = next(iter(selected_lot_ids))
        lot = await session.get(ParkingLot, selected_lot_id)
        common["parking_lot_id"] = selected_lot_id
    if not rules:
        enabled = settings.enable_incheon_fee_collection if airport.code == "ICN" else settings.enable_fee_collection
        return unavailable(
            "rules_unavailable" if enabled else "collection_disabled",
            "선택한 주차장·차량의 저장 요금 규칙이 없습니다."
            if enabled else "이 공항의 요금 수집이 꺼져 있고 선택한 주차장·차량의 저장 규칙이 없습니다.",
        )
    if {rule.day_type for rule in rules} != {"weekday", "holiday"}:
        return unavailable("incomplete_rules", "평일·휴일 요금 규칙이 완전하지 않아 계산할 수 없습니다.")
    if airport.code == "ICN" and any(
        rule.daily_max_fee <= 0 or rule.unit_minutes <= 0 or rule.unit_fee <= 0
        or rule.basic_minutes <= 0 or rule.basic_fee <= 0 for rule in rules
    ):
        return unavailable("incomplete_rules", "인천 주차장의 기본·추가·일 최대요금 규칙이 완전하지 않아 계산할 수 없습니다.")
    if airport.code not in OFFICIAL_FEE_URLS:
        return unavailable("policy_unverified", "이 공항의 무료 회차·일일 요금 적용 기준 확인이 필요합니다.")
    if airport.code == "CJJ" and payload.vehicle_size == "large" and (lot is None or "5" not in lot.name):
        return unavailable("vehicle_unsupported", "청주공항 대형차는 대형 전용 주차장을 선택해 주세요.")

    holiday_dates = frozenset()
    holiday_weekdays = frozenset({5, 6})
    sample = any((rule.raw_item_json or {}).get("seeded") is True for rule in rules)
    if airport.code in {"GMP", "PUS", "CJU"}:
        local_entry = to_seoul(payload.entry_at)
        start_date = local_entry.date()
        end_date = to_seoul(payload.exit_at - timedelta(microseconds=1)).date()
        calendar = await holiday_service.get_holidays(start_date, end_date)
        if calendar.status not in {"success", "sample"}:
            return unavailable("holiday_calendar_unavailable", "법정공휴일 정보를 확인하지 못해 정확한 요금을 계산할 수 없습니다.")
        sample = sample or calendar.status == "sample"
        holiday_dates = frozenset(item.local_date for item in calendar.items if item.is_holiday)
        holiday_weekdays = frozenset({4, 5, 6})
    else:
        # 공식적으로 매일 같은 요금인 공항은 휴일 API 장애에 의존하지 않는다.
        holiday_weekdays = frozenset()

    grace = 20 if airport.code == "PUS" and lot is not None and lot.name.startswith("P3") else 10

    try:
        calculated = calculate_total_fee(
            payload.entry_at, payload.exit_at, rules,
            holiday_dates=holiday_dates, holiday_weekdays=holiday_weekdays, grace_minutes=grace,
        )
    except ValueError:
        return unavailable("invalid_rules", "저장된 요금 규칙의 시간·금액을 확인해야 합니다.")
    return FeeCalculationResponse(
        supported=True,
        total_fee=calculated.total_fee,
        breakdown=calculated.breakdown,
        rule_updated_at=min(serialize_utc(rule.source_updated_at) for rule in rules),
        message="샘플 규칙으로 계산한 일반요금입니다. 할인은 반영하지 않았습니다."
        if sample else "저장된 공개 규칙으로 계산한 일반요금입니다. 할인은 반영하지 않았습니다.",
        **common,
    )
