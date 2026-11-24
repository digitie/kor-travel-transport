"""T1 export 본문 구성의 성능 경로(감사 T1-03·T1-04·T1-05·T1-06·T1-08·T1-09·RT-04·RT-08).

- 응답 바이트가 바뀌기 전 구현(ORM 엔터티 → pydantic 반환 → FastAPI 직렬화)과 같다.
- 본문은 읽기 transaction을 닫은 뒤(연결 반납) event loop 밖 worker thread에서 만든다.
- gzip level 1은 요청이 받을 때만, `Vary: Accept-Encoding`과 함께 낸다.
- PostgreSQL snapshot은 REPEATABLE READ READ ONLY + 문장·잠금 상한이며, pool로 돌아간 연결에는 남지 않는다.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import threading
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi import APIRouter, Depends, Query, Request
from fastapi.testclient import TestClient
from krairport import KrairportClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.service_exports as se
from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.main import create_app
from app.models import (
    Airport,
    FuelLatestPrice,
    FuelPriceSnapshot,
    FuelStation,
    HighwayIncidentSnapshot,
    ParkingLot,
    RestAreaFuelPrice,
    RestAreaReference,
)
from app.schemas import (
    AirportExportResponse,
    ExportAirport,
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
from app.services.export_addresses import export_admin_addresses
from app.services.rest_area_collection import REST_AREA_FUEL_SOURCE, REST_AREA_SOURCE
from app.services.transport_collection import INCIDENT_SOURCE, OPINET_SOURCE, upsert_latest_fuel_prices
from test_service_exports import HEADERS, LOOPBACK_CLIENT, TOKEN, _run, _set_state

PATHS = (
    "/fuel-stations", "/rest-areas", "/rest-area-fuel-prices", "/highway-incidents/active", "/airports",
)


def _legacy_router() -> APIRouter:
    """바뀌기 전(origin/main 156bf5c) 핸들러 본문 그대로 — 바이트 동등성의 기준이다.

    상태 판정·cursor·snapshot helper는 현재 모듈 것을 쓰지만 데이터 조회·DTO 구성·직렬화는 옛 방식이다
    (ORM 엔터티 적재, pydantic 반환 → FastAPI 기본 직렬화, 요청 끝까지 snapshot 유지).
    """
    router = APIRouter(prefix="/legacy")

    async def get_db(request: Request):
        async with request.app.state.session_factory() as session:
            yield session

    @router.get("/fuel-stations", response_model=FuelStationExportPage)
    async def export_fuel_stations(
        cursor: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=se.MAX_PAGE_SIZE),
        session: AsyncSession = Depends(get_db),
    ) -> FuelStationExportPage:
        await se._begin_snapshot(session)
        state = await se._state(session, OPINET_SOURCE)
        collection = se._require_current(se._reference_collection(OPINET_SOURCE, state))
        after = se._decode_cursor(cursor)
        query = (
            select(FuelStation)
            .where(FuelStation.source == OPINET_SOURCE, FuelStation.source_station_id.is_not(None),
                   FuelStation.id > after)
            .order_by(FuelStation.id).limit(limit + 1)
        )
        query = se._current_set(query, FuelStation.last_seen_at, state)
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
        addresses = await export_admin_addresses(session, "fuel_station", page)
        items = [ExportFuelStation(
            natural_key=row.source_station_id, source=row.source, name=row.name,
            brand_code=row.brand_code, brand_name=row.brand_name, phone=row.phone, address=row.address,
            longitude=row.longitude, latitude=row.latitude, is_self=row.is_self, is_24h=row.is_24h,
            has_carwash=row.has_carwash, has_maintenance=row.has_maintenance, has_cvs=row.has_cvs,
            first_seen_at=serialize_utc(row.first_seen_at), last_seen_at=serialize_utc(row.last_seen_at),
            prices=prices.get(row.id, []), admin=addresses.get(row.id), raw=row.raw_item_json,
        ) for row in page]
        return FuelStationExportPage(
            generated_at=se.now_utc(), collection=collection, items=items,
            next_cursor=str(page[-1].id) if has_more else None, has_more=has_more,
        )

    @router.get("/rest-areas", response_model=RestAreaExportPage)
    async def export_rest_areas(
        cursor: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=se.MAX_PAGE_SIZE),
        session: AsyncSession = Depends(get_db),
    ) -> RestAreaExportPage:
        await se._begin_snapshot(session)
        state = await se._state(session, REST_AREA_SOURCE)
        collection = se._require_current(se._reference_collection(REST_AREA_SOURCE, state))
        query = (
            select(RestAreaReference)
            .where(RestAreaReference.source == REST_AREA_SOURCE, RestAreaReference.id > se._decode_cursor(cursor))
            .order_by(RestAreaReference.id).limit(limit + 1)
        )
        rows = list((await session.scalars(se._current_set(query, RestAreaReference.last_seen_at, state))).all())
        page, has_more = rows[:limit], len(rows) > limit
        addresses = await export_admin_addresses(session, "rest_area", page)
        items = [ExportRestArea(
            natural_key=row.identity_key, source=row.source, name=row.name, route_name=row.route_name,
            direction=row.direction, longitude=row.longitude, latitude=row.latitude,
            has_gas_station=row.has_gas_station, has_lpg_station=row.has_lpg_station,
            has_ev_charger=row.has_ev_charger, phone_number=row.phone_number,
            data_reference_date=row.data_reference_date, first_seen_at=serialize_utc(row.first_seen_at),
            last_seen_at=serialize_utc(row.last_seen_at), admin=addresses.get(row.id),
            raw=row.raw_item_json,
        ) for row in page]
        return RestAreaExportPage(
            generated_at=se.now_utc(), collection=collection, items=items,
            next_cursor=str(page[-1].id) if has_more else None, has_more=has_more,
        )

    @router.get("/rest-area-fuel-prices", response_model=RestAreaFuelPriceExportPage)
    async def export_rest_area_fuel_prices(
        cursor: str | None = Query(default=None, max_length=20),
        limit: int = Query(default=500, ge=1, le=se.MAX_PAGE_SIZE),
        session: AsyncSession = Depends(get_db),
    ) -> RestAreaFuelPriceExportPage:
        await se._begin_snapshot(session)
        state = await se._state(session, REST_AREA_FUEL_SOURCE)
        collection = se._require_current(se._reference_collection(REST_AREA_FUEL_SOURCE, state))
        query = (
            select(RestAreaFuelPrice)
            .where(RestAreaFuelPrice.source == REST_AREA_FUEL_SOURCE, RestAreaFuelPrice.id > se._decode_cursor(cursor))
            .order_by(RestAreaFuelPrice.id).limit(limit + 1)
        )
        rows = list((await session.scalars(se._current_set(query, RestAreaFuelPrice.last_seen_at, state))).all())
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
            generated_at=se.now_utc(), collection=collection, items=items,
            next_cursor=str(page[-1].id) if has_more else None, has_more=has_more,
        )

    @router.get("/highway-incidents/active", response_model=HighwayIncidentActiveSet)
    async def export_active_highway_incidents(session: AsyncSession = Depends(get_db)) -> HighwayIncidentActiveSet:
        await se._begin_snapshot(session)
        state = await se._state(session, INCIDENT_SOURCE)
        assert state is not None and state.last_success_at is not None and state.last_error is None
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
            generated_at=se.now_utc(), collection=se._collection(INCIDENT_SOURCE, state, False),
            collected_at=collected_at, items=items,
        )

    @router.get("/airports", response_model=AirportExportResponse)
    async def export_airports(session: AsyncSession = Depends(get_db)) -> AirportExportResponse:
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
        return AirportExportResponse(generated_at=se.now_utc(), items=items)

    return router


@pytest.fixture
def render_client(test_settings: Settings, monkeypatch: pytest.MonkeyPatch):
    test_settings.transport_service_export_token = TOKEN
    test_settings.trusted_hosts_csv = "testserver,127.0.0.1"
    app = create_app(test_settings)
    app.include_router(_legacy_router())
    fixed = now_utc()
    # 옛·새 응답의 generated_at과 stale 판정을 같은 시각으로 고정해 바이트를 그대로 비교한다.
    monkeypatch.setattr(se, "now_utc", lambda: fixed)
    with TestClient(app, client=LOOPBACK_CLIENT) as client:
        client.fixed_now = fixed
        yield client


_TRICKY_RAW = {
    "UNI_ID": "A0000001", "nested": {"list": [1, 2.5, None, True, "ㄱ"], "empty": {}},
    "float": 0.1, "tiny": 1e-07, "big": 12345678901234567890, "neg": -0.0,
    "text": "줄\n바꿈 \"따옴표\" \\ </script>   \U0001F697 \x01",
}


async def _seed_all(session: AsyncSession, now) -> None:
    from kortravelcommon.address_providers import VworldKakaoAddressResolver
    from kortravelcommon.reverse_address import AddressTarget, reverse_address_tables
    from app.models import Base

    entries, _ = reverse_address_tables(Base.metadata)

    async def address(kind: str, row_id: int, lon: float, lat: float, provider: str = "vworld") -> None:
        key = f"{kind}:{row_id}"
        await session.execute(entries.insert().values(
            provider_id=VworldKakaoAddressResolver.provider_id, target_key=key,
            coordinate_key=AddressTarget(key, lon, lat).coordinate_key, longitude=lon, latitude=lat,
            status="ok", failures=0, checked_at=now, resolved_at=now - timedelta(minutes=3),
            payload={"provider": provider,
                     "address": {"legal_dong_code": "0123456789", "admin_dong_code": " 0012345678 ",
                                 "road_address": "도로 주소", "parcel_address": "", "postal_code": "01234"},
                     "region": {"sido": "시도", "sigungu": "시군구", "legal_dong": "법정동"}},
        ))

    stations = []
    specs = [
        ("A0000001", 127.0123456789, 37.5, True, _TRICKY_RAW),
        ("A0000002", None, None, None, None),
        (None, 127.1, 37.6, False, {"UNI_ID": None}),
        ("A0000004", 126.9, 35.1, False, {"k": [{"x": 1}]}),
        ("A0000005", 129.0, 35.2, None, {}),
        ("A0000006", 128.5, 36.0, True, {"UNI_ID": "A0000006"}),
    ]
    for index, (station_id, lon, lat, flag, raw) in enumerate(specs):
        station = FuelStation(
            source=OPINET_SOURCE, identity_key=f"station:{station_id or index}", source_station_id=station_id,
            name=f"주유소 {index} \"따옴표\"", brand_code="SKE" if index % 2 else None,
            brand_name="SK에너지" if index % 2 else None, phone="02-000-0000" if index % 3 else None,
            address=f"서울 종로구 {index}", query_level="sigungu", sido_value="11", sido_name="서울",
            sigungu_value="110", sigungu_name="종로", source_kinds=["station"], longitude=lon, latitude=lat,
            is_self=flag, is_24h=not flag if flag is not None else None, has_carwash=flag, has_maintenance=None,
            has_cvs=True, discount_info="쓰지 않는 열", first_seen_at=now - timedelta(days=30 + index),
            last_seen_at=now - timedelta(hours=index), raw_item_json=raw,
        )
        session.add(station)
        await session.flush()
        stations.append(station)
        for code, price, updated in (
            ("B027", Decimal("1699.50") + index, now - timedelta(hours=2)),
            ("D047", None if index == 1 else Decimal("1550"), None),
            ("K015", Decimal("1000.05"), now - timedelta(days=1)),
        ):
            if index == 4 and code != "B027":
                continue
            session.add(FuelPriceSnapshot(
                fuel_station_id=station.id, source=OPINET_SOURCE, product_code=code, price=price,
                provider_updated_at=updated, observed_at=now - timedelta(minutes=index),
                collected_at=now - timedelta(minutes=index),
            ))
    await session.flush()
    await upsert_latest_fuel_prices(session)
    await address("fuel_station", stations[0].id, 127.0123456789, 37.5)
    await address("fuel_station", stations[3].id, 126.9, 35.1, provider="kakao")
    await _set_state(session, OPINET_SOURCE, last_success_at=now - timedelta(hours=1),
                     last_error="TimeoutError: later attempt failed")

    areas = []
    for index in range(4):
        area = RestAreaReference(
            source=REST_AREA_SOURCE, identity_key=f"휴게소{index}::노선::방향", name=f"휴게소{index}",
            route_name="경부고속도로" if index else None, direction="부산방향", longitude=127.0 + index / 10,
            latitude=36.0 + index / 10, has_gas_station=bool(index % 2), has_lpg_station=None,
            has_ev_charger=True, phone_number=None if index else "031-000-0000",
            data_reference_date="2026-09-01" if index else None, first_seen_at=now - timedelta(days=9),
            last_seen_at=now - timedelta(hours=2), raw_item_json={"restAreaNm": f"휴게소{index}", "n": index / 3},
        )
        session.add(area)
        await session.flush()
        areas.append(area)
    await address("rest_area", areas[1].id, 127.1, 36.1)
    await _set_state(session, REST_AREA_SOURCE, last_success_at=now - timedelta(hours=1), last_error=None)

    for index in range(3):
        session.add(RestAreaFuelPrice(
            source=REST_AREA_FUEL_SOURCE, service_area_code=f"A0000{index}", service_area_code2=None,
            service_area_name=f"행담도{index}", route_code="0150", route_name="서해안선", direction="목포",
            oil_company="SK" if index else None, has_lpg=bool(index), phone_number=None, address="충남 당진",
            gasoline_price=1700 + index, diesel_price=None if index == 2 else 1600, lpg_price=None,
            first_seen_at=now - timedelta(days=2), last_seen_at=now - timedelta(minutes=30 + index),
            raw_item_json={"serviceAreaCode": f"A0000{index}", "gasolinePrice": f"{1700 + index}원"},
        ))
    await _set_state(session, REST_AREA_FUEL_SOURCE, last_success_at=now - timedelta(minutes=30), last_error=None)

    collected = now - timedelta(minutes=4)
    for identity, observed, raw in (
        ("A", collected - timedelta(hours=1), {"raw": {"seriesNM": "1", "old": True}}),
        ("A", collected, {"raw": {"seriesNM": "1", "accPointNM": "서울IC \"진입\""}}),
        ("B", collected, {"no_raw_key": 1}),
        ("C", collected, None),
        ("D", collected - timedelta(hours=2), {"raw": {"too": "old"}}),
    ):
        session.add(HighwayIncidentSnapshot(
            source=INCIDENT_SOURCE, identity_key=identity, observed_at=observed,
            collected_at=collected if identity != "D" else collected - timedelta(hours=2),
            occurred_date="2026.11.24", occurred_time="09:00:00", incident_type="작업", incident_type_code="03",
            direction="부산방향", message=f"{identity} 작업", point_name=f"{identity}지점", route_no="0010",
            route_name="경부선", process_status="진행", process_status_code="1", latitude=37.0,
            longitude=127.0, congestion_length=1.5 if identity == "A" else None,
            series_no=7 if identity == "A" else None, raw_item_json=raw,
        ))
    await _set_state(session, INCIDENT_SOURCE, last_success_at=collected, last_error=None, next_due_at=None)


def _pages(client: TestClient, prefix: str, path: str, limit: int | None, headers: dict[str, str]) -> list[bytes]:
    """cursor를 따라 끝까지 읽은 페이지 본문(httpx가 gzip을 풀어 준 바이트)."""
    bodies, cursor = [], None
    while True:
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = limit
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get(f"{prefix}{path}", params=params, headers=headers)
        assert response.status_code == 200, (prefix, path, response.text)
        assert response.headers["content-type"] == "application/json"
        bodies.append(response.content)
        payload = response.json()
        cursor = payload.get("next_cursor")
        if not cursor:
            return bodies


@pytest.mark.parametrize("limit", [None, 1, 2])
def test_t1_bodies_are_byte_identical_to_the_previous_implementation(render_client: TestClient, limit) -> None:
    _run(render_client, lambda session: _seed_all(session, render_client.fixed_now))
    for path in PATHS:
        page_limit = None if path in {"/highway-incidents/active", "/airports"} else limit
        legacy = _pages(render_client, "/legacy", path, page_limit, HEADERS)
        for encoding in ("gzip", "identity"):
            current = _pages(render_client, "/v1/service/exports", path, page_limit,
                             {**HEADERS, "Accept-Encoding": encoding})
            assert current == legacy, (path, limit, encoding)
        # 시드가 실제로 각 분기를 지나는지(빈 집합끼리 같아서 통과하지 않게).
        items = [item for body in legacy for item in json.loads(body)["items"]]
        assert items, path
    fuel = [item for body in _pages(render_client, "/legacy", "/fuel-stations", None, HEADERS)
            for item in json.loads(body)["items"]]
    assert [item["natural_key"] for item in fuel] == ["A0000001", "A0000002", "A0000004", "A0000005", "A0000006"]
    assert fuel[0]["admin"]["provider"] == "vworld" and fuel[2]["admin"]["provider"] == "kakao"
    assert fuel[0]["raw"]["text"] == _TRICKY_RAW["text"]
    assert {price["price"] for price in fuel[1]["prices"]} == {1700.5, None, 1000.05}
    incidents = json.loads(_pages(render_client, "/legacy", "/highway-incidents/active", None, HEADERS)[0])
    assert [(item["identity_key"], item["raw"]) for item in incidents["items"]] == [
        ("A", {"seriesNM": "1", "accPointNM": "서울IC \"진입\""}), ("B", None), ("C", None),
    ]


def test_t1_gzip_is_negotiated_with_vary(render_client: TestClient) -> None:
    _run(render_client, lambda session: _seed_all(session, render_client.fixed_now))
    path = "/v1/service/exports/fuel-stations"
    with render_client.stream("GET", path, headers={**HEADERS, "Accept-Encoding": "gzip"}) as response:
        raw = b"".join(response.iter_raw())
        assert response.headers["content-encoding"] == "gzip"
        assert "Accept-Encoding" in _vary(response)
    with render_client.stream("GET", path, headers={**HEADERS, "Accept-Encoding": "identity"}) as response:
        plain = b"".join(response.iter_raw())
        assert "content-encoding" not in response.headers
        assert "Accept-Encoding" in _vary(response)
    assert gzip.decompress(raw) == plain and len(raw) < len(plain)
    # q=0은 거절이다(T4 `accepts_gzip`과 같은 해석).
    refused = render_client.get(path, headers={**HEADERS, "Accept-Encoding": "gzip;q=0"})
    assert "content-encoding" not in refused.headers and refused.content == plain


def _vary(response) -> set[str]:
    # CORS middleware가 `Origin`을 덧붙인다.
    return {value.strip() for value in response.headers["vary"].split(",")}


def test_small_bodies_stay_uncompressed() -> None:
    body, compressed = se._encode(lambda: ExportAirport(code="X", name_english="x", has_parking_data=False), True)
    assert compressed is False and json.loads(body)["code"] == "X"


def test_t1_releases_the_snapshot_before_building_off_the_event_loop(
    render_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """감사 T1-04·RT-08 — 본문 구성 때는 읽기 transaction이 닫혀(연결 반납) 있고, event loop 밖 thread다.

    rollback이 만료시킨 ORM 객체를 그 뒤에 읽으면 async lazy load가 `MissingGreenlet`(500)을 내므로, 이 경로는
    CI PostgreSQL에서도 그대로 돈다.
    """
    _run(render_client, lambda session: _seed_all(session, render_client.fixed_now))
    sessions: list[AsyncSession] = []
    loop_threads: set[int] = set()
    real_factory = render_client.app.state.session_factory

    def tracking_factory():
        # 요청 의존성 `get_db`가 `request.app.state.session_factory`로 세션을 연다(event loop thread).
        loop_threads.add(threading.get_ident())
        session = real_factory()
        sessions.append(session)
        return session

    monkeypatch.setattr(render_client.app.state, "session_factory", tracking_factory)
    observed: list[tuple[bool, bool]] = []
    encode = se._encode

    def spy(build, compress):
        try:
            asyncio.get_running_loop()
            on_loop = True
        except RuntimeError:
            on_loop = threading.get_ident() in loop_threads
        observed.append((on_loop, sessions[-1].in_transaction()))
        return encode(build, compress)

    monkeypatch.setattr(se, "_encode", spy)
    for path in PATHS:
        assert render_client.get(f"/v1/service/exports{path}", headers=HEADERS).status_code == 200, path
    assert len(sessions) == len(PATHS)
    assert observed == [(False, False)] * len(PATHS)


@pytest.mark.parametrize("path", ["/fuel-stations", "/rest-areas", "/rest-area-fuel-prices"])
def test_cursor_outside_int4_is_a_client_error(render_client: TestClient, path: str) -> None:
    """감사 T1-09 — int4 PK 범위 밖 cursor는 DB bind 오류(500) 대신 422다."""
    _run(render_client, lambda session: _seed_all(session, render_client.fixed_now))
    url = f"/v1/service/exports{path}"
    assert render_client.get(url, params={"cursor": str(2**31 - 1)}, headers=HEADERS).status_code == 200
    for cursor in (str(2**31), "9" * 20):
        response = render_client.get(url, params={"cursor": cursor}, headers=HEADERS)
        assert response.status_code == 422, (cursor, response.text)
    assert render_client.get(url, params={"cursor": "0"}, headers=HEADERS).status_code == 200


def test_airport_export_does_not_build_a_provider_client(
    render_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """감사 T1-08 — 정적 번들 공개 함수만 쓴다(ADR-004: 라이브러리 공개 API 사용)."""
    def forbidden(*_args, **_kwargs):
        raise AssertionError("KrairportClient must not be constructed per request")

    monkeypatch.setattr(KrairportClient, "__init__", forbidden)
    payload = render_client.get("/v1/service/exports/airports", headers=HEADERS).json()
    assert {"ICN", "GMP"} <= {item["code"] for item in payload["items"]}


def test_snapshot_is_read_only_with_bounded_timeouts_and_resets_on_return(test_settings: Settings) -> None:
    """감사 RT-04 — PostgreSQL에서 RR READ ONLY + statement 20s·lock 3s이고, pool로 돌아간 연결에는 남지 않는다."""
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 전용 — CI는 TEST_DATABASE_URL로 실행한다")

    async def scenario() -> None:
        # 테스트 기본 NullPool과 달리 연결 재사용을 보려고 연결 1개짜리 pool을 따로 만든다.
        engine = create_async_engine(test_settings.database_url, pool_size=1, max_overflow=0)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        settings_sql = text(
            "SELECT current_setting('transaction_isolation'), current_setting('transaction_read_only'), "
            "current_setting('statement_timeout'), current_setting('lock_timeout'), pg_backend_pid()"
        )
        try:
            async with factory() as session:
                default = (await session.execute(settings_sql)).one()
            async with factory() as session:
                await se._begin_snapshot(session)
                inside = (await session.execute(settings_sql)).one()
                await se._end_snapshot(session)
                assert not session.in_transaction()
            async with factory() as session:
                after = (await session.execute(settings_sql)).one()
                # 같은 연결에서 쓰기 transaction이 READ ONLY에 걸리지 않는다.
                await session.execute(text("CREATE TEMP TABLE t1_render_probe (id int)"))
                await session.rollback()
        finally:
            await engine.dispose()
        assert tuple(inside[:4]) == ("repeatable read", "on", "20s", "3s")
        assert after[4] == inside[4] == default[4]
        assert tuple(after[:4]) == tuple(default[:4]) and after[1] == "off"

    asyncio.run(scenario())
