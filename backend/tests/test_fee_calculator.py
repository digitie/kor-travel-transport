from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.fee_calculator import calculate_total_fee
from app.services.parsers import ParsedFeeRule


def _rule(vehicle_size: str, day_type: str, basic_fee: int, unit_fee: int, daily_max_fee: int) -> ParsedFeeRule:
    return ParsedFeeRule(
        airport_code="GMP",
        airport_name="김포국제공항",
        parking_lot_name="국내선 제1주차장",
        vehicle_size=vehicle_size,
        day_type=day_type,
        free_minutes=30,
        basic_minutes=30,
        basic_fee=basic_fee,
        unit_minutes=15,
        unit_fee=unit_fee,
        daily_max_fee=daily_max_fee,
        source_updated_at=datetime.now(tz=ZoneInfo("UTC")),
        raw_item={},
    )


def test_calculate_total_fee_weekday() -> None:
    entry_at = datetime(2026, 4, 24, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    exit_at = datetime(2026, 4, 24, 11, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    result = calculate_total_fee(
        entry_at,
        exit_at,
        [_rule("small", "weekday", 1000, 500, 20000), _rule("small", "holiday", 1500, 700, 25000)],
    )

    assert result.total_fee == 4000
    assert result.breakdown[0]["day_type"] == "weekday"


def test_calculate_total_fee_multi_day_cap() -> None:
    entry_at = datetime(2026, 4, 25, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    exit_at = datetime(2026, 4, 26, 13, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    result = calculate_total_fee(
        entry_at,
        exit_at,
        [_rule("small", "weekday", 1000, 500, 20000), _rule("small", "holiday", 1500, 700, 25000)],
    )

    assert result.total_fee == 33400
    assert len(result.breakdown) == 2


def test_midnight_does_not_restart_basic_charge() -> None:
    entry = datetime(2026, 4, 21, 23, 50, tzinfo=ZoneInfo("Asia/Seoul"))
    result = calculate_total_fee(entry, entry + timedelta(minutes=20), [
        _rule("small", "weekday", 1000, 500, 20000), _rule("small", "holiday", 1500, 700, 25000),
    ], grace_minutes=10)
    assert result.total_fee == 1000
    assert len(result.breakdown) == 1


def test_free_exit_is_grace_not_deducted_time() -> None:
    entry = datetime(2026, 4, 21, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    rules = [_rule("small", "weekday", 1000, 500, 20000), _rule("small", "holiday", 1500, 700, 25000)]
    assert calculate_total_fee(entry, entry + timedelta(minutes=10), rules, grace_minutes=10).total_fee == 0
    assert calculate_total_fee(entry, entry + timedelta(minutes=10, seconds=1), rules, grace_minutes=10).total_fee == 1000
    assert calculate_total_fee(entry, entry + timedelta(minutes=31), rules, grace_minutes=10).total_fee == 1500


def test_gmp_friday_and_public_holiday_use_holiday_rules() -> None:
    rules = [_rule("small", "weekday", 1000, 500, 20000), _rule("small", "holiday", 1500, 700, 25000)]
    for entry in (
        datetime(2026, 4, 24, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        datetime(2026, 5, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    ):
        result = calculate_total_fee(entry, entry + timedelta(minutes=31), rules,
            holiday_weekdays=frozenset({4, 5, 6}), holiday_dates=frozenset({date(2026, 5, 5)}), grace_minutes=10)
        assert result.total_fee == 2200
        assert result.breakdown[0]["day_type"] == "holiday"


def test_second_day_does_not_restart_basic_fee_or_free_grace() -> None:
    entry = datetime(2026, 11, 5, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    rules = [_rule("small", "weekday", 1000, 500, 20000), _rule("small", "holiday", 1000, 500, 30000)]
    result = calculate_total_fee(entry, entry + timedelta(days=1, minutes=5), rules,
        holiday_weekdays=frozenset({4, 5, 6}), grace_minutes=10)
    assert result.total_fee == 20500
    assert [line["applied_fee"] for line in result.breakdown] == [20000, 500]
