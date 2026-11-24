"""내부 서비스용 일괄 export `/v1/service/exports/*` (ADR-013).

kor-travel-map이 OpiNet·KREX·공항 데이터를 provider에 직접 묻지 않고 transport가 저장한 값을
읽어 가는 경로다. 공개 지도 API와 달리 원본 provider 행(`raw`)을 함께 주므로 토큰과 **접속한
쪽의 주소**(loopback 기본)로 닫는다. 토큰이 없거나 짧거나 다르거나, 허용 대역 밖에서 접속하면 경로
자체를 숨긴다(404) — 관리자 좌표 보정 경로와 같은 관례다. `Host` 헤더는 호출자가 마음대로 정하는
값이라 판정에 쓰지 않는다(backend는 host network라 `request.client`가 실제 peer 주소다).

모든 dataset은 같은 원칙을 따른다: 200이면 그 응답의 집합은 "마지막 성공 수집의 현재 집합"이라는
뜻이고, 소비자는 거기 없는 행을 사라진 것으로 다뤄도 된다. 그 전제가 서지 않으면 503이다.

- 참조 데이터(주유소·휴게소·휴게소 유가)는 **마지막 성공 수집 시각**으로만 판정한다. 성공이 stale
  기준(`REFERENCE_STALE_AFTER`) 안이면 그 뒤의 시도가 실패했어도 마지막 성공 수집의 집합을 200으로
  낸다(실패한 시도는 저장 transaction을 되돌려 그 집합을 바꾸지 않는다). 그 사실은
  `collection.last_attempt_failed`로 알린다. 성공이 없거나 기준을 넘었으면 503이다.
- 돌발 활성 집합은 "지금"의 집합이라 마지막 수집이 실패했거나 30분을 넘으면 503이다.

200 본문의 `collection.failed`·`stale`은 언제나 false다. 한 응답 안의 상태 행과 데이터 행은
REPEATABLE READ 한 snapshot에서 읽는다.

응답 본문(DTO 구성·JSON 직렬화·gzip)은 마지막 SQL 뒤 읽기 transaction을 닫고(연결을 pool로 반납) 전용
worker thread에서 만든다 — 단일 uvicorn event loop를 막지 않고, snapshot을 송신 끝까지 쥐지 않는다
(감사 T1-03·T1-04·RT-08). 본문 바이트는 FastAPI 기본 직렬화(pydantic `dump_json`)와 같다.
"""

from __future__ import annotations

import gzip
import ipaddress
import json
import secrets
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import datetime, timedelta
from functools import cache, partial
from typing import Any

from anyio import CapacityLimiter, to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from krairport import list_airports
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import Text, cast, false, func, select, text
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
from app.services.export_addresses import build_admin_addresses, fetch_admin_address_rows
from app.public_parking_routes import build_public_parking_export_router
from app.services.export_current import build_current_export_router
from app.services.export_references import build_reference_export_router
from app.services.export_price_history import build_price_history_router
from app.services.parking_history_cache import accepts_gzip
from app.services.rest_area_collection import REST_AREA_FUEL_SOURCE, REST_AREA_SOURCE
from app.services.transport_collection import (
    FUEL_STALE_AFTER,
    INCIDENT_SOURCE,
    OPINET_SOURCE,
)

SERVICE_TOKEN_HEADER = "x-kor-travel-transport-service-token"
MIN_SERVICE_TOKEN_LENGTH = 32
#: 참조 데이터는 마지막 성공 수집보다 이만큼 이전까지 본 행을 현재 집합으로 본다. 한 번의 부분
#: 수집(일부 지역 실패)으로 행이 사라졌다고 판단하지 않기 위한 여유다.
CURRENT_SET_WINDOW = timedelta(days=3)
#: 돌발 활성 집합은 5분 수집이 이보다 오래 성공하지 못하면 내주지 않는다(소비자가 해소로 오판).
INCIDENT_ACTIVE_SET_MAX_AGE = timedelta(minutes=30)
#: 참조 데이터 stale 기준 — 마지막 **성공** 수집에서 이만큼 지나면 503(그 사이의 실패한 시도는 503 사유가
#: 아니다). 정기 주기(유가 8시간·휴게소 1일·휴게소 유가 4시간)의 약 3배. 오피넷은 공개 API의 유가
#: 신선도(`FUEL_STALE_AFTER`)와 같은 값을 쓴다.
REFERENCE_STALE_AFTER = {
    OPINET_SOURCE: FUEL_STALE_AFTER,
    REST_AREA_SOURCE: timedelta(days=3),
    REST_AREA_FUEL_SOURCE: timedelta(hours=12),
}
MAX_PAGE_SIZE = 1000
#: keyset cursor는 int4 PK다. 범위 밖 값은 bind 단계에서 DataError(일반 500)가 되므로 422로 막는다(감사 T1-09).
MAX_CURSOR = 2**31 - 1
#: snapshot 문장 상한. Map read timeout(30초)보다 짧게 둬, Map이 포기한 페이지를 서버가 끝까지 만들며
#: 연결을 쥐지 않게 한다(감사 RT-04, T1 timeout 예산). 페이지 SQL은 PK·보조 인덱스 조회라 평소 수십 ms다.
SNAPSHOT_STATEMENT_TIMEOUT = "20s"
#: AccessExclusive를 기다리는 DDL(migration) 뒤에 줄 서서 statement_timeout까지 막히지 않게 한다.
SNAPSHOT_LOCK_TIMEOUT = "3s"
#: 본문 구성(DTO·JSON·gzip)을 동시에 돌리는 worker thread 수 상한(감사 T1-03). 공개 유가 지도
#: `fuel_map_limiter`와 같은 2다 — 단일 프로세스의 GIL·CPU를 export가 독점하지 않게 한다.
RENDER_CONCURRENCY = 2
#: 이보다 작은 본문은 압축하지 않는다(T4 가격 이력 `_response`와 같은 기준, 감사 T1-06).
GZIP_MIN_BYTES = 512
#: 한 번의 `dump_json`으로 직렬화하는 item 수. 이 단위로 GIL을 놓아 event loop가 끼어들 틈을 둔다(로컬 500행
#: 주유소 페이지에서 묶음당 약 5ms 이하, 전체 직렬화 시간은 한 번에 할 때와 비슷했다).
DUMP_GROUP = 25


def _raw_text(column: Any) -> Any:
    """원본 행(JSONB)을 문자열로 받아 worker thread에서 `json.loads`한다(감사 T1-03).

    asyncpg는 JSONB를 fetch 중(event loop)에 `json.loads`로 푼다(합성 500행에서 약 16ms). jsonb의
    text 출력은 asyncpg가 받는 문자열과 같은 정규형이라 풀린 값도 같다(기본 deserializer = `json.loads`).
    """
    return cast(column, Text).label(column.key)


_FUEL_STATION_COLUMNS = (
    FuelStation.id, FuelStation.source_station_id, FuelStation.source, FuelStation.name, FuelStation.brand_code,
    FuelStation.brand_name, FuelStation.phone, FuelStation.address, FuelStation.longitude, FuelStation.latitude,
    FuelStation.is_self, FuelStation.is_24h, FuelStation.has_carwash, FuelStation.has_maintenance,
    FuelStation.has_cvs, FuelStation.first_seen_at, FuelStation.last_seen_at,
    _raw_text(FuelStation.raw_item_json),
)
_FUEL_PRICE_COLUMNS = (
    FuelLatestPrice.fuel_station_id, FuelLatestPrice.product_code, FuelLatestPrice.price,
    FuelLatestPrice.provider_updated_at, FuelLatestPrice.observed_at, FuelLatestPrice.collected_at,
)
_REST_AREA_COLUMNS = (
    RestAreaReference.id, RestAreaReference.identity_key, RestAreaReference.source, RestAreaReference.name,
    RestAreaReference.route_name, RestAreaReference.direction, RestAreaReference.longitude,
    RestAreaReference.latitude, RestAreaReference.has_gas_station, RestAreaReference.has_lpg_station,
    RestAreaReference.has_ev_charger, RestAreaReference.phone_number, RestAreaReference.data_reference_date,
    RestAreaReference.first_seen_at, RestAreaReference.last_seen_at,
    _raw_text(RestAreaReference.raw_item_json),
)
_REST_AREA_FUEL_COLUMNS = (
    RestAreaFuelPrice.id, RestAreaFuelPrice.service_area_code, RestAreaFuelPrice.source,
    RestAreaFuelPrice.service_area_code2, RestAreaFuelPrice.service_area_name, RestAreaFuelPrice.route_code,
    RestAreaFuelPrice.route_name, RestAreaFuelPrice.direction, RestAreaFuelPrice.oil_company,
    RestAreaFuelPrice.has_lpg, RestAreaFuelPrice.phone_number, RestAreaFuelPrice.address,
    RestAreaFuelPrice.gasoline_price, RestAreaFuelPrice.diesel_price, RestAreaFuelPrice.lpg_price,
    RestAreaFuelPrice.last_seen_at, _raw_text(RestAreaFuelPrice.raw_item_json),
)
_INCIDENT_COLUMNS = (
    HighwayIncidentSnapshot.identity_key, HighwayIncidentSnapshot.source, HighwayIncidentSnapshot.occurred_date,
    HighwayIncidentSnapshot.occurred_time, HighwayIncidentSnapshot.incident_type,
    HighwayIncidentSnapshot.incident_type_code, HighwayIncidentSnapshot.direction, HighwayIncidentSnapshot.message,
    HighwayIncidentSnapshot.point_name, HighwayIncidentSnapshot.route_no, HighwayIncidentSnapshot.route_name,
    HighwayIncidentSnapshot.process_status, HighwayIncidentSnapshot.process_status_code,
    HighwayIncidentSnapshot.latitude, HighwayIncidentSnapshot.longitude, HighwayIncidentSnapshot.congestion_length,
    HighwayIncidentSnapshot.series_no, HighwayIncidentSnapshot.observed_at, HighwayIncidentSnapshot.collected_at,
    _raw_text(HighwayIncidentSnapshot.raw_item_json),
)


def build_service_export_router(
    settings: Settings, get_db: Callable[..., AsyncIterator[AsyncSession]],
) -> APIRouter:
    def require_service_token(request: Request) -> None:
        require_service_access(request, settings)

    router = APIRouter(prefix="/service/exports", dependencies=[Depends(require_service_token)],
                       tags=["service-exports"])
    router.include_router(build_public_parking_export_router(get_db))
    # app마다 하나. 기동 전(event loop 밖)에 만들어도 anyio가 첫 사용 때 backend에 묶는다(`fuel_map_limiter`와 같다).
    render_limiter = CapacityLimiter(RENDER_CONCURRENCY)

    @router.get("/fuel-stations", response_model=FuelStationExportPage)
    async def export_fuel_stations(
        request: Request,
        cursor: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=MAX_PAGE_SIZE),
        session: AsyncSession = Depends(get_db),
    ) -> Response:
        """오피넷 주유소와 유종별 최신 가격. 안정 ID(uni_id)가 없는 행은 내보내지 않는다."""
        await _begin_snapshot(session)
        state = await _state(session, OPINET_SOURCE)
        collection = _require_current(_reference_collection(OPINET_SOURCE, state))
        after = _decode_cursor(cursor)
        query = (
            select(*_FUEL_STATION_COLUMNS)
            .where(FuelStation.source == OPINET_SOURCE, FuelStation.source_station_id.is_not(None),
                   FuelStation.id > after)
            .order_by(FuelStation.id).limit(limit + 1)
        )
        query = _current_set(query, FuelStation.last_seen_at, state)
        stations = list((await session.execute(query)).all())
        page, has_more = stations[:limit], len(stations) > limit
        prices: Sequence[Any] = ()
        if page:
            prices = (await session.execute(select(*_FUEL_PRICE_COLUMNS).where(
                FuelLatestPrice.fuel_station_id.in_([row.id for row in page]),
            ).order_by(FuelLatestPrice.fuel_station_id, FuelLatestPrice.product_code))).all()
        addresses = await fetch_admin_address_rows(session, "fuel_station", page)
        await _end_snapshot(session)
        return await _render(request, render_limiter, partial(
            _fuel_station_page, collection, page, has_more, prices, addresses,
        ))

    @router.get("/rest-areas", response_model=RestAreaExportPage)
    async def export_rest_areas(
        request: Request,
        cursor: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=MAX_PAGE_SIZE),
        session: AsyncSession = Depends(get_db),
    ) -> Response:
        """고속도로 휴게소 기준정보(data.go.kr 표준데이터)."""
        await _begin_snapshot(session)
        state = await _state(session, REST_AREA_SOURCE)
        collection = _require_current(_reference_collection(REST_AREA_SOURCE, state))
        query = (
            select(*_REST_AREA_COLUMNS)
            .where(RestAreaReference.source == REST_AREA_SOURCE, RestAreaReference.id > _decode_cursor(cursor))
            .order_by(RestAreaReference.id).limit(limit + 1)
        )
        rows = list((await session.execute(_current_set(query, RestAreaReference.last_seen_at, state))).all())
        page, has_more = rows[:limit], len(rows) > limit
        addresses = await fetch_admin_address_rows(session, "rest_area", page)
        await _end_snapshot(session)
        return await _render(request, render_limiter, partial(
            _rest_area_page, collection, page, has_more, addresses,
        ))

    @router.get("/rest-area-fuel-prices", response_model=RestAreaFuelPriceExportPage)
    async def export_rest_area_fuel_prices(
        request: Request,
        cursor: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=MAX_PAGE_SIZE),
        session: AsyncSession = Depends(get_db),
    ) -> Response:
        """휴게소 주유소 현재 유가(한국도로공사 EX). `observed_at`은 transport 수집 시각이다."""
        await _begin_snapshot(session)
        state = await _state(session, REST_AREA_FUEL_SOURCE)
        collection = _require_current(_reference_collection(REST_AREA_FUEL_SOURCE, state))
        query = (
            select(*_REST_AREA_FUEL_COLUMNS)
            .where(RestAreaFuelPrice.source == REST_AREA_FUEL_SOURCE, RestAreaFuelPrice.id > _decode_cursor(cursor))
            .order_by(RestAreaFuelPrice.id).limit(limit + 1)
        )
        rows = list((await session.execute(_current_set(query, RestAreaFuelPrice.last_seen_at, state))).all())
        page, has_more = rows[:limit], len(rows) > limit
        await _end_snapshot(session)
        return await _render(request, render_limiter, partial(_rest_area_fuel_page, collection, page, has_more))

    @router.get("/highway-incidents/active", response_model=HighwayIncidentActiveSet)
    async def export_active_highway_incidents(
        request: Request, session: AsyncSession = Depends(get_db),
    ) -> Response:
        """마지막 성공 돌발 수집의 활성 사건 전체(페이지 없음).

        수집이 실패했거나 30분 넘게 성공하지 못했으면 503이다 — 오래된 집합을 주면 소비자가
        사라진 사건을 해소로 오판한다. 전국 활성 돌발 0건은 상류 이상으로 보고 수집이 성공으로 받지 않으므로
        빈 목록 대신 503이 된다(INCIDENT-EMPTY-SET-20261124).
        """
        await _begin_snapshot(session)
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
        rows = (await session.execute(
            select(*_INCIDENT_COLUMNS).join(ranked, HighwayIncidentSnapshot.id == ranked.c.id)
            .where(ranked.c.rank == 1).order_by(HighwayIncidentSnapshot.id)
        )).all()
        # `state`는 ORM 객체라 snapshot을 닫으면(rollback) 만료된다 — 응답에 쓸 값은 그 전에 꺼낸다.
        collection = _collection(INCIDENT_SOURCE, state, False)
        await _end_snapshot(session)
        if not rows:
            # 수집이 0건을 성공으로 받지 않지만(INCIDENT-EMPTY-SET-20261124), 배포 직전의 옛 "0건 성공" 상태나 다른 경로가
            # 행 없이 성공 시각만 올린 경우에도 빈 집합을 전량 해소로 내보내지 않는다.
            raise HTTPException(status_code=503, detail="고속도로 돌발 활성 집합이 비었습니다(상류 이상으로 보고 내지 않습니다).")
        return await _render(request, render_limiter, partial(_incident_set, collection, collected_at, rows))

    @router.get("/airports", response_model=AirportExportResponse)
    async def export_airports(request: Request, session: AsyncSession = Depends(get_db)) -> Response:
        """운영 중인 국내 공항 전체(krairport 번들 메타데이터, 주차 수집 여부와 무관)."""
        await _begin_snapshot(session)
        with_parking = set((await session.scalars(
            select(Airport.code).join(ParkingLot, ParkingLot.airport_id == Airport.id).distinct()
        )).all())
        await _end_snapshot(session)
        return await _render(request, render_limiter, partial(_airport_page, with_parking))

    router.include_router(build_current_export_router(settings, get_db))
    router.include_router(build_reference_export_router(settings, get_db))
    router.include_router(build_price_history_router(settings, get_db))
    return router


def require_service_access(request: Request, settings: Settings) -> None:
    """내부 export와 같은 토큰·실제 peer 경계를 MCP에도 적용한다."""
    configured = settings.transport_service_export_token or ""
    provided = request.headers.get(SERVICE_TOKEN_HEADER, "")
    if len(configured) < MIN_SERVICE_TOKEN_LENGTH or not secrets.compare_digest(
        configured.encode(), provided.encode(),
    ) or not _client_allowed(request, settings):
        raise HTTPException(status_code=404, detail="Not Found")


def _client_allowed(request: Request, settings: Settings) -> bool:
    """접속한 peer 주소가 허용 대역 안인가. IPv4-mapped IPv6는 IPv4로 본다."""
    if request.client is None:
        return False
    try:
        address = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in settings.service_export_allowed_client_networks)


async def _end_snapshot(session: AsyncSession) -> None:
    """마지막 SQL 뒤 읽기 snapshot을 닫아 pool 연결을 돌려준다(감사 T1-04·RT-08, T4 `price_history`와 같다).

    읽기 전용이라 rollback이다. rollback은 세션의 ORM 객체(`state`)를 만료시키므로 이 뒤에는 ORM 속성을
    읽지 않는다 — 만료된 속성을 읽으면 async lazy load가 `MissingGreenlet`을 낸다. 데이터 행은 Core `Row`,
    상태는 미리 만든 `ExportCollectionState`·datetime으로 넘긴다.
    """
    await session.rollback()


async def _begin_snapshot(session: AsyncSession) -> None:
    """상태 행과 데이터 행을 한 snapshot에서 읽도록 트랜잭션을 REPEATABLE READ READ ONLY로 연다.

    첫 문장 전에 불러야 한다. 연결이 pool로 돌아갈 때 SQLAlchemy가 격리 수준과 READ ONLY를 되돌리고,
    `SET LOCAL` 상한은 transaction과 함께 사라진다(감사 RT-04 — T2/T3 `_snapshot_transaction`과 같은 방식).
    """
    if session.bind.dialect.name == "postgresql":
        await session.connection(execution_options={
            "isolation_level": "REPEATABLE READ", "postgresql_readonly": True,
        })
        await session.execute(text(f"SET LOCAL statement_timeout = '{SNAPSHOT_STATEMENT_TIMEOUT}'"))
        await session.execute(text(f"SET LOCAL lock_timeout = '{SNAPSHOT_LOCK_TIMEOUT}'"))


def _require_current(collection: ExportCollectionState) -> ExportCollectionState:
    """집합을 낼 수 없으면(이력 없음·`failed`·`stale`) 503 — 소비자가 빈·낡은 집합을 삭제로 읽지 않게."""
    if collection.last_success_at is None or collection.failed or collection.stale:
        raise HTTPException(
            status_code=503, detail=f"{collection.source} 수집이 최근에 성공하지 않았습니다.",
        )
    return collection


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isascii() or not cursor.isdecimal() or int(cursor) > MAX_CURSOR:
        raise HTTPException(status_code=422, detail="cursor는 이전 응답의 next_cursor를 그대로 보내야 합니다.")
    return int(cursor)


async def _state(session: AsyncSession, source: str) -> TransportCollectionState | None:
    return await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == source))


def _current_set(query: Any, last_seen_column: Any, state: TransportCollectionState | None) -> Any:
    """마지막 성공 수집 근처에 본 행만 현재 집합으로 낸다. 수집 이력이 없으면 빈 집합이다."""
    if state is None or state.last_success_at is None:
        return query.where(false())
    return query.where(last_seen_column >= serialize_utc(state.last_success_at) - CURRENT_SET_WINDOW)


def _collection(
    source: str, state: TransportCollectionState | None, stale: bool, *, failed: bool | None = None,
) -> ExportCollectionState:
    """`failed`는 "실패 때문에 집합을 낼 수 없다"(503 사유), `last_attempt_failed`는 마지막 시도의 사실이다.

    `failed`를 주지 않으면 마지막 시도의 실패가 곧 503 사유다(돌발 활성 집합).
    """
    last_attempt_failed = bool(state and state.last_error)
    return ExportCollectionState(
        source=source,
        last_success_at=serialize_utc(state.last_success_at) if state and state.last_success_at else None,
        failed=last_attempt_failed if failed is None else failed,
        stale=stale,
        last_attempt_failed=last_attempt_failed,
    )


def _reference_collection(source: str, state: TransportCollectionState | None) -> ExportCollectionState:
    """참조 데이터는 마지막 성공 수집의 나이로만 판정한다(ADR-013 결정 3).

    실패한 시도는 저장 transaction을 되돌리므로 마지막 성공 수집의 집합이 그대로 남는다. 성공이 stale 기준
    안이면 그 집합을 내고(`failed=false`, `last_attempt_failed=true`), 기준을 넘으면 `stale`로 503이다.
    """
    last_success: datetime | None = serialize_utc(state.last_success_at) if state and state.last_success_at else None
    stale = last_success is None or now_utc() - last_success > REFERENCE_STALE_AFTER[source]
    return _collection(source, state, stale, failed=False)


async def _render(request: Request, limiter: CapacityLimiter, build: Callable[[], BaseModel]) -> Response:
    """`build`(DTO 구성)·JSON 직렬화·gzip을 전용 limiter 아래 worker thread에서 한다(감사 T1-03·T1-06).

    호출 전에 `_end_snapshot`으로 연결을 반납해 둔다 — `build`는 세션을 쓰지 않는다. `response_model`은
    OpenAPI 문서에 그대로 남고, 본문은 FastAPI 기본 경로(`TypeAdapter.dump_json(by_alias=True)`)와 같은 바이트다.
    gzip은 요청이 받을 때만 level 1이다(Map httpx 기본 `Accept-Encoding: gzip, deflate`).
    """
    compress = accepts_gzip(request.headers.get("accept-encoding", ""))
    body, compressed = await to_thread.run_sync(_encode, build, compress, limiter=limiter)
    headers = {"Vary": "Accept-Encoding"}
    if compressed:
        headers["Content-Encoding"] = "gzip"
    return Response(body, media_type="application/json", headers=headers)


def _encode(build: Callable[[], BaseModel], compress: bool) -> tuple[bytes, bool]:
    body = _dump(build())
    if compress and len(body) >= GZIP_MIN_BYTES:
        return gzip.compress(body, compresslevel=1, mtime=0), True
    return body, False


def _dump(page: BaseModel) -> bytes:
    """`TypeAdapter(type(page)).dump_json(page, by_alias=True)`와 같은 바이트를 item 묶음 단위로 만든다.

    pydantic-core는 `dump_json` 동안 GIL을 놓지 않는다. 500행(약 1.7MB)을 한 번에 직렬화하면 그동안 worker
    thread가 event loop를 멈추므로, 봉투(`items=[]`)와 item 묶음(`DUMP_GROUP`개)을 따로 직렬화해 이어 붙인다.
    JSON 문자열 안의 `"`는 언제나 escape되므로 봉투에서 따옴표 그대로의 `"items":[]`는 key 하나뿐이다.
    """
    items = getattr(page, "items", None)
    if not items:
        return _adapter(type(page)).dump_json(page, by_alias=True)
    envelope = _adapter(type(page)).dump_json(page.model_copy(update={"items": []}), by_alias=True)
    group = _list_adapter(type(items[0]))
    body = b",".join(
        group.dump_json(items[start:start + DUMP_GROUP], by_alias=True)[1:-1]
        for start in range(0, len(items), DUMP_GROUP)
    )
    return envelope.replace(b'"items":[]', b'"items":[' + body + b"]", 1)


@cache
def _adapter(model: type[BaseModel]) -> TypeAdapter[Any]:
    return TypeAdapter(model)


@cache
def _list_adapter(model: type[BaseModel]) -> TypeAdapter[Any]:
    return TypeAdapter(list[model])  # type: ignore[valid-type]


def _loads(value: str | None) -> Any:
    return None if value is None else json.loads(value)


# 아래 구성 함수는 worker thread에서 돈다. 인자는 닫힌 snapshot에서 꺼낸 Core `Row`·평범한 값뿐이다.

def _fuel_station_page(
    collection: ExportCollectionState, page: Sequence[Any], has_more: bool, price_rows: Sequence[Any],
    address_rows: Sequence[tuple[int, Any, Any]],
) -> FuelStationExportPage:
    prices: dict[int, list[ExportFuelPrice]] = {}
    for row in price_rows:
        prices.setdefault(row.fuel_station_id, []).append(ExportFuelPrice(
            product_code=row.product_code,
            price=float(row.price) if row.price is not None else None,
            provider_updated_at=serialize_utc(row.provider_updated_at) if row.provider_updated_at else None,
            observed_at=serialize_utc(row.observed_at),
            collected_at=serialize_utc(row.collected_at),
        ))
    addresses = build_admin_addresses(address_rows)
    items = [ExportFuelStation(
        natural_key=row.source_station_id, source=row.source, name=row.name,
        brand_code=row.brand_code, brand_name=row.brand_name, phone=row.phone, address=row.address,
        longitude=row.longitude, latitude=row.latitude, is_self=row.is_self, is_24h=row.is_24h,
        has_carwash=row.has_carwash, has_maintenance=row.has_maintenance, has_cvs=row.has_cvs,
        first_seen_at=serialize_utc(row.first_seen_at), last_seen_at=serialize_utc(row.last_seen_at),
        prices=prices.get(row.id, []), admin=addresses.get(row.id), raw=_loads(row.raw_item_json),
    ) for row in page]
    return FuelStationExportPage(
        generated_at=now_utc(), collection=collection, items=items,
        next_cursor=str(page[-1].id) if has_more else None, has_more=has_more,
    )


def _rest_area_page(
    collection: ExportCollectionState, page: Sequence[Any], has_more: bool,
    address_rows: Sequence[tuple[int, Any, Any]],
) -> RestAreaExportPage:
    addresses = build_admin_addresses(address_rows)
    items = [ExportRestArea(
        natural_key=row.identity_key, source=row.source, name=row.name, route_name=row.route_name,
        direction=row.direction, longitude=row.longitude, latitude=row.latitude,
        has_gas_station=row.has_gas_station, has_lpg_station=row.has_lpg_station,
        has_ev_charger=row.has_ev_charger, phone_number=row.phone_number,
        data_reference_date=row.data_reference_date, first_seen_at=serialize_utc(row.first_seen_at),
        last_seen_at=serialize_utc(row.last_seen_at), admin=addresses.get(row.id),
        raw=_loads(row.raw_item_json),
    ) for row in page]
    return RestAreaExportPage(
        generated_at=now_utc(), collection=collection, items=items,
        next_cursor=str(page[-1].id) if has_more else None, has_more=has_more,
    )


def _rest_area_fuel_page(
    collection: ExportCollectionState, page: Sequence[Any], has_more: bool,
) -> RestAreaFuelPriceExportPage:
    items = [ExportRestAreaFuelPrice(
        service_area_code=row.service_area_code, source=row.source,
        service_area_code2=row.service_area_code2, service_area_name=row.service_area_name,
        route_code=row.route_code, route_name=row.route_name, direction=row.direction,
        oil_company=row.oil_company, has_lpg=row.has_lpg, phone_number=row.phone_number,
        address=row.address, gasoline_price=row.gasoline_price, diesel_price=row.diesel_price,
        lpg_price=row.lpg_price, observed_at=serialize_utc(row.last_seen_at), raw=_loads(row.raw_item_json),
    ) for row in page]
    return RestAreaFuelPriceExportPage(
        generated_at=now_utc(), collection=collection, items=items,
        next_cursor=str(page[-1].id) if has_more else None, has_more=has_more,
    )


def _incident_set(
    collection: ExportCollectionState, collected_at: datetime, rows: Sequence[Any],
) -> HighwayIncidentActiveSet:
    items = [ExportHighwayIncident(
        identity_key=row.identity_key, source=row.source, occurred_date=row.occurred_date,
        occurred_time=row.occurred_time, incident_type=row.incident_type,
        incident_type_code=row.incident_type_code, direction=row.direction, message=row.message,
        point_name=row.point_name, route_no=row.route_no, route_name=row.route_name,
        process_status=row.process_status, process_status_code=row.process_status_code,
        latitude=row.latitude, longitude=row.longitude, congestion_length=row.congestion_length,
        series_no=row.series_no, observed_at=serialize_utc(row.observed_at),
        collected_at=serialize_utc(row.collected_at),
        raw=_incident_raw(_loads(row.raw_item_json)),
    ) for row in rows]
    return HighwayIncidentActiveSet(
        generated_at=now_utc(), collection=collection, collected_at=collected_at, items=items,
    )


def _incident_raw(value: Any) -> Any:
    return (value or {}).get("raw") if isinstance(value, dict) else None


def _airport_page(with_parking: set[str]) -> AirportExportResponse:
    # 정적 번들 공개 함수다 — 요청마다 httpx 클라이언트 2개를 만들던 `KrairportClient()`를 쓰지 않는다(감사 T1-08).
    items = [ExportAirport(
        code=airport.code, icao_code=airport.icao_code, name_korean=airport.name_korean,
        name_english=airport.name_english, municipality=airport.municipality,
        longitude=airport.coordinate.lon if airport.coordinate else None,
        latitude=airport.coordinate.lat if airport.coordinate else None,
        airport_type=getattr(airport.airport_type, "value", airport.airport_type),
        metadata_source=airport.source, has_parking_data=airport.code in with_parking,
    ) for airport in sorted(list_airports(active=True), key=lambda value: value.code)]
    return AirportExportResponse(generated_at=now_utc(), items=items)
