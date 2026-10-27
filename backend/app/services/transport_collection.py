"""고속도로와 오피넷 교통·유가 데이터의 수집 및 PostgreSQL 저장."""

from __future__ import annotations

from app.services.fuel_statistics import cleanup_fuel_statistics, try_publish_fuel_statistics

import asyncio
import hashlib
import json
import logging
import re
import time
import traceback
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import islice
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from krex import Incident, KrexClient, KrexParseError, KrexQuotaExceededError, TrafficFlow
from opinet import OpinetCheckpointBusyError
from opinet.experimental import (
    BrowserStation,
    OpinetBrowserCollector,
    OpinetBrowserSnapshot,
)
from sqlalchemy import JSON, Integer, and_, cast, func, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.models import (
    CollectionRun,
    FuelLatestPrice,
    FuelPriceSnapshot,
    FuelStation,
    HighwayIncidentSnapshot,
    HighwayTrafficSnapshot,
    RawApiResponse,
    TransportCollectionState,
)
from app.services.collection import KAC_QUOTA_SOURCE

logger = logging.getLogger(__name__)

TRAFFIC_SOURCE = "krex_traffic_flow"
INCIDENT_SOURCE = "krex_traffic_incident"
OPINET_SOURCE = "opinet_browser"
# 정기 수집은 약 8시간 간격이다. 세 번 연속 성공하지 못하면 최신 유가를 오래됐다고 표시한다.
FUEL_STALE_AFTER = timedelta(hours=24)
KREX_PAGE_SIZE = 1000
KREX_MAX_PAGES = 100
KREX_MAX_FILTER_VALUES = 20
TRANSPORT_COLLECTION_ADVISORY_LOCK_KEY = 420040
TRANSPORT_TRIGGER_PREFIX = "transport_"
HIGHWAY_FETCH_TIMEOUT_SECONDS = 120
# 직전 동일 scope 성공 집합의 25% 미만은 완결 증거를 재확인한다.
HIGHWAY_ABNORMAL_DROP_FACTOR = 4
#: 유가 브라우저 수집(Playwright로 오피넷 화면 조회)의 상한. odroid(ARM, CPU 포화)에서 성공한 수집이
#: 5,946~6,371초 걸리고 옛 상한 7,200초 근처에서 시간 초과가 반복돼(2026-10-23 소유자 결정) 3.5시간으로
#: 올린다. 저장·정리 여유를 두고 job 전체 상한(`definitions.MAX_RUNTIME_SECONDS - 60` = 14,340초)과
#: Dagster run 상한(14,400초) 안에 들어야 한다 — `test_fuel_fetch_timeout_fits_inside_job_budget`이 지킨다.
FUEL_FETCH_TIMEOUT_SECONDS = 12_600
#: 성공한 유가 수집의 다음 예정은 수집 **시작** + 주기(8시간)에서 이만큼 당긴다. 정기 schedule은 8시간 정각마다
#: tick하고 run의 실제 시작은 tick보다 큐·기동 지연만큼 늦는데, 그 지연은 run마다 다르다. 시작 + 8시간을 그대로
#: 쓰면 다음 run의 지연이 조금만 짧아도 다음 tick이 "아직 이르다"로 건너뛰어 실제 주기가 16시간이 된다
#: (2026-10-23 소유자 결정, ADR-013 개정). 당기는 폭은 지연의 흔들림만 덮는 크기라, Dagster 정기 실행은 여전히
#: 8시간 tick마다다(KST 00·08·16시, 하루 3 tick). tick 없이 예정 시각까지 자는 in-process scheduler는 이 폭을
#: 되돌려 기다린다(`next_collection_delay`) — 그렇지 않으면 7시간 45분마다 돈다.
FUEL_NEXT_DUE_START_SLACK = timedelta(minutes=15)
#: 유가 스냅샷 upsert 한 문장에 싣는 행 수. bind 파라미터 상한(PostgreSQL·SQLite 32,767)과 수집 엔진의
#: 문장당 `command_timeout`(60초) 안에 들도록 정한다. 주유소 41열 x 500 = 20,500개, 유가 9열 x 2,000 = 18,000개.
FUEL_STATION_UPSERT_BATCH = 500
FUEL_PRICE_UPSERT_BATCH = 2_000
#: 기존 소통 관측 조회와 ORM flush의 일시 보유량을 제한한다. pair 400개는 SQLite 999 bind 안에도 든다.
TRAFFIC_SNAPSHOT_BATCH = 400
#: 유가 스냅샷 저장 시도 횟수. 일시적 DB 오류(`_is_transient_database_error`)에만 한 번 더 저장한다.
FUEL_STORE_ATTEMPTS = 2
CollectionScope = Literal["all", "highway", "fuel"]

T = TypeVar("T")


async def fuel_read_model_freshness(
    session: AsyncSession,
) -> tuple[bool, TransportCollectionState | None]:
    """최신 유가가 오래됐는지와 그 근거인 오피넷 수집 상태를 돌려준다.

    `fuel_latest_prices`는 원본과 같은 트랜잭션에서 갱신되므로 원본과 어긋나지
    않는다(0022). 남은 위험은 수집 자체가 멈추거나 실패하는 것뿐이라 그것만 본다.
    저장된 가격이 하나도 없으면 오래된 가격도 없으므로 stale이 아니다.
    """
    state = await session.scalar(select(TransportCollectionState).where(
        TransportCollectionState.source == OPINET_SOURCE,
    ))
    has_prices = await session.scalar(select(FuelLatestPrice.fuel_station_id).limit(1)) is not None
    if not has_prices:
        return False, state
    stale = (
        state is None
        or state.last_success_at is None
        or state.last_error is not None
        or now_utc() - serialize_utc(state.last_success_at) > FUEL_STALE_AFTER
    )
    return stale, state


async def get_or_create_state(session: AsyncSession, source: str) -> TransportCollectionState:
    state = await session.scalar(
        select(TransportCollectionState).where(TransportCollectionState.source == source)
    )
    if state is None:
        if session.bind.dialect.name == "postgresql":
            # 서로 다른 수집 작업의 첫 실행이 같은 상태 행을 동시에 만들어도
            # 원본 트랜잭션을 unique 충돌로 되돌리지 않는다.
            await session.execute(text(
                "INSERT INTO transport_collection_states (source, updated_at) "
                "VALUES (:source, :updated_at) ON CONFLICT (source) DO NOTHING"
            ), {"source": source, "updated_at": now_utc()})
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == source,
            ))
        else:
            state = TransportCollectionState(source=source, updated_at=now_utc())
            session.add(state)
            await session.flush()
    return state


async def upsert_latest_fuel_prices(
    session: AsyncSession, *, collected_at: datetime | None = None,
) -> None:
    """원본 유가 행에서 주유소·유종별 최신 행을 `fuel_latest_prices`에 반영한다.

    `collected_at`을 주면 그 수집 배치가 쓴 행만 읽는다(수집 경로). 생략하면 전 이력을
    다시 읽는다(테스트 시드·수동 복구). 기존 행보다 오래된 원본은 덮어쓰지 않는다 —
    순서 기준은 MV 시절과 같은 `(collected_at, id)`다.
    """
    ranked = select(
        FuelPriceSnapshot.fuel_station_id, FuelPriceSnapshot.product_code,
        FuelPriceSnapshot.id.label("snapshot_id"), FuelPriceSnapshot.price,
        FuelPriceSnapshot.provider_updated_at, FuelPriceSnapshot.observed_at,
        FuelPriceSnapshot.collected_at,
        func.row_number().over(
            partition_by=(FuelPriceSnapshot.fuel_station_id, FuelPriceSnapshot.product_code),
            order_by=(FuelPriceSnapshot.collected_at.desc(), FuelPriceSnapshot.id.desc()),
        ).label("rank"),
    )
    if collected_at is not None:
        ranked = ranked.where(FuelPriceSnapshot.collected_at == collected_at)
    ranked_subquery = ranked.subquery()
    columns = ("fuel_station_id", "product_code", "snapshot_id", "price",
               "provider_updated_at", "observed_at", "collected_at")
    source_rows = select(*(ranked_subquery.c[name] for name in columns)).where(ranked_subquery.c.rank == 1)
    insert = postgresql_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(FuelLatestPrice).from_select(list(columns), source_rows)
    await session.execute(_latest_fuel_price_upsert(statement))


def _latest_fuel_price_upsert(statement: Any) -> Any:
    """원본의 (수집 시각, id) 순서를 보존하는 최신 유가 upsert."""
    table = FuelLatestPrice.__table__
    return statement.on_conflict_do_update(
        index_elements=["fuel_station_id", "product_code"],
        set_={name: statement.excluded[name] for name in (
            "snapshot_id", "price", "provider_updated_at", "observed_at", "collected_at",
        )},
        where=or_(
            statement.excluded.collected_at > table.c.collected_at,
            and_(
                statement.excluded.collected_at == table.c.collected_at,
                statement.excluded.snapshot_id >= table.c.snapshot_id,
            ),
        ),
    )


def highway_scope_key(settings: Settings, source: str) -> str:
    """수집과 export가 같은 원천 필터 범위를 사용한다."""
    if source == INCIDENT_SOURCE:
        return "incidents:all:v1"
    filters = [sorted(settings.transport_route_nos), sorted(settings.transport_conzone_ids)]
    return hashlib.sha256(json.dumps(filters, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class HighwayPayload:
    traffic: tuple[TrafficFlow, ...] | Exception | None
    incidents: tuple[Incident, ...] | Exception | None
    # 완결된 total_count와 실제 페이지 수가 일치한 source만 넣는다.
    complete_sources: tuple[str, ...] = ()


class TransportProvider(Protocol):
    mode: str
    enabled_sources: tuple[str, ...]

    async def collect_highway(self, *, sources: tuple[str, ...] = (TRAFFIC_SOURCE, INCIDENT_SOURCE)) -> HighwayPayload:
        """고속도로 소통·돌발 정보를 조회한다."""

    async def collect_fuel(self) -> OpinetBrowserSnapshot | None:
        """오피넷 공개 화면을 조회한다."""

    def next_fuel_interval(self) -> timedelta:
        """다음 오피넷 브라우저 수집까지의 지연을 반환한다."""

    async def aclose(self) -> None:
        """내부 HTTP/브라우저 자원을 닫는다."""


class DisabledTransportProvider:
    mode = "disabled"
    enabled_sources: tuple[str, ...] = ()

    async def collect_highway(self, *, sources: tuple[str, ...] = (TRAFFIC_SOURCE, INCIDENT_SOURCE)) -> HighwayPayload:
        return HighwayPayload(traffic=(), incidents=())

    async def collect_fuel(self) -> OpinetBrowserSnapshot | None:
        return None

    def next_fuel_interval(self) -> timedelta:
        return timedelta(hours=12)

    async def aclose(self) -> None:
        return None


class FixtureTransportProvider:
    """네트워크 키가 없는 로컬 테스트용 provider."""

    mode = "sample"
    enabled_sources: tuple[str, ...] = (TRAFFIC_SOURCE, INCIDENT_SOURCE)

    async def collect_highway(self, *, sources: tuple[str, ...] = (TRAFFIC_SOURCE, INCIDENT_SOURCE)) -> HighwayPayload:
        return HighwayPayload(traffic=(), incidents=())

    async def collect_fuel(self) -> OpinetBrowserSnapshot | None:
        return None

    def next_fuel_interval(self) -> timedelta:
        return timedelta(hours=10)

    async def aclose(self) -> None:
        return None


class LiveTransportProvider:
    """`python-krex-api`와 최신 `python-opinet-api`를 이용하는 provider."""

    mode = "live"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.krex = KrexClient(
            ex_api_key=settings.kex_ex_api_key,
            go_api_key=settings.data_go_kr_service_key,
            timeout=settings.api_timeout_seconds,
        )
        self.opinet = (
            OpinetBrowserCollector(
                query_level=settings.opinet_query_level,
                browser_channel=settings.opinet_browser_channel or None,
                timeout_ms=settings.opinet_browser_timeout_ms,
                checkpoint_path=settings.opinet_checkpoint_path or None,
            )
            if settings.opinet_browser_enabled
            else None
        )
        sources: list[str] = [TRAFFIC_SOURCE, INCIDENT_SOURCE]
        if self.opinet is not None:
            sources.append(OPINET_SOURCE)
        self.enabled_sources = tuple(sources)

    async def collect_highway(self, *, sources: tuple[str, ...] = (TRAFFIC_SOURCE, INCIDENT_SOURCE)) -> HighwayPayload:
        route_nos = self.settings.transport_route_nos
        conzone_ids = self.settings.transport_conzone_ids
        if len(route_nos) > KREX_MAX_FILTER_VALUES or len(conzone_ids) > KREX_MAX_FILTER_VALUES:
            raise ValueError(
                "TRANSPORT_ROUTE_NOS_CSV and TRANSPORT_CONZONE_IDS_CSV each allow at most "
                f"{KREX_MAX_FILTER_VALUES} values"
            )

        complete_sources: set[str] = set()

        async def fetch(source: str):
            if source not in sources:
                return None
            try:
                async with asyncio.timeout(HIGHWAY_FETCH_TIMEOUT_SECONDS):
                    if source == TRAFFIC_SOURCE:
                        # 0405는 서버 페이지/필터가 없다. 전체 응답 한 번만 읽는다.
                        page = await self.krex.traffic.flow_all()
                        total_count = getattr(page, "total_count", None)
                        if total_count is not None and total_count != len(page.items):
                            raise KrexParseError("traffic.flow returned an incomplete total_count")
                        raw = getattr(page, "raw", None)
                        if (isinstance(raw, Mapping) and ("count" in raw or "totalCount" in raw)
                                and getattr(page, "total_count", None) == len(page.items)):
                            complete_sources.add(source)
                        return tuple(
                            item for item in page.items
                            if (not route_nos or item.route_no in route_nos)
                            and (not conzone_ids or item.conzone_id in conzone_ids)
                        )
                    return await _collect_krex_pages(
                        lambda page_no: self.krex.traffic.incident(
                            num_of_rows=KREX_PAGE_SIZE, page_no=page_no,
                        ), "traffic.incident",
                        on_complete=lambda _count: complete_sources.add(source),
                    )
            except Exception as exc:
                return exc

        # 한 소스의 timeout/quota가 이미 조회한 다른 소스를 버리지 않는다.
        traffic, incidents = await asyncio.gather(fetch(TRAFFIC_SOURCE), fetch(INCIDENT_SOURCE))
        return HighwayPayload(traffic=traffic, incidents=incidents,
                              complete_sources=tuple(sorted(complete_sources)))

    async def collect_fuel(self) -> OpinetBrowserSnapshot | None:
        if self.opinet is None:
            return None
        return await self.opinet.collect_once()

    async def pending_fuel_snapshot(self) -> OpinetBrowserSnapshot | None:
        return await self.opinet.pending_snapshot() if self.opinet is not None else None

    def acknowledge_fuel_snapshot(self, snapshot: OpinetBrowserSnapshot) -> None:
        if self.opinet is not None:
            self.opinet.acknowledge_snapshot(snapshot)

    def next_fuel_interval(self) -> timedelta:
        if self.opinet is None:
            return timedelta(hours=12)
        return self.opinet.throttle.sample_run_interval(self.opinet.rng)

    async def aclose(self) -> None:
        await self.krex.aclose()


def build_transport_provider(settings: Settings) -> TransportProvider:
    if not settings.transport_collection_enabled:
        return DisabledTransportProvider()
    if (
        settings.use_sample_client_when_no_key
        and not settings.kex_ex_api_key
        and not settings.data_go_kr_service_key
    ):
        return FixtureTransportProvider()
    return LiveTransportProvider(settings)


class TransportCollectionService:
    """수집 실행을 직렬화하고 provider 결과를 정규화해 저장한다."""

    def __init__(self, settings: Settings, provider: TransportProvider | None = None) -> None:
        self.settings = settings
        self.provider = provider or build_transport_provider(settings)
        self.operation_locks = {"highway": asyncio.Lock(), "fuel": asyncio.Lock()}

    @property
    def client_mode(self) -> str:
        return self.provider.mode

    @property
    def enabled_sources(self) -> list[str]:
        return list(self.provider.enabled_sources)

    @property
    def enabled(self) -> bool:
        return self.provider.mode != "disabled"

    async def close(self) -> None:
        await self.provider.aclose()

    async def collect(
        self,
        session: AsyncSession,
        trigger: str = "transport_scheduler",
        *,
        scope: CollectionScope = "all",
    ) -> dict[str, Any]:
        if scope not in ("all", "highway", "fuel"):
            raise ValueError("알 수 없는 교통정보 수집 범위")
        groups = ("highway", "fuel") if scope == "all" else (scope,)
        async with AsyncExitStack() as stack:
            # 전체 수집도 같은 순서로 잠가 교착과 작업별 중복 실행을 막는다.
            for group in groups:
                await stack.enter_async_context(self.operation_locks[group])
                await self._acquire_database_lock(session, group)
            normalized_trigger = (
                trigger if trigger.startswith(TRANSPORT_TRIGGER_PREFIX) else f"{TRANSPORT_TRIGGER_PREFIX}{trigger}"
            )
            return await self._collect_unlocked(session, normalized_trigger, scope)

    @staticmethod
    async def _acquire_database_lock(session: AsyncSession, group: str) -> None:
        """다중 backend process가 scheduler를 중복 실행하지 않도록 잠근다."""
        bind = session.get_bind()
        if bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": TRANSPORT_COLLECTION_ADVISORY_LOCK_KEY + (group == "fuel")},
            )

    async def _collect_unlocked(
        self, session: AsyncSession, trigger: str, scope: CollectionScope
    ) -> dict[str, Any]:
        started_at = now_utc()
        run = CollectionRun(
            started_at=started_at,
            finished_at=None,
            status="running",
            trigger=trigger,
            error_message=None,
        )
        session.add(run)
        await session.flush()

        errors: list[str] = []
        raw_count = 0
        traffic_count = 0
        incident_count = 0
        fuel_station_count = 0
        fuel_price_count = 0
        # 이번 실행이 유가 통계를 새로 발행했는가(None=발행 시도 없음). op metadata로 실패를 보이게 한다.
        fuel_statistics_published: bool | None = None
        collected_source = False

        if not self.enabled:
            run.status = "skipped"
            run.finished_at = now_utc()
            await session.commit()
            summary = self._summary(
                run,
                client_mode=self.client_mode,
                raw_count=0,
                traffic_count=0,
                incident_count=0,
                fuel_station_count=0,
                fuel_price_count=0,
                errors=[],
            )
            if scope == "fuel":
                summary.update(fuel_ready=False, next_fuel_due_at=None, last_fuel_success_at=None,
                               errors=["OpiNet browser collection is unavailable (provider=disabled)."])
            return summary

        due_highway_sources = []
        if scope != "fuel":
            for source in (TRAFFIC_SOURCE, INCIDENT_SOURCE):
                if source in self.provider.enabled_sources and await self._source_is_due(session, source):
                    due_highway_sources.append(source)
        highway_sources = tuple(due_highway_sources)
        highway_due = bool(highway_sources)
        fuel_enabled = scope != "highway" and OPINET_SOURCE in self.provider.enabled_sources
        pending_fuel = None
        pending_fuel_error = None
        fuel_checkpoint_busy = False
        if fuel_enabled and (pending := getattr(self.provider, "pending_fuel_snapshot", None)) is not None:
            try:
                pending_fuel = await pending()
            except OpinetCheckpointBusyError:
                # 다른 작성자의 정상 수집 중에는 source 오류·성공·예약을 바꾸지 않는다.
                fuel_checkpoint_busy = True
            except Exception as exc:
                # 로컬 체크포인트의 잠금·손상·파일 오류도 원장과 source 상태에 남긴다.
                pending_fuel_error = exc
        fuel_storage_only = pending_fuel is not None or pending_fuel_error is not None
        fuel_due = fuel_enabled and not fuel_checkpoint_busy and (fuel_storage_only or await self._fuel_is_due(session))
        # 이미 성공 저장된 원천의 개수만 비교한다. 큰 raw 본문은 Python으로 가져오지 않는다.
        highway_baselines = {
            source: await self._highway_success_count(session, source) for source in highway_sources
        }
        claimed_sources = []
        if highway_due:
            claimed_sources.extend(highway_sources)
        if fuel_due:
            claimed_sources.append(OPINET_SOURCE)
        fuel_claim_fields = ("last_started_at", "last_success_at", "next_due_at", "last_error", "updated_at")
        fuel_claim_before: dict[str, Any] | None = None
        fuel_claim_after: tuple[Any, ...] | None = None

        def fuel_state_version(state: TransportCollectionState) -> tuple[Any, ...]:
            values = (getattr(state, name) for name in fuel_claim_fields)
            return tuple(serialize_utc(value) if isinstance(value, datetime) else value for value in values)

        for source in claimed_sources:
            if source == OPINET_SOURCE and not fuel_storage_only:
                previous = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == source).execution_options(populate_existing=True))
                if previous is not None:
                    fuel_claim_before = {name: getattr(previous, name) for name in fuel_claim_fields}
            state = await self._get_or_create_state(session, source)
            if source == OPINET_SOURCE and fuel_storage_only:
                # 이미 완료된 브라우저 결과의 저장만 재개한다. 외부 요청 예약은 유지한다.
                if state.last_started_at is None:
                    state.last_started_at = started_at
                    state.next_due_at = (started_at + self.provider.next_fuel_interval()
                                         - FUEL_NEXT_DUE_START_SLACK)
                continue
            await self._mark_source_started(session, source)
            # 외부 요청 전에 예약을 확정한다. 재시작/취소도 provider 호출 예산을 되돌리지 않는다.
            reservation = (
                self.provider.next_fuel_interval() if source == OPINET_SOURCE
                else timedelta(seconds=(FUEL_FETCH_TIMEOUT_SECONDS if fuel_due else 0) + 2 * HIGHWAY_FETCH_TIMEOUT_SECONDS + 900)
            )
            # 완료 checkpoint를 다른 실행이 먼저 저장해도 같은 정규 예약을 보존한다.
            # in-process는 이 tick 여유를 되돌려 실제 최소 수집 간격을 지킨다.
            state.next_due_at = serialize_utc(state.last_started_at) + reservation
            if source == OPINET_SOURCE:
                state.next_due_at -= FUEL_NEXT_DUE_START_SLACK
                fuel_claim_after = fuel_state_version(state)
        await session.commit()
        run_id = run.id

        # 이 구간에서는 DB 트랜잭션/connection/advisory lock을 유지하지 않는다.
        # 다른 프로세스는 짧은 claim transaction에서 next_due_at 예약을 보고 건너뛴다.
        highway_result: HighwayPayload | Exception | None = None
        fuel_result: OpinetBrowserSnapshot | Exception | None = None
        persisted_sources: set[str] = set()

        async def restore_unused_fuel_claim() -> None:
            # pending 확인과 실제 작성자 잠금 획득 사이의 경합은 외부 요청이 아니다.
            # 아직 우리 claim 그대로일 때만 되돌려 다른 실행의 성공·오류·예약은 보존한다.
            await self._acquire_database_lock(session, "fuel")
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE).execution_options(populate_existing=True))
            if state is not None and fuel_state_version(state) == fuel_claim_after:
                if fuel_claim_before is None:
                    await session.delete(state)
                else:
                    for name, value in fuel_claim_before.items():
                        setattr(state, name, value)
            await session.commit()

        async def fuel_checkpoint_was_superseded() -> bool:
            # 저장 잠금 안에서만 호출한다. state ORM identity cache에 의존하지 않는다.
            row = (await session.execute(select(
                TransportCollectionState.last_success_at, TransportCollectionState.updated_at,
                TransportCollectionState.last_error,
            ).where(TransportCollectionState.source == OPINET_SOURCE))).one_or_none()
            if row is None or row.last_success_at is None:
                return False
            candidate = fuel_result if isinstance(fuel_result, OpinetBrowserSnapshot) else pending_fuel
            if candidate is not None:
                return serialize_utc(row.last_success_at) >= serialize_utc(candidate.collected_at)
            return row.last_error is None and (
                serialize_utc(row.last_success_at) >= started_at
                or (fuel_storage_only and serialize_utc(row.updated_at) > started_at)
            )

        try:
            if highway_due:
                try:
                    async with asyncio.timeout(2 * HIGHWAY_FETCH_TIMEOUT_SECONDS):
                        highway_result = await self.provider.collect_highway(sources=highway_sources)
                except Exception as exc:
                    highway_result = exc
                highway_result = await self._confirm_highway_payload(
                    highway_result, highway_sources, highway_baselines,
                )
            if fuel_due:
                fuel_started = time.monotonic()
                logger.info("fuel browser collection started run_id=%s timeout=%ss", run_id, FUEL_FETCH_TIMEOUT_SECONDS)
                try:
                    if pending_fuel_error is not None:
                        fuel_result = pending_fuel_error
                    elif pending_fuel is not None:
                        fuel_result = pending_fuel
                        logger.info("fuel completed checkpoint resumed without browser requests run_id=%s", run_id)
                    else:
                        async with asyncio.timeout(FUEL_FETCH_TIMEOUT_SECONDS):
                            fuel_result = await self.provider.collect_fuel()
                except OpinetCheckpointBusyError:
                    fuel_checkpoint_busy = True
                    fuel_due = False
                    persisted_sources.add(OPINET_SOURCE)
                    await restore_unused_fuel_claim()
                except Exception as exc:
                    fuel_result = exc
                logger.info(
                    "fuel browser collection %s run_id=%s elapsed=%.0fs timeout=%ss",
                    "busy" if fuel_checkpoint_busy else "failed" if isinstance(fuel_result, Exception) else "finished",
                    run_id, time.monotonic() - fuel_started, FUEL_FETCH_TIMEOUT_SECONDS,
                )

            if highway_due:
                for source, field, store in (
                    (TRAFFIC_SOURCE, "traffic", self._store_traffic),
                    (INCIDENT_SOURCE, "incidents", self._store_incidents),
                ):
                    if source not in highway_sources:
                        continue
                    result = highway_result if isinstance(highway_result, Exception) else getattr(highway_result, field, None)
                    try:
                        items = await self._collect_highway_source(session, run_id, errors, source, result)
                        count = await store(session, run_id, items) if items is not None else 0
                        if source == TRAFFIC_SOURCE and items is not None:
                            await self._refresh_recent_traffic_statistics(session, items)
                        await session.commit()
                    except Exception as exc:
                        # 해당 소스만 되돌린다. 앞선 소스의 데이터·성공 상태는 이미 확정됐다.
                        await session.rollback()
                        await self._collect_highway_source(session, run_id, errors, source, exc)
                        await session.commit()
                        items = None
                    persisted_sources.add(source)
                    if items is not None:
                        collected_source = True
                        raw_count += 1
                        if source == TRAFFIC_SOURCE:
                            traffic_count += count
                        else:
                            incident_count += count

            if fuel_due:
                store_started = time.monotonic()
                error_mark = len(errors)
                checkpoint_to_ack = None
                for attempt in range(1, FUEL_STORE_ATTEMPTS + 1):
                    try:
                        # 완료 checkpoint를 동시에 읽은 실행도 저장은 직렬화한다. 잠금
                        # 획득 뒤 최신 source 시각을 다시 읽어 오래된 재생이 최신 값을 되돌리지 않는다.
                        await self._acquire_database_lock(session, "fuel")
                        if await fuel_checkpoint_was_superseded():
                            checkpoint_to_ack = fuel_result if isinstance(fuel_result, OpinetBrowserSnapshot) else None
                            snapshot = None
                            await session.commit()
                            logger.info("fuel checkpoint already committed or superseded run_id=%s; no data rewritten", run_id)
                            break
                        snapshot = await self._collect_fuel(session, run_id, errors, fuel_result,
                                                            preserve_due=fuel_storage_only)
                        if snapshot is not None:
                            fuel_station_count, fuel_price_count = await self._store_fuel_snapshot(
                                session, run_id, snapshot,
                            )
                            await self._mark_fuel_success(session, snapshot.collected_at, preserve_due=fuel_storage_only)
                        await session.commit()
                        checkpoint_to_ack = snapshot
                        break
                    except Exception as exc:
                        await session.rollback()
                        # 브라우저 수집(30~50분, 하루 최대 3회)은 이미 메모리에 있다. 저장 단계의 일시적
                        # DB 시간 초과·연결 끊김 한 번으로 그것을 버리지 않고, 공급자를 다시 부르지 않은 채
                        # 저장만 한 번 더 한다. 같은 오류가 반복되거나 다른 종류의 오류면 실패로 기록한다.
                        if attempt < FUEL_STORE_ATTEMPTS and _is_transient_database_error(exc):
                            logger.warning(
                                "fuel snapshot store attempt %s hit a transient database error; retrying once: %s",
                                attempt, _safe_error(exc, self.settings),
                            )
                            del errors[error_mark:]
                            continue
                        await self._acquire_database_lock(session, "fuel")
                        if await fuel_checkpoint_was_superseded():
                            checkpoint_to_ack = fuel_result if isinstance(fuel_result, OpinetBrowserSnapshot) else None
                            snapshot = None
                            del errors[error_mark:]
                            await session.commit()
                            break
                        await self._collect_fuel(session, run_id, errors, exc, preserve_due=fuel_storage_only)
                        await session.commit()
                        snapshot = None
                        fuel_station_count = fuel_price_count = 0
                        break
                persisted_sources.add(OPINET_SOURCE)
                logger.info(
                    "fuel snapshot store %s run_id=%s stations=%s prices=%s elapsed=%.0fs",
                    "finished" if snapshot is not None else "skipped",
                    run_id, fuel_station_count, fuel_price_count, time.monotonic() - store_started,
                )
                if checkpoint_to_ack is not None:
                    acknowledge = getattr(self.provider, "acknowledge_fuel_snapshot", None)
                    if acknowledge is not None:
                        try:
                            acknowledge(checkpoint_to_ack)
                        except Exception as exc:
                            # 원본 commit 이후의 파일 실패는 이미 확정한 성공을 취소하지 않는다.
                            logger.warning("fuel checkpoint acknowledgement failed: %s", _safe_error(exc, self.settings))
                if snapshot is not None:
                    # 원본·최신 가격·성공 상태는 이미 원자적으로 확정됐다.
                    # 통계 실패는 이 성공을 취소하거나 비싼 브라우저 재수집을 유발하지 않는다.
                    fuel_statistics_published = await try_publish_fuel_statistics(
                        session, OPINET_SOURCE, snapshot.collected_at,
                    )
                    await session.commit()
                    await cleanup_fuel_statistics(session, OPINET_SOURCE)
                    collected_source = True
                    raw_count += 1
            # rollback은 ORM 객체를 만료시키므로 async get으로 명시적으로 다시 읽는다.
            run = await session.get(CollectionRun, run_id)
            if not errors and not collected_source and raw_count == 0:
                run.status = "skipped"
            elif not errors:
                run.status = "success"
            elif raw_count == 0 and traffic_count == 0 and incident_count == 0 and fuel_station_count == 0:
                run.status = "failed"
            else:
                run.status = "partial_success"
            run.finished_at = now_utc()
            run.error_message = "\n".join(errors) if errors else None
            await session.commit()
        except (Exception, asyncio.CancelledError) as exc:
            message = "collection cancelled" if isinstance(exc, asyncio.CancelledError) else _safe_error(exc, self.settings)
            try:
                await session.rollback()
                failed_run = await session.get(CollectionRun, run_id)
                failed_run.status = "failed"
                failed_run.finished_at = now_utc()
                failed_run.error_message = message
                # 자기 실행의 종료는 source 잠금과 독립적이다. source 게시가 계속 막혀도
                # in-process 실행까지 running으로 남기지 않는다.
                await session.commit()
                for source in claimed_sources:
                    if source in persisted_sources:
                        continue
                    if source == OPINET_SOURCE:
                        await self._acquire_database_lock(session, "fuel")
                        if await fuel_checkpoint_was_superseded():
                            continue
                    state = await self._get_or_create_state(session, source)
                    state.last_error = message
                    state.updated_at = now_utc()
                await session.commit()
            except Exception as recording_error:
                try:
                    await session.rollback()
                except Exception:
                    logger.warning("transport failure state rollback failed run_id=%s", run_id)
                logger.warning("transport failure state publication failed run_id=%s: %s",
                               run_id, _safe_error(recording_error, self.settings))
                # 후행 DB 오류가 원래 취소를 일반 실패로 바꿔 scheduler 종료를 막지 않는다.
                raise exc from recording_error
            raise

        logger.info(
            "transport collection finished run_id=%s status=%s mode=%s traffic=%s incidents=%s stations=%s prices=%s errors=%s",
            run.id,
            run.status,
            self.client_mode,
            traffic_count,
            incident_count,
            fuel_station_count,
            fuel_price_count,
            len(errors),
        )
        summary = self._summary(
            run,
            client_mode=self.client_mode,
            raw_count=raw_count,
            traffic_count=traffic_count,
            incident_count=incident_count,
            fuel_station_count=fuel_station_count,
            fuel_price_count=fuel_price_count,
            errors=errors,
        )
        if scope == "fuel":
            state = (await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE).execution_options(populate_existing=True))
                     if fuel_enabled else None)
            summary.update({
                "fuel_ready": (state is not None and state.last_success_at is not None and state.last_error is None
                               and now_utc() - serialize_utc(state.last_success_at) <= FUEL_STALE_AFTER),
                "next_fuel_due_at": serialize_utc(state.next_due_at).isoformat() if state and state.next_due_at else None,
                "last_fuel_success_at": serialize_utc(state.last_success_at).isoformat() if state and state.last_success_at else None,
                "fuel_statistics_published": fuel_statistics_published,
            })
            if not fuel_enabled:
                summary["errors"] = [f"OpiNet browser collection is unavailable (provider={self.client_mode})."]
            elif run.status == "skipped" and state is not None and state.last_error:
                summary["errors"] = [state.last_error]
            if fuel_checkpoint_busy:
                summary["skip_reason"] = "collector_busy"
                if not summary["errors"]:
                    summary["errors"] = ["OpiNet browser collection is already in progress."]
        return summary

    def _highway_scope_key(self, source: str) -> str:
        return highway_scope_key(self.settings, source)

    async def _highway_success_count(self, session: AsyncSession, source: str) -> int | None:
        latest = (select(RawApiResponse.body_text).where(
            RawApiResponse.source == source, RawApiResponse.status_code == 200,
            RawApiResponse.parse_status == "received",
        ).order_by(RawApiResponse.id.desc()).limit(1).subquery())
        body = latest.c.body_text
        if session.bind.dialect.name == "postgresql":
            document = cast(body, JSON)
            scope = func.json_extract_path_text(document, "_collection_guard", "scope_key")
            count = func.coalesce(
                cast(func.json_extract_path_text(document, "_collection_guard", "item_count"), Integer),
                func.json_array_length(func.json_extract_path(document, "items")),
            )
        else:
            scope = func.json_extract(body, "$._collection_guard.scope_key")
            count = func.coalesce(func.json_extract(body, "$._collection_guard.item_count"),
                                  func.json_array_length(body, "$.items"))
        previous = (await session.execute(select(scope, count).select_from(latest))).first()
        if previous is None:
            return None
        previous_scope, previous_count = previous
        # 옛 traffic raw에는 필터가 없어 다른 scope의 크기와 비교하면 안 된다.
        if previous_scope != self._highway_scope_key(source) and not (
            previous_scope is None and source == INCIDENT_SOURCE
        ):
            return None
        return previous_count if isinstance(previous_count, int) and previous_count >= 0 else None

    @staticmethod
    def _highway_result_suspicious(result: tuple, baseline: int | None) -> bool:
        return not result or (baseline is not None and len(result) * HIGHWAY_ABNORMAL_DROP_FACTOR < baseline)

    async def _confirm_highway_payload(
        self, payload: HighwayPayload | Exception, sources: tuple[str, ...],
        baselines: dict[str, int | None],
    ) -> HighwayPayload | Exception:
        if isinstance(payload, Exception):
            return payload
        fields = {TRAFFIC_SOURCE: "traffic", INCIDENT_SOURCE: "incidents"}
        suspicious = tuple(source for source in sources
                           if isinstance(getattr(payload, fields[source]), KrexParseError)
                           or (isinstance(getattr(payload, fields[source]), tuple)
                               and self._highway_result_suspicious(
                                   getattr(payload, fields[source]), baselines[source],
                               )))
        if not suspicious:
            return payload
        # 재확인도 provider의 source 격리·기존 상한 안에서 한 번만 한다.
        # 호출 동안 DB transaction/connection은 앞선 claim commit으로 반환돼 있다.
        try:
            # source별 timeout이 gather 결과로 돌아오게 최초조회와 같은 여유를 둔다.
            async with asyncio.timeout(2 * HIGHWAY_FETCH_TIMEOUT_SECONDS):
                retried = await self.provider.collect_highway(sources=suspicious)
        except Exception as exc:
            retried = exc
        updates: dict[str, Any] = {}
        for source in suspicious:
            field = fields[source]
            first = getattr(payload, field)
            result = retried if isinstance(retried, Exception) else getattr(retried, field)
            if isinstance(result, tuple):
                recovered = not self._highway_result_suspicious(result, baselines[source])
                # 빈200의 반복만으로 완결로 인정하지 않는다. 두 응답 모두 명시한 total_count를
                # 전체 페이지와 대조했고 같은 개수일 때만 정상 소멸/급감을 수용한다.
                confirmed = (isinstance(first, tuple) and not isinstance(retried, Exception)
                             and source in payload.complete_sources
                             and source in retried.complete_sources and len(first) == len(result))
                if not recovered and not confirmed:
                    result = ValueError(
                        f"{source}: unconfirmed empty or reduced response; keeping last successful set"
                    )
            updates[field] = result
        return replace(payload, **updates)

    async def _collect_highway_source(
        self,
        session: AsyncSession,
        collection_run_id: int,
        errors: list[str],
        source: str,
        result: tuple | Exception | None,
    ) -> tuple | None:
        endpoint = "python-krex-api:traffic.flow" if source == TRAFFIC_SOURCE else "python-krex-api:traffic.incident"
        if result is None:
            result = ValueError("고속도로 provider 결과가 없습니다")
        if isinstance(result, Exception):
            message = _safe_error(result, self.settings)
            errors.append(message)
            await self._store_error_response(
                session,
                collection_run_id=collection_run_id,
                source=source,
                endpoint=endpoint,
                message=message,
            )
            await self._mark_source_failure(
                session, source, message,
                delay_seconds=(self.settings.transport_quota_backoff_seconds
                               if isinstance(result, KrexQuotaExceededError) else None),
            )
            return None
        # 저장 예외는 provider 실패와 구분해 바깥의 durable 실패 처리로 전달한다.
        await self._store_raw_response(
            session, collection_run_id=collection_run_id, source=source, endpoint=endpoint,
            body={"items": [_provider_json(item) for item in result], "_collection_guard": {
                "scope_key": self._highway_scope_key(source), "item_count": len(result),
            }},
        )
        await self._mark_source_success(session, source, now_utc())
        return result

    async def _collect_fuel(
        self,
        session: AsyncSession,
        collection_run_id: int,
        errors: list[str],
        result: OpinetBrowserSnapshot | Exception | None,
        *, preserve_due: bool = False,
    ) -> OpinetBrowserSnapshot | None:
        try:
            if isinstance(result, Exception):
                raise result
            snapshot = result
            if snapshot is None:
                raise ValueError("python-opinet-api returned no browser snapshot")
            if not snapshot.regions or not snapshot.stations:
                raise ValueError(
                    "python-opinet-api returned an empty browser snapshot; refusing to mark fuel data fresh"
                )
            if not any(price.price is not None and price.price > 0
                       for station in snapshot.stations for price in station.prices):
                raise ValueError("python-opinet-api returned no usable fuel prices")
        except Exception as exc:
            message = _safe_error(exc, self.settings)
            errors.append(message)
            await self._mark_fuel_failure(session, message, preserve_due=preserve_due)
            await self._store_error_response(
                session,
                collection_run_id=collection_run_id,
                source=OPINET_SOURCE,
                endpoint="python-opinet-api:OpinetBrowserCollector",
                message=message,
            )
            return None

        # DB 예외는 provider 오류 처리와 구분해 소스 transaction 복구 단계로 전달한다.
        await self._store_raw_response(
            session, collection_run_id=collection_run_id, source=OPINET_SOURCE,
            endpoint=snapshot.source_url,
            body={
                "collected_at": serialize_utc(snapshot.collected_at).isoformat(),
                "region_count": len(snapshot.regions),
                "station_count": len(snapshot.stations),
            },
        )
        return snapshot

    async def _store_raw_response(
        self,
        session: AsyncSession,
        *,
        collection_run_id: int,
        source: str,
        endpoint: str,
        body: Mapping[str, Any],
    ) -> None:
        session.add(
            RawApiResponse(
                collection_run_id=collection_run_id,
                source=source,
                endpoint=endpoint,
                request_params_json=None,
                status_code=200,
                body_text=json.dumps(body, ensure_ascii=False, default=str),
                received_at=now_utc(),
                parse_status="received",
                parse_error=None,
            )
        )
        await session.flush()

    async def _store_error_response(
        self,
        session: AsyncSession,
        *,
        collection_run_id: int,
        source: str,
        endpoint: str,
        message: str,
    ) -> None:
        session.add(
            RawApiResponse(
                collection_run_id=collection_run_id,
                source=source,
                endpoint=endpoint,
                request_params_json=None,
                status_code=0,
                body_text="",
                received_at=now_utc(),
                parse_status="failed",
                parse_error=message,
            )
        )
        await session.flush()

    async def _store_traffic(
        self,
        session: AsyncSession,
        collection_run_id: int,
        items: tuple[TrafficFlow, ...],
    ) -> int:
        stored = 0
        collected_at = now_utc()
        seen_keys: set[tuple[str, datetime]] = set()
        for chunk in _chunked(items, TRAFFIC_SNAPSHOT_BATCH):
            batch: list[tuple[TrafficFlow, str | None, datetime, str]] = []
            for item in chunk:
                direction = _enum_value(item.direction)
                observed_at = _parse_provider_datetime(item.updated_at, self.settings.app_timezone) or collected_at
                identity_key = _traffic_identity(item, direction)
                dedupe_key = (identity_key, observed_at)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                batch.append((item, direction, observed_at, identity_key))
            if not batch:
                continue
            # SQLite는 저장된 UTC 시각의 tzinfo를 돌려주지 않는다. provider 입력의
            # KST 기본값과 구분해 UTC로 정규화해야 같은 관측을 새 행으로 오인하지 않는다.
            existing_by_key = {
                (row.identity_key, serialize_utc(row.observed_at)): row
                for row in await session.scalars(
                    select(HighwayTrafficSnapshot).where(
                        HighwayTrafficSnapshot.source == TRAFFIC_SOURCE,
                        tuple_(HighwayTrafficSnapshot.identity_key, HighwayTrafficSnapshot.observed_at).in_(
                            [(identity_key, observed_at) for _, _, observed_at, identity_key in batch]
                        ),
                    )
                )
            }
            for item, direction, observed_at, identity_key in batch:
                existing = existing_by_key.get((identity_key, observed_at))
                if existing is not None:
                    # KREX가 동일한 관측 시각을 반복할 수 있다. 행을 하나 더 만들지는
                    # 않되, 이번 조회로 확인한 원본 값과 수집 시각은 갱신해야 공개 API가
                    # 실제 최신 확인 상태를 정확하게 표현한다.
                    existing.collection_run_id = collection_run_id
                    existing.collected_at = collected_at
                    existing.route_no = item.route_no
                    existing.route_name = item.route_name
                    existing.conzone_id = item.conzone_id
                    existing.conzone_name = item.conzone_name
                    existing.direction = direction
                    existing.speed = item.speed
                    existing.free_flow_speed = item.free_flow_speed
                    existing.congestion_level = _enum_value(item.congestion_level)
                    existing.raw_item_json = _provider_json(item)
                    continue
                session.add(
                    HighwayTrafficSnapshot(
                        collection_run_id=collection_run_id,
                        source=TRAFFIC_SOURCE,
                        identity_key=identity_key,
                        observed_at=observed_at,
                        collected_at=collected_at,
                        route_no=item.route_no,
                        route_name=item.route_name,
                        conzone_id=item.conzone_id,
                        conzone_name=item.conzone_name,
                        direction=direction,
                        speed=item.speed,
                        free_flow_speed=item.free_flow_speed,
                        congestion_level=_enum_value(item.congestion_level),
                        raw_item_json=_provider_json(item),
                    )
                )
                stored += 1
            await session.flush()
            existing_by_key.clear()
        await session.flush()
        if self.settings.transport_map_current_enabled:
            from app.services.traffic_current import update_traffic_current

            await update_traffic_current(
                session, source=TRAFFIC_SOURCE, scope_key=self._highway_scope_key(TRAFFIC_SOURCE),
                collection_run_id=collection_run_id, pairs=seen_keys, confirmed_at=collected_at,
            )
        return stored

    async def _refresh_recent_traffic_statistics(
        self,
        session: AsyncSession,
        items: tuple[TrafficFlow, ...],
    ) -> None:
        """최근 두 시간과 이번 수집의 과거 정정 bucket을 5분 집계로 다시 만든다."""
        bind = session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        current = now_utc().replace(second=0, microsecond=0)
        rebuild_from = current - timedelta(hours=2, minutes=current.minute % 5)
        await self._rebuild_traffic_statistics_range(session, rebuild_from)

        # KREX는 이미 저장한 과거 시각의 값을 정정할 수 있다. 최근 범위보다 오래된
        # 이번 수집 bucket은 좁게 별도 재집계해 stale 통계를 남기지 않는다.
        corrected_buckets: set[datetime] = set()
        for item in items:
            observed_at = _parse_provider_datetime(item.updated_at, self.settings.app_timezone)
            if observed_at is None or observed_at >= rebuild_from:
                continue
            bucket = observed_at.replace(second=0, microsecond=0)
            corrected_buckets.add(bucket - timedelta(minutes=bucket.minute % 5))
        for bucket_start in sorted(corrected_buckets):
            await self._rebuild_traffic_statistics_range(
                session,
                bucket_start,
                bucket_start + timedelta(minutes=5),
            )

    @staticmethod
    async def _rebuild_traffic_statistics_range(
        session: AsyncSession,
        rebuild_from: datetime,
        rebuild_until: datetime | None = None,
    ) -> None:
        params = {"rebuild_from": rebuild_from, "rebuild_until": rebuild_until}
        source_filter = "observed_at >= :rebuild_from"
        bucket_filter = "bucket_start >= :rebuild_from"
        if rebuild_until is not None:
            source_filter += " AND observed_at < :rebuild_until"
            bucket_filter += " AND bucket_start < :rebuild_until"
        await session.execute(
            text("DELETE FROM highway_traffic_five_minute_statistics WHERE " + bucket_filter),
            params,
        )
        await session.execute(
            text(
                """
                INSERT INTO highway_traffic_five_minute_statistics (
                    bucket_start, route_no_key, direction_key, observations,
                    speed_observations, speed_sum, minimum_speed, maximum_speed,
                    free_flow_speed_observations, free_flow_speed_sum, latest_observed_at
                )
                SELECT
                    date_bin(INTERVAL '5 minutes', observed_at, TIMESTAMPTZ '2000-01-01 00:00:00+00'),
                    COALESCE(route_no, ''), COALESCE(direction, ''), COUNT(*),
                    COUNT(speed), SUM(speed), MIN(speed), MAX(speed),
                    COUNT(free_flow_speed), SUM(free_flow_speed), MAX(observed_at)
                FROM highway_traffic_snapshots
                WHERE """ + source_filter + """
                GROUP BY 1, 2, 3
                """
            ),
            params,
        )

    async def _store_incidents(
        self,
        session: AsyncSession,
        collection_run_id: int,
        items: tuple[Incident, ...],
    ) -> int:
        stored = 0
        collected_at = now_utc()
        seen_keys: set[str] = set()
        for item in items:
            identity_key = _incident_identity(item)
            if identity_key in seen_keys:
                continue
            seen_keys.add(identity_key)
            observed_at = collected_at
            latest = await session.scalar(
                select(HighwayIncidentSnapshot)
                .where(
                    HighwayIncidentSnapshot.source == INCIDENT_SOURCE,
                    HighwayIncidentSnapshot.identity_key == identity_key,
                )
                .order_by(
                    HighwayIncidentSnapshot.observed_at.desc(),
                    HighwayIncidentSnapshot.id.desc(),
                )
                .limit(1)
            )
            if latest is not None and _incident_state_matches(latest, item):
                # 상태 변경 이력은 보존하고 실제 재관측 시각만 갱신한다.
                # 지도 TTL은 이 시각을 사용해 장기 공사/통제를 누락하지 않는다.
                latest.collected_at = max(serialize_utc(latest.collected_at), collected_at)
                continue
            existing = await session.scalar(
                select(HighwayIncidentSnapshot).where(
                    HighwayIncidentSnapshot.source == INCIDENT_SOURCE,
                    HighwayIncidentSnapshot.identity_key == identity_key,
                    HighwayIncidentSnapshot.observed_at == observed_at,
                )
            )
            if existing is not None:
                continue
            session.add(
                HighwayIncidentSnapshot(
                    collection_run_id=collection_run_id,
                    source=INCIDENT_SOURCE,
                    identity_key=identity_key,
                    observed_at=observed_at,
                    collected_at=collected_at,
                    occurred_date=item.occurred_date,
                    occurred_time=item.occurred_time,
                    incident_type=item.incident_type,
                    incident_type_code=item.incident_type_code,
                    direction=item.direction,
                    message=item.message,
                    point_name=item.point_name,
                    route_no=item.route_no,
                    route_name=item.route_name,
                    process_status=item.process_status,
                    process_status_code=item.process_status_code,
                    latitude=item.latitude,
                    longitude=item.longitude,
                    congestion_length=item.congestion_length,
                    series_no=item.series_no,
                    raw_item_json=_provider_json(item),
                )
            )
            stored += 1
        # 이번 수집이 재관측한 행은 모두 collected_at이 이 값이다. 상태의 성공 시각을 같은 값으로
        # 맞춰 service export가 "마지막 성공 수집의 활성 집합"을 정확히 고르게 한다(ADR-013).
        state = await self._get_or_create_state(session, INCIDENT_SOURCE)
        state.last_success_at = collected_at
        await session.flush()
        return stored

    async def _store_fuel_snapshot(
        self,
        session: AsyncSession,
        collection_run_id: int,
        snapshot: OpinetBrowserSnapshot,
    ) -> tuple[int, int]:
        """오피넷 스냅샷을 집합 단위 upsert로 저장하고 (새 주유소 수, 새 유가 행 수)를 돌려준다.

        행마다 select→update/insert 하던 옛 구현(운영 크기 스냅샷당 DB 호출 실측 142,621번, 운영에서 14~16분)을
        `INSERT … ON CONFLICT … DO UPDATE` 묶음으로 바꿨다. 의미는 옛 구현과 같다.

        - 주유소 키는 `(source, identity_key)`. 기존 행은 `_station_values` 열(`last_seen_at` 포함)만
          갱신하고 `first_seen_at`은 두며, 이번 스냅샷에 없는 주유소는 건드리지 않는다.
        - 유가 키는 `(fuel_station_id, source, product_code, observed_at)`. 기존 행은 `price`,
          `provider_updated_at`, `collected_at`, `raw_item_json`만 갱신하고 `collection_run_id`는 둔다.
        - 같은 키가 한 스냅샷에 두 번 오면 마지막 값이 이기고 순서(새 id 배정)는 처음 위치를 따른다.
          한 문장 안에 같은 키가 두 번 있으면 PostgreSQL ON CONFLICT가 거부하므로 미리 합친다.
        - 반환 개수는 옛 구현처럼 이번 호출이 **새로 만든** 행 수다. 갱신은 `collection_run_id`·주유소 수를
          바꾸지 않으므로 같은 트랜잭션 안의 전후 개수 차이가 곧 삽입 수다.

        트랜잭션은 나누지 않는다. `fuel_latest_prices`와 수집 성공 상태가 원본과 같은 트랜잭션에서
        확정돼야 읽는 쪽이 반쪽 스냅샷을 보지 않는다(0022). 문장 하나는 bind 파라미터 상한과
        수집 엔진의 문장당 `command_timeout`(60초) 안에 들도록 묶음 크기를 제한한다.
        """
        collected_at = serialize_utc(snapshot.collected_at, self.settings.app_timezone)
        insert = postgresql_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        station_table = FuelStation.__table__
        price_table = FuelPriceSnapshot.__table__

        station_rows: dict[str, dict[str, Any]] = {}
        station_prices: list[tuple[str, BrowserStation]] = []
        for item in snapshot.stations:
            identity_key = _station_identity(item)
            station_rows[identity_key] = {
                "source": OPINET_SOURCE,
                "identity_key": identity_key,
                "first_seen_at": collected_at,
                **_station_values(item, collected_at),
            }
            station_prices.append((identity_key, item))

        stations_before = await self._count_opinet_stations(session)
        station_ids: dict[str, int] = {}
        if station_rows:
            station_statement = insert(station_table)
            station_statement = station_statement.on_conflict_do_update(
                index_elements=["source", "identity_key"],
                set_={
                    name: station_statement.excluded[name]
                    for name in next(iter(station_rows.values()))
                    if name not in ("source", "identity_key", "first_seen_at")
                },
            ).returning(station_table.c.identity_key, station_table.c.id)
            for chunk in _chunked(station_rows.values(), FUEL_STATION_UPSERT_BATCH):
                result = await session.execute(
                    station_statement.execution_options(insertmanyvalues_page_size=len(chunk)), chunk,
                )
                station_ids.update((identity_key, station_id) for identity_key, station_id in result.all())
                del result, chunk
        # 가격 행을 만들기 전에 주유소 저장용 원본 복사본을 해제한다.
        # 재시도에 필요한 snapshot과 station_prices는 그대로 보존한다.
        station_rows.clear()
        station_count = await self._count_opinet_stations(session) - stations_before

        price_rows: dict[tuple[int, str, datetime], dict[str, Any]] = {}
        for identity_key, item in station_prices:
            station_id = station_ids[identity_key]
            raw_item = _plain_json(item.raw)
            for price in item.prices:
                provider_updated_at = (
                    serialize_utc(price.updated_at, self.settings.app_timezone)
                    if price.updated_at is not None
                    else None
                )
                observed_at = provider_updated_at or collected_at
                product_code = _enum_value(price.product_code) or "unknown"
                price_rows[(station_id, product_code, observed_at)] = {
                    "collection_run_id": collection_run_id,
                    "fuel_station_id": station_id,
                    "source": OPINET_SOURCE,
                    "product_code": product_code,
                    "price": _decimal_or_none(price.price),
                    "provider_updated_at": provider_updated_at,
                    "observed_at": observed_at,
                    "collected_at": collected_at,
                    "raw_item_json": raw_item,
                }

        prices_before = await self._count_run_fuel_prices(session, collection_run_id)
        if price_rows:
            price_statement = insert(price_table)
            price_statement = price_statement.on_conflict_do_update(
                index_elements=["fuel_station_id", "source", "product_code", "observed_at"],
                set_={
                    name: price_statement.excluded[name]
                    for name in ("price", "provider_updated_at", "collected_at", "raw_item_json")
                },
            ).returning(
                price_table.c.id.label("snapshot_id"), price_table.c.fuel_station_id,
                price_table.c.product_code, price_table.c.price, price_table.c.provider_updated_at,
                price_table.c.observed_at, price_table.c.collected_at,
            )
            for chunk in _chunked(price_rows.values(), FUEL_PRICE_UPSERT_BATCH):
                result = await session.execute(
                    price_statement.execution_options(insertmanyvalues_page_size=len(chunk)), chunk,
                )
                # 방금 쓴 원본 id를 그대로 사용한다. 전체 이력을 재검색·정렬하지 않으며
                # 기존 행의 재확인·정정도 실제 원본 id로 갱신한다.
                latest_rows: dict[tuple[int, str], dict[str, Any]] = {}
                for row in result.mappings():
                    key = (row["fuel_station_id"], row["product_code"])
                    previous = latest_rows.get(key)
                    if previous is None or row["snapshot_id"] > previous["snapshot_id"]:
                        latest_rows[key] = dict(row)
                await session.execute(
                    _latest_fuel_price_upsert(insert(FuelLatestPrice.__table__).values(list(latest_rows.values())))
                )
        price_count = await self._count_run_fuel_prices(session, collection_run_id) - prices_before
        return station_count, price_count

    @staticmethod
    async def _count_opinet_stations(session: AsyncSession) -> int:
        return int(await session.scalar(
            select(func.count()).select_from(FuelStation).where(FuelStation.source == OPINET_SOURCE)
        ) or 0)

    @staticmethod
    async def _count_run_fuel_prices(session: AsyncSession, collection_run_id: int) -> int:
        return int(await session.scalar(
            select(func.count()).select_from(FuelPriceSnapshot).where(
                FuelPriceSnapshot.collection_run_id == collection_run_id,
                FuelPriceSnapshot.source == OPINET_SOURCE,
            )
        ) or 0)

    async def _source_is_due(self, session: AsyncSession, source: str) -> bool:
        state = await session.scalar(select(TransportCollectionState).where(
            TransportCollectionState.source == source
        ))
        return state is None or state.next_due_at is None or now_utc() >= serialize_utc(state.next_due_at)

    async def _fuel_is_due(self, session: AsyncSession) -> bool:
        state = await session.scalar(
            select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE)
        )
        next_due_at = self._effective_fuel_due_at(state)
        return next_due_at is None or now_utc() >= next_due_at

    def _effective_fuel_due_at(self, state: TransportCollectionState | None) -> datetime | None:
        """수집 진입과 대기는 같은 예정 시각을 사용한다. 성공 예약의 tick 여유만 되돌린다."""
        if state is None or state.next_due_at is None:
            return None
        due = serialize_utc(state.next_due_at)
        if (self.settings.scheduler_mode == "in_process" and state.last_started_at is not None
                and due == (serialize_utc(state.last_started_at) + self.provider.next_fuel_interval()
                            - FUEL_NEXT_DUE_START_SLACK)):
            due += FUEL_NEXT_DUE_START_SLACK
        return due

    async def _mark_fuel_success(self, session: AsyncSession, collected_at: datetime, *, preserve_due: bool = False) -> None:
        """다음 예정은 수집 완료가 아니라 이번 수집의 **시작**(`last_started_at`)에서 잰다.

        완료 + 8시간은 수집이 1~2시간 걸리는 동안 다음 8시간 tick을 늘 건너뛰게 해 실제 주기가 16시간이었다.
        실패 경로도 claim 때 확정한 시작 기준 예약을 보존한다.
        """
        state = await self._get_or_create_state(session, OPINET_SOURCE)
        if state.last_started_at is None:  # claim(`_mark_source_started`)을 거치지 않은 호출은 버그다.
            raise RuntimeError("fuel success recorded without a claimed start")
        state.last_success_at = collected_at
        if not preserve_due:
            state.next_due_at = (serialize_utc(state.last_started_at) + self.provider.next_fuel_interval()
                                 - FUEL_NEXT_DUE_START_SLACK)
        state.last_error = None
        state.updated_at = now_utc()
        await session.flush()

    async def _mark_fuel_failure(self, session: AsyncSession, message: str, *, preserve_due: bool = False) -> None:
        state = await self._get_or_create_state(session, OPINET_SOURCE)
        # 비싼 수집·저장 뒤 실패한 시각에서 8시간을 다시 더하면 다음 정기 tick까지
        # 건너뛴다. 외부 조회 전에 확정한 예약은 실패·재시작에도 늘리지 않는다.
        if not preserve_due and state.last_started_at is not None:
            state.next_due_at = (serialize_utc(state.last_started_at) + self.provider.next_fuel_interval()
                                 - FUEL_NEXT_DUE_START_SLACK)
        elif state.next_due_at is None:
            state.next_due_at = serialize_utc(state.last_started_at or now_utc()) + self.provider.next_fuel_interval()
        state.last_error = message
        state.updated_at = now_utc()
        await session.flush()

    async def _mark_source_started(self, session: AsyncSession, source: str) -> None:
        state = await self._get_or_create_state(session, source)
        state.last_started_at = now_utc()
        state.updated_at = now_utc()
        await session.flush()

    async def _mark_source_success(
        self,
        session: AsyncSession,
        source: str,
        completed_at: datetime,
    ) -> None:
        state = await self._get_or_create_state(session, source)
        state.last_success_at = completed_at
        state.next_due_at = serialize_utc(state.last_started_at or completed_at) + timedelta(
            seconds=self.settings.transport_collect_interval_seconds
        )
        state.last_error = None
        state.updated_at = now_utc()
        await session.flush()

    async def _mark_source_failure(
        self,
        session: AsyncSession,
        source: str,
        message: str,
        *,
        delay_seconds: int | None = None,
    ) -> None:
        state = await self._get_or_create_state(session, source)
        delay = delay_seconds or self.settings.transport_collect_interval_seconds
        state.next_due_at = now_utc() + timedelta(seconds=delay)
        state.last_error = message
        state.updated_at = now_utc()
        await session.flush()

    async def _get_or_create_state(self, session: AsyncSession, source: str) -> TransportCollectionState:
        return await get_or_create_state(session, source)

    async def next_collection_delay(self, session: AsyncSession, scope: CollectionScope) -> float:
        """고정 tick과 DB 예정 시각의 미세한 차이 때문에 한 주기를 건너뛰지 않는다."""
        interval = self.settings.transport_collect_interval_seconds
        if scope == "fuel":
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE))
            due = self._effective_fuel_due_at(state)
            return float(interval) if due is None else max(1.0, (due - now_utc()).total_seconds())
        sources = (TRAFFIC_SOURCE, INCIDENT_SOURCE)
        due_dates = (await session.scalars(
            select(TransportCollectionState.next_due_at).where(
                TransportCollectionState.source.in_(sources)
            )
        )).all()
        if not due_dates or any(value is None for value in due_dates):
            return float(interval)
        remaining = min((serialize_utc(value) - now_utc()).total_seconds() for value in due_dates)
        return max(1.0, remaining)

    async def status(self, session: AsyncSession) -> dict[str, Any]:
        fuel_prices_stale, _read_model = await fuel_read_model_freshness(session)
        states = (
            await session.execute(
                select(TransportCollectionState).order_by(TransportCollectionState.source)
            )
        ).scalars().all()
        fuel_state = next((item for item in states if item.source == OPINET_SOURCE), None)
        recent_runs = (await session.scalars(
            select(CollectionRun)
            .where(
                CollectionRun.trigger.startswith(TRANSPORT_TRIGGER_PREFIX, autoescape=True),
                CollectionRun.status != "skipped",
            )
            .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
            .limit(10)
        )).all()
        last_run = recent_runs[0] if recent_runs else None
        def public_run(run: CollectionRun) -> dict[str, Any]:
            return {
                "id": run.id,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "status": run.status,
                "trigger": run.trigger,
                # The public endpoint deliberately exposes only a stable error marker.
                "error": "collection_failed" if run.error_message else None,
            }

        running_condition = (
            CollectionRun.trigger.startswith(TRANSPORT_TRIGGER_PREFIX, autoescape=True),
            CollectionRun.status == "running",
        )
        running_result = (await session.execute(
            select(CollectionRun, func.count().over().label("total_runs")).where(*running_condition)
            .order_by(CollectionRun.started_at, CollectionRun.id).limit(100)
        )).all()
        running_run_count = int(running_result[0].total_runs) if running_result else 0
        running_rows = [row[0] for row in running_result]
        run_items = [public_run(run) for run in recent_runs]
        return {
            "scheduler_enabled": self.settings.enable_scheduler and self.enabled,
            "collection_enabled": self.enabled,
            "collect_interval_seconds": self.settings.transport_collect_interval_seconds,
            "client_mode": self.client_mode,
            "enabled_sources": self.enabled_sources,
            "fuel_prices_stale": fuel_prices_stale,
            "last_fuel_success_at": fuel_state.last_success_at if fuel_state is not None else None,
            "next_fuel_due_at": fuel_state.next_due_at if fuel_state is not None else None,
            "last_fuel_error": fuel_state.last_error if fuel_state is not None else None,
            "last_run": run_items[0] if last_run is not None else None,
            "recent_runs": run_items,
            "running_run_count": running_run_count,
            "running_runs": [public_run(run) for run in running_rows],
            "sources": [
                {
                    "source": item.source,
                    "last_started_at": item.last_started_at,
                    "last_success_at": item.last_success_at,
                    "next_due_at": item.next_due_at,
                    "last_error": item.last_error,
                }
                # 공항 KAC 할당량 원장은 같은 표에 두지만 교통 원천이 아니다(공항 collector-status가 소유).
                for item in states if item.source != KAC_QUOTA_SOURCE
            ],
        }

    @staticmethod
    def _summary(
        run: CollectionRun,
        *,
        client_mode: str,
        raw_count: int,
        traffic_count: int,
        incident_count: int,
        fuel_station_count: int,
        fuel_price_count: int,
        errors: list[str],
    ) -> dict[str, Any]:
        return {
            "collection_run_id": run.id,
            "status": run.status,
            "client_mode": client_mode,
            "raw_response_count": raw_count,
            "traffic_snapshot_count": traffic_count,
            "incident_snapshot_count": incident_count,
            "fuel_station_count": fuel_station_count,
            "fuel_price_count": fuel_price_count,
            "errors": errors,
        }


async def _collect_krex_pages(
    fetch: Callable[[int], Awaitable[Any]],
    endpoint: str,
    *,
    on_complete: Callable[[int], None] | None = None,
) -> tuple[T, ...]:
    """페이지 전체를 읽고 provider가 보고한 total_count와 대조한다."""
    items: list[T] = []
    expected_count: int | None = None
    page_no = 1
    while True:
        page = await fetch(page_no)
        page_items = tuple(page.items)
        if page.total_count is not None:
            if page.total_count < 0:
                raise RuntimeError(f"{endpoint} returned an invalid total_count")
            if expected_count is None:
                expected_count = page.total_count
            elif page.total_count != expected_count:
                raise RuntimeError(f"{endpoint} changed total_count while paging")
        if page_no > 100 or len(items) + len(page_items) > 50_000:
            raise RuntimeError(f"{endpoint} exceeded bounded pagination budget")
        items.extend(page_items)
        if expected_count is not None:
            if len(items) > expected_count:
                raise RuntimeError(f"{endpoint} returned more items than total_count")
            if len(items) >= expected_count:
                break
            if not page_items:
                raise RuntimeError(
                    f"{endpoint} pagination ended early: expected {expected_count}, received {len(items)}"
                )
        else:
            page_size = page.num_of_rows or KREX_PAGE_SIZE
            if not page_items or len(page_items) < page_size:
                break
        if page_no >= KREX_MAX_PAGES:
            raise RuntimeError(f"{endpoint} exceeded the {KREX_MAX_PAGES}-page safety limit")
        page_no += 1
    if expected_count is not None and on_complete is not None:
        on_complete(expected_count)
    return tuple(items)


def _chunked(rows: Iterable[T], size: int) -> Iterator[list[T]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    iterator = iter(rows)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _station_identity(item: BrowserStation) -> str:
    if item.station_id:
        return f"station:{item.station_id}"
    fallback = "|".join(
        (
            item.region.sido_value,
            item.region.sigungu_value,
            item.name,
            str(item.katec_x),
            str(item.katec_y),
        )
    )
    return f"fallback:{hashlib.sha256(fallback.encode('utf-8')).hexdigest()}"


def _station_values(item: BrowserStation, seen_at: datetime) -> dict[str, Any]:
    return {
        "source_station_id": item.station_id,
        "name": item.name,
        "brand_code": item.brand_code,
        "brand_name": item.brand_name,
        "phone": item.phone,
        "address": item.address,
        "business_number": item.business_number,
        "cb_code": item.cb_code,
        "station_type": _enum_value(item.station_type),
        "query_level": item.query_level,
        "sido_value": item.region.sido_value,
        "sido_name": item.region.sido_name,
        "sigungu_value": item.region.sigungu_value,
        "sigungu_name": item.region.sigungu_name,
        "dong_value": item.region.dong_value,
        "dong_name": item.region.dong_name,
        "katec_x": item.katec_x,
        "katec_y": item.katec_y,
        "longitude": item.lon,
        "latitude": item.lat,
        "source_kinds": list(item.source_kinds),
        "is_illegal": item.is_illegal,
        "is_self": item.is_self,
        "is_24h": item.is_24h,
        "is_kpetro": item.is_kpetro,
        "is_electronic": item.is_electronic,
        "is_good": item.is_good,
        "is_good_strong": item.is_good_strong,
        "is_region_franchise": item.is_region_franchise,
        "has_carwash": item.has_carwash,
        "has_maintenance": item.has_maintenance,
        "has_cvs": item.has_cvs,
        "cs_yn": item.cs_yn,
        "discount_info": item.discount_info,
        "save_event_info": item.save_event_info,
        "representative_event_info": item.representative_event_info,
        "on_event_info": item.on_event_info,
        "other_business_info": item.other_business_info,
        "last_seen_at": seen_at,
        "raw_item_json": _plain_json(item.raw),
    }


def _traffic_identity(item: TrafficFlow, direction: str | None) -> str:
    if item.vds_id:
        return f"vds:{item.vds_id}:{direction or ''}"
    if item.conzone_id:
        return f"conzone:{item.conzone_id}:{direction or ''}"
    key = "|".join((item.route_no or "", item.route_name or "", item.conzone_name or "", direction or ""))
    return f"flow:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"


def _incident_identity(item: Incident) -> str:
    if item.series_no is not None:
        return f"series:{item.series_no}"
    key = "|".join(
        (
            item.occurred_date or "",
            item.occurred_time or "",
            item.route_no or "",
            item.point_name or "",
            item.message or "",
        )
    )
    return f"incident:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"


def _incident_state_matches(stored: HighwayIncidentSnapshot, item: Incident) -> bool:
    return (
        stored.occurred_date,
        stored.occurred_time,
        stored.incident_type,
        stored.incident_type_code,
        stored.direction,
        stored.message,
        stored.point_name,
        stored.route_no,
        stored.route_name,
        stored.process_status,
        stored.process_status_code,
        stored.latitude,
        stored.longitude,
        stored.congestion_length,
        stored.series_no,
    ) == (
        item.occurred_date,
        item.occurred_time,
        item.incident_type,
        item.incident_type_code,
        item.direction,
        item.message,
        item.point_name,
        item.route_no,
        item.route_name,
        item.process_status,
        item.process_status_code,
        item.latitude,
        item.longitude,
        item.congestion_length,
        item.series_no,
    )


def _parse_provider_datetime(value: str | None, timezone_name: str) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        digits = re.sub(r"\D", "", text)
        parsed = None
        for length, fmt in ((14, "%Y%m%d%H%M%S"), (12, "%Y%m%d%H%M"), (8, "%Y%m%d")):
            if len(digits) >= length:
                try:
                    parsed = datetime.strptime(digits[:length], fmt)
                    break
                except ValueError:
                    continue
        if parsed is None:
            return None
    return serialize_utc(parsed, timezone_name)
def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _decimal_or_none(value: float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _provider_json(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return _plain_json(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return _plain_json(value)
    return _plain_json(vars(value))


def _plain_json(value: Any) -> Any:
    value_type = type(value)
    if (
        value_type is str or value_type is int or value_type is float
        or value_type is bool or value is None
    ):
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain_json(item) for item in value]
    if isinstance(value, datetime):
        return serialize_utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return getattr(value, "value", value)


def _is_transient_database_error(error: BaseException) -> bool:
    """저장 단계에서 한 번 더 시도할 만한 DB 오류인가.

    수집 엔진은 asyncpg `command_timeout`/연결 `timeout`을 쓰는데, 둘 다 넘으면 SQLAlchemy가 번역하지 않은
    내장 `TimeoutError`(메시지 없음)가 그대로 올라온다(2026-10-12 운영 이미지에서 재현). 연결이 끊긴 경우는
    SQLAlchemy가 `connection_invalidated`로 표시한다. 제약 위반 같은 결정적 오류는 다시 해도 같으므로 제외한다.
    """
    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    if not isinstance(error, DBAPIError):
        return False
    # asyncpg의 서버 statement_timeout은 내장 TimeoutError가 아닌 SQLSTATE 57014다.
    # lock_timeout·직렬화 실패·교착도 같은 스냅샷으로 제한된 저장 재시도가 가능하다.
    return bool(error.connection_invalidated) or getattr(error.orig, "sqlstate", None) in {
        "57014", "55P03", "40001", "40P01",
    }


#: `app` 패키지 디렉터리. 우리 코드 frame을 경로 모양이 아니라 실제 위치로 가린다.
_APP_PACKAGE_DIR = Path(__file__).resolve().parents[1]


def _app_relative(filename: str) -> str | None:
    try:
        return Path(filename).resolve().relative_to(_APP_PACKAGE_DIR.parent).as_posix()
    except (OSError, ValueError):
        return None


def _frame_label(frame: traceback.FrameSummary) -> str:
    path = _app_relative(frame.filename)
    if path is None:
        normalized = frame.filename.replace("\\", "/")
        path = (normalized.rsplit("site-packages/", 1)[1] if "site-packages/" in normalized
                else normalized.rsplit("/", 1)[-1])
    return f"{path}:{frame.lineno} in {frame.name}"


def _is_app_frame(frame: traceback.FrameSummary) -> bool:
    path = _app_relative(frame.filename)
    return path is not None and path.startswith(f"{_APP_PACKAGE_DIR.name}/")


def _error_origin(error: BaseException) -> str:
    """메시지가 빈 예외의 발생 위치 — 가장 안쪽 frame과, 그것이 아니면 가장 안쪽 우리 코드(`app` 패키지) frame.

    파일·줄·함수 이름만 담는다(값·URL·인자는 담지 않는다).
    """
    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return ""
    origin = f" at {_frame_label(frames[-1])}"
    app_frames = [frame for frame in frames if _is_app_frame(frame)]
    if app_frames and app_frames[-1] is not frames[-1]:
        origin += f" (from {_frame_label(app_frames[-1])})"
    return origin


def _safe_error(error: Exception, settings: Settings) -> str:
    # 메시지가 빈 예외(예: asyncpg 시간 초과의 내장 TimeoutError)는 종류 이름만으로는 어디서 났는지 알 수 없다
    # (2026-10-07·10-10 유가 실패가 "TimeoutError" 한 단어만 남겼다). 발생 위치를 붙인다.
    message = str(error).strip() or f"{error.__class__.__name__}{_error_origin(error)}"
    for secret in (settings.kex_ex_api_key, settings.data_go_kr_service_key):
        if secret:
            message = message.replace(secret, "<redacted>")
    return " ".join(message.split())
