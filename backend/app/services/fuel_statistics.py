"""수집 완료 시 통계를 미리 집계한다. 지역 세대·일별 통계는 영구 보존한다."""
from __future__ import annotations

import json
import logging
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Float, String, and_, cast, delete, exists, func, insert, literal, or_, select, text, tuple_, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc
from app.models import (
    FuelLatestPrice, FuelStation, FuelStatisticsDaily, FuelStatisticsHistory, FuelStatisticsPoint,
    FuelStatisticsState, FuelRegionSummary, RestAreaFuelPrice, TransportCollectionState,
)
from app.services.flight_status import sanitize_upstream_error
from app.services.fuel_station_filters import SIDO_DISPLAY_NAMES, sido_display_name, station_for_point

if TYPE_CHECKING:
    from app.services.fuel_station_filters import FuelStationFilters

OPINET = "opinet_browser"
HIGHWAY = "krex_rest_area_fuel"
SCOPES = {"nationwide", "sido", "sigungu", "highways", "highway", "highway_direction"}
logger = logging.getLogger(__name__)
_viewport_cache: OrderedDict[tuple, tuple[float, list[dict]]] = OrderedDict()


async def lock_fuel_statistics(session: AsyncSession, source: str) -> None:
    if session.bind.dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 420061 if source == OPINET else 420062})


def _key(*values: str) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


class _Accumulator:
    def __init__(self, label: str) -> None:
        self.label = label
        self.count = 0
        self.total = 0.0
        self.squares = 0.0
        self.minimum = math.inf
        self.maximum = 0.0
        self.cheapest: dict | None = None
        self.cheapest_count = 0
        self.ranked: list[dict] = []

    def add(self, point: dict) -> None:
        price = float(point["price"])
        self.count += 1
        self.total += price
        self.squares += price * price
        self.maximum = max(self.maximum, price)
        self.ranked.append({**{k: point[k] for k in ("station_key", "name", "address", "longitude", "latitude")}, "price": price})
        self.ranked.sort(key=lambda row: (row["price"], row["station_key"]))
        del self.ranked[10:]
        if price < self.minimum:
            self.minimum, self.cheapest_count = price, 1
            self.cheapest = {k: point[k] for k in ("station_key", "name", "address", "longitude", "latitude")}
        elif price == self.minimum:
            self.cheapest_count += 1
            if self.cheapest is not None and point["station_key"] < self.cheapest["station_key"]:
                self.cheapest = {k: point[k] for k in ("station_key", "name", "address", "longitude", "latitude")}

    def metrics(self) -> dict:
        average = self.total / self.count
        return {**_metrics(self.count, average, self.minimum, self.maximum,
                          self.squares / self.count, self.cheapest, self.cheapest_count),
                "cheapest_stations": self.ranked, "ranking_complete": True}


def _metrics(count: int, average: float, minimum: float, maximum: float,
             mean_square: float, cheapest: dict | None, cheapest_count: int) -> dict:
    return {
        "station_count": count, "average_price": round(average, 2),
        "minimum_price": minimum, "maximum_price": maximum,
        "price_spread": round(maximum - minimum, 2),
        "standard_deviation": round(math.sqrt(max(0, mean_square - average * average)), 2),
        "saving_50l": round((average - minimum) * 50, 2),
        "cheapest_station": cheapest, "cheapest_station_count": cheapest_count,
    }


async def _opinet_cohort_matches(session: AsyncSession, stamp: datetime) -> bool:
    """이미 공개된 구 모집단도 같은 성공 원본으로 정정하며, 정상 재시도는 쓰지 않는다."""
    expected = select(cast(FuelLatestPrice.fuel_station_id, String),
                      FuelLatestPrice.product_code, FuelLatestPrice.price).join(
        FuelStation, FuelStation.id == FuelLatestPrice.fuel_station_id,
    ).where(FuelStation.source == OPINET, FuelLatestPrice.price > 0,
            FuelLatestPrice.collected_at == stamp)
    published = select(FuelStatisticsPoint.station_key, FuelStatisticsPoint.product_code,
                       FuelStatisticsPoint.price).where(
        FuelStatisticsPoint.source == OPINET, FuelStatisticsPoint.generated_at == stamp)
    differences = union_all(
        select(literal(1)).select_from(expected.except_(published).subquery()),
        select(literal(1)).select_from(published.except_(expected).subquery()),
    ).subquery()
    return not bool(await session.scalar(select(exists(select(1).select_from(differences)))))


async def publish_fuel_statistics(session: AsyncSession, source: str, collected_at: datetime) -> None:
    """세대별로 준비하고 마지막에만 원천 잠금을 잡아 공개 포인터를 전환한다."""
    await session.flush()
    stamp = serialize_utc(collected_at)
    if session.bind.dialect.name == "postgresql":
        # 같은 세대의 중복 재시도만 직렬화한다. 다른 세대·원천의 준비는 병행한다.
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:generation, 0))"),
                              {"generation": f"fuel-statistics:{source}:{stamp.isoformat()}"})
    state = await session.get(FuelStatisticsState, source, populate_existing=True)
    if state is not None and serialize_utc(state.generated_at) > stamp:
        return
    collection = await session.scalar(select(TransportCollectionState).where(
        TransportCollectionState.source == source,
    ).execution_options(populate_existing=True))
    if collection and collection.last_success_at and serialize_utc(collection.last_success_at) != stamp:
        return
    rebuild_current = bool(state is not None and serialize_utc(state.generated_at) == stamp
                           and source == OPINET and not await _opinet_cohort_matches(session, stamp))
    if state is not None and serialize_utc(state.generated_at) == stamp and not rebuild_current:
        return
    day = stamp.astimezone(ZoneInfo("Asia/Seoul")).date()
    # 원본 저장 트랜잭션은 호출자가 먼저 확정한다. 같은 collected_at 재시도도
    # savepoint 안에서 교체한다. 현재 세대의 구 모집단 정정도 같은 commit으로 공개한다.
    await session.execute(delete(FuelStatisticsPoint).where(
        FuelStatisticsPoint.source == source, FuelStatisticsPoint.generated_at == stamp,
    ))
    groups: dict[tuple[str, str, str], _Accumulator] = {}
    regions: dict[tuple[str, str, str], dict] = {}
    pending: list[dict] = []

    async def consume(point: dict, scopes: list[tuple[str, str, str]]) -> None:
        pending.append(point)
        for scope, scope_key, label in scopes:
            key = (scope, scope_key, point["product_code"])
            group = groups.get(key)
            if group is None:
                group = groups[key] = _Accumulator(label)
            group.add(point)
        if len(pending) >= 500:
            await session.execute(insert(FuelStatisticsPoint), pending)
            pending.clear()

    if source == OPINET:
        statement = select(
            FuelStation.id, FuelStation.name, FuelStation.address, FuelStation.brand_name,
            FuelStation.longitude, FuelStation.latitude, FuelStation.sido_value, FuelStation.sido_name,
            FuelStation.sigungu_value, FuelStation.sigungu_name, FuelLatestPrice.product_code, FuelLatestPrice.price,
        ).join(FuelLatestPrice, FuelLatestPrice.fuel_station_id == FuelStation.id).where(
            FuelStation.source == source, FuelLatestPrice.price > 0,
            FuelLatestPrice.collected_at == stamp,
        ).order_by(FuelStation.id, FuelLatestPrice.product_code).execution_options(yield_per=500)
        stream = await session.stream(statement)
        async for row in stream:
            point = {"source": source, "station_key": str(row.id), "generated_at": stamp,
                     "name": row.name, "address": row.address, "brand_name": row.brand_name,
                     "longitude": row.longitude, "latitude": row.latitude,
                     "product_code": row.product_code, "price": float(row.price)}
            scopes = [("nationwide", "all", "전국")]
            # 같은 시도라도 오피넷 원문 이름이 행마다 다르다(짧은/정식). 지역 카드·이력 이름은 화면 이름 하나로 쓴다.
            sido_label = sido_display_name(row.sido_value, row.sido_name) if row.sido_name or row.sido_value in SIDO_DISPLAY_NAMES else None
            if row.sido_value:
                scopes.append(("sido", _key(row.sido_value), sido_label or "시도 미제공"))
            if row.sido_value and row.sigungu_value:
                scopes.append(("sigungu", _key(row.sido_value, row.sigungu_value),
                               f"{sido_label or row.sido_value} {row.sigungu_name or row.sigungu_value}".strip()))
            for scope, key, label in scopes[1:]:
                region = regions.setdefault((scope, key, row.product_code), {
                    "region_key": ":".join([source, row.sido_value] + ([row.sigungu_value] if scope == "sigungu" else [])),
                    "label": label, "longitude": 0., "latitude": 0., "located": 0,
                })
                if (row.longitude is not None and row.latitude is not None
                        and -180 <= row.longitude <= 180 and -90 <= row.latitude <= 90):
                    region["longitude"] += row.longitude
                    region["latitude"] += row.latitude
                    region["located"] += 1
            await consume(point, scopes)
    elif source == HIGHWAY:
        stream = await session.stream(select(RestAreaFuelPrice).where(
            RestAreaFuelPrice.source == source, RestAreaFuelPrice.last_seen_at == collected_at,
        ).order_by(RestAreaFuelPrice.service_area_code).execution_options(yield_per=500))
        async for row in stream.scalars():
            route = row.route_name or "노선 미제공"
            route_key = row.route_code or route
            direction = row.direction or "방향 미제공"
            for product, price in (("B027", row.gasoline_price), ("D047", row.diesel_price), ("K015", row.lpg_price)):
                if price is None or price <= 0:
                    continue
                await consume({"source": source, "station_key": row.service_area_code, "generated_at": stamp,
                               "name": row.service_area_name or row.service_area_code, "address": row.address,
                               "brand_name": row.oil_company, "longitude": None, "latitude": None,
                               "product_code": product, "price": float(price)}, [
                    ("highways", "all", "고속도로 전체"),
                    ("highway", _key(route_key), route),
                    ("highway_direction", _key(route_key, direction), f"{route} · {direction}"),
                ])
    else:
        raise ValueError("지원하지 않는 유가 원천입니다.")
    if pending:
        await session.execute(insert(FuelStatisticsPoint), pending)
    rows = [{"source": source, "scope": scope, "scope_key": key, "product_code": product,
             "day": day, "generated_at": stamp, "label": group.label, "metrics_json": group.metrics()}
            for (scope, key, product), group in groups.items()]
    history_rows = [_history_row(row) for row in rows]
    # 원본 조회·정규화·point insert 중에는 이 잠금을 보유하지 않는다.
    await lock_fuel_statistics(session, source)
    # 다른 게시자가 먼저 끝났을 수 있다. identity map의 오래된 state를 재사용하지 않는다.
    state = await session.scalar(select(FuelStatisticsState).where(
        FuelStatisticsState.source == source,
    ).execution_options(populate_existing=True))
    collection = await session.scalar(select(TransportCollectionState).where(
        TransportCollectionState.source == source,
    ).execution_options(populate_existing=True))
    superseded = bool(collection and collection.last_success_at and
                      serialize_utc(collection.last_success_at) != stamp)
    already_published = state is not None and (serialize_utc(state.generated_at) > stamp
        or (serialize_utc(state.generated_at) == stamp and not rebuild_current))
    if superseded or already_published:
        await session.execute(delete(FuelStatisticsPoint).where(
            FuelStatisticsPoint.source == source, FuelStatisticsPoint.generated_at == stamp,
        ))
        return
    # 지역 이력도 포인터와 같은 transaction으로 공개한다. 이전 세대는 삭제하지 않는다.
    await session.execute(delete(FuelRegionSummary).where(
        FuelRegionSummary.source == source, FuelRegionSummary.generated_at == stamp,
    ))
    region_rows = []
    for (scope, key, product), region in regions.items():
        group = groups[(scope, key, product)]
        region_rows.append({"source": source, "generated_at": stamp, "scope": scope,
            "region_key": region["region_key"], "product_code": product, "label": region["label"],
            "longitude": region["longitude"] / region["located"] if region["located"] else None,
            "latitude": region["latitude"] / region["located"] if region["located"] else None,
            "average_price": group.total / group.count, "station_count": group.count,
            "metrics_json": group.metrics()})
    for offset in range(0, len(region_rows), 250):
        await session.execute(insert(FuelRegionSummary), region_rows[offset:offset + 250])
    # 하루의 마지막 성공본은 교체하되 지난 날짜는 보존한다. UI 조회 창과 저장 수명은 별개다.
    await session.execute(delete(FuelStatisticsDaily).where(
        FuelStatisticsDaily.source == source,
        FuelStatisticsDaily.day == day,
    ))
    for offset in range(0, len(rows), 250):
        await session.execute(insert(FuelStatisticsDaily), rows[offset:offset + 250])
    # 장기 추이 표도 같은 transaction으로 그날 값을 교체한다. 일별 행과 늘 같은 세대·같은 값이다.
    await session.execute(delete(FuelStatisticsHistory).where(
        FuelStatisticsHistory.source == source, FuelStatisticsHistory.day == day,
    ))
    for offset in range(0, len(history_rows), 500):
        await session.execute(insert(FuelStatisticsHistory), history_rows[offset:offset + 500])
    # 직전 공개 날짜와 전날을 일별 행(정본)에 다시 맞춘다. 0049 배포 중 옛 이미지가 migration 뒤에 공개한 날(일별 행만
    # 바뀐다)을 남기지 않는다 — 옛 이미지가 자정을 넘겨 두 날을 공개해도 새 이미지의 첫 공개가 둘 다 본다. 이미 같으면
    # 키만 비교하고(JSON을 읽지 않는다) 아무 행도 쓰지 않는다.
    for previous in sorted({day - timedelta(days=1), *([state.day] if state is not None and state.day < day else [])}):
        await _sync_history_day(session, source, previous)
    if state is None:
        session.add(FuelStatisticsState(source=source, generated_at=stamp, day=day))
    else:
        state.generated_at, state.day = stamp, day
    await session.flush()


def _history_row(row: dict) -> dict:
    metrics = row["metrics_json"]
    return {key: row[key] for key in ("source", "scope", "scope_key", "product_code", "day", "generated_at", "label")} | {
        "average_price": metrics["average_price"], "minimum_price": metrics.get("minimum_price"),
        "maximum_price": metrics.get("maximum_price"), "station_count": metrics["station_count"]}


async def _sync_history_day(session: AsyncSession, source: str, day: date) -> None:
    """그날 장기 추이 행을 일별 행(정본)과 같게 한다. 세대가 다른 행만 지우고 빠진 행만 일별 JSON에서 채운다."""
    d, h = FuelStatisticsDaily, FuelStatisticsHistory
    same_key = and_(d.source == h.source, d.scope == h.scope, d.scope_key == h.scope_key,
                    d.product_code == h.product_code, d.day == h.day)
    await session.execute(delete(h).where(
        h.source == source, h.day == day, ~exists().where(same_key, d.generated_at == h.generated_at),
    ).execution_options(synchronize_session=False))
    # 빠진 키가 있을 때만 일별 JSON을 읽는다(평소에는 기본키 비교만 한다).
    if not await session.scalar(select(exists().where(d.source == source, d.day == day, ~exists().where(same_key)))):
        return
    average, count = d.metrics_json["average_price"].as_float(), d.metrics_json["station_count"].as_integer()
    await session.execute(insert(h).from_select(
        ["source", "scope", "scope_key", "product_code", "day", "generated_at", "label",
         "average_price", "minimum_price", "maximum_price", "station_count"],
        select(d.source, d.scope, d.scope_key, d.product_code, d.day, d.generated_at, d.label, average,
               d.metrics_json["minimum_price"].as_float(), d.metrics_json["maximum_price"].as_float(), count)
        .where(d.source == source, d.day == day, average > 0, count > 0, ~exists().where(same_key)),
    ))


def _deferred_cause(exc: BaseException) -> str:
    """한 줄 원인: 예외 유형과 URL·키를 가린 짧은 메시지. SQL 원문 전체를 로그에 싣지 않는다."""
    message = " ".join(sanitize_upstream_error(str(exc), None).split())[:200]
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


async def try_publish_fuel_statistics(session: AsyncSession, source: str, collected_at: datetime) -> bool:
    """통계를 발행했으면 True. 실패는 원본 수집 성공을 취소하지 않고 False와 한 줄 원인 경고로 남긴다."""
    # 통계 실패가 오래 걸린 원본 수집 성공을 취소하지 않게 savepoint로 격리한다.
    try:
        async with session.begin_nested():
            await publish_fuel_statistics(session, source, collected_at)
    except Exception as exc:
        # 유가 op가 이 logger를 Dagster event log로 넘긴다(포화된 ARM의 반복 command_timeout을 run에서 보이게).
        logger.warning("fuel statistics publication deferred source=%s cause=%s", source, _deferred_cause(exc))
        return False
    return True


#: 한 정리 문장이 지우는 최대 행 수. 세대 하나는 약 3만 행이다(2026-11-23 운영).
PRUNE_BATCH_ROWS = 5_000
#: 수집 한 번이 정리에 쓰는 시간(초). 배치는 따로 commit되므로 ingest를 붙잡지 않는다.
PRUNE_BUDGET_SECONDS = 60.0


async def prune_fuel_statistics(session: AsyncSession, source: str, *, batch_rows: int = PRUNE_BATCH_ROWS) -> int:
    """이전 공개 세대를 오래된 것부터 최대 ``batch_rows``행 지운다. 준비 중이거나 최신인 세대는 보존한다.

    후보 선택과 삭제를 한 문장으로 둔다. 예전에는 키 2,000개를 읽어 `(키 4열) IN ((...), ...)` 8,000개
    매개변수로 다시 보냈는데, 운영 ARM에서 그 문장의 계획만 3.2초였고(행 튜플 IN이 기본키 탐색 2,000개의
    BitmapOr가 된다) 컴파일·prepare까지 더해 첫 배치가 15초 예산을 다 써 수집마다 2,000행만 지웠다.
    하위 질의 IN은 세대 색인 순서 읽기 + 기본키 중첩 루프로 계획되고 계획 시간은 행 수와 무관하다.
    """
    p = FuelStatisticsPoint
    stamp = select(FuelStatisticsState.generated_at).where(FuelStatisticsState.source == source).scalar_subquery()
    # 공개 전환과 별도 트랜잭션이다. 취소/실패하면 다음 수집이 이어서 정리한다.
    candidates = select(p.source, p.station_key, p.product_code, p.generated_at).where(
        p.source == source, p.generated_at < stamp,
    ).order_by(p.generated_at).limit(batch_rows)
    if session.bind.dialect.name == "postgresql":
        # 동시 정리끼리 같은 행을 기다리지 않는다. 공개 세대 쓰기와는 행이 겹치지 않는다.
        candidates = candidates.with_for_update(skip_locked=True)
    result = await session.execute(
        delete(p).where(tuple_(p.source, p.station_key, p.product_code, p.generated_at).in_(candidates))
        .execution_options(synchronize_session=False),
    )
    return result.rowcount or 0


@dataclass(frozen=True, slots=True)
class FuelStatisticsCleanup:
    """수집 한 번의 이전 세대 정리 결과. 원천 성공과 분리하되 결과는 op metadata·로그로 보이게 한다.

    - ``done``: 지울 이전 세대가 더 없다.
    - ``budget_exhausted``: 예산이 끝나 이전 세대가 남았다. 다음 수집이 이어서 지운다(정상 따라잡기).
    - ``failed``: 정리 문장이 실패했다(``cause``는 가린 한 줄). 지운 배치는 이미 commit됐다.
    """

    deleted: int
    outcome: Literal["done", "budget_exhausted", "failed"]
    cause: str | None = None

    def metadata(self) -> dict[str, Any]:
        """수집 결과 dict에 싣는 값(원문·SQL 없이 결과 종류와 행 수만)."""
        return {"fuel_statistics_cleanup": self.outcome, "fuel_statistics_pruned_rows": self.deleted}


async def cleanup_fuel_statistics(
    session: AsyncSession, source: str, *, budget_seconds: float = PRUNE_BUDGET_SECONDS,
    batch_rows: int = PRUNE_BATCH_ROWS, clock: Callable[[], float] = time.monotonic,
) -> FuelStatisticsCleanup:
    """공개 잠금 없이 짧은 정리 트랜잭션을 반복한다. 실패는 수집 성공과 분리하되 결과로 돌려준다.

    예산은 배치 사이에서만 본다(한 배치는 짧은 한 문장). 세대 하나(약 3만 행)보다 수집 한 번의
    정리량이 훨씬 커서 쌓인 세대도 몇 번의 수집 안에 따라잡는다. 실패·예산 소진은 경고로 남긴다 —
    유가 op들이 이 logger를 Dagster event log로 넘긴다(`definitions.FUEL_STATISTICS_LOGGERS`).
    """
    deadline = clock() + budget_seconds
    deleted = 0
    drained = False
    try:
        while clock() < deadline:
            count = await prune_fuel_statistics(session, source, batch_rows=batch_rows)
            await session.commit()
            deleted += count
            if count < batch_rows:
                drained = True
                break
    except Exception as exc:
        await session.rollback()
        cause = _deferred_cause(exc)
        logger.warning("fuel statistics cleanup failed source=%s deleted=%s cause=%s; "
                       "previous generations remain until the next collection", source, deleted, cause)
        return FuelStatisticsCleanup(deleted, "failed", cause)
    if not drained:
        logger.warning("fuel statistics cleanup budget exhausted source=%s deleted=%s budget=%ss; "
                       "previous generations remain and the next collection continues", source, deleted,
                       budget_seconds)
        return FuelStatisticsCleanup(deleted, "budget_exhausted")
    if deleted:
        logger.info("fuel statistics cleanup source=%s deleted=%s", source, deleted)
    return FuelStatisticsCleanup(deleted, "done")


async def _legacy_global_rankings(session: AsyncSession, source: str, scope: str,
                                  selected_key: str | None, generated_at: datetime | None,
                                  current: list[FuelStatisticsDaily]) -> dict[str, list[dict]]:
    """현재 전체 모집단의 동결 point로만 구 순위를 보완한다. 통계/원본 쓰기는 없다.

    지역·노선의 과거 membership은 point에 없으므로 현재 기준정보로 추정하지 않는다.
    별도 SQL이 읽는 현재 state/daily/point는 한 snapshot이고, 그 사이 세대나 집계가
    바뀌었거나 point가 일부 없으면 원래 알려진 최저가 한 곳을 그대로 유지한다.
    """
    needed = {row.product_code: row.metrics_json for row in current
              if row.scope_key == selected_key and not row.metrics_json.get("ranking_complete")}
    if scope not in {"nationwide", "highways"} or selected_key != "all" or not generated_at or not needed:
        return {}
    p, d, state = FuelStatisticsPoint, FuelStatisticsDaily, FuelStatisticsState
    partition = [p.product_code]
    ranked = select(
        p.product_code, p.station_key, p.name, p.address, p.longitude, p.latitude, p.price,
        d.metrics_json, func.row_number().over(partition_by=partition,
            order_by=[p.price, p.station_key]).label("rank"),
        func.count().over(partition_by=partition).label("count"),
        func.avg(p.price).over(partition_by=partition).label("average"),
        func.min(p.price).over(partition_by=partition).label("minimum"),
        func.max(p.price).over(partition_by=partition).label("maximum"),
    ).select_from(p).join(state, and_(p.source == state.source, p.generated_at == state.generated_at)).join(d, and_(
        d.source == state.source, d.day == state.day, d.generated_at == state.generated_at,
        d.scope == scope, d.scope_key == selected_key, d.product_code == p.product_code,
    )).where(state.source == source, state.generated_at == generated_at,
             p.product_code.in_(needed), p.price > 0).subquery()
    rows = (await session.execute(select(ranked).where(ranked.c.rank <= 10)
                                  .order_by(ranked.c.product_code, ranked.c.rank))).mappings()
    result: dict[str, list[dict]] = {}
    for row in rows:
        metrics = needed[row["product_code"]]
        if (row["metrics_json"] != metrics or row["count"] != metrics["station_count"]
                or any(not math.isclose(float(row[name]), float(metrics[name + "_price"]), abs_tol=.011, rel_tol=0)
                       for name in ("average", "minimum", "maximum"))):
            continue
        result.setdefault(row["product_code"], []).append({
            **{key: row[key] for key in ("station_key", "name", "address", "longitude", "latitude")},
            "price": float(row["price"]),
        })
    return {product: values for product, values in result.items()
            if len(values) == min(10, needed[product]["station_count"])}


async def fuel_statistics_page(session: AsyncSession, scope: str, product_code: str,
                               scope_key: str | None = None) -> dict:
    source = OPINET if scope in {"nationwide", "sido", "sigungu"} else HIGHWAY
    d, state = FuelStatisticsDaily, FuelStatisticsState
    product_filter = literal(True) if product_code == "ALL" else d.product_code == product_code
    current_keys = select(d.scope_key).join(state, and_(
        d.source == state.source, d.day == state.day, d.generated_at == state.generated_at,
    )).where(d.source == source, d.scope == scope, product_filter).distinct().cte("fuel_current_keys")
    chosen = func.coalesce(
        select(current_keys.c.scope_key).where(current_keys.c.scope_key == scope_key).scalar_subquery(),
        select(func.min(current_keys.c.scope_key)).scalar_subquery(),
    )
    day_start = func.date(state.day, "-29 days") if session.bind.dialect.name == "sqlite" else state.day - 29
    # 현재 범주와 선택 범주의 30일 이력을 한 SQL snapshot에서 읽는다.
    # 발행의 delete/insert 사이 또는 자정 보관 정리 사이를 섞어 읽지 않는다.
    rows = (await session.execute(select(d, state.generated_at, state.day, chosen).select_from(state).outerjoin(d, and_(
        d.source == state.source, d.scope == scope, product_filter,
        d.day.between(day_start, state.day), d.generated_at <= state.generated_at,
        or_(and_(d.day == state.day, d.generated_at == state.generated_at), d.scope_key == chosen),
    )).where(state.source == source).order_by(d.scope_key, d.day, d.product_code))).all()
    generated_at = rows[0][1] if rows else None
    selected_key = rows[0][3] if rows else None
    current = [row[0] for row in rows if row[0] is not None and row[0].day == row[2]
               and serialize_utc(row[0].generated_at) == serialize_utc(row[1])]
    legacy_rankings = await _legacy_global_rankings(session, source, scope, selected_key, generated_at, current)
    history = [{"day": row[0].day, "generated_at": row[0].generated_at,
                "product_code": row[0].product_code,
                "average_price": row[0].metrics_json["average_price"],
                "station_count": row[0].metrics_json["station_count"],
                "minimum_price": row[0].metrics_json.get("minimum_price"),
                "maximum_price": row[0].metrics_json.get("maximum_price"),
                "cheapest_station": row[0].metrics_json.get("cheapest_station")}
               for row in rows if row[0] is not None and row[0].scope_key == selected_key]
    collection = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == source))
    pending = bool(collection and collection.last_success_at and (
        generated_at is None or serialize_utc(collection.last_success_at) > serialize_utc(generated_at)))
    return {"scope": scope, "product_code": product_code, "history_scope_key": selected_key,
            "generated_at": generated_at, "update_pending": pending,
            "items": [{**row.metrics_json, "scope_key": row.scope_key, "label": row.label,
                       "generated_at": row.generated_at, "product_code": row.product_code,
                       "cheapest_stations": (legacy_rankings.get(row.product_code)
                           or row.metrics_json.get("cheapest_stations", [])) if row.scope_key == selected_key else [],
                       "ranking_complete": bool(row.scope_key == selected_key and (
                           row.metrics_json.get("ranking_complete") or row.product_code in legacy_rankings))}
                      for row in current], "history": history}


#: 장기 추이 한 유종의 최대 점 수. 일 단위 약 13개월, 주 단위 약 7.7년, 월 단위 약 33년이다.
HISTORY_MAX_POINTS = 400
HISTORY_BUCKETS = ("day", "week", "month")
HISTORY_MIN_DAY = date(2000, 1, 1)
HISTORY_MAX_DAY = date(9999, 12, 31)
#: 버킷 평균의 정의(응답 ``average_method``). 주유소 수로 가중하지 않는다.
HISTORY_AVERAGE_METHOD = "mean_of_daily_averages"
#: 화면과 같은 유종 순서(휘발유→경유→고급유→LPG→등유). 그 밖은 코드 순으로 뒤에 둔다.
_PRODUCT_ORDER = {code: index for index, code in enumerate(("B027", "D047", "B034", "K015", "C004"))}


class FuelHistoryRequestError(ValueError):
    """장기 추이 요청이 계약 밖이다(HTTP 422)."""


def _bucket_start(day: date, bucket: str) -> date:
    if bucket == "week":
        return day - timedelta(days=day.weekday())  # ISO 주: 월요일 시작
    if bucket == "month":
        return day.replace(day=1)
    return day


def _bucket_count(start: date, end: date, bucket: str) -> int:
    if bucket == "month":
        return (end.year - start.year) * 12 + end.month - start.month + 1
    if bucket == "week":
        return (_bucket_start(end, "week") - _bucket_start(start, "week")).days // 7 + 1
    return (end - start).days + 1


def _months_before(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 - months
    return date(index // 12, index % 12 + 1, 1)


async def fuel_statistics_history(session: AsyncSession, scope: str, scope_key: str | None, product_code: str,
                                  from_day: date | None, to_day: date | None, bucket: str = "auto") -> dict:
    """공개 세대까지의 장기 일별 요약을 일·주·월 점으로 돌려준다. 순위 JSON은 읽지 않는다.

    - 공개 state와 추이 행을 한 SQL snapshot에서 읽고, 공개 세대 날짜·시각보다 새 행은 내지 않는다(``to``는 공개 날짜로 낮춘다).
    - ``from``이 없으면 저장된 첫 날짜부터다(``to`` 기준 ``HISTORY_MAX_POINTS``개월 전까지만 읽는다).
    - 버킷 평균은 그 버킷에 기록이 있는 날짜들의 일별 평균을 같은 비중으로 평균한다(주유소 수 가중 아님). 최저·최고는
      일별 최저의 최저·일별 최고의 최고, 주유소 수는 일별 주유소 수 평균(반올림), ``generated_at``은 버킷 마지막 날의 세대다.
    - ``auto``는 실제 기록 범위가 ``HISTORY_MAX_POINTS``점 안에 드는 가장 작은 버킷(일→주→월)을 고른다. 버킷을 지정했는데
      한 유종의 점이 그보다 많아지는 범위면 ``FuelHistoryRequestError``다.
    """
    source = OPINET if scope in {"nationwide", "sido", "sigungu"} else HIGHWAY
    if scope_key is None:
        if scope not in {"nationwide", "highways"}:
            raise FuelHistoryRequestError("이 범위는 scope_key가 필요합니다(통계 페이지의 history_scope_key·items[].scope_key).")
        scope_key = "all"
    for value in (from_day, to_day):
        if value is not None and not HISTORY_MIN_DAY <= value <= HISTORY_MAX_DAY:
            raise FuelHistoryRequestError(f"날짜는 {HISTORY_MIN_DAY}~{HISTORY_MAX_DAY} 사이여야 합니다.")
    if from_day is not None and to_day is not None:
        if from_day > to_day:
            raise FuelHistoryRequestError("from은 to보다 늦을 수 없습니다.")
        if _bucket_count(from_day, to_day, "month") > HISTORY_MAX_POINTS:
            raise FuelHistoryRequestError(f"조회 기간은 {HISTORY_MAX_POINTS}개월 이하여야 합니다.")
    h, state = FuelStatisticsHistory, FuelStatisticsState
    # 공개 날짜보다 새 날짜·세대는 읽지 않는다. 같은 문장이 state를 읽으므로 공개 전환과 섞이지 않는다.
    conditions = [h.source == state.source, h.scope == scope, h.scope_key == scope_key,
                  h.day <= state.day, h.generated_at <= state.generated_at]
    if product_code != "ALL":
        conditions.append(h.product_code == product_code)
    if to_day is not None:
        conditions.append(h.day <= to_day)
    if from_day is not None:
        conditions.append(h.day >= from_day)
    # 읽는 양은 실제 끝(min(to, 공개 날짜)) 기준 월 단위 최대 점 수(약 33년)로 묶는다. 정확한 달 경계는 아래에서 자른다.
    # to가 공개 날짜보다 한참 늦어도(9999-12-31 같은 "끝 없음") 하한이 공개 날짜 기준이라 빈 응답이 되지 않는다.
    span = HISTORY_MAX_POINTS * 31
    if session.bind.dialect.name == "sqlite":
        bound = state.day if to_day is None else func.min(state.day, to_day.isoformat())
        conditions.append(h.day >= func.date(bound, f"-{span} days"))
    else:
        bound = state.day if to_day is None else func.least(state.day, to_day)
        conditions.append(h.day >= bound - span)
    rows = (await session.execute(select(
        state.generated_at.label("state_generated_at"), state.day.label("state_day"),
        h.product_code, h.day, h.generated_at, h.label, h.average_price, h.minimum_price, h.maximum_price,
        h.station_count,
    ).select_from(state).outerjoin(h, and_(*conditions)).where(state.source == source)
        .order_by(h.product_code, h.day))).all()
    generated_at = rows[0].state_generated_at if rows else None
    state_day = rows[0].state_day if rows else None
    end = to_day if state_day is None else min(to_day, state_day) if to_day is not None else state_day
    points = [row for row in rows if row.day is not None]
    if end is not None and from_day is not None and from_day <= end             and _bucket_count(from_day, end, "month") > HISTORY_MAX_POINTS:
        raise FuelHistoryRequestError(f"조회 기간은 {HISTORY_MAX_POINTS}개월 이하여야 합니다.")
    if end is not None:
        floor = _months_before(end, HISTORY_MAX_POINTS - 1)
        points = [row for row in points if row.day >= floor]
    if points:
        first = min(row.day for row in points)
        start = max(first, from_day) if from_day is not None else first
    else:
        # 공개 날짜보다 늦은 from은 아직 기록이 없는 범위다. 요청하지 않은 하루 범위를 지어내지 않는다.
        start = from_day if from_day is not None and (end is None or from_day <= end) else (
            None if from_day is not None else end)
    chosen = "day" if bucket == "auto" else bucket
    if points and bucket == "auto":
        chosen = next((name for name in HISTORY_BUCKETS if _bucket_count(start, end, name) <= HISTORY_MAX_POINTS), "month")
    elif points and _bucket_count(start, end, bucket) > HISTORY_MAX_POINTS:
        raise FuelHistoryRequestError(
            f"{bucket} 단위 점이 {HISTORY_MAX_POINTS}개를 넘습니다. from을 늦추거나 bucket=week·month·auto를 쓰세요.")
    grouped: dict[tuple[str, date], list] = {}
    for row in points:
        grouped.setdefault((row.product_code, _bucket_start(row.day, chosen)), []).append(row)
    result = []
    for (product, bucket_day), members in sorted(grouped.items(), key=lambda item: (
            _PRODUCT_ORDER.get(item[0][0], len(_PRODUCT_ORDER)), item[0][0], item[0][1])):
        last = members[-1]
        minimums = [float(row.minimum_price) for row in members if row.minimum_price is not None]
        maximums = [float(row.maximum_price) for row in members if row.maximum_price is not None]
        result.append({
            "product_code": product, "day": bucket_day, "first_day": members[0].day, "last_day": last.day,
            "day_count": len(members), "generated_at": last.generated_at,
            "average_price": round(sum(float(row.average_price) for row in members) / len(members), 2),
            "minimum_price": min(minimums) if minimums else None,
            "maximum_price": max(maximums) if maximums else None,
            "station_count": round(sum(row.station_count for row in members) / len(members)),
        })
    collection = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == source))
    pending = bool(collection and collection.last_success_at and (
        generated_at is None or serialize_utc(collection.last_success_at) > serialize_utc(generated_at)))
    return {"scope": scope, "scope_key": scope_key, "product_code": product_code, "source": source,
            "label": max(points, key=lambda row: row.day).label if points else None,
            "bucket": chosen, "average_method": HISTORY_AVERAGE_METHOD, "max_points": HISTORY_MAX_POINTS,
            "from_day": start, "to_day": end, "generated_at": generated_at, "update_pending": pending,
            "points": result}


def with_publication_status(items: list[dict], last_success_at: datetime | None) -> list[dict]:
    # 가격 원본이 먼저 성공한 경우도 매 요청 확인한다. 캐시된 통계 값은 수정하지 않는다.
    return [{**item, "update_pending": bool(last_success_at and
             serialize_utc(last_success_at) > serialize_utc(item["generated_at"]))} for item in items]



async def viewport_fuel_statistics(session: AsyncSession, bounds: tuple[float, float, float, float],
                                   sources: list[str], products: list[str], query: str | None,
                                   filters: "FuelStationFilters | None" = None) -> list[dict]:
    """현재 화면 전체를 한 SQL로 집계한다. marker limit/cluster/원본 이력과 무관하다."""
    state = await session.get(FuelStatisticsState, OPINET)
    if state is None or (sources and OPINET not in sources):
        return []
    key = (session.bind, serialize_utc(state.generated_at), bounds, tuple(sorted(products)), (query or "").strip(),
           filters.key() if filters is not None else ())
    cached = _viewport_cache.get(key)
    if cached and cached[0] > time.monotonic():
        _viewport_cache.move_to_end(key)
        return cached[1]
    p = FuelStatisticsPoint
    conditions = [p.source == OPINET, p.longitude.between(bounds[0], bounds[2]),
                  p.latitude.between(bounds[1], bounds[3])]
    if products:
        conditions.append(p.product_code.in_(products))
    if query and query.strip():
        conditions.append(or_(*(column.icontains(query.strip(), autoescape=True)
                                for column in (p.name, p.brand_name, p.address))))
    # 가격·코드만 물질화해 큰 문자열 정렬과 전체 행 row_number를 피한다.
    candidates = select(p.product_code, p.price, p.station_key).join(FuelStatisticsState, and_(
        p.source == FuelStatisticsState.source, p.generated_at == FuelStatisticsState.generated_at,
    ))
    if filters is not None and filters.active:
        # 공개 화면 필터(셀프·상표 등)는 주유소 행 조건이다. 같은 조건을 지도 마커와 공유한다.
        candidates = candidates.join(FuelStation, station_for_point(p))
        conditions.extend([*filters.station_conditions(), *filters.point_conditions()])
    candidates = candidates.where(*conditions).cte("fuel_candidates")
    c = candidates.c
    aggregates = select(
        c.product_code, func.count().label("count"), func.avg(c.price).label("average"),
        func.min(c.price).label("minimum"), func.max(c.price).label("maximum"),
        func.avg(cast(c.price, Float) * cast(c.price, Float)).label("mean_square"),
    ).group_by(c.product_code).cte("fuel_aggregates")
    a = aggregates.c
    cheapest = select(c.product_code, func.min(c.station_key).label("station_key"),
                      func.count().label("cheapest_count")).join(aggregates, and_(
        c.product_code == a.product_code, c.price == a.minimum,
    )).group_by(c.product_code).cte("fuel_cheapest")
    rows = (await session.execute(select(
        a, cheapest.c.cheapest_count, p.generated_at,
        p.station_key, p.name, p.address, p.longitude, p.latitude,
    ).join(cheapest, cheapest.c.product_code == a.product_code).join(p, and_(
        p.source == OPINET, p.generated_at == select(FuelStatisticsState.generated_at).where(
            FuelStatisticsState.source == OPINET,
        ).scalar_subquery(),
        p.product_code == a.product_code, p.station_key == cheapest.c.station_key,
    )).order_by(a.product_code))).mappings()
    result = [{"product_code": row["product_code"], "generated_at": row["generated_at"],
               **_metrics(row["count"], float(row["average"]), float(row["minimum"]), float(row["maximum"]),
                          float(row["mean_square"]), {name: row[name] for name in
                          ("station_key", "name", "address", "longitude", "latitude")}, row["cheapest_count"])}
              for row in rows]
    _viewport_cache[key] = (time.monotonic() + 10, result)
    _viewport_cache.move_to_end(key)
    while len(_viewport_cache) > 64:
        _viewport_cache.popitem(last=False)
    return result
