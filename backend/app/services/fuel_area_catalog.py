"""공개 유가 "지역 이동": 시도 → 시군구 목록과 각 시군구의 지도 범위(주유소 좌표 기준).

행정 경계 데이터는 이 저장소에 없다. 오피넷 주유소의 시도·시군구 코드와 좌표로 범위를 만들고, 좌표 오류 한두 곳이
범위를 크게 넓히지 않게 20곳 이상인 시군구는 경·위도 각각 2~98% 분위로 자른다. 결과는 10분 동안 프로세스에 둔다.
"""
from __future__ import annotations

import math
import time
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelStation
from app.schemas import FuelAreaCatalogResponse
from app.services.fuel_station_filters import OPINET

CACHE_SECONDS = 600
TRIM_FROM = 20
_cache: dict[object, tuple[float, dict]] = {}


def _trimmed(values: list[float]) -> tuple[float, float]:
    values = sorted(values)
    if len(values) < TRIM_FROM:
        return values[0], values[-1]
    low = values[math.floor(.02 * (len(values) - 1))]
    high = values[math.ceil(.98 * (len(values) - 1))]
    return low, high


async def fuel_area_catalog(session: AsyncSession) -> dict:
    key = session.bind
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    s = FuelStation
    rows = (await session.execute(select(s.sido_value, s.sido_name, s.sigungu_value, s.sigungu_name, s.longitude, s.latitude).where(
        s.source == OPINET, s.sido_value != "", s.sigungu_value != "",
        s.longitude.between(124, 132), s.latitude.between(32, 39.5),
    ))).all()
    groups: dict[tuple[str, str], dict] = {}
    names: dict[str, str] = {}
    for row in rows:
        names.setdefault(row.sido_value, row.sido_name or row.sido_value)
        group = groups.setdefault((row.sido_value, row.sigungu_value), {
            "sigungu_value": row.sigungu_value, "sigungu_name": row.sigungu_name or row.sigungu_value, "lons": [], "lats": [],
        })
        group["lons"].append(row.longitude)
        group["lats"].append(row.latitude)
    sido: dict[str, list[dict]] = {}
    for (sido_value, _), group in sorted(groups.items(), key=lambda item: (item[0][0], item[1]["sigungu_name"])):
        west, east = _trimmed(group["lons"])
        south, north = _trimmed(group["lats"])
        sido.setdefault(sido_value, []).append({
            "sigungu_value": group["sigungu_value"], "sigungu_name": group["sigungu_name"], "station_count": len(group["lons"]),
            "bounds": [round(west, 5), round(south, 5), round(east, 5), round(north, 5)],
        })
    result = {"items": [{"sido_value": value, "sido_name": names[value], "sigungu": items} for value, items in sorted(sido.items())]}
    if result["items"]:
        # 빈 목록(첫 수집 전)은 캐시하지 않는다. 엔진별 키가 쌓이지 않게 몇 개만 둔다.
        while len(_cache) >= 4:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic() + CACHE_SECONDS, result)
    return result


def build_fuel_area_catalog_router(get_db: Callable[..., AsyncIterator[AsyncSession]]) -> APIRouter:
    router = APIRouter()

    @router.get("/transport/fuel/area-catalog", response_model=FuelAreaCatalogResponse)
    async def area_catalog(session: AsyncSession = Depends(get_db)) -> dict:
        """시도(오피넷 코드순) → 시군구(이름순) 목록과 각 시군구 주유소 좌표 범위 [서, 남, 동, 북]. 10분 캐시."""
        return await fuel_area_catalog(session)

    return router
