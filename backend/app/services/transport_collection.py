"""고속도로와 오피넷 교통·유가 데이터의 수집 및 PostgreSQL 저장."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Protocol, TypeVar
from zoneinfo import ZoneInfo

from krex import Incident, KrexClient, KrexQuotaExceededError, TrafficFlow
from opinet.experimental import (
    BrowserStation,
    OpinetBrowserCollector,
    OpinetBrowserSnapshot,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.models import (
    CollectionRun,
    FuelPriceSnapshot,
    FuelStation,
    HighwayIncidentSnapshot,
    HighwayTrafficSnapshot,
    RawApiResponse,
    TransportCollectionState,
)

logger = logging.getLogger(__name__)

TRAFFIC_SOURCE = "krex_traffic_flow"
INCIDENT_SOURCE = "krex_traffic_incident"
OPINET_SOURCE = "opinet_browser"
KREX_PAGE_SIZE = 1000
KREX_MAX_PAGES = 100
KREX_MAX_FILTER_VALUES = 20
TRANSPORT_COLLECTION_ADVISORY_LOCK_KEY = 420040
TRANSPORT_TRIGGER_PREFIX = "transport_"
HIGHWAY_FETCH_TIMEOUT_SECONDS = 120
FUEL_FETCH_TIMEOUT_SECONDS = 7200
CollectionScope = Literal["all", "highway", "fuel"]

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class HighwayPayload:
    traffic: tuple[TrafficFlow, ...] | Exception | None
    incidents: tuple[Incident, ...] | Exception | None


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
    enabled_sources: tuple[str, ...] = (TRAFFIC_SOURCE, INCIDENT_SOURCE, OPINET_SOURCE)

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

        async def fetch(source: str):
            if source not in sources:
                return None
            try:
                async with asyncio.timeout(HIGHWAY_FETCH_TIMEOUT_SECONDS):
                    if source == TRAFFIC_SOURCE:
                        # 0405는 서버 페이지/필터가 없다. 전체 응답 한 번만 읽는다.
                        page = await self.krex.traffic.flow_all()
                        return tuple(
                            item for item in page.items
                            if (not route_nos or item.route_no in route_nos)
                            and (not conzone_ids or item.conzone_id in conzone_ids)
                        )
                    return await _collect_krex_pages(
                        lambda page_no: self.krex.traffic.incident(
                            num_of_rows=KREX_PAGE_SIZE, page_no=page_no,
                        ), "traffic.incident",
                    )
            except Exception as exc:
                return exc

        # 한 소스의 timeout/quota가 이미 조회한 다른 소스를 버리지 않는다.
        traffic, incidents = await asyncio.gather(fetch(TRAFFIC_SOURCE), fetch(INCIDENT_SOURCE))
        return HighwayPayload(traffic=traffic, incidents=incidents)

    async def collect_fuel(self) -> OpinetBrowserSnapshot | None:
        if self.opinet is None:
            return None
        return await self.opinet.collect_once()

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
        collected_source = False

        if not self.enabled:
            run.status = "skipped"
            run.finished_at = now_utc()
            await session.commit()
            return self._summary(
                run,
                client_mode=self.client_mode,
                raw_count=0,
                traffic_count=0,
                incident_count=0,
                fuel_station_count=0,
                fuel_price_count=0,
                errors=[],
            )

        due_highway_sources = []
        if scope != "fuel":
            for source in (TRAFFIC_SOURCE, INCIDENT_SOURCE):
                if source in self.provider.enabled_sources and await self._source_is_due(session, source):
                    due_highway_sources.append(source)
        highway_sources = tuple(due_highway_sources)
        highway_due = bool(highway_sources)
        fuel_due = scope != "highway" and OPINET_SOURCE in self.provider.enabled_sources and await self._fuel_is_due(session)
        claimed_sources = []
        if highway_due:
            claimed_sources.extend(highway_sources)
        if fuel_due:
            claimed_sources.append(OPINET_SOURCE)
        for source in claimed_sources:
            await self._mark_source_started(session, source)
            state = await self._get_or_create_state(session, source)
            # 외부 요청 전에 예약을 확정한다. 재시작/취소도 provider 호출 예산을 되돌리지 않는다.
            reservation = (
                self.provider.next_fuel_interval() if source == OPINET_SOURCE
                else timedelta(seconds=(FUEL_FETCH_TIMEOUT_SECONDS if fuel_due else 0) + 2 * HIGHWAY_FETCH_TIMEOUT_SECONDS + 900)
            )
            state.next_due_at = started_at + reservation
        await session.commit()
        run_id = run.id

        # 이 구간에서는 DB 트랜잭션/connection/advisory lock을 유지하지 않는다.
        # 다른 프로세스는 짧은 claim transaction에서 next_due_at 예약을 보고 건너뛴다.
        highway_result: HighwayPayload | Exception | None = None
        fuel_result: OpinetBrowserSnapshot | Exception | None = None
        persisted_sources: set[str] = set()
        try:
            if highway_due:
                try:
                    async with asyncio.timeout(2 * HIGHWAY_FETCH_TIMEOUT_SECONDS):
                        highway_result = await self.provider.collect_highway(sources=highway_sources)
                except Exception as exc:
                    highway_result = exc
            if fuel_due:
                try:
                    async with asyncio.timeout(FUEL_FETCH_TIMEOUT_SECONDS):
                        fuel_result = await self.provider.collect_fuel()
                except Exception as exc:
                    fuel_result = exc

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
                try:
                    snapshot = await self._collect_fuel(session, run_id, errors, fuel_result)
                    if snapshot is not None:
                        fuel_station_count, fuel_price_count = await self._store_fuel_snapshot(
                            session, run_id, snapshot,
                        )
                        await self._mark_fuel_success(session, snapshot.collected_at)
                    await session.commit()
                except Exception as exc:
                    await session.rollback()
                    await self._collect_fuel(session, run_id, errors, exc)
                    await session.commit()
                    snapshot = None
                    fuel_station_count = fuel_price_count = 0
                persisted_sources.add(OPINET_SOURCE)
                if snapshot is not None:
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
            await session.rollback()
            failed_run = await session.get(CollectionRun, run_id)
            failed_run.status = "failed"
            failed_run.finished_at = now_utc()
            message = "collection cancelled" if isinstance(exc, asyncio.CancelledError) else _safe_error(exc, self.settings)
            failed_run.error_message = message
            for source in claimed_sources:
                if source in persisted_sources:
                    continue
                state = await self._get_or_create_state(session, source)
                state.last_error = message
                state.updated_at = now_utc()
            await session.commit()
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
        return self._summary(
            run,
            client_mode=self.client_mode,
            raw_count=raw_count,
            traffic_count=traffic_count,
            incident_count=incident_count,
            fuel_station_count=fuel_station_count,
            fuel_price_count=fuel_price_count,
            errors=errors,
        )

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
            body={"items": [_provider_json(item) for item in result]},
        )
        await self._mark_source_success(session, source, now_utc())
        return result

    async def _collect_fuel(
        self,
        session: AsyncSession,
        collection_run_id: int,
        errors: list[str],
        result: OpinetBrowserSnapshot | Exception | None,
    ) -> OpinetBrowserSnapshot | None:
        try:
            if isinstance(result, Exception):
                raise result
            snapshot = result
            if snapshot is None:
                return None
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
            await self._mark_fuel_failure(session, message)
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
        for item in items:
            direction = _enum_value(item.direction)
            observed_at = _parse_provider_datetime(item.updated_at, self.settings.app_timezone) or collected_at
            identity_key = _traffic_identity(item, direction)
            dedupe_key = (identity_key, observed_at)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            existing = await session.scalar(
                select(HighwayTrafficSnapshot).where(
                    HighwayTrafficSnapshot.source == TRAFFIC_SOURCE,
                    HighwayTrafficSnapshot.identity_key == identity_key,
                    HighwayTrafficSnapshot.observed_at == observed_at,
                )
            )
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
        return stored

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
        await session.flush()
        return stored

    async def _store_fuel_snapshot(
        self,
        session: AsyncSession,
        collection_run_id: int,
        snapshot: OpinetBrowserSnapshot,
    ) -> tuple[int, int]:
        station_count = 0
        price_count = 0
        collected_at = serialize_utc(snapshot.collected_at, self.settings.app_timezone)
        for item in snapshot.stations:
            identity_key = _station_identity(item)
            station = await session.scalar(
                select(FuelStation).where(
                    FuelStation.source == OPINET_SOURCE,
                    FuelStation.identity_key == identity_key,
                )
            )
            values = _station_values(item, collected_at)
            if station is None:
                station = FuelStation(
                    source=OPINET_SOURCE,
                    identity_key=identity_key,
                    first_seen_at=collected_at,
                    **values,
                )
                session.add(station)
                station_count += 1
                await session.flush()
            else:
                for key, value in values.items():
                    setattr(station, key, value)
                station.last_seen_at = collected_at

            for price in item.prices:
                provider_updated_at = (
                    serialize_utc(price.updated_at, self.settings.app_timezone)
                    if price.updated_at is not None
                    else None
                )
                observed_at = provider_updated_at or collected_at
                product_code = _enum_value(price.product_code) or "unknown"
                existing = await session.scalar(
                    select(FuelPriceSnapshot).where(
                        FuelPriceSnapshot.fuel_station_id == station.id,
                        FuelPriceSnapshot.source == OPINET_SOURCE,
                        FuelPriceSnapshot.product_code == product_code,
                        FuelPriceSnapshot.observed_at == observed_at,
                    )
                )
                price_value = _decimal_or_none(price.price)
                raw_item = _plain_json(item.raw)
                if existing is None:
                    session.add(
                        FuelPriceSnapshot(
                            collection_run_id=collection_run_id,
                            fuel_station_id=station.id,
                            source=OPINET_SOURCE,
                            product_code=product_code,
                            price=price_value,
                            provider_updated_at=provider_updated_at,
                            observed_at=observed_at,
                            collected_at=collected_at,
                            raw_item_json=raw_item,
                        )
                    )
                    price_count += 1
                else:
                    existing.price = price_value
                    existing.provider_updated_at = provider_updated_at
                    existing.collected_at = collected_at
                    existing.raw_item_json = raw_item
        await session.flush()
        return station_count, price_count

    async def _source_is_due(self, session: AsyncSession, source: str) -> bool:
        state = await session.scalar(select(TransportCollectionState).where(
            TransportCollectionState.source == source
        ))
        return state is None or state.next_due_at is None or now_utc() >= serialize_utc(state.next_due_at)

    async def _fuel_is_due(self, session: AsyncSession) -> bool:
        state = await session.scalar(
            select(TransportCollectionState).where(TransportCollectionState.source == OPINET_SOURCE)
        )
        if state is None or state.next_due_at is None:
            return True
        next_due_at = state.next_due_at
        return now_utc() >= serialize_utc(next_due_at)

    async def _mark_fuel_success(self, session: AsyncSession, collected_at: datetime) -> None:
        state = await self._get_or_create_state(session, OPINET_SOURCE)
        state.last_success_at = collected_at
        state.next_due_at = collected_at + self.provider.next_fuel_interval()
        state.last_error = None
        state.updated_at = now_utc()
        await session.flush()

    async def _mark_fuel_failure(self, session: AsyncSession, message: str) -> None:
        state = await self._get_or_create_state(session, OPINET_SOURCE)
        state.next_due_at = now_utc() + self.provider.next_fuel_interval()
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
        state = await session.scalar(
            select(TransportCollectionState).where(TransportCollectionState.source == source)
        )
        if state is None:
            state = TransportCollectionState(source=source, updated_at=now_utc())
            session.add(state)
            await session.flush()
        return state

    async def next_collection_delay(self, session: AsyncSession, scope: CollectionScope) -> float:
        """고정 tick과 DB 예정 시각의 미세한 차이 때문에 한 주기를 건너뛰지 않는다."""
        sources = (OPINET_SOURCE,) if scope == "fuel" else (TRAFFIC_SOURCE, INCIDENT_SOURCE)
        due_dates = (await session.scalars(
            select(TransportCollectionState.next_due_at).where(
                TransportCollectionState.source.in_(sources)
            )
        )).all()
        interval = self.settings.transport_collect_interval_seconds
        if not due_dates or any(value is None for value in due_dates):
            return float(interval)
        remaining = min((serialize_utc(value) - now_utc()).total_seconds() for value in due_dates)
        return max(1.0, remaining)

    async def status(self, session: AsyncSession) -> dict[str, Any]:
        states = (
            await session.execute(
                select(TransportCollectionState).order_by(TransportCollectionState.source)
            )
        ).scalars().all()
        fuel_state = next((item for item in states if item.source == OPINET_SOURCE), None)
        last_run = await session.scalar(
            select(CollectionRun)
            .where(
                CollectionRun.trigger.startswith(TRANSPORT_TRIGGER_PREFIX, autoescape=True),
                CollectionRun.status != "skipped",
            )
            .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
            .limit(1)
        )
        return {
            "scheduler_enabled": self.settings.enable_scheduler and self.enabled,
            "collection_enabled": self.enabled,
            "collect_interval_seconds": self.settings.transport_collect_interval_seconds,
            "client_mode": self.client_mode,
            "enabled_sources": self.enabled_sources,
            "last_fuel_success_at": fuel_state.last_success_at if fuel_state is not None else None,
            "next_fuel_due_at": fuel_state.next_due_at if fuel_state is not None else None,
            "last_fuel_error": fuel_state.last_error if fuel_state is not None else None,
            "last_run": (
                {
                    "id": last_run.id,
                    "started_at": last_run.started_at,
                    "finished_at": last_run.finished_at,
                    "status": last_run.status,
                    "trigger": last_run.trigger,
                    # The public endpoint deliberately exposes only a stable error marker.
                    "error": "collection_failed" if last_run.error_message else None,
                }
                if last_run is not None
                else None
            ),
            "sources": [
                {
                    "source": item.source,
                    "last_started_at": item.last_started_at,
                    "last_success_at": item.last_success_at,
                    "next_due_at": item.next_due_at,
                    "last_error": item.last_error,
                }
                for item in states
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
    return tuple(items)


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


def _safe_error(error: Exception, settings: Settings) -> str:
    message = str(error).strip() or error.__class__.__name__
    for secret in (settings.kex_ex_api_key, settings.data_go_kr_service_key):
        if secret:
            message = message.replace(secret, "<redacted>")
    return " ".join(message.split())
