from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


SEOUL_TZ = ZoneInfo("Asia/Seoul")
UTC_TZ = ZoneInfo("UTC")


def now_utc() -> datetime:
    return datetime.now(tz=UTC_TZ)


def ensure_tz(value: datetime, tz_name: str = "Asia/Seoul") -> datetime:
    if value.tzinfo is not None:
        return value
    return value.replace(tzinfo=ZoneInfo(tz_name))


def to_seoul(value: datetime) -> datetime:
    return ensure_tz(value).astimezone(SEOUL_TZ)


def seconds_until_next_seoul_midnight(value: datetime) -> int:
    """다음 Asia/Seoul 자정까지 남은 초(최소 1). KST 날짜로 초기화되는 일일 호출 상한의 Retry-After에 쓴다."""
    local = to_seoul(value)
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - local).total_seconds()))


def to_utc(value: datetime, default_tz: str = "Asia/Seoul") -> datetime:
    return ensure_tz(value, default_tz).astimezone(UTC_TZ)


def serialize_utc(value: datetime, default_tz: str = "UTC") -> datetime:
    return ensure_tz(value, default_tz).astimezone(UTC_TZ)


def combine_korean_timestamp(date_text: str | None, time_text: str | None) -> datetime:
    date_value = (date_text or "").strip()
    time_value = (time_text or "").strip()

    if len(date_value) == 8 and len(time_value) == 6:
        combined = datetime.strptime(f"{date_value}{time_value}", "%Y%m%d%H%M%S")
    elif len(date_value) == 8 and len(time_value) == 4:
        combined = datetime.strptime(f"{date_value}{time_value}", "%Y%m%d%H%M")
    else:
        return now_utc()

    return to_utc(combined, "Asia/Seoul")


def align_to_ten_minutes(value: datetime) -> datetime:
    local = to_seoul(value)
    minute = local.minute - (local.minute % 10)
    return local.replace(minute=minute, second=0, microsecond=0).astimezone(UTC_TZ)


def align_to_interval(value: datetime, interval_minutes: int, tz_name: str = "Asia/Seoul") -> datetime:
    if interval_minutes <= 0 or interval_minutes > 60:
        raise ValueError("interval_minutes must be between 1 and 60")

    tz = ZoneInfo(tz_name)
    local = ensure_tz(value, tz_name).astimezone(tz)
    minute = local.minute - (local.minute % interval_minutes)
    return local.replace(minute=minute, second=0, microsecond=0).astimezone(UTC_TZ)


def split_by_local_day(start: datetime, end: datetime, tz_name: str = "Asia/Seoul") -> list[tuple[datetime, datetime]]:
    if end <= start:
        return []

    tz = ZoneInfo(tz_name)
    cursor = ensure_tz(start, tz_name).astimezone(tz)
    boundary_end = ensure_tz(end, tz_name).astimezone(tz)
    chunks: list[tuple[datetime, datetime]] = []

    while cursor < boundary_end:
        next_midnight = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        chunk_end = min(next_midnight, boundary_end)
        chunks.append((cursor.astimezone(UTC_TZ), chunk_end.astimezone(UTC_TZ)))
        cursor = chunk_end

    return chunks
