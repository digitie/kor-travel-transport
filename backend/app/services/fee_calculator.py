from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from math import ceil
from zoneinfo import ZoneInfo


@dataclass(slots=True)
class CalculatedFee:
    total_fee: int
    breakdown: list[dict[str, int | str]]


def resolve_day_type(
    value: datetime,
    tz_name: str = "Asia/Seoul",
    *,
    holiday_dates: frozenset[date] = frozenset(),
    holiday_weekdays: frozenset[int] = frozenset({5, 6}),
) -> str:
    local = value.astimezone(ZoneInfo(tz_name))
    return "holiday" if local.weekday() in holiday_weekdays or local.date() in holiday_dates else "weekday"


def calculate_total_fee(
    entry_at: datetime,
    exit_at: datetime,
    rules: list[object],
    tz_name: str = "Asia/Seoul",
    *,
    holiday_dates: frozenset[date] = frozenset(),
    holiday_weekdays: frozenset[int] = frozenset({5, 6}),
    grace_minutes: int | None = None,
) -> CalculatedFee:
    if entry_at.tzinfo is None or exit_at.tzinfo is None:
        raise ValueError("입출차 시각에는 시간대가 필요합니다.")
    if exit_at <= entry_at:
        raise ValueError("출차 시각은 입차 시각보다 늦어야 합니다.")

    rules_by_day_type = {rule.day_type: rule for rule in rules}
    if "weekday" not in rules_by_day_type or "holiday" not in rules_by_day_type:
        raise ValueError("평일/휴일 요금 규칙이 모두 필요합니다.")

    total_fee = 0
    breakdown: list[dict[str, int | str]] = []

    # 1일은 입차 시각부터 24시간이다. 기본요금/무료 회차는 최초 입차에만
    # 적용하고, 다음 24시간의 잔여 체류에는 추가 단위요금부터 적용한다.
    first_day_type = resolve_day_type(entry_at, tz_name, holiday_dates=holiday_dates, holiday_weekdays=holiday_weekdays)
    first_rule = rules_by_day_type[first_day_type]
    free_minutes = first_rule.free_minutes if grace_minutes is None else grace_minutes
    is_free_visit = (exit_at - entry_at).total_seconds() <= free_minutes * 60
    chunk_start = entry_at
    while chunk_start < exit_at:
        chunk_end = min(chunk_start + timedelta(hours=24), exit_at)
        day_type = resolve_day_type(chunk_start, tz_name, holiday_dates=holiday_dates, holiday_weekdays=holiday_weekdays)
        rule = rules_by_day_type[day_type]
        if rule.basic_minutes <= 0 or rule.unit_minutes <= 0 or min(rule.basic_fee, rule.unit_fee, rule.daily_max_fee) < 0:
            raise ValueError("요금 규칙의 시간 또는 금액이 올바르지 않습니다.")
        duration_minutes = max(1, ceil((chunk_end - chunk_start).total_seconds() / 60))

        if is_free_visit:
            fee = 0
        elif chunk_start == entry_at:
            fee = rule.basic_fee
            remaining = max(0, duration_minutes - rule.basic_minutes)
            if remaining:
                fee += ceil(remaining / max(rule.unit_minutes, 1)) * rule.unit_fee
            if rule.daily_max_fee > 0:
                fee = min(fee, rule.daily_max_fee)
        else:
            fee = ceil(duration_minutes / rule.unit_minutes) * rule.unit_fee
            if rule.daily_max_fee > 0:
                fee = min(fee, rule.daily_max_fee)

        total_fee += fee
        breakdown.append(
            {
                "date": chunk_start.astimezone(ZoneInfo(tz_name)).date().isoformat(),
                "day_type": rule.day_type,
                "duration_minutes": duration_minutes,
                "applied_fee": fee,
            }
        )
        chunk_start = chunk_end

    return CalculatedFee(total_fee=total_fee, breakdown=breakdown)

