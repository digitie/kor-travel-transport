"""TAGO 일반철도 조회 API. provider 요청·응답 검증은 기존 datagokr를 사용한다."""
import asyncio
import json
from typing import Literal
from kric import KorailPublicClient
from datetime import date, timedelta

from datagokr import AsyncTokenBucket, DataGoKrClient
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc, serialize_utc, to_seoul
from app.models import GeneralRailQuerySnapshot
from app.schemas import (
    GeneralRailCatalogResponse, GeneralRailCode, GeneralRailStation, GeneralRailStationsResponse,
    GeneralRailTimetableResponse, GeneralRailTrip, GeneralRailGuideResponse, GeneralRailGuideStation,
)
from app.services.general_rail_storage import save_general_rail


def build_general_rail_router(get_db) -> APIRouter:
    router = APIRouter(prefix="/transport/rail/general")
    # 한 API worker의 동시 cache miss를 합친다. 성공만 DB에 저장하고 403/429/파싱 실패는
    # 빈 시간표로 만들지 않는다. 다른 provider의 KRIC/버스 보호 상태는 건드리지 않는다.
    states = {name: {"lock": asyncio.Lock(), "blocked_until": None, "day": None, "attempts": 0} for name in ("tago", "guide")}
    tago_limiter = AsyncTokenBucket(max_rps=1, capacity=1)

    async def query(request, session, operation, key, response_type, fetch, *, ttl_hours, public=False):
        state = states["guide" if public else "tago"]
        saved = await session.get(GeneralRailQuerySnapshot, (operation, key))
        previous = response_type.model_validate(saved.response_json) if saved else None
        if saved and now_utc() - serialize_utc(saved.fetched_at) < timedelta(hours=ttl_hours):
            return previous
        await session.rollback()
        async with state["lock"]:
            saved = await session.get(GeneralRailQuerySnapshot, (operation, key), populate_existing=True)
            previous = response_type.model_validate(saved.response_json) if saved else None
            if saved and now_utc() - serialize_utc(saved.fetched_at) < timedelta(hours=ttl_hours):
                return previous
            await session.rollback()
            settings = request.app.state.settings
            if not public and not settings.data_go_kr_service_key:
                if previous:
                    return previous.model_copy(update={"stale": True})
                raise HTTPException(status_code=503, detail="일반철도 TAGO 제공기관 연결 설정이 없습니다.")
            now = now_utc()
            if state["day"] != to_seoul(now).date():
                state["day"], state["attempts"] = to_seoul(now).date(), 0
            blocked_until = state["blocked_until"]
            if blocked_until and now < blocked_until or state["attempts"] >= 96:
                if previous:
                    return previous.model_copy(update={"stale": True})
                raise HTTPException(status_code=429, detail="일반철도 제공기관 호출 보호 중입니다. 잠시 후 다시 조회해 주세요.", headers={"Retry-After": str(max(1, int((blocked_until - now).total_seconds()))) if blocked_until and now < blocked_until else "3600"})
            state["attempts"] += 1
            try:
                context = KorailPublicClient(timeout=settings.api_timeout_seconds) if public else DataGoKrClient(api_key=settings.data_go_kr_service_key, timeout=settings.api_timeout_seconds, max_rps=1, rate_limiter=tago_limiter)
                async with context as client:
                    response = await fetch(client)
            except HTTPException:
                raise
            except Exception as exc:
                state["blocked_until"] = now_utc() + timedelta(minutes=15)
                if previous:
                    return previous.model_copy(update={"stale": True})
                denied = getattr(exc, "status_code", None) in (401, 403)
                message = "일반철도 TAGO 접근이 거부되었습니다. 열차정보 서비스 활용 승인과 제공기관 연결 상태를 확인해 주세요." if denied else "일반철도 제공기관 응답을 확인하지 못했습니다. 잠시 후 다시 조회해 주세요."
                if public:
                    message = "코레일 공개 역 안내를 확인하지 못했습니다. 잠시 후 다시 조회해 주세요."
                raise HTTPException(status_code=502, detail=message) from None
            await save_general_rail(session, operation, key, response)
            return response

    @router.get("/catalog", response_model=GeneralRailCatalogResponse)
    async def catalog(request: Request, session: AsyncSession = Depends(get_db)):
        async def fetch(client):
            cities = await client.train.city_list()
            classes = await client.train.class_list()
            return GeneralRailCatalogResponse(fetched_at=now_utc(),
                cities=[GeneralRailCode(code=row.city_code, name=row.city_name) for row in cities.items],
                train_classes=[GeneralRailCode(code=row.grade_id, name=row.grade_name) for row in classes.items])
        return await query(request, session, "catalog", "all", GeneralRailCatalogResponse, fetch, ttl_hours=24)

    @router.get("/stations", response_model=GeneralRailStationsResponse)
    async def stations(request: Request, city_code: str = Query(pattern=r"^\d{1,4}$"), session: AsyncSession = Depends(get_db)):
        saved_catalog = await session.get(GeneralRailQuerySnapshot, ("catalog", "all"))
        cities = GeneralRailCatalogResponse.model_validate(saved_catalog.response_json).cities if saved_catalog else []
        if city_code not in {row.code for row in cities}:
            raise HTTPException(status_code=422, detail="일반철도 지역 목록에서 지역을 다시 선택해 주세요.")
        async def fetch(client):
            page = await client.train.station_list(city_code=city_code, num_of_rows=1000)
            if page.total_count is None or page.total_count > len(page.items):
                raise ValueError("general rail station catalog is incomplete")
            return GeneralRailStationsResponse(fetched_at=now_utc(), city_code=city_code,
                items=[GeneralRailStation(station_id=row.station_id, station_name=row.station_name) for row in page.items])
        return await query(request, session, "stations", city_code, GeneralRailStationsResponse, fetch, ttl_hours=24)

    @router.get("/timetable", response_model=GeneralRailTimetableResponse)
    async def timetable(request: Request, departure_station_id: str = Query(pattern=r"^[A-Za-z0-9]{1,40}$"),
        arrival_station_id: str = Query(pattern=r"^[A-Za-z0-9]{1,40}$"), service_date: date = Query(alias="date"),
        train_grade_code: str | None = Query(default=None, pattern=r"^[A-Za-z0-9]{1,4}$"), session: AsyncSession = Depends(get_db)):
        today = to_seoul(now_utc()).date()
        if departure_station_id == arrival_station_id or not today <= service_date <= today + timedelta(days=9):
            raise HTTPException(status_code=422, detail="서로 다른 출발·도착역과 오늘부터 9일 이내 출발일을 선택해 주세요.")
        station_catalogs = (await session.scalars(select(GeneralRailQuerySnapshot).where(GeneralRailQuerySnapshot.operation == "stations"))).all()
        station_ids = {row.station_id for saved in station_catalogs for row in GeneralRailStationsResponse.model_validate(saved.response_json).items}
        if {departure_station_id, arrival_station_id} - station_ids:
            raise HTTPException(status_code=404, detail="저장된 일반철도 역 목록에서 출발·도착역을 다시 선택해 주세요.")
        if train_grade_code is not None:
            saved_catalog = await session.get(GeneralRailQuerySnapshot, ("catalog", "all"))
            grades = GeneralRailCatalogResponse.model_validate(saved_catalog.response_json).train_classes if saved_catalog else []
            if train_grade_code not in {row.code for row in grades}:
                raise HTTPException(status_code=422, detail="열차 종류 목록에서 차량을 다시 선택해 주세요.")
        key = json.dumps([departure_station_id, arrival_station_id, service_date.isoformat(), train_grade_code], separators=(",", ":"))
        async def fetch(client):
            page = await client.train.timetable_list(departure_station_id=departure_station_id,
                arrival_station_id=arrival_station_id, departure_date=service_date, train_grade_code=train_grade_code, num_of_rows=1000)
            return GeneralRailTimetableResponse(fetched_at=now_utc(), service_date=service_date,
                departure_station_id=departure_station_id, arrival_station_id=arrival_station_id,
                total=page.total_count, truncated=page.total_count is None or page.total_count > len(page.items),
                items=[GeneralRailTrip(train_number=row.train_number, grade_name=row.grade_name,
                    departure_station_name=row.dep_place_name, arrival_station_name=row.arr_place_name,
                    departure_planned_time=row.dep_planned_time, arrival_planned_time=row.arr_planned_time,
                    adult_fare=row.adult_charge) for row in page.items])
        return await query(request, session, "timetable", key, GeneralRailTimetableResponse, fetch, ttl_hours=.25)
    @router.get("/guide", response_model=GeneralRailGuideResponse)
    async def guide(request: Request, kind: Literal["ktx", "main"] = "ktx",
        category_code: str = Query(default="", pattern=r"^[A-Za-z0-9_]{0,40}$"), session: AsyncSession = Depends(get_db)):
        async def fetch(client):
            first = await client.get_guide_page(kind=kind)
            if category_code and category_code not in {row.code for row in first.categories}:
                raise HTTPException(status_code=422, detail="역 안내의 노선·권역 목록에서 다시 선택해 주세요.")
            page = await client.get_located_category_stations(kind=kind, category_code=category_code) if category_code else first
            return GeneralRailGuideResponse(fetched_at=now_utc(), kind=kind, category_code=category_code,
                categories=[GeneralRailCode(code=row.code, name=row.name) for row in page.categories], total=page.total,
                items=[GeneralRailGuideStation(provider_id=row.station_sequence, station_code=row.station_code,
                    station_name=row.station_name, address=row.address, phone=row.phone,
                    longitude=row.longitude, latitude=row.latitude) for row in page.stations] if category_code else [])
        return await query(request, session, "station_guide", json.dumps([kind, category_code]), GeneralRailGuideResponse, fetch, ttl_hours=24, public=True)
    return router
