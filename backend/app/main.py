from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextlib import suppress
from datetime import date, datetime, time, timedelta
from http import HTTPStatus
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings, get_settings
from app.core.time_utils import now_utc, serialize_utc, to_seoul
from app.db.session import create_engine_and_session_factory, init_database
from app.models import (
    Airport,
    CollectionRun,
    FuelPriceSnapshot,
    FuelStation,
    HighwayIncidentSnapshot,
    HighwayTrafficSnapshot,
    ParkingFeeRule,
    ParkingLot,
    ParkingSnapshot,
    RawApiResponse,
)
from app.schemas import (
    AirportSummary,
    BackupFile,
    BackupListResponse,
    BackupRestoreResponse,
    CollectionSummary,
    CollectionRunStatus,
    CollectorStatusResponse,
    DashboardAnalyticsResponse,
    DashboardBootstrapResponse,
    FeeCalculationRequest,
    FeeCalculationResponse,
    FlightStatusResponse,
    FuelPriceItem,
    FuelPriceStatistics,
    FuelStationItem,
    FuelStationResponse,
    HealthResponse,
    HighwayIncidentItem,
    HighwayIncidentResponse,
    HighwayIncidentStatistics,
    HighwayTrafficItem,
    HighwayTrafficResponse,
    HighwayTrafficStatistics,
    HolidayItemSummary,
    HolidayPatternItem,
    HolidayPatternResponse,
    HolidaySummaryResponse,
    HourlyBucket,
    ParkingCurrentResponse,
    ParkingHistoryResponse,
    ParkingLotSummary,
    ParkingStatus,
    ParkingTimeSeriesResponse,
    ThresholdEvent,
    ThresholdInsightsResponse,
    ThresholdDateHistoryItem,
    ThresholdWeekdayTime,
    TimeSeriesPoint,
    TransportCollectorStatus,
    TransportStatisticsResponse,
    WeekdayBucket,
    WeekdayHourlyPattern,
)
from app.services.analytics import (
    build_special_day_patterns,
    build_threshold_insights,
    build_hourly_buckets,
    build_time_series,
    build_weekday_buckets,
    build_weekday_hour_patterns,
    classify_status_level,
    deduplicate_snapshot_rows,
    deduplicate_snapshots,
    detect_threshold_events,
)
from app.services.analytics_cache import (
    DEFAULT_THRESHOLD_EVENTS_DAYS,
    DEFAULT_THRESHOLD_EVENTS_LIMIT,
    DEFAULT_THRESHOLD_INSIGHTS_DAYS,
    DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES,
    DEFAULT_TIMESERIES_DAYS,
    DEFAULT_TIMESERIES_FUTURE_HOURS,
    DEFAULT_TIMESERIES_INTERVAL_MINUTES,
    DEFAULT_WEEKDAY_HOUR_DAYS,
    METRIC_THRESHOLD_EVENTS,
    METRIC_THRESHOLD_INSIGHTS,
    METRIC_TIMESERIES,
    METRIC_WEEKDAY_HOUR,
    load_cached_analytics,
    refresh_default_analytics_cache,
)
from app.services.backup_restore import (
    backup_path_for_download,
    create_backup,
    list_backups,
    remove_backup,
    restore_backup,
    save_uploaded_backup,
)
from app.services.collection import CollectionService
from app.services.fee_calculator import calculate_total_fee
from app.services.flight_status import FlightStatusService
from app.services.holidays import (
    HolidayItem,
    HolidayService,
    WEEKDAY_LABELS as HOLIDAY_WEEKDAY_LABELS,
    collapse_holidays_by_date,
    format_holiday_sentence,
)
from app.services.sample_data import seed_sample_database
from app.services.transport_collection import CollectionScope, OPINET_SOURCE, TRANSPORT_TRIGGER_PREFIX, TransportCollectionService

logger = logging.getLogger(__name__)

# T-036: 과거 자료 조회의 명시적 start_date/end_date 범위 상한(일). 관측 데이터는
# 삭제 정책 없이 전체 보존되므로 상한이 없으면 임의로 큰 범위가 무거운 시계열
# 버킷 계산(interval_minutes=10 기준 1년이면 5만 버킷 이상)을 유발할 수 있다.
# 같은 엔드포인트의 상대(`days`, 최대 30일) 조회보다 3배 넓다 - 상대 조회는 기본
# 캐시를 계속 갱신하며 자주 호출되지만, 명시적 범위 조회는 캐시를 타지 않는
# 일회성 히스토리 조회라 더 넓은 상한을 허용해도 상시 부하로 이어지지 않는다
# (threshold_insights의 기존 90일 상한과 동일한 값).
MAX_TIMESERIES_RANGE_DAYS = 90


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    engine, session_factory = create_engine_and_session_factory(resolved_settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await init_database(engine)
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.settings = resolved_settings
        app.state.collection_service = CollectionService(resolved_settings)
        app.state.transport_collection_service = TransportCollectionService(resolved_settings)
        app.state.flight_status_service = FlightStatusService(resolved_settings)
        app.state.holiday_service = HolidayService(resolved_settings)
        app.state.scheduler_task = None
        app.state.transport_scheduler_task = None
        app.state.fuel_scheduler_task = None

        if resolved_settings.seed_sample_data and app.state.collection_service.client_mode == "sample":
            async with session_factory() as session:
                await seed_sample_database(session)
                await refresh_default_analytics_cache(session, resolved_settings)
                await session.commit()
        elif resolved_settings.seed_sample_data:
            logger.info("sample seeding skipped because client_mode=%s", app.state.collection_service.client_mode)

        if resolved_settings.enable_scheduler and resolved_settings.scheduler_mode == "in_process":
            logger.info(
                "scheduler enabled effective_interval_seconds=%s configured_interval_seconds=%s client_mode=%s sources=%s airports=%s",
                resolved_settings.effective_collect_interval_seconds,
                resolved_settings.collect_interval_seconds,
                app.state.collection_service.client_mode,
                ",".join(app.state.collection_service.enabled_sources),
                ",".join(resolved_settings.supported_airport_codes),
            )
            app.state.scheduler_task = asyncio.create_task(_run_scheduler(app))
            if app.state.transport_collection_service.enabled:
                app.state.transport_scheduler_task = asyncio.create_task(_run_transport_scheduler(app, "highway"))
                if OPINET_SOURCE in app.state.transport_collection_service.enabled_sources:
                    app.state.fuel_scheduler_task = asyncio.create_task(_run_transport_scheduler(app, "fuel"))
        elif resolved_settings.enable_scheduler:
            logger.info("in-process scheduler disabled; Dagster owns collection execution")

        try:
            yield
        finally:
            scheduler_task = app.state.scheduler_task
            if scheduler_task is not None:
                scheduler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await scheduler_task
            transport_tasks = (app.state.transport_scheduler_task, app.state.fuel_scheduler_task)
            for task in transport_tasks:
                if task is not None:
                    task.cancel()
            for task in transport_tasks:
                if task is None:
                    continue
                with suppress(asyncio.CancelledError):
                    await task
            await app.state.transport_collection_service.close()
            await engine.dispose()

    app = FastAPI(
        title=resolved_settings.app_name,
        lifespan=lifespan,
        docs_url="/docs" if resolved_settings.enable_api_docs else None,
        redoc_url="/redoc" if resolved_settings.enable_api_docs else None,
        openapi_url="/openapi.json" if resolved_settings.enable_api_docs else None,
    )
    @app.exception_handler(HTTPException)
    async def problem_json_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        # RFC 7807 (ADR-005): every error response uses the same shape,
        # regardless of which route raised it. `detail` is kept so existing
        # clients reading `payload.detail` (frontend/src/lib/api.ts) still work.
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "type": "about:blank",
                "title": HTTPStatus(exc.status_code).phrase,
                "status": exc.status_code,
                "detail": exc.detail,
                "instance": request.url.path,
            },
            headers=exc.headers,
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def problem_json_validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # FastAPI raises RequestValidationError separately from HTTPException
        # for bad query/body params, so it needs its own RFC 7807 handler
        # to keep the "every error response uses the same shape" contract.
        status_code = HTTPStatus.UNPROCESSABLE_ENTITY
        return JSONResponse(
            status_code=status_code,
            content={
                "type": "about:blank",
                "title": status_code.phrase,
                "status": int(status_code),
                "detail": jsonable_encoder(exc.errors()),
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    @app.exception_handler(Exception)
    async def problem_json_internal_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # 예외 원문에는 SQL·DB 접속정보·인증키가 포함될 수 있으므로 응답에 사용하지 않는다.
        return JSONResponse(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            content={
                "type": "about:blank",
                "title": HTTPStatus.INTERNAL_SERVER_ERROR.phrase,
                "status": int(HTTPStatus.INTERNAL_SERVER_ERROR),
                "detail": "서버 내부 오류가 발생했습니다.",
                "instance": request.url.path,
            },
            media_type="application/problem+json",
        )

    if resolved_settings.trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=resolved_settings.trusted_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        if forwarded_proto == "https":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    def custom_openapi() -> dict:
        """Keep the committed schema aligned with the RFC 7807 error handlers."""
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components["ProblemDetails"] = {
            "type": "object",
            "required": ["type", "title", "status", "detail", "instance"],
            "properties": {
                "type": {"type": "string", "format": "uri-reference"},
                "title": {"type": "string"},
                "status": {"type": "integer"},
                "detail": {
                    "description": "문제의 세부 내용 또는 검증 오류 목록",
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {}},
                        {"type": "object", "additionalProperties": True},
                    ],
                },
                "instance": {"type": "string"},
            },
        }
        documented_errors = {
            ("/v1/parking/analytics/timeseries", "get"): (400,),
            ("/v1/holidays/summary", "get"): (400,),
            ("/v1/flights/status", "get"): (400,),
            ("/v1/fees/calculate", "post"): (404,),
            ("/v1/admin/collect", "post"): (404, 409, 429, 502),
            ("/v1/admin/backups", "post"): (503,),
            ("/v1/admin/backups/{filename}", "get"): (400, 404),
            ("/v1/admin/backups/restore", "post"): (400, 404, 409, 503),
        }
        for path, path_item in schema.get("paths", {}).items():
            for method, operation in path_item.items():
                if not isinstance(operation, dict) or "responses" not in operation:
                    continue
                codes = [code for code in operation["responses"] if str(code).startswith(("4", "5"))]
                codes.extend(str(code) for code in documented_errors.get((path, method), ()))
                codes.append("500")
                for code in codes:
                    operation["responses"][code] = {
                        "description": "요청 검증 오류" if code == "422" else "애플리케이션 오류",
                        "content": {
                            "application/problem+json": {
                                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                            }
                        },
                    }
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi

    def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
        return request.app.state.session_factory

    async def get_db(
        session_factory: async_sessionmaker[AsyncSession] = Depends(get_session_factory),
    ) -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    def get_collection_service(request: Request) -> CollectionService:
        return request.app.state.collection_service

    def get_flight_status_service(request: Request) -> FlightStatusService:
        return request.app.state.flight_status_service

    def get_holiday_service(request: Request) -> HolidayService:
        return request.app.state.holiday_service

    def get_transport_collection_service(request: Request) -> TransportCollectionService:
        return request.app.state.transport_collection_service

    @app.get("/health", response_model=HealthResponse)
    async def health(session: AsyncSession = Depends(get_db)) -> HealthResponse:
        seeded = await session.scalar(select(func.count(ParkingSnapshot.id)))
        return HealthResponse(
            status="ok",
            database="ready",
            seeded=bool(seeded),
            release_sha=resolved_settings.release_sha,
        )

    router = APIRouter()

    @router.get("/airports", response_model=list[AirportSummary])
    async def airports(session: AsyncSession = Depends(get_db)) -> list[AirportSummary]:
        result = await session.execute(
            select(Airport).options(selectinload(Airport.parking_lots)).order_by(Airport.code)
        )
        airports = result.scalars().all()
        payload: list[AirportSummary] = []
        for airport in airports:
            lots = sorted(airport.parking_lots, key=lambda parking_lot: parking_lot.name)
            payload.append(
                AirportSummary(
                    code=airport.code,
                    name_ko=airport.name_ko,
                    name_en=airport.name_en,
                    source=airport.source,
                    parking_lots=[
                        ParkingLotSummary(
                            id=lot.id,
                            source_lot_id=lot.source_lot_id,
                            legacy_source_lot_id=lot.legacy_source_lot_id,
                            name=lot.name,
                            terminal=lot.terminal,
                            category=lot.category,
                            is_active=lot.is_active,
                        )
                        for lot in lots
                    ],
                )
            )
        return payload

    @router.get("/transport/highways/traffic", response_model=HighwayTrafficResponse)
    async def transport_highway_traffic(
        route_no: str | None = Query(default=None),
        days: int = Query(default=1, ge=1, le=30),
        limit: int = Query(default=200, ge=1, le=1000),
        session: AsyncSession = Depends(get_db),
    ) -> HighwayTrafficResponse:
        cutoff = now_utc() - timedelta(days=days)
        query = select(HighwayTrafficSnapshot).where(HighwayTrafficSnapshot.observed_at >= cutoff)
        if route_no:
            query = query.where(HighwayTrafficSnapshot.route_no == route_no.strip())
        query = query.order_by(
            HighwayTrafficSnapshot.observed_at.desc(), HighwayTrafficSnapshot.id.desc()
        ).limit(limit)
        rows = (await session.execute(query)).scalars().all()
        return HighwayTrafficResponse(
            generated_at=now_utc(),
            days=days,
            route_no=route_no.strip() if route_no else None,
            items=[
                HighwayTrafficItem(
                    source=row.source,
                    identity_key=row.identity_key,
                    observed_at=serialize_utc(row.observed_at),
                    collected_at=serialize_utc(row.collected_at),
                    route_no=row.route_no,
                    route_name=row.route_name,
                    conzone_id=row.conzone_id,
                    conzone_name=row.conzone_name,
                    direction=row.direction,
                    speed=row.speed,
                    free_flow_speed=row.free_flow_speed,
                    congestion_level=row.congestion_level,
                )
                for row in rows
            ],
        )

    @router.get("/transport/highways/incidents", response_model=HighwayIncidentResponse)
    async def transport_highway_incidents(
        route_no: str | None = Query(default=None),
        days: int = Query(default=1, ge=1, le=30),
        limit: int = Query(default=200, ge=1, le=1000),
        session: AsyncSession = Depends(get_db),
    ) -> HighwayIncidentResponse:
        cutoff = now_utc() - timedelta(days=days)
        query = select(HighwayIncidentSnapshot).where(HighwayIncidentSnapshot.observed_at >= cutoff)
        if route_no:
            query = query.where(HighwayIncidentSnapshot.route_no == route_no.strip())
        query = query.order_by(
            HighwayIncidentSnapshot.observed_at.desc(), HighwayIncidentSnapshot.id.desc()
        ).limit(limit)
        rows = (await session.execute(query)).scalars().all()
        return HighwayIncidentResponse(
            generated_at=now_utc(),
            days=days,
            route_no=route_no.strip() if route_no else None,
            items=[
                HighwayIncidentItem(
                    source=row.source,
                    identity_key=row.identity_key,
                    observed_at=serialize_utc(row.observed_at),
                    collected_at=serialize_utc(row.collected_at),
                    occurred_date=row.occurred_date,
                    occurred_time=row.occurred_time,
                    incident_type=row.incident_type,
                    incident_type_code=row.incident_type_code,
                    direction=row.direction,
                    message=row.message,
                    point_name=row.point_name,
                    route_no=row.route_no,
                    route_name=row.route_name,
                    process_status=row.process_status,
                    process_status_code=row.process_status_code,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    congestion_length=row.congestion_length,
                    series_no=row.series_no,
                )
                for row in rows
            ],
        )

    @router.get("/transport/fuel/stations", response_model=FuelStationResponse)
    async def transport_fuel_stations(
        sido_value: str | None = Query(default=None, description="저장된 화면 검색 시도 문맥. 실제 소재지 필터가 아닙니다."),
        sigungu_value: str | None = Query(default=None, description="저장된 화면 검색 시군구 문맥. 실제 소재지 필터가 아닙니다."),
        product_code: str | None = Query(default=None),
        days: int = Query(default=2, ge=1, le=30),
        limit: int = Query(default=200, ge=1, le=1000),
        session: AsyncSession = Depends(get_db),
    ) -> FuelStationResponse:
        cutoff = now_utc() - timedelta(days=days)
        query = select(FuelStation).where(FuelStation.last_seen_at >= cutoff)
        if sido_value:
            query = query.where(FuelStation.sido_value == sido_value.strip())
        if sigungu_value:
            query = query.where(FuelStation.sigungu_value == sigungu_value.strip())
        query = query.order_by(FuelStation.last_seen_at.desc(), FuelStation.id.desc()).limit(limit)
        stations = (await session.execute(query)).scalars().all()
        station_ids = [station.id for station in stations]
        price_rows: list[FuelPriceSnapshot] = []
        if station_ids:
            # Keep the response bounded by one row per station/product.  A
            # plain period query would load every historical observation for
            # all selected stations before Python discarded all but the latest
            # row, which grows with retention rather than with this request.
            ranked_prices = (
                select(
                    FuelPriceSnapshot.id.label("price_id"),
                    func.row_number()
                    .over(
                        partition_by=(
                            FuelPriceSnapshot.fuel_station_id,
                            FuelPriceSnapshot.product_code,
                        ),
                        order_by=(
                            FuelPriceSnapshot.collected_at.desc(),
                            FuelPriceSnapshot.id.desc(),
                        ),
                    )
                    .label("row_number"),
                )
                .where(
                    FuelPriceSnapshot.fuel_station_id.in_(station_ids),
                    FuelPriceSnapshot.collected_at >= cutoff,
                )
            )
            if product_code:
                ranked_prices = ranked_prices.where(
                    FuelPriceSnapshot.product_code == product_code.strip()
                )
            ranked_prices_subquery = ranked_prices.subquery()
            price_query = (
                select(FuelPriceSnapshot)
                .join(
                    ranked_prices_subquery,
                    FuelPriceSnapshot.id == ranked_prices_subquery.c.price_id,
                )
                .where(ranked_prices_subquery.c.row_number == 1)
                .order_by(FuelPriceSnapshot.fuel_station_id, FuelPriceSnapshot.product_code)
            )
            price_rows = (await session.execute(price_query)).scalars().all()

        latest_prices: dict[tuple[int, str], FuelPriceSnapshot] = {}
        for row in price_rows:
            latest_prices.setdefault((row.fuel_station_id, row.product_code), row)

        items: list[FuelStationItem] = []
        for station in stations:
            prices = [
                FuelPriceItem(
                    product_code=row.product_code,
                    price=float(row.price) if row.price is not None else None,
                    provider_updated_at=(serialize_utc(row.provider_updated_at) if row.provider_updated_at else None),
                    observed_at=serialize_utc(row.observed_at),
                    collected_at=serialize_utc(row.collected_at),
                )
                for (station_id, _product), row in sorted(latest_prices.items())
                if station_id == station.id
            ]
            items.append(
                FuelStationItem(
                    source=station.source,
                    identity_key=station.identity_key,
                    source_station_id=station.source_station_id,
                    name=station.name,
                    brand_code=station.brand_code,
                    brand_name=station.brand_name,
                    phone=station.phone,
                    address=station.address,
                    business_number=station.business_number,
                    cb_code=station.cb_code,
                    station_type=station.station_type,
                    query_level=station.query_level,
                    sido_value=station.sido_value,
                    sido_name=station.sido_name,
                    sigungu_value=station.sigungu_value,
                    sigungu_name=station.sigungu_name,
                    dong_value=station.dong_value,
                    dong_name=station.dong_name,
                    katec_x=station.katec_x,
                    katec_y=station.katec_y,
                    longitude=station.longitude,
                    latitude=station.latitude,
                    source_kinds=station.source_kinds or [],
                    is_illegal=station.is_illegal,
                    is_self=station.is_self,
                    is_24h=station.is_24h,
                    is_kpetro=station.is_kpetro,
                    is_electronic=station.is_electronic,
                    is_good=station.is_good,
                    is_good_strong=station.is_good_strong,
                    is_region_franchise=station.is_region_franchise,
                    has_carwash=station.has_carwash,
                    has_maintenance=station.has_maintenance,
                    has_cvs=station.has_cvs,
                    cs_yn=station.cs_yn,
                    discount_info=station.discount_info,
                    save_event_info=station.save_event_info,
                    representative_event_info=station.representative_event_info,
                    on_event_info=station.on_event_info,
                    other_business_info=station.other_business_info,
                    first_seen_at=serialize_utc(station.first_seen_at),
                    last_seen_at=serialize_utc(station.last_seen_at),
                    prices=prices,
                )
            )
        return FuelStationResponse(
            generated_at=now_utc(),
            days=days,
            sido_value=sido_value.strip() if sido_value else None,
            sigungu_value=sigungu_value.strip() if sigungu_value else None,
            product_code=product_code.strip() if product_code else None,
            items=items,
        )

    @router.get("/transport/collector-status", response_model=TransportCollectorStatus)
    async def transport_collector_status(
        session: AsyncSession = Depends(get_db),
        service: TransportCollectionService = Depends(get_transport_collection_service),
    ) -> TransportCollectorStatus:
        status = await service.status(session)
        for key in ("last_fuel_success_at", "next_fuel_due_at"):
            if status[key] is not None:
                status[key] = serialize_utc(status[key])
        for item in status["sources"]:
            for key in ("last_started_at", "last_success_at", "next_due_at"):
                if item[key] is not None:
                    item[key] = serialize_utc(item[key])
            if item["last_error"] is not None:
                item["last_error"] = "collection_failed"
        if status["last_run"] is not None:
            for key in ("started_at", "finished_at"):
                if status["last_run"][key] is not None:
                    status["last_run"][key] = serialize_utc(status["last_run"][key])
        if status["last_fuel_error"] is not None:
            status["last_fuel_error"] = "collection_failed"
        return TransportCollectorStatus(**status)

    @router.get("/transport/statistics", response_model=TransportStatisticsResponse)
    async def transport_statistics(
        route_no: str | None = Query(default=None),
        days: int = Query(default=7, ge=1, le=90),
        session: AsyncSession = Depends(get_db),
    ) -> TransportStatisticsResponse:
        cutoff = now_utc() - timedelta(days=days)
        normalized_route_no = route_no.strip() if route_no else None

        traffic_query = (
            select(
                HighwayTrafficSnapshot.route_no,
                HighwayTrafficSnapshot.direction,
                func.count().label("observations"),
                func.avg(HighwayTrafficSnapshot.speed).label("average_speed"),
                func.min(HighwayTrafficSnapshot.speed).label("minimum_speed"),
                func.max(HighwayTrafficSnapshot.speed).label("maximum_speed"),
                func.avg(HighwayTrafficSnapshot.free_flow_speed).label("average_free_flow_speed"),
                func.max(HighwayTrafficSnapshot.observed_at).label("latest_observed_at"),
            )
            .where(HighwayTrafficSnapshot.observed_at >= cutoff)
        )
        if normalized_route_no:
            traffic_query = traffic_query.where(HighwayTrafficSnapshot.route_no == normalized_route_no)
        traffic_rows = (
            await session.execute(
                traffic_query.group_by(
                    HighwayTrafficSnapshot.route_no,
                    HighwayTrafficSnapshot.direction,
                ).order_by(
                    HighwayTrafficSnapshot.route_no,
                    HighwayTrafficSnapshot.direction,
                )
            )
        ).all()

        incidents_query = (
            select(
                HighwayIncidentSnapshot.route_no,
                func.count().label("incidents"),
                func.max(HighwayIncidentSnapshot.observed_at).label("latest_observed_at"),
            )
            .where(HighwayIncidentSnapshot.observed_at >= cutoff)
        )
        if normalized_route_no:
            incidents_query = incidents_query.where(HighwayIncidentSnapshot.route_no == normalized_route_no)
        incident_rows = (
            await session.execute(
                incidents_query.group_by(HighwayIncidentSnapshot.route_no).order_by(
                    HighwayIncidentSnapshot.route_no
                )
            )
        ).all()

        fuel_rows = (
            await session.execute(
                select(
                    FuelPriceSnapshot.product_code,
                    func.count(func.distinct(FuelPriceSnapshot.fuel_station_id)).label("stations"),
                    func.count().label("observations"),
                    func.avg(FuelPriceSnapshot.price).label("average_price"),
                    func.min(FuelPriceSnapshot.price).label("minimum_price"),
                    func.max(FuelPriceSnapshot.price).label("maximum_price"),
                    func.max(FuelPriceSnapshot.observed_at).label("latest_observed_at"),
                    func.max(FuelPriceSnapshot.collected_at).label("latest_collected_at"),
                )
                .where(
                    FuelPriceSnapshot.collected_at >= cutoff,
                    FuelPriceSnapshot.price.is_not(None),
                )
                .group_by(FuelPriceSnapshot.product_code)
                .order_by(FuelPriceSnapshot.product_code)
            )
        ).all()

        return TransportStatisticsResponse(
            generated_at=now_utc(),
            days=days,
            route_no=normalized_route_no,
            traffic=[
                HighwayTrafficStatistics(
                    route_no=row.route_no,
                    direction=row.direction,
                    observations=int(row.observations),
                    average_speed=float(row.average_speed) if row.average_speed is not None else None,
                    minimum_speed=float(row.minimum_speed) if row.minimum_speed is not None else None,
                    maximum_speed=float(row.maximum_speed) if row.maximum_speed is not None else None,
                    average_free_flow_speed=(
                        float(row.average_free_flow_speed)
                        if row.average_free_flow_speed is not None
                        else None
                    ),
                    latest_observed_at=(
                        serialize_utc(row.latest_observed_at) if row.latest_observed_at else None
                    ),
                )
                for row in traffic_rows
            ],
            incidents=[
                HighwayIncidentStatistics(
                    route_no=row.route_no,
                    incidents=int(row.incidents),
                    latest_observed_at=(
                        serialize_utc(row.latest_observed_at) if row.latest_observed_at else None
                    ),
                )
                for row in incident_rows
            ],
            fuel_prices=[
                FuelPriceStatistics(
                    product_code=row.product_code,
                    stations=int(row.stations),
                    observations=int(row.observations),
                    average_price=float(row.average_price) if row.average_price is not None else None,
                    minimum_price=float(row.minimum_price) if row.minimum_price is not None else None,
                    maximum_price=float(row.maximum_price) if row.maximum_price is not None else None,
                    latest_observed_at=(
                        serialize_utc(row.latest_observed_at) if row.latest_observed_at else None
                    ),
                    latest_collected_at=(
                        serialize_utc(row.latest_collected_at) if row.latest_collected_at else None
                    ),
                )
                for row in fuel_rows
            ],
        )

    @router.get("/parking/current", response_model=ParkingCurrentResponse)
    async def parking_current(
        airport_code: str | None = Query(default=None),
        session: AsyncSession = Depends(get_db),
    ) -> ParkingCurrentResponse:
        airport_id: int | None = None
        if airport_code:
            airport_id = await session.scalar(select(Airport.id).where(Airport.code == airport_code.upper()))
            if airport_id is None:
                return ParkingCurrentResponse(generated_at=now_utc(), items=[])

        latest_snapshot_id = (
            select(ParkingSnapshot.id)
            .where(
                ParkingSnapshot.airport_id == ParkingLot.airport_id,
                ParkingSnapshot.parking_lot_id == ParkingLot.id,
            )
            .order_by(ParkingSnapshot.observed_at.desc(), ParkingSnapshot.id.desc())
            .limit(1)
            .correlate(ParkingLot)
            .scalar_subquery()
        )
        query = (
            select(ParkingSnapshot, ParkingLot, Airport)
            .select_from(ParkingLot)
            .join(Airport, Airport.id == ParkingLot.airport_id)
            .join(ParkingSnapshot, ParkingSnapshot.id == latest_snapshot_id)
            .order_by(ParkingLot.id)
        )
        if airport_id is not None:
            query = query.where(ParkingLot.airport_id == airport_id)

        rows = (await session.execute(query)).all()
        items = [
            ParkingStatus(
                airport_code=airport.code,
                airport_name=airport.name_ko,
                parking_lot_id=lot.id,
                parking_lot_name=lot.name,
                terminal=lot.terminal,
                category=lot.category,
                observed_at=serialize_utc(snapshot.observed_at),
                collected_at=serialize_utc(snapshot.collected_at),
                occupied_spaces=snapshot.occupied_spaces,
                total_spaces=snapshot.total_spaces,
                available_spaces=snapshot.available_spaces,
                congestion_label=snapshot.congestion_label,
                congestion_ratio=snapshot.congestion_ratio,
                status_level=classify_status_level(snapshot.available_spaces, snapshot.total_spaces),
            )
            for snapshot, lot, airport in rows
        ]
        items.sort(key=lambda item: (item.airport_code, item.available_spaces))
        return ParkingCurrentResponse(generated_at=now_utc(), items=items)

    @router.get("/parking/history", response_model=ParkingHistoryResponse)
    async def parking_history(
        airport_code: str | None = Query(default=None),
        parking_lot_id: int | None = Query(default=None),
        days: int = Query(default=3, ge=1, le=30),
        session: AsyncSession = Depends(get_db),
    ) -> ParkingHistoryResponse:
        cutoff = now_utc() - timedelta(days=days)
        query = select(ParkingSnapshot).where(ParkingSnapshot.observed_at >= cutoff).order_by(ParkingSnapshot.observed_at)

        if parking_lot_id:
            query = query.where(ParkingSnapshot.parking_lot_id == parking_lot_id)
        elif airport_code:
            airport = await session.scalar(select(Airport).where(Airport.code == airport_code.upper()))
            if airport is None:
                return ParkingHistoryResponse(items=[])
            query = query.where(ParkingSnapshot.airport_id == airport.id)

        snapshots = deduplicate_snapshots((await session.execute(query)).scalars().all())
        return ParkingHistoryResponse(
            items=[
                {
                    "observed_at": serialize_utc(snapshot.observed_at),
                    "occupied_spaces": snapshot.occupied_spaces,
                    "total_spaces": snapshot.total_spaces,
                    "available_spaces": snapshot.available_spaces,
                }
                for snapshot in snapshots
            ]
        )

    @router.get("/parking/analytics/by-hour", response_model=list[HourlyBucket])
    async def parking_by_hour(
        airport_code: str | None = Query(default=None),
        parking_lot_id: int | None = Query(default=None),
        days: int = Query(default=14, ge=1, le=60),
        session: AsyncSession = Depends(get_db),
    ) -> list[HourlyBucket]:
        snapshots = await _load_snapshots(session, airport_code, parking_lot_id, days)
        return [HourlyBucket(**bucket) for bucket in build_hourly_buckets(snapshots)]

    @router.get("/parking/analytics/by-weekday", response_model=list[WeekdayBucket])
    async def parking_by_weekday(
        airport_code: str | None = Query(default=None),
        parking_lot_id: int | None = Query(default=None),
        days: int = Query(default=14, ge=1, le=60),
        session: AsyncSession = Depends(get_db),
    ) -> list[WeekdayBucket]:
        snapshots = await _load_snapshots(session, airport_code, parking_lot_id, days)
        return [WeekdayBucket(**bucket) for bucket in build_weekday_buckets(snapshots)]

    @router.get("/parking/analytics/by-weekday-hour", response_model=list[WeekdayHourlyPattern])
    async def parking_by_weekday_hour(
        airport_code: str | None = Query(default=None),
        parking_lot_id: int | None = Query(default=None),
        days: int = Query(default=14, ge=1, le=60),
        session: AsyncSession = Depends(get_db),
    ) -> list[WeekdayHourlyPattern]:
        if airport_code and days == DEFAULT_WEEKDAY_HOUR_DAYS:
            cached = await load_cached_analytics(
                session,
                metric=METRIC_WEEKDAY_HOUR,
                airport_code=airport_code,
                parking_lot_id=parking_lot_id,
                days=days,
            )
            if cached is not None:
                return [WeekdayHourlyPattern(**pattern) for pattern in cached]

        snapshots = await _load_snapshots(session, airport_code, parking_lot_id, days)
        return [WeekdayHourlyPattern(**pattern) for pattern in build_weekday_hour_patterns(snapshots)]

    @router.get(
        "/parking/analytics/timeseries",
        response_model=ParkingTimeSeriesResponse,
        description=(
            "상대 조회(`days`)와 명시적 범위 조회(`start_date`+`end_date`)는 상호배타적이다. "
            "start_date/end_date를 지정하면 days와 future_hours는 무시되고(future_hours=0으로 "
            "고정) airport_code 또는 parking_lot_id가 필요하며, 최대 90일까지 조회할 수 있다."
        ),
    )
    async def parking_time_series(
        airport_code: str | None = Query(default=None),
        parking_lot_id: int | None = Query(default=None),
        days: int = Query(default=7, ge=1, le=30),
        interval_minutes: int = Query(default=DEFAULT_TIMESERIES_INTERVAL_MINUTES, ge=10, le=60),
        future_hours: int = Query(default=0, ge=0, le=12),
        session: AsyncSession = Depends(get_db),
        start_date: str | None = Query(default=None, description="명시적 범위 조회 시작일(YYYY-MM-DD). end_date와 함께 지정한다. 지정 시 days/future_hours는 무시된다."),
        end_date: str | None = Query(default=None, description="명시적 범위 조회 종료일(YYYY-MM-DD). start_date와 함께 지정한다."),
    ) -> ParkingTimeSeriesResponse:
        # T-036: 명시적 과거 날짜범위 조회. days와 상호배타적이며 지정 시 이쪽이 우선한다.
        if start_date or end_date:
            if not (start_date and end_date):
                raise HTTPException(status_code=400, detail="start_date와 end_date는 함께 지정해야 합니다.")
            if not airport_code and not parking_lot_id:
                raise HTTPException(
                    status_code=400,
                    detail="start_date/end_date 조회는 airport_code 또는 parking_lot_id가 필요합니다.",
                )
            resolved_start = _parse_local_date_query(start_date, "start_date")
            resolved_end = _parse_local_date_query(end_date, "end_date")
            if resolved_end < resolved_start:
                raise HTTPException(status_code=400, detail="end_date는 start_date보다 빠를 수 없습니다.")
            span_days = (resolved_end - resolved_start).days + 1
            if span_days > MAX_TIMESERIES_RANGE_DAYS:
                raise HTTPException(
                    status_code=400,
                    detail=f"조회 기간은 최대 {MAX_TIMESERIES_RANGE_DAYS}일까지 가능합니다.",
                )
            snapshots = await _load_snapshots_between_local_dates(
                session, airport_code, parking_lot_id, resolved_start, resolved_end
            )
            # Anchor bucket placement on the *requested* end of range, not on whichever
            # snapshot happens to be latest - otherwise a trailing collection gap (a
            # maintenance-window restore, an upstream rate-limit block, or simply asking
            # for "today" before end of day) silently shifts the whole window backward
            # while start_date/end_date below keep claiming the originally-requested range.
            tz = ZoneInfo(resolved_settings.app_timezone)
            range_end_exclusive_local = datetime.combine(resolved_end, time.min, tzinfo=tz) + timedelta(days=1)
            anchor_at = range_end_exclusive_local - timedelta(minutes=interval_minutes)
            return ParkingTimeSeriesResponse(
                generated_at=now_utc(),
                airport_code=airport_code.upper() if airport_code else None,
                parking_lot_id=parking_lot_id,
                days=span_days,
                interval_minutes=interval_minutes,
                future_hours=0,
                start_date=resolved_start.isoformat(),
                end_date=resolved_end.isoformat(),
                items=[
                    TimeSeriesPoint(**point)
                    for point in build_time_series(
                        snapshots,
                        days=span_days,
                        interval_minutes=interval_minutes,
                        future_hours=0,
                        tz_name=resolved_settings.app_timezone,
                        anchor_at=anchor_at,
                    )
                ],
            )

        if (
            airport_code
            and days == DEFAULT_TIMESERIES_DAYS
            and interval_minutes == DEFAULT_TIMESERIES_INTERVAL_MINUTES
            and future_hours == DEFAULT_TIMESERIES_FUTURE_HOURS
        ):
            cached = await load_cached_analytics(
                session,
                metric=METRIC_TIMESERIES,
                airport_code=airport_code,
                parking_lot_id=parking_lot_id,
                days=days,
                interval_minutes=interval_minutes,
                future_hours=future_hours,
            )
            if cached is not None:
                return ParkingTimeSeriesResponse(**cached)

        snapshots = await _load_snapshots(
            session,
            airport_code,
            parking_lot_id,
            days,
            buffer_minutes=interval_minutes,
        )
        return ParkingTimeSeriesResponse(
            generated_at=now_utc(),
            airport_code=airport_code.upper() if airport_code else None,
            parking_lot_id=parking_lot_id,
            days=days,
            interval_minutes=interval_minutes,
            future_hours=future_hours,
            items=[
                TimeSeriesPoint(**point)
                for point in build_time_series(
                    snapshots,
                    days=days,
                    interval_minutes=interval_minutes,
                    future_hours=future_hours,
                    tz_name=resolved_settings.app_timezone,
                )
            ],
        )

    @router.get("/holidays/summary", response_model=HolidaySummaryResponse)
    async def holiday_summary(
        start_date: str | None = Query(default=None),
        end_date: str | None = Query(default=None),
        service: HolidayService = Depends(get_holiday_service),
    ) -> HolidaySummaryResponse:
        today = to_seoul(now_utc()).date()
        week_start = today - timedelta(days=today.weekday())
        resolved_start = _parse_local_date_query(start_date, "start_date") if start_date else week_start - timedelta(days=7)
        resolved_end = _parse_local_date_query(end_date, "end_date") if end_date else week_start + timedelta(days=20)
        if resolved_end < resolved_start:
            raise HTTPException(status_code=400, detail="end_date는 start_date보다 빠를 수 없습니다.")

        result = await service.get_holidays(resolved_start, resolved_end)
        collapsed_items = collapse_holidays_by_date(result.items)
        summary_items = [_build_holiday_summary_item(item.local_date, item.name) for item in collapsed_items]
        return HolidaySummaryResponse(
            generated_at=now_utc(),
            start_date=resolved_start.isoformat(),
            end_date=resolved_end.isoformat(),
            source=result.source,
            status=result.status,
            error_message=result.error_message,
            sentence=format_holiday_sentence(collapsed_items),
            items=summary_items,
        )

    @router.get("/parking/analytics/holiday-patterns", response_model=HolidayPatternResponse)
    async def holiday_patterns(
        airport_code: str | None = Query(default=None),
        parking_lot_id: int | None = Query(default=None),
        limit: int = Query(default=8, ge=1, le=16),
        session: AsyncSession = Depends(get_db),
        service: HolidayService = Depends(get_holiday_service),
    ) -> HolidayPatternResponse:
        today = to_seoul(now_utc()).date()
        lookback_days = max(90, limit * 14)
        holiday_result = await service.get_holidays(today - timedelta(days=lookback_days), today)
        holiday_items = collapse_holidays_by_date(holiday_result.items)
        special_days = _build_recent_special_days(today, holiday_items, limit)
        snapshots: list[ParkingSnapshot] = []
        if special_days:
            local_dates = [local_date for local_date, _name, _day_type in special_days]
            snapshots = await _load_snapshots_between_local_dates(
                session,
                airport_code,
                parking_lot_id,
                min(local_dates),
                max(local_dates),
            )

        return HolidayPatternResponse(
            generated_at=now_utc(),
            airport_code=airport_code.upper() if airport_code else None,
            parking_lot_id=parking_lot_id,
            source=holiday_result.source,
            status=holiday_result.status,
            error_message=holiday_result.error_message,
            items=[
                HolidayPatternItem(**pattern)
                for pattern in build_special_day_patterns(
                    snapshots,
                    special_days,
                    tz_name=resolved_settings.app_timezone,
                )
            ],
        )

    @router.get("/flights/status", response_model=FlightStatusResponse)
    async def flight_status(
        airport_code: str = Query(..., min_length=3, max_length=3),
        local_date: str | None = Query(default=None),
        service: FlightStatusService = Depends(get_flight_status_service),
    ) -> FlightStatusResponse:
        if local_date is None:
            query_date = to_seoul(now_utc()).date()
        else:
            try:
                query_date = date.fromisoformat(local_date)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="local_date는 YYYY-MM-DD 형식이어야 합니다.") from exc

        return FlightStatusResponse(**await service.get_status(airport_code, query_date))

    @router.get("/parking/analytics/threshold-events", response_model=list[ThresholdEvent])
    async def threshold_events(
        airport_code: str | None = Query(default=None),
        parking_lot_id: int | None = Query(default=None),
        days: int = Query(default=14, ge=1, le=60),
        limit: int = Query(default=20, ge=1, le=100),
        session: AsyncSession = Depends(get_db),
    ) -> list[ThresholdEvent]:
        if airport_code and days == DEFAULT_THRESHOLD_EVENTS_DAYS and limit == DEFAULT_THRESHOLD_EVENTS_LIMIT:
            cached = await load_cached_analytics(
                session,
                metric=METRIC_THRESHOLD_EVENTS,
                airport_code=airport_code,
                parking_lot_id=parking_lot_id,
                days=days,
                limit=limit,
            )
            if cached is not None:
                return [ThresholdEvent(**event) for event in cached]

        rows = await _load_snapshot_rows(session, airport_code, parking_lot_id, days)
        return [
            ThresholdEvent(**{**event, "crossed_at": serialize_utc(event["crossed_at"])})
            for event in detect_threshold_events(rows, limit=limit)
        ]

    @router.get("/parking/analytics/threshold-insights", response_model=ThresholdInsightsResponse)
    async def threshold_insights(
        airport_code: str | None = Query(default=None),
        parking_lot_id: int | None = Query(default=None),
        days: int = Query(default=21, ge=3, le=90),
        interval_minutes: int = Query(default=10, ge=10, le=60),
        session: AsyncSession = Depends(get_db),
    ) -> ThresholdInsightsResponse:
        if (
            airport_code
            and days == DEFAULT_THRESHOLD_INSIGHTS_DAYS
            and interval_minutes == DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES
        ):
            cached = await load_cached_analytics(
                session,
                metric=METRIC_THRESHOLD_INSIGHTS,
                airport_code=airport_code,
                parking_lot_id=parking_lot_id,
                days=days,
                interval_minutes=interval_minutes,
            )
            if cached is not None:
                return ThresholdInsightsResponse(**cached)

        snapshots = await _load_snapshots(
            session,
            airport_code,
            parking_lot_id,
            days,
            buffer_minutes=interval_minutes,
        )
        points = build_time_series(
            snapshots,
            days=days,
            interval_minutes=interval_minutes,
            tz_name=resolved_settings.app_timezone,
        )
        insights = build_threshold_insights(
            points,
            tz_name=resolved_settings.app_timezone,
        )
        return ThresholdInsightsResponse(
            generated_at=now_utc(),
            airport_code=airport_code.upper() if airport_code else None,
            parking_lot_id=parking_lot_id,
            days=days,
            interval_minutes=interval_minutes,
            weekday_items=[ThresholdWeekdayTime(**item) for item in insights["weekday_items"]],
            history_items=[
                ThresholdDateHistoryItem(
                    **{**item, "crossed_at": serialize_utc(item["crossed_at"])}
                )
                for item in insights["history_items"]
            ],
        )

    @router.post("/fees/calculate", response_model=FeeCalculationResponse)
    async def calculate_fees(
        payload: FeeCalculationRequest,
        session: AsyncSession = Depends(get_db),
    ) -> FeeCalculationResponse:
        airport = await session.scalar(select(Airport).where(Airport.code == payload.airport_code.upper()))
        if airport is None:
            raise HTTPException(status_code=404, detail="지원하지 않는 공항입니다.")

        if payload.parking_lot_id is not None:
            lot = await session.scalar(
                select(ParkingLot).where(
                    ParkingLot.id == payload.parking_lot_id,
                    ParkingLot.airport_id == airport.id,
                )
            )
            if lot is None:
                raise HTTPException(status_code=404, detail="해당 공항의 주차장을 찾지 못했습니다.")

        query = select(ParkingFeeRule).where(
            ParkingFeeRule.airport_id == airport.id,
            ParkingFeeRule.vehicle_size == payload.vehicle_size,
        ).order_by(
            ParkingFeeRule.parking_lot_id.is_(None).desc(),
            ParkingFeeRule.parking_lot_id,
            ParkingFeeRule.day_type,
        )
        if payload.parking_lot_id is not None:
            query = query.where(
                (ParkingFeeRule.parking_lot_id == payload.parking_lot_id) | (ParkingFeeRule.parking_lot_id.is_(None))
            )

        fetched_rules = (await session.execute(query)).scalars().all()
        # Generic rules are the fallback; a lot-specific rule must win
        # deterministically when both rows exist.
        generic_rules = [rule for rule in fetched_rules if rule.parking_lot_id is None]
        if payload.parking_lot_id is not None:
            rules = generic_rules + [
                rule for rule in fetched_rules if rule.parking_lot_id == payload.parking_lot_id
            ]
        elif generic_rules:
            rules = generic_rules
        else:
            # Some providers publish only lot-specific rules. For an airport
            # wide quote, use the lowest-id lot deterministically instead of
            # letting database row order decide which rule wins.
            lot_ids = sorted({rule.parking_lot_id for rule in fetched_rules if rule.parking_lot_id is not None})
            rules = [rule for rule in fetched_rules if rule.parking_lot_id == (lot_ids[0] if lot_ids else None)]
        if not rules:
            return FeeCalculationResponse(
                supported=False,
                airport_code=airport.code,
                vehicle_size=payload.vehicle_size,
                message="요금 규칙을 찾지 못했습니다.",
            )

        calculated = calculate_total_fee(payload.entry_at, payload.exit_at, rules)
        return FeeCalculationResponse(
            supported=True,
            airport_code=airport.code,
            vehicle_size=payload.vehicle_size,
            total_fee=calculated.total_fee,
            breakdown=calculated.breakdown,
        )

    @router.post("/admin/collect", response_model=CollectionSummary)
    async def admin_collect(
        session: AsyncSession = Depends(get_db),
        service: CollectionService = Depends(get_collection_service),
    ) -> CollectionSummary:
        if not resolved_settings.manual_collect_enabled:
            raise HTTPException(status_code=404, detail="수동 수집 endpoint가 비활성화되어 있습니다.")
        rate_limit_state = await service.get_upstream_rate_limit_state(session)
        can_collect_incheon = resolved_settings.enable_incheon_collection or resolved_settings.enable_incheon_fee_collection
        if rate_limit_state.is_blocked and rate_limit_state.blocked_until is not None and not can_collect_incheon:
            blocked_until_kst = to_seoul(rate_limit_state.blocked_until).strftime("%Y-%m-%d %H:%M:%S KST")
            raise HTTPException(
                status_code=429,
                detail=(
                    "공공데이터 API 요청 한도에 도달해 현재 수집을 잠시 멈췄습니다. "
                    f"{blocked_until_kst} 이후에 다시 시도해 주세요."
                ),
            )

        latest_snapshot = await _load_latest_snapshot_metadata(session)
        latest_collected_at = latest_snapshot["collected_at"]
        cooldown = timedelta(seconds=resolved_settings.manual_collect_min_interval_seconds)
        if latest_collected_at is not None:
            normalized_collected_at = serialize_utc(latest_collected_at)
            available_at = normalized_collected_at + cooldown
            if now_utc() < available_at:
                latest_collected_at_kst = to_seoul(normalized_collected_at).strftime("%Y-%m-%d %H:%M:%S KST")
                available_at_kst = to_seoul(available_at).strftime("%Y-%m-%d %H:%M:%S KST")
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"마지막 업데이트 시각이 {latest_collected_at_kst} 입니다. "
                        f"{resolved_settings.manual_collect_min_interval_seconds // 60}분이 지나지 않아 "
                        f"{available_at_kst} 이후에 다시 실행할 수 있습니다."
                    ),
                )
        summary = await service.collect(session, trigger="manual")
        if summary["snapshot_count"] > 0:
            await refresh_default_analytics_cache(session, resolved_settings)
            await session.commit()
        if summary["status"] == "failed":
            rate_limit_state = await service.get_upstream_rate_limit_state(session)
            if rate_limit_state.is_blocked and rate_limit_state.blocked_until is not None:
                blocked_until_kst = to_seoul(rate_limit_state.blocked_until).strftime("%Y-%m-%d %H:%M:%S KST")
                raise HTTPException(
                    status_code=429,
                    detail=(
                        "공공데이터 API 요청 한도에 도달해 현재 수집을 잠시 멈췄습니다. "
                        f"{blocked_until_kst} 이후에 다시 시도해 주세요."
                    ),
                )
            raise HTTPException(
                status_code=502,
                detail=summary["errors"][0] if summary["errors"] else "수집 실행에 실패했습니다.",
            )
        return CollectionSummary(**summary)

    @router.get("/admin/collector-status", response_model=CollectorStatusResponse)
    async def admin_collector_status(
        session: AsyncSession = Depends(get_db),
        service: CollectionService = Depends(get_collection_service),
    ) -> CollectorStatusResponse:
        recent_runs = await _load_collection_run_statuses(session, limit=5)
        last_run = recent_runs[0] if recent_runs else None
        latest_snapshot = await _load_latest_snapshot_metadata(session)
        latest_observed_at = latest_snapshot["observed_at"]
        latest_collected_at = latest_snapshot["collected_at"]
        earliest_observed_at = latest_snapshot["earliest_observed_at"]
        manual_collect_available_at = None
        manual_collect_blocked = False
        rate_limit_state = await service.get_upstream_rate_limit_state(session)

        if latest_collected_at is not None:
            manual_collect_available_at = serialize_utc(latest_collected_at) + timedelta(
                seconds=resolved_settings.manual_collect_min_interval_seconds
            )
            manual_collect_blocked = now_utc() < manual_collect_available_at

        return CollectorStatusResponse(
            scheduler_enabled=resolved_settings.enable_scheduler,
            collect_interval_seconds=resolved_settings.collect_interval_seconds,
            effective_collect_interval_seconds=resolved_settings.effective_collect_interval_seconds,
            scheduler_safety_buffer_seconds=resolved_settings.scheduler_safety_buffer_seconds,
            manual_collect_enabled=resolved_settings.manual_collect_enabled,
            manual_collect_min_interval_seconds=resolved_settings.manual_collect_min_interval_seconds,
            client_mode=service.client_mode,
            enabled_sources=service.enabled_sources,
            data_go_kr_service_key_configured=bool(resolved_settings.data_go_kr_service_key),
            supported_airport_codes=resolved_settings.supported_airport_codes,
            latest_snapshot_observed_at=serialize_utc(latest_observed_at) if latest_observed_at else None,
            latest_snapshot_collected_at=serialize_utc(latest_collected_at) if latest_collected_at else None,
            earliest_snapshot_observed_at=serialize_utc(earliest_observed_at) if earliest_observed_at else None,
            manual_collect_available_at=manual_collect_available_at,
            manual_collect_blocked=manual_collect_blocked,
            upstream_rate_limited=rate_limit_state.is_blocked,
            upstream_rate_limited_until=(
                serialize_utc(rate_limit_state.blocked_until) if rate_limit_state.blocked_until else None
            ),
            last_run=last_run,
            recent_runs=recent_runs,
        )

    @router.get("/admin/backups", response_model=BackupListResponse)
    async def admin_backups() -> BackupListResponse:
        items = await list_backups(resolved_settings.backup_dir)
        return BackupListResponse(
            items=[BackupFile(filename=item.filename, size_bytes=item.size_bytes, created_at=item.created_at) for item in items]
        )

    @router.post("/admin/backups", response_model=BackupFile, status_code=201)
    async def admin_create_backup(
        service: CollectionService = Depends(get_collection_service),
    ) -> BackupFile:
        async with service.operation_lock:
            try:
                item = await create_backup(
                    resolved_settings.backup_dir,
                    resolved_settings.database_url,
                    resolved_settings.backup_retention_count,
                    resolved_settings.backup_command_timeout_seconds,
                    resolved_settings.backup_storage_limit_bytes,
                )
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return BackupFile(filename=item.filename, size_bytes=item.size_bytes, created_at=item.created_at)

    @router.get("/admin/backups/{filename}")
    async def admin_download_backup(filename: str) -> FileResponse:
        try:
            path = backup_path_for_download(resolved_settings.backup_dir, filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if path.is_symlink() or not path.is_file():
            raise HTTPException(status_code=404, detail="백업 파일을 찾지 못했습니다.")
        return FileResponse(path, media_type="application/octet-stream", filename=filename)

    @router.post("/admin/backups/restore", response_model=BackupRestoreResponse)
    async def admin_restore_backup(
        file: UploadFile = File(...),
        service: CollectionService = Depends(get_collection_service),
    ) -> BackupRestoreResponse:
        if not file.filename or not file.filename.lower().endswith(".dump"):
            raise HTTPException(status_code=400, detail=".dump 형식의 PostgreSQL 백업만 복원할 수 있습니다.")
        if resolved_settings.enable_scheduler:
            raise HTTPException(
                status_code=409,
                detail="수집 scheduler가 실행 중입니다. 5분 데이터 연속성을 위해 유지보수 창에서 scheduler를 중지한 뒤 복원하세요.",
            )
        async with service.operation_lock:
            uploaded = None
            try:
                pre_restore = await create_backup(
                    resolved_settings.backup_dir,
                    resolved_settings.database_url,
                    resolved_settings.backup_retention_count,
                    resolved_settings.backup_command_timeout_seconds,
                    resolved_settings.backup_storage_limit_bytes,
                )
                uploaded = await save_uploaded_backup(
                    file,
                    resolved_settings.backup_dir,
                    resolved_settings.backup_storage_limit_bytes,
                    protected_filenames={pre_restore.filename},
                    upload_timeout_seconds=resolved_settings.backup_upload_timeout_seconds,
                )
                restored = await restore_backup(
                    resolved_settings.backup_dir,
                    resolved_settings.database_url,
                    uploaded.filename,
                    resolved_settings.backup_command_timeout_seconds,
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail="업로드한 백업 파일을 찾지 못했습니다.") from exc
            except (RuntimeError, ValueError) as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            finally:
                if uploaded is not None:
                    await remove_backup(resolved_settings.backup_dir, uploaded.filename)
        return BackupRestoreResponse(
            status="restored",
            restored_from=BackupFile(
                filename=restored.filename,
                size_bytes=restored.size_bytes,
                created_at=restored.created_at,
            ),
            pre_restore_backup=BackupFile(
                filename=pre_restore.filename,
                size_bytes=pre_restore.size_bytes,
                created_at=pre_restore.created_at,
            ),
        )

    @router.get("/dashboard/bootstrap", response_model=DashboardBootstrapResponse)
    async def dashboard_bootstrap(
        airport_code: str | None = Query(default=None),
        session: AsyncSession = Depends(get_db),
        collection_service: CollectionService = Depends(get_collection_service),
        holiday_service: HolidayService = Depends(get_holiday_service),
    ) -> DashboardBootstrapResponse:
        """Return the first-paint payload in one request instead of four N+1 calls."""

        return DashboardBootstrapResponse(
            airports=await airports(session),
            current=await parking_current(airport_code, session),
            collector=await admin_collector_status(session, collection_service),
            holidays=await holiday_summary(None, None, holiday_service),
        )

    @router.get("/dashboard/analytics", response_model=DashboardAnalyticsResponse)
    async def dashboard_analytics(
        airport_code: str = Query(..., min_length=3, max_length=3),
        parking_lot_id: int | None = Query(default=None),
        session: AsyncSession = Depends(get_db),
        holiday_service: HolidayService = Depends(get_holiday_service),
    ) -> DashboardAnalyticsResponse:
        """Return the database-backed analytics together; flight data stays isolated."""

        return DashboardAnalyticsResponse(
            threshold_events=await threshold_events(
                airport_code,
                parking_lot_id,
                DEFAULT_THRESHOLD_EVENTS_DAYS,
                DEFAULT_THRESHOLD_EVENTS_LIMIT,
                session,
            ),
            threshold_insights=await threshold_insights(
                airport_code,
                parking_lot_id,
                DEFAULT_THRESHOLD_INSIGHTS_DAYS,
                DEFAULT_THRESHOLD_INSIGHTS_INTERVAL_MINUTES,
                session,
            ),
            weekday_hour_patterns=await parking_by_weekday_hour(
                airport_code,
                parking_lot_id,
                DEFAULT_WEEKDAY_HOUR_DAYS,
                session,
            ),
            holiday_patterns=await holiday_patterns(
                airport_code,
                parking_lot_id,
                8,
                session,
                holiday_service,
            ),
            time_series=await parking_time_series(
                airport_code,
                parking_lot_id,
                DEFAULT_TIMESERIES_DAYS,
                DEFAULT_TIMESERIES_INTERVAL_MINUTES,
                DEFAULT_TIMESERIES_FUTURE_HOURS,
                session,
                start_date=None,
                end_date=None,
            ),
        )

    async def _load_snapshots(
        session: AsyncSession,
        airport_code: str | None,
        parking_lot_id: int | None,
        days: int,
        buffer_minutes: int = 0,
    ) -> list[ParkingSnapshot]:
        cutoff = now_utc() - timedelta(days=days, minutes=buffer_minutes)
        query = select(ParkingSnapshot).where(ParkingSnapshot.observed_at >= cutoff)

        if parking_lot_id:
            query = query.where(ParkingSnapshot.parking_lot_id == parking_lot_id)
        elif airport_code:
            airport = await session.scalar(select(Airport).where(Airport.code == airport_code.upper()))
            if airport is None:
                return []
            query = query.where(ParkingSnapshot.airport_id == airport.id)

        return deduplicate_snapshots((await session.execute(query)).scalars().all())

    async def _load_snapshots_between_local_dates(
        session: AsyncSession,
        airport_code: str | None,
        parking_lot_id: int | None,
        start_date: date,
        end_date: date,
    ) -> list[ParkingSnapshot]:
        tz = ZoneInfo(resolved_settings.app_timezone)
        start_at = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(ZoneInfo("UTC"))
        end_at = (datetime.combine(end_date, time.min, tzinfo=tz) + timedelta(days=1)).astimezone(ZoneInfo("UTC"))
        query = select(ParkingSnapshot).where(
            ParkingSnapshot.observed_at >= start_at,
            ParkingSnapshot.observed_at < end_at,
        )

        if parking_lot_id:
            query = query.where(ParkingSnapshot.parking_lot_id == parking_lot_id)
        elif airport_code:
            airport = await session.scalar(select(Airport).where(Airport.code == airport_code.upper()))
            if airport is None:
                return []
            query = query.where(ParkingSnapshot.airport_id == airport.id)

        return deduplicate_snapshots((await session.execute(query)).scalars().all())

    async def _load_snapshot_rows(
        session: AsyncSession,
        airport_code: str | None,
        parking_lot_id: int | None,
        days: int,
    ) -> list[tuple[ParkingSnapshot, ParkingLot, Airport]]:
        cutoff = now_utc() - timedelta(days=days)
        query = (
            select(ParkingSnapshot, ParkingLot, Airport)
            .join(ParkingLot, ParkingLot.id == ParkingSnapshot.parking_lot_id)
            .join(Airport, Airport.id == ParkingSnapshot.airport_id)
            .where(ParkingSnapshot.observed_at >= cutoff)
        )
        if parking_lot_id:
            query = query.where(ParkingSnapshot.parking_lot_id == parking_lot_id)
        elif airport_code:
            query = query.where(Airport.code == airport_code.upper())
        return deduplicate_snapshot_rows((await session.execute(query)).all())

    # `/health` stays unversioned (kor-travel-map convention: health/version are
    # fixed, everything else is versioned). All other routes live under `/v1`
    # (ADR-005) -- a clean-cut, no legacy unprefixed alias.
    app.include_router(router, prefix="/v1")

    return app


def _parse_local_date_query(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name}는 YYYY-MM-DD 형식이어야 합니다.") from exc


def _build_holiday_summary_item(local_date: date, name: str) -> HolidayItemSummary:
    weekday = local_date.weekday()
    return HolidayItemSummary(
        local_date=local_date.isoformat(),
        name=name,
        weekday=weekday,
        weekday_name=HOLIDAY_WEEKDAY_LABELS[weekday],
    )


def _build_recent_special_days(
    today: date,
    holiday_items: list[HolidayItem],
    limit: int,
) -> list[tuple[date, str, str]]:
    holiday_names = {item.local_date: item.name for item in holiday_items}
    special_days: list[tuple[date, str, str]] = []
    cursor = today
    while len(special_days) < limit:
        if cursor in holiday_names:
            special_days.append((cursor, holiday_names[cursor], "holiday"))
        elif cursor.weekday() == 5:
            special_days.append((cursor, "토요일", "saturday"))
        elif cursor.weekday() == 6:
            special_days.append((cursor, "일요일", "sunday"))
        cursor -= timedelta(days=1)
    return special_days


async def _run_scheduler(app: FastAPI) -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    service: CollectionService = app.state.collection_service
    settings: Settings = app.state.settings

    loop = asyncio.get_running_loop()
    next_deadline = loop.time()
    while True:
        async with session_factory() as session:
            try:
                summary = await service.collect(session, trigger="scheduler")
                logger.info(
                    "scheduler tick completed run_id=%s status=%s client_mode=%s raw=%s snapshots=%s fee_rules=%s",
                    summary["collection_run_id"],
                    summary["status"],
                    summary["client_mode"],
                    summary["raw_response_count"],
                    summary["snapshot_count"],
                    summary["fee_rule_count"],
                )
                if summary["snapshot_count"] > 0:
                    refreshed = await refresh_default_analytics_cache(session, settings)
                    await session.commit()
                    logger.info("analytics cache refreshed scopes=%s", refreshed)
            except Exception:
                await session.rollback()
                logger.exception("scheduler tick failed")
        next_deadline += settings.effective_collect_interval_seconds
        delay = next_deadline - loop.time()
        if delay < 0:
            logger.warning(
                "scheduler collection overran interval by %.1f seconds; starting next tick immediately",
                -delay,
            )
            next_deadline = loop.time()
            delay = 0
        await asyncio.sleep(delay)


async def _run_transport_scheduler(app: FastAPI, scope: CollectionScope = "highway") -> None:
    session_factory: async_sessionmaker[AsyncSession] = app.state.session_factory
    service: TransportCollectionService = app.state.transport_collection_service
    settings: Settings = app.state.settings

    while True:
        delay = float(settings.transport_collect_interval_seconds)
        async with session_factory() as session:
            try:
                summary = await service.collect(session, trigger=f"transport_{scope}_scheduler", scope=scope)
                logger.info(
                    "transport scheduler tick completed run_id=%s status=%s mode=%s traffic=%s incidents=%s stations=%s prices=%s",
                    summary["collection_run_id"],
                    summary["status"],
                    summary["client_mode"],
                    summary["traffic_snapshot_count"],
                    summary["incident_snapshot_count"],
                    summary["fuel_station_count"],
                    summary["fuel_price_count"],
                )
                delay = await service.next_collection_delay(session, scope)
            except Exception:
                await session.rollback()
                logger.exception("transport scheduler tick failed")
        await asyncio.sleep(delay)


async def _load_collection_run_statuses(
    session: AsyncSession,
    limit: int = 5,
) -> list[CollectionRunStatus]:
    runs = (
        await session.execute(
            select(CollectionRun)
            .where(~CollectionRun.trigger.startswith(TRANSPORT_TRIGGER_PREFIX, autoescape=True))
            .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    if not runs:
        return []

    run_ids = [run.id for run in runs]
    raw_counts = {
        collection_run_id: count
        for collection_run_id, count in (
            await session.execute(
                select(RawApiResponse.collection_run_id, func.count(RawApiResponse.id))
                .where(RawApiResponse.collection_run_id.in_(run_ids))
                .group_by(RawApiResponse.collection_run_id)
            )
        ).all()
    }
    snapshot_counts = {
        collection_run_id: count
        for collection_run_id, count in (
            await session.execute(
                select(ParkingSnapshot.collection_run_id, func.count(ParkingSnapshot.id))
                .where(ParkingSnapshot.collection_run_id.in_(run_ids))
                .group_by(ParkingSnapshot.collection_run_id)
            )
        ).all()
    }

    return [
        CollectionRunStatus(
            id=run.id,
            started_at=serialize_utc(run.started_at),
            finished_at=serialize_utc(run.finished_at) if run.finished_at else None,
            status=run.status,
            trigger=run.trigger,
            error_message=run.error_message,
            raw_response_count=raw_counts.get(run.id, 0),
            snapshot_count=snapshot_counts.get(run.id, 0),
        )
        for run in runs
    ]


async def _load_latest_snapshot_metadata(session: AsyncSession) -> dict[str, object | None]:
    # Polled every 15s by every open tab (admin/collector-status) - one round trip for
    # all three aggregates instead of three, Postgres computes each via its own
    # min/max-over-index scan regardless.
    row = (
        await session.execute(
            select(
                func.max(ParkingSnapshot.observed_at),
                func.max(ParkingSnapshot.collected_at),
                func.min(ParkingSnapshot.observed_at),
            )
        )
    ).one()
    return {
        "observed_at": row[0],
        "collected_at": row[1],
        "earliest_observed_at": row[2],
    }


app = create_app()
