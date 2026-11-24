from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, NamedTuple

from sqlalchemy import BigInteger, Date, Integer, Text, case, cast, extract, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import logging

from app.core.config import Settings
from app.core.time_utils import ensure_tz, now_utc, serialize_utc
from app.models import Airport, AnalyticsCache, ParkingLot, ParkingSnapshot
from app.services.analytics import (
    SpecialDayHourAggregate,
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
logger = logging.getLogger(__name__)
MAX_ANALYTICS_CACHE_AGE = timedelta(minutes=10)
#: 대시보드 묶음은 엄격한 재사용 조건(생성 10분 이내·그 뒤 같은 범위 새 적재 없음)을 못 채워도 직전 사전집계를 낸다 —
#: 수집 직후 갱신 전에 요청이 원본 계산(운영 ICN 25~30초, 같은 프로세스의 다른 공항 요청까지 막음)으로 떨어지지 않게 한다.
#: 공항 수집은 행을 넣을 때 `collected_at`을 찍고 실행 끝(보통 4~9분, 상한 `JOB_MAX_RUNTIME_SECONDS` 30분)에 commit하고,
#: 그 직후 같은 job이 기본 범위 사전집계를 다시 만든다(운영 ARM 약 5분, 2026-11-23 보고).
#: - 사전집계 뒤의 새 적재가 모두 `DASHBOARD_REFRESH_GRACE` 안이면 갱신 대기로 본다(수집 상한 30분 + 갱신 시간을 덮는다).
#:   그보다 오래된 새 적재가 있으면 갱신이 실패·중단된 것이라 원본에서 계산한다.
#: - 새 적재가 없으면(원천 장애로 적재 0건 등) 사전집계가 그대로 맞으므로 `DASHBOARD_STALE_CACHE_MAX_AGE`까지 낸다
#:   (기간 경계·시계열 미래 구간이 생성 시각 기준이라 상한을 둔다).
DASHBOARD_REFRESH_GRACE = timedelta(minutes=40)
DASHBOARD_STALE_CACHE_MAX_AGE = timedelta(hours=2)


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


class CompactSnapshot(NamedTuple):
    """분석 계산에 필요한 관측 값만 담는 읽기 전용 행.

    행마다 `Row._mapping`·`SimpleNamespace(**...)`를 만들면 공항 21일치(수만 행)에서
    그 변환이 분석 계산보다 비쌌다. 위치 기반 생성으로 같은 속성 이름·값을 유지한다.
    """

    id: int
    airport_id: int
    parking_lot_id: int
    observed_at: datetime
    occupied_spaces: int
    total_spaces: int
    available_spaces: int


async def load_compact_analytics_snapshots(
    session: AsyncSession, conditions: list[Any],
) -> list[CompactSnapshot]:
    """원본 JSON·ORM 객체 없이 동일 소스 우선순위의 계산용 값만 읽는다."""
    ranked = _ranked_snapshot_values(conditions)
    rows = (await session.execute(select(
        ranked.c.id, ranked.c.airport_id, ranked.c.parking_lot_id, ranked.c.observed_at,
        ranked.c.occupied_spaces, ranked.c.total_spaces, ranked.c.available_spaces,
    ).where(ranked.c.rank == 1).order_by(
        ranked.c.observed_at, ranked.c.parking_lot_id, ranked.c.id,
    ))).all()
    make = CompactSnapshot._make
    return [make(row) for row in rows]


async def aggregate_special_day_hours(
    session: AsyncSession, conditions: list[Any], tz_name: str,
) -> dict[tuple[date, int], SpecialDayHourAggregate]:
    """특수일 패턴의 시각별 표본을 PostgreSQL에서 요약한다.

    `special_day_hour_aggregates`와 같은 순서로 계산한다: 같은 소스 우선순위 중복 제거 →
    같은 관측 시각의 주차장 합계 → 현지 날짜·시별 개수/합/최소/최대. 원본 관측 수만큼의 행을
    API로 옮기지 않고 날짜×24행 이하만 받는다.
    """
    ranked = _ranked_snapshot_values(conditions)
    totals = select(
        ranked.c.observed_at,
        func.sum(ranked.c.available_spaces).label("total"),
    ).where(ranked.c.rank == 1).group_by(ranked.c.observed_at).subquery()
    # timestamptz를 설정 시간대의 현지 시각으로 바꾼다(`AT TIME ZONE`). 날짜·시는 안쪽에서
    # 한 번만 계산하고 바깥은 그 열로 묶는다.
    local_observed_at = func.timezone(cast(literal(tz_name), Text), totals.c.observed_at)
    local = select(
        cast(local_observed_at, Date).label("local_date"),
        cast(extract("hour", local_observed_at), Integer).label("local_hour"),
        totals.c.total,
    ).subquery()
    rows = (await session.execute(select(
        local.c.local_date, local.c.local_hour,
        func.count().label("observations"),
        cast(func.sum(local.c.total), BigInteger).label("total"),
        cast(func.min(local.c.total), BigInteger).label("minimum"),
        cast(func.max(local.c.total), BigInteger).label("maximum"),
    ).group_by(local.c.local_date, local.c.local_hour))).all()
    return {
        (row.local_date, row.local_hour): SpecialDayHourAggregate(
            int(row.observations), int(row.total), int(row.minimum), int(row.maximum),
        )
        for row in rows
    }


async def load_compact_analytics_rows(
    session: AsyncSession, conditions: list[Any],
) -> list[tuple[ParkingSnapshot, ParkingLot, Airport]]:
    ranked = _ranked_snapshot_values(conditions, with_references=True)
    rows = (await session.execute(select(
        ranked.c.id, ranked.c.airport_id, ranked.c.parking_lot_id, ranked.c.observed_at,
        ranked.c.occupied_spaces, ranked.c.total_spaces, ranked.c.available_spaces,
        ranked.c.parking_lot_name, ranked.c.airport_code, ranked.c.airport_name,
    ).where(ranked.c.rank == 1).order_by(
        ranked.c.observed_at, ranked.c.parking_lot_id, ranked.c.id,
    ))).all()
    return compact_rows_with_references(
        (CompactSnapshot._make(row[:7]), row[7], row[8], row[9]) for row in rows
    )


def compact_rows_with_references(
    values: Iterable[tuple[CompactSnapshot, str, str, str]],
) -> list[tuple[CompactSnapshot, SimpleNamespace, SimpleNamespace]]:
    """(관측, 주차장 이름, 공항 코드, 공항 이름)을 임계치 계산의 (관측, 주차장, 공항) 행으로 바꾼다.

    같은 주차장·공항은 같은 참조 객체를 공유한다(계산은 속성만 읽는다).
    """
    lots: dict[tuple[int, str], SimpleNamespace] = {}
    airports: dict[tuple[str, str], SimpleNamespace] = {}
    result = []
    for snapshot, lot_name, airport_code, airport_name in values:
        lot = lots.get((snapshot.parking_lot_id, lot_name))
        if lot is None:
            lot = lots[(snapshot.parking_lot_id, lot_name)] = SimpleNamespace(id=snapshot.parking_lot_id, name=lot_name)
        airport = airports.get((airport_code, airport_name))
        if airport is None:
            airport = airports[(airport_code, airport_name)] = SimpleNamespace(code=airport_code, name_ko=airport_name)
        result.append((snapshot, lot, airport))
    return result


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
    refresh_grace: bool = False,
) -> Any | None:
    """재사용 조건을 채운 캐시 payload.

    `refresh_grace`면 엄격한 조건을 못 채울 때도 갱신 대기 중인 직전 사전집계를 낸다(`DASHBOARD_REFRESH_GRACE`).
    """
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
    if cached is None and refresh_grace:
        # 갱신 유예보다 오래된 새 적재가 있으면 갱신이 실패·중단된 것이다 — 직전 사전집계를 내지 않는다.
        overdue_snapshots = newer_snapshots.where(ParkingSnapshot.collected_at <= checked_at - DASHBOARD_REFRESH_GRACE)
        cached = await session.scalar(
            select(AnalyticsCache).where(
                AnalyticsCache.metric == metric,
                AnalyticsCache.scope_key == build_analytics_scope_key(airport_code, parking_lot_id),
                AnalyticsCache.days == days,
                AnalyticsCache.interval_minutes == interval_minutes,
                AnalyticsCache.limit == limit,
                AnalyticsCache.future_hours == future_hours,
                AnalyticsCache.generated_at >= checked_at - DASHBOARD_STALE_CACHE_MAX_AGE,
                AnalyticsCache.generated_at <= checked_at,
                ~overdue_snapshots.correlate(AnalyticsCache).exists(),
            )
        )
    return cached.payload_json if cached else None


async def snapshot_source_fingerprint(session: AsyncSession) -> tuple[int, ...]:
    """원본 관측 테이블의 commit 순서 지문(보이는 최대 id).

    수집기는 `collected_at`을 행 삽입 시각으로 찍고 실행 끝에 commit한다. 그 사이에 계산한 결과는
    `collected_at > 생성 시각` 검사로 무효화되지 않는다. 관측은 삽입 전용이고 수집기는 advisory lease로
    하나만 돌므로, commit 전 행의 id는 계산 때 보이던 최대 id보다 크고 commit 뒤 최대 id가 바뀐다.
    PostgreSQL 누적 통계(n_tup_ins)는 반영이 지연될 수 있어 쓰지 않는다.
    """
    return (int(await session.scalar(select(func.max(ParkingSnapshot.id))) or 0),)


async def analytics_generation_is_fresh(
    session: AsyncSession,
    *,
    airport_code: str | None,
    parking_lot_id: int | None,
    generated_at: datetime,
) -> bool:
    """`load_cached_analytics`와 같은 재사용 조건을 프로세스 안 계산 결과에 적용한다.

    생성(원본 첫 조회 전 시각) 뒤 10분 안이고, 그 뒤에 적재된 같은 범위 관측이 없어야 한다.
    """
    checked_at = now_utc()
    if not checked_at - MAX_ANALYTICS_CACHE_AGE <= generated_at <= checked_at:
        return False
    newer_snapshots = select(ParkingSnapshot.id).where(ParkingSnapshot.collected_at > generated_at)
    if airport_code:
        newer_snapshots = newer_snapshots.where(ParkingSnapshot.airport_id == (
            select(Airport.id).where(Airport.code == airport_code.upper()).scalar_subquery()
        ))
    if parking_lot_id is not None:
        newer_snapshots = newer_snapshots.where(ParkingSnapshot.parking_lot_id == parking_lot_id)
    return not await session.scalar(select(newer_snapshots.exists()))


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
    cache_rows: dict[tuple, AnalyticsCache] | None = None,
) -> None:
    generated_at = generated_at or now_utc()
    scope_key = build_analytics_scope_key(airport_code, parking_lot_id)
    identity = (metric, scope_key, days, interval_minutes, limit, future_hours)
    cached = cache_rows.get(identity) if cache_rows is not None else await session.scalar(
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
        cached = AnalyticsCache(
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
        session.add(cached)
        if cache_rows is not None:
            cache_rows[identity] = cached
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
            # 대시보드 갱신 유예(`DASHBOARD_REFRESH_GRACE`)가 이 갱신에 기댄다. 건너뛴 사실을 남긴다.
            logger.warning("default analytics cache refresh skipped: airport collection lock is busy")
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
    # 네 metric × 공항/주차장 scope의 반복 조회를 합친다. 기존 payload도 함께
    # 읽어야 ORM이 같은 JSON을 재기록하지 않는 기존 변경 감지를 유지한다.
    cached_rows = (await session.scalars(select(AnalyticsCache).where(
        AnalyticsCache.airport_code.in_([airport.code for airport in airports]),
    ))).all()
    cache_rows = {(row.metric, row.scope_key, row.days, row.interval_minutes, row.limit, row.future_hours): row
                  for row in cached_rows}
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
                generated_at=generated_at, cache_rows=cache_rows,
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
    cache_rows: dict[tuple, AnalyticsCache] | None = None,
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
        generated_at=generated_at, cache_rows=cache_rows,
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
        generated_at=generated_at, cache_rows=cache_rows,
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
        generated_at=generated_at, cache_rows=cache_rows,
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
        generated_at=generated_at, cache_rows=cache_rows,
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
