"""내부 서비스용 일괄 export `/v1/service/exports/*` (ADR-012).

kor-travel-map이 OpiNet·KREX·공항 데이터를 provider에 직접 묻지 않고 transport가 저장한 값을
읽어 가는 경로다. 공개 지도 API와 달리 원본 provider 행(`raw`)을 함께 주므로 토큰과 loopback
Host로 닫는다. 토큰이 없거나 짧거나 다르거나, 외부 reverse proxy의 Host로 들어오면 경로 자체를
숨긴다(404) — 관리자 좌표 보정 경로와 같은 관례다.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from krairport import KrairportClient
from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.models import (
    Airport,
    FuelLatestPrice,
    FuelStation,
    HighwayIncidentSnapshot,
    ParkingLot,
    RestAreaFuelPrice,
    RestAreaReference,
    TransportCollectionState,
)
from app.schemas import (
    AirportExportResponse,
    ExportAirport,
    ExportCollectionState,
    ExportFuelPrice,
    ExportFuelStation,
    ExportHighwayIncident,
    ExportRestArea,
    ExportRestAreaFuelPrice,
    FuelStationExportPage,
    HighwayIncidentActiveSet,
    RestAreaExportPage,
    RestAreaFuelPriceExportPage,
)
from app.services.rest_area_collection import REST_AREA_FUEL_SOURCE, REST_AREA_SOURCE
from app.services.transport_collection import INCIDENT_SOURCE, OPINET_SOURCE, fuel_read_model_freshness

SERVICE_TOKEN_HEADER = "x-kor-travel-transport-service-token"
MIN_SERVICE_TOKEN_LENGTH = 32
#: 참조 데이터는 마지막 성공 수집보다 이만큼 이전까지 본 행을 현재 집합으로 본다. 한 번의 부분
#: 수집(일부 지역 실패)으로 행이 사라졌다고 판단하지 않기 위한 여유다.
CURRENT_SET_WINDOW = timedelta(days=3)
#: 돌발 활성 집합은 5분 수집이 이보다 오래 성공하지 못하면 내주지 않는다(소비자가 해소로 오판).
INCIDENT_ACTIVE_SET_MAX_AGE = timedelta(minutes=30)
#: 참조 데이터 stale 표시 기준. 정기 주기(유가 8시간·휴게소 1일·유가 4시간)의 약 3배.
REFERENCE_STALE_AFTER = {
    REST_AREA_SOURCE: timedelta(days=3),
    REST_AREA_FUEL_SOURCE: timedelta(hours=12),
}
MAX_PAGE_SIZE = 1000


def build_service_export_router(
    settings: Settings, get_db: Callable[..., AsyncIterator[AsyncSession]],
) -> APIRouter:
    def require_service_token(request: Request) -> None:
        configured = settings.transport_service_export_token or ""
        provided = request.headers.get(SERVICE_TOKEN_HEADER, "")
        host = (request.url.hostname or "").lower()
        token_ok = len(configured) >= MIN_SERVICE_TOKEN_LENGTH and secrets.compare_digest(
            configured.encode(), provided.encode(),
        )
        if not token_ok or host not in settings.service_export_allowed_hosts:
            raise HTTPException(status_code=404, detail="Not Found")

    router = APIRouter(prefix="/service/exports", dependencies=[Depends(require_service_token)],
                       tags=["service-exports"])

    @router.get("/fuel-stations", response_model=FuelStationExportPage)
    async def export_fuel_stations(
        cursor: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=MAX_PAGE_SIZE),
        session: AsyncSession = Depends(get_db),
    ) -> FuelStationExportPage:
        """오피넷 주유소와 유종별 최신 가격. 안정 ID(uni_id)가 없는 행은 내보내지 않는다."""
        stale, state = await fuel_read_model_freshness(session)
        collection = _collection(OPINET_SOURCE, state, stale)
        after = _decode_cursor(cursor)
        query = (
            select(FuelStation)
            .where(FuelStation.source == OPINET_SOURCE, FuelStation.source_station_id.is_not(None),
                   FuelStation.id > after)
            .order_by(FuelStation.id).limit(limit + 1)
        )
        query = _current_set(query, FuelStation.last_seen_at, state)
        stations = list((await session.scalars(query)).all())
        page, has_more = stations[:limit], len(stations) > limit
        prices: dict[int, list[ExportFuelPrice]] = {}
        if page:
            rows = (await session.scalars(select(FuelLatestPrice).where(
                FuelLatestPrice.fuel_station_id.in_([row.id for row in page]),
            ).order_by(FuelLatestPrice.fuel_station_id, FuelLatestPrice.product_code))).all()
            for row in rows:
                prices.setdefault(row.fuel_station_id, []).append(ExportFuelPrice(
                    product_code=row.product_code,
                    price=float(row.price) if row.price is not None else None,
                    provider_updated_at=serialize_utc(row.provider_updated_at) if row.provider_updated_at else None,
                    observed_at=serialize_utc(row.observed_at),
                    collected_at=serialize_utc(row.collected_at),
                ))
        items = [ExportFuelStation(
            natural_key=row.source_station_id, source=row.source, name=row.name,
            brand_code=row.brand_code, brand_name=row.brand_name, phone=row.phone, address=row.address,
            longitude=row.longitude, latitude=row.latitude, is_self=row.is_self, is_24h=row.is_24h,
            has_carwash=row.has_carwash, has_maintenance=row.has_maintenance, has_cvs=row.has_cvs,
            first_seen_at=serialize_utc(row.first_seen_at), last_seen_at=serialize_utc(row.last_seen_at),
            prices=prices.get(row.id, []), raw=row.raw_item_json,
        ) for row in page]
        return FuelStationExportPage(
            generated_at=now_utc(), collection=collection, items=items,
            next_cursor=str(page[-1].id) if has_more else None, has_more=has_more,
        )

    @router.get("/rest-areas", response_model=RestAreaExportPage)
    async def export_rest_areas(
        cursor: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=MAX_PAGE_SIZE),
        session: AsyncSession = Depends(get_db),
    ) -> RestAreaExportPage:
        """고속도로 휴게소 기준정보(data.go.kr 표준데이터)."""
        state = await _state(session, REST_AREA_SOURCE)
        query = (
            select(RestAreaReference)
            .where(RestAreaReference.source == REST_AREA_SOURCE, RestAreaReference.id > _decode_cursor(cursor))
            .order_by(RestAreaReference.id).limit(limit + 1)
        )
        rows = list((await session.scalars(_current_set(query, RestAreaReference.last_seen_at, state))).all())
        page, has_more = rows[:limit], len(rows) > limit
        items = [ExportRestArea(
            natural_key=row.identity_key, source=row.source, name=row.name, route_name=row.route_name,
            direction=row.direction, longitude=row.longitude, latitude=row.latitude,
            has_gas_station=row.has_gas_station, has_lpg_station=row.has_lpg_station,
            has_ev_charger=row.has_ev_charger, phone_number=row.phone_number,
            data_reference_date=row.data_reference_date, first_seen_at=serialize_utc(row.first_seen_at),
            last_seen_at=serialize_utc(row.last_seen_at), raw=row.raw_item_json,
        ) for row in page]
        return RestAreaExportPage(
            generated_at=now_utc(), collection=_reference_collection(REST_AREA_SOURCE, state), items=items,
            next_cursor=str(page[-1].id) if has_more else None, has_more=has_more,
        )

    @router.get("/rest-area-fuel-prices", response_model=RestAreaFuelPriceExportPage)
    async def export_rest_area_fuel_prices(
        cursor: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=MAX_PAGE_SIZE),
        session: AsyncSession = Depends(get_db),
    ) -> RestAreaFuelPriceExportPage:
        """휴게소 주유소 현재 유가(한국도로공사 EX). `observed_at`은 transport 수집 시각이다."""
        state = await _state(session, REST_AREA_FUEL_SOURCE)
        query = (
            select(RestAreaFuelPrice)
            .where(RestAreaFuelPrice.source == REST_AREA_FUEL_SOURCE, RestAreaFuelPrice.id > _decode_cursor(cursor))
            .order_by(RestAreaFuelPrice.id).limit(limit + 1)
        )
        rows = list((await session.scalars(_current_set(query, RestAreaFuelPrice.last_seen_at, state))).all())
        page, has_more = rows[:limit], len(rows) > limit
        items = [ExportRestAreaFuelPrice(
            service_area_code=row.service_area_code, source=row.source,
            service_area_code2=row.service_area_code2, service_area_name=row.service_area_name,
            route_code=row.route_code, route_name=row.route_name, direction=row.direction,
            oil_company=row.oil_company, has_lpg=row.has_lpg, phone_number=row.phone_number,
            address=row.address, gasoline_price=row.gasoline_price, diesel_price=row.diesel_price,
            lpg_price=row.lpg_price, observed_at=serialize_utc(row.last_seen_at), raw=row.raw_item_json,
        ) for row in page]
        return RestAreaFuelPriceExportPage(
            generated_at=now_utc(), collection=_reference_collection(REST_AREA_FUEL_SOURCE, state), items=items,
            next_cursor=str(page[-1].id) if has_more else None, has_more=has_more,
        )

    @router.get("/highway-incidents/active", response_model=HighwayIncidentActiveSet)
    async def export_active_highway_incidents(session: AsyncSession = Depends(get_db)) -> HighwayIncidentActiveSet:
        """마지막 성공 돌발 수집의 활성 사건 전체(페이지 없음).

        수집이 실패했거나 30분 넘게 성공하지 못했으면 503이다 — 오래된 집합을 주면 소비자가
        사라진 사건을 해소로 오판한다. 빈 목록은 "현재 돌발 없음"이라는 확인된 사실이다.
        """
        state = await _state(session, INCIDENT_SOURCE)
        if (state is None or state.last_success_at is None or state.last_error is not None
                or now_utc() - serialize_utc(state.last_success_at) > INCIDENT_ACTIVE_SET_MAX_AGE):
            raise HTTPException(status_code=503, detail="고속도로 돌발 수집이 최근에 성공하지 않았습니다.")
        collected_at = serialize_utc(state.last_success_at)
        ranked = select(
            HighwayIncidentSnapshot.id.label("id"),
            func.row_number().over(
                partition_by=HighwayIncidentSnapshot.identity_key,
                order_by=(HighwayIncidentSnapshot.observed_at.desc(), HighwayIncidentSnapshot.id.desc()),
            ).label("rank"),
        ).where(
            HighwayIncidentSnapshot.source == INCIDENT_SOURCE,
            HighwayIncidentSnapshot.collected_at >= collected_at,
        ).subquery()
        rows = (await session.scalars(
            select(HighwayIncidentSnapshot).join(ranked, HighwayIncidentSnapshot.id == ranked.c.id)
            .where(ranked.c.rank == 1).order_by(HighwayIncidentSnapshot.id)
        )).all()
        items = [ExportHighwayIncident(
            identity_key=row.identity_key, source=row.source, occurred_date=row.occurred_date,
            occurred_time=row.occurred_time, incident_type=row.incident_type,
            incident_type_code=row.incident_type_code, direction=row.direction, message=row.message,
            point_name=row.point_name, route_no=row.route_no, route_name=row.route_name,
            process_status=row.process_status, process_status_code=row.process_status_code,
            latitude=row.latitude, longitude=row.longitude, congestion_length=row.congestion_length,
            series_no=row.series_no, observed_at=serialize_utc(row.observed_at),
            collected_at=serialize_utc(row.collected_at),
            raw=(row.raw_item_json or {}).get("raw") if isinstance(row.raw_item_json, dict) else None,
        ) for row in rows]
        return HighwayIncidentActiveSet(
            generated_at=now_utc(), collection=_collection(INCIDENT_SOURCE, state, False),
            collected_at=collected_at, items=items,
        )

    @router.get("/airports", response_model=AirportExportResponse)
    async def export_airports(session: AsyncSession = Depends(get_db)) -> AirportExportResponse:
        """운영 중인 국내 공항 전체(krairport 번들 메타데이터, 주차 수집 여부와 무관)."""
        with_parking = set((await session.scalars(
            select(Airport.code).join(ParkingLot, ParkingLot.airport_id == Airport.id).distinct()
        )).all())
        client = KrairportClient()
        try:
            airports = client.airports(active=True)
        finally:
            await client.aclose()
        items = [ExportAirport(
            code=airport.code, icao_code=airport.icao_code, name_korean=airport.name_korean,
            name_english=airport.name_english, municipality=airport.municipality,
            longitude=airport.coordinate.lon if airport.coordinate else None,
            latitude=airport.coordinate.lat if airport.coordinate else None,
            airport_type=getattr(airport.airport_type, "value", airport.airport_type),
            metadata_source=airport.source, has_parking_data=airport.code in with_parking,
        ) for airport in sorted(airports, key=lambda value: value.code)]
        return AirportExportResponse(generated_at=now_utc(), items=items)

    return router


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isascii() or not cursor.isdecimal():
        raise HTTPException(status_code=422, detail="cursor는 이전 응답의 next_cursor를 그대로 보내야 합니다.")
    return int(cursor)


async def _state(session: AsyncSession, source: str) -> TransportCollectionState | None:
    return await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == source))


def _current_set(query: Any, last_seen_column: Any, state: TransportCollectionState | None) -> Any:
    """마지막 성공 수집 근처에 본 행만 현재 집합으로 낸다. 수집 이력이 없으면 빈 집합이다."""
    if state is None or state.last_success_at is None:
        return query.where(false())
    return query.where(last_seen_column >= serialize_utc(state.last_success_at) - CURRENT_SET_WINDOW)


def _collection(source: str, state: TransportCollectionState | None, stale: bool) -> ExportCollectionState:
    return ExportCollectionState(
        source=source,
        last_success_at=serialize_utc(state.last_success_at) if state and state.last_success_at else None,
        failed=bool(state and state.last_error),
        stale=stale,
    )


def _reference_collection(source: str, state: TransportCollectionState | None) -> ExportCollectionState:
    last_success: datetime | None = serialize_utc(state.last_success_at) if state and state.last_success_at else None
    stale = (last_success is None or bool(state and state.last_error)
             or now_utc() - last_success > REFERENCE_STALE_AFTER[source])
    return _collection(source, state, stale)
