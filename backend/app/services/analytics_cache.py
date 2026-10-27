from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import ensure_tz, now_utc, serialize_utc
from app.models import Airport, AnalyticsCache, ParkingLot, ParkingSnapshot
from app.services.analytics import (
    build_threshold_insights,
    build_time_series,
    build_weekday_hour_patterns,
    detect_threshold_events,
)

METRIC_TIMESERIES = "timeseries"
METRIC_WEEKDAY_HOUR = "weekday_hour"
METRIC_THRESHOLD_EVENTS = "threshold_events"
METRIC_THRESHOLD_INSIGHTS = "threshold_insights"

DEFAULT_TIMESERIES_DAYS = 7
DEFAULT_TIMESERIES_INTERVAL_MINUTES = 10
DEFAULT_TIMESERIES_FUTURE_HOURS = 0
DEFAULT_WEEKDAY_HOUR_DAYS = 14
DEFAULT_THRESHOLD_EVENTS_DAYS = 14
DEFAULT_THRESHOLD_EVENTS_LIMIT = 20
DEFAULT_THRESHOLD_INSIGHTS_DAYS = 21
DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES = 10
# 5분 수집 두 주기를 넘긴 파생 결과는 원본으로 다시 계산한다.
MAX_ANALYTICS_CACHE_AGE = timedelta(minutes=10)


def _ranked_snapshot_values(conditions: list[Any], *, with_references: bool = False):
    query = select(
        ParkingSnapshot.id,
        ParkingSnapshot.airport_id,
        ParkingSnapshot.parking_lot_id,
        ParkingSnapshot.observed_at,
        ParkingSnapshot.occupied_spaces,
        ParkingSnapshot.total_spaces,
        ParkingSnapshot.available_spaces,
        func.row_number().over(
            partition_by=(ParkingSnapshot.parking_lot_id, ParkingSnapshot.observed_at),
            order_by=(
                case((func.substr(ParkingSnapshot.source, 1, 10) == "migration_", 1), else_=0),
                ParkingSnapshot.collected_at.desc(),
                ParkingSnapshot.id.desc(),
            ),
        ).label("rank"),
    ).select_from(ParkingSnapshot)
    if with_references:
        # 기존 joined loader처럼 유효한 기준정보와 결합한 뒤 중복을 제거한다.
        query = query.add_columns(
            ParkingLot.name.label("parking_lot_name"),
            Airport.code.label("airport_code"),
            Airport.name_ko.label("airport_name"),
        ).join(ParkingLot, ParkingLot.id == ParkingSnapshot.parking_lot_id).join(
            Airport, Airport.id == ParkingSnapshot.airport_id,
        )
    return query.where(*conditions).subquery()


async def load_compact_analytics_snapshots(
    session: AsyncSession, conditions: list[Any],
) -> list[ParkingSnapshot]:
    """원본 JSON·ORM 객체 없이 동일 소스 우선순위의 계산용 값만 읽는다."""
    ranked = _ranked_snapshot_values(conditions)
    rows = (await session.execute(select(
        ranked.c.id, ranked.c.airport_id, ranked.c.parking_lot_id, ranked.c.observed_at,
        ranked.c.occupied_spaces, ranked.c.total_spaces, ranked.c.available_spaces,
    ).where(ranked.c.rank == 1).order_by(
        ranked.c.observed_at, ranked.c.parking_lot_id, ranked.c.id,
    ))).all()
    return [SimpleNamespace(**row._mapping) for row in rows]


async def load_compact_analytics_rows(
    session: AsyncSession, conditions: list[Any],
) -> list[tuple[ParkingSnapshot, ParkingLot, Airport]]:
    ranked = _ranked_snapshot_values(conditions, with_references=True)
    rows = (await session.execute(select(ranked).where(ranked.c.rank == 1).order_by(
        ranked.c.observed_at, ranked.c.parking_lot_id, ranked.c.id,
    ))).all()
    return [(
        SimpleNamespace(**row._mapping),
        SimpleNamespace(id=row.parking_lot_id, name=row.parking_lot_name),
        SimpleNamespace(code=row.airport_code, name_ko=row.airport_name),
    ) for row in rows]


def build_analytics_scope_key(airport_code: str | None, parking_lot_id: int | None) -> str:
    airport_part = (airport_code or "*").upper()
    lot_part = str(parking_lot_id) if parking_lot_id is not None else "*"
    return f"{airport_part}:{lot_part}"


def serialize_json_payload(value: Any) -> Any:
    if isinstance(value, datetime):
        return serialize_utc(value).isoformat()
    if isinstance(value, list):
        return [serialize_json_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_json_payload(item) for key, item in value.items()}
    return value


async def load_cached_analytics(
    session: AsyncSession,
    *,
    metric: str,
    airport_code: str | None,
    parking_lot_id: int | None,
    days: int = 0,
    interval_minutes: int = 0,
    limit: int = 0,
    future_hours: int = 0,
) -> Any | None:
    checked_at = now_utc()
    newer_snapshots = select(1).select_from(ParkingSnapshot).where(
        ParkingSnapshot.collected_at > AnalyticsCache.generated_at,
    )
    if airport_code:
        newer_snapshots = newer_snapshots.where(ParkingSnapshot.airport_id == (
            select(Airport.id).where(Airport.code == airport_code.upper()).scalar_subquery()
        ))
    if parking_lot_id is not None:
        newer_snapshots = newer_snapshots.where(ParkingSnapshot.parking_lot_id == parking_lot_id)
    cached = await session.scalar(
        select(AnalyticsCache).where(
            AnalyticsCache.metric == metric,
            AnalyticsCache.scope_key == build_analytics_scope_key(airport_code, parking_lot_id),
            AnalyticsCache.days == days,
            AnalyticsCache.interval_minutes == interval_minutes,
            AnalyticsCache.limit == limit,
            AnalyticsCache.future_hours == future_hours,
            AnalyticsCache.generated_at >= checked_at - MAX_ANALYTICS_CACHE_AGE,
            AnalyticsCache.generated_at <= checked_at,
            # observed_at이 더 오래된 지연 관측도 새 적재면 무효화한다.
            ~newer_snapshots.correlate(AnalyticsCache).exists(),
        )
    )
    return cached.payload_json if cached else None


async def store_cached_analytics(
    session: AsyncSession,
    *,
    metric: str,
    airport_code: str,
    parking_lot_id: int | None,
    days: int = 0,
    interval_minutes: int = 0,
    limit: int = 0,
    future_hours: int = 0,
    source_observed_at: datetime | None,
    payload: Any,
    generated_at: datetime | None = None,
) -> None:
    generated_at = generated_at or now_utc()
    scope_key = build_analytics_scope_key(airport_code, parking_lot_id)
    cached = await session.scalar(
        select(AnalyticsCache).where(
            AnalyticsCache.metric == metric,
            AnalyticsCache.scope_key == scope_key,
            AnalyticsCache.days == days,
            AnalyticsCache.interval_minutes == interval_minutes,
            AnalyticsCache.limit == limit,
            AnalyticsCache.future_hours == future_hours,
        )
    )
    serialized_payload = serialize_json_payload(payload)
    if cached is None:
        session.add(
            AnalyticsCache(
                metric=metric,
                scope_key=scope_key,
                airport_code=airport_code,
                parking_lot_id=parking_lot_id,
                days=days,
                interval_minutes=interval_minutes,
                limit=limit,
                future_hours=future_hours,
                generated_at=generated_at,
                source_observed_at=source_observed_at,
                payload_json=serialized_payload,
                updated_at=generated_at,
            )
        )
        return

    cached.airport_code = airport_code
    cached.parking_lot_id = parking_lot_id
    cached.generated_at = generated_at
    cached.source_observed_at = source_observed_at
    cached.payload_json = serialized_payload
    cached.updated_at = generated_at


async def refresh_default_analytics_cache(
    session: AsyncSession,
    settings: Settings,
    airport_codes: Iterable[str] | None = None,
) -> int:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        # CollectionService의 기존 전용 session lease와 같은 key다. 원본의 지연 commit과
        # 다른 refresh가 조회 중간에 끼지 않게 하며, 경합 시 직접 조회 fallback을 유지한다.
        acquired = await session.scalar(text(
            "SELECT pg_try_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"
        ))
        if not acquired:
            return 0
    generated_at = now_utc()
    codes = [code.upper() for code in (airport_codes or settings.supported_airport_codes)]
    airports = (
        await session.execute(
            select(Airport)
            .where(Airport.code.in_(codes))
            .order_by(Airport.code)
        )
    ).scalars().all()

    lots = await _load_analytics_lots(session)
    refreshed = 0
    for airport in airports:
        lot_ids = sorted(lot.id for lot in lots.values() if lot.airport_id == airport.id and lot.is_active)
        snapshots = await _load_snapshots(
            session, airport.id, None, DEFAULT_THRESHOLD_INSIGHTS_DAYS,
            buffer_minutes=DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES,
        )
        by_lot = defaultdict(list)
        for snapshot in snapshots:
            by_lot[snapshot.parking_lot_id].append(snapshot)
        for parking_lot_id in [None, *lot_ids]:
            refreshed += await _refresh_scope_from_snapshots(
                session, settings, airport, parking_lot_id,
                snapshots if parking_lot_id is None else by_lot[parking_lot_id], lots,
                generated_at=generated_at,
            )
    return refreshed


async def refresh_scope_analytics_cache(
    session: AsyncSession,
    settings: Settings,
    airport: Airport,
    parking_lot_id: int | None,
    *,
    generated_at: datetime | None = None,
) -> int:
    # 계산 종료 시각이 아닌 첫 원본 조회 전 시각을 watermark로 쓴다.
    generated_at = generated_at or now_utc()
    snapshots = await _load_snapshots(
        session, airport.id, parking_lot_id, DEFAULT_THRESHOLD_INSIGHTS_DAYS,
        buffer_minutes=DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES,
    )
    return await _refresh_scope_from_snapshots(
        session, settings, airport, parking_lot_id, snapshots, await _load_analytics_lots(session),
        generated_at=generated_at,
    )


async def _refresh_scope_from_snapshots(
    session: AsyncSession,
    settings: Settings,
    airport: Airport,
    parking_lot_id: int | None,
    snapshots: list[ParkingSnapshot],
    lots: dict[int, ParkingLot],
    *,
    generated_at: datetime,
) -> int:
    refreshed = 0
    source_observed_at = await _load_latest_observed_at(session, airport.id, parking_lot_id)

    time_series_snapshots = _snapshots_in_window(
        snapshots, DEFAULT_TIMESERIES_DAYS,
        buffer_minutes=DEFAULT_TIMESERIES_INTERVAL_MINUTES,
    )
    await store_cached_analytics(
        session,
        metric=METRIC_TIMESERIES,
        airport_code=airport.code,
        parking_lot_id=parking_lot_id,
        days=DEFAULT_TIMESERIES_DAYS,
        interval_minutes=DEFAULT_TIMESERIES_INTERVAL_MINUTES,
        future_hours=DEFAULT_TIMESERIES_FUTURE_HOURS,
        source_observed_at=source_observed_at,
        generated_at=generated_at,
        payload={
            "generated_at": generated_at,
            "airport_code": airport.code,
            "parking_lot_id": parking_lot_id,
            "days": DEFAULT_TIMESERIES_DAYS,
            "interval_minutes": DEFAULT_TIMESERIES_INTERVAL_MINUTES,
            "future_hours": DEFAULT_TIMESERIES_FUTURE_HOURS,
            "items": build_time_series(
                time_series_snapshots,
                days=DEFAULT_TIMESERIES_DAYS,
                interval_minutes=DEFAULT_TIMESERIES_INTERVAL_MINUTES,
                future_hours=DEFAULT_TIMESERIES_FUTURE_HOURS,
                tz_name=settings.app_timezone,
            ),
        },
    )
    refreshed += 1

    weekday_snapshots = _snapshots_in_window(snapshots, DEFAULT_WEEKDAY_HOUR_DAYS)
    await store_cached_analytics(
        session,
        metric=METRIC_WEEKDAY_HOUR,
        airport_code=airport.code,
        parking_lot_id=parking_lot_id,
        days=DEFAULT_WEEKDAY_HOUR_DAYS,
        source_observed_at=source_observed_at,
        generated_at=generated_at,
        payload=build_weekday_hour_patterns(weekday_snapshots, tz_name=settings.app_timezone),
    )
    refreshed += 1

    threshold_rows = [
        (snapshot, lots[snapshot.parking_lot_id], airport)
        for snapshot in _snapshots_in_window(snapshots, DEFAULT_THRESHOLD_EVENTS_DAYS)
        if snapshot.parking_lot_id in lots
    ]
    threshold_events = [
        {**event, "crossed_at": serialize_utc(event["crossed_at"])}
        for event in detect_threshold_events(threshold_rows, limit=DEFAULT_THRESHOLD_EVENTS_LIMIT)
    ]
    await store_cached_analytics(
        session,
        metric=METRIC_THRESHOLD_EVENTS,
        airport_code=airport.code,
        parking_lot_id=parking_lot_id,
        days=DEFAULT_THRESHOLD_EVENTS_DAYS,
        limit=DEFAULT_THRESHOLD_EVENTS_LIMIT,
        source_observed_at=source_observed_at,
        generated_at=generated_at,
        payload=threshold_events,
    )
    refreshed += 1

    threshold_snapshots = _snapshots_in_window(
        snapshots, DEFAULT_THRESHOLD_INSIGHTS_DAYS,
        buffer_minutes=DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES,
    )
    threshold_points = build_time_series(
        threshold_snapshots,
        days=DEFAULT_THRESHOLD_INSIGHTS_DAYS,
        interval_minutes=DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES,
        tz_name=settings.app_timezone,
    )
    threshold_insights = build_threshold_insights(threshold_points, tz_name=settings.app_timezone)
    await store_cached_analytics(
        session,
        metric=METRIC_THRESHOLD_INSIGHTS,
        airport_code=airport.code,
        parking_lot_id=parking_lot_id,
        days=DEFAULT_THRESHOLD_INSIGHTS_DAYS,
        interval_minutes=DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES,
        source_observed_at=source_observed_at,
        generated_at=generated_at,
        payload={
            "generated_at": generated_at,
            "airport_code": airport.code,
            "parking_lot_id": parking_lot_id,
            "days": DEFAULT_THRESHOLD_INSIGHTS_DAYS,
            "interval_minutes": DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES,
            "weekday_items": threshold_insights["weekday_items"],
            "history_items": threshold_insights["history_items"],
        },
    )
    refreshed += 1
    return refreshed


async def _load_latest_observed_at(
    session: AsyncSession,
    airport_id: int,
    parking_lot_id: int | None,
) -> datetime | None:
    query = select(func.max(ParkingSnapshot.observed_at)).where(ParkingSnapshot.airport_id == airport_id)
    if parking_lot_id is not None:
        query = query.where(ParkingSnapshot.parking_lot_id == parking_lot_id)
    return await session.scalar(query)


async def _load_snapshots(
    session: AsyncSession,
    airport_id: int,
    parking_lot_id: int | None,
    days: int,
    buffer_minutes: int = 0,
) -> list[ParkingSnapshot]:
    cutoff = now_utc() - timedelta(days=days, minutes=buffer_minutes)
    conditions = [ParkingSnapshot.airport_id == airport_id, ParkingSnapshot.observed_at >= cutoff]
    if parking_lot_id is not None:
        conditions.append(ParkingSnapshot.parking_lot_id == parking_lot_id)
    return await load_compact_analytics_snapshots(session, conditions)


def _snapshots_in_window(
    snapshots: list[ParkingSnapshot], days: int, buffer_minutes: int = 0,
) -> list[ParkingSnapshot]:
    cutoff = now_utc() - timedelta(days=days, minutes=buffer_minutes)
    return [snapshot for snapshot in snapshots if ensure_tz(snapshot.observed_at, "UTC") >= cutoff]


async def _load_analytics_lots(session: AsyncSession) -> dict[int, ParkingLot]:
    rows = (await session.execute(select(
        ParkingLot.id, ParkingLot.airport_id, ParkingLot.name, ParkingLot.is_active,
    ))).all()
    return {row.id: SimpleNamespace(**row._mapping) for row in rows}
