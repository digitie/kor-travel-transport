"""공개 유가 지도 중심의 시군구를 "중심에서 가장 가까운 오피넷 주유소의 시군구"로 근사한다.

이 저장소에는 시군구 경계(폴리곤)가 없다. 주소 provider(VWorld·Kakao, `fuel_search_location`)는 외부 호출이라
지도를 옮길 때마다 부르는 공개 경로에는 쓰지 않는다. 그래서 지역 칩의 기본값만 이 근사로 정한다:

- 모집단은 "지역 이동" 목록(`fuel_area_catalog`)과 같은 오피넷 주유소(시도·시군구 코드와 한국 범위 좌표가 있는 행)다.
  유종·필터와 무관하다(지역의 정체는 필터로 바뀌지 않는다).
- 시군구 경계 근처에서는 이웃 시군구의 주유소가 더 가까울 수 있다(근사). 중심에서 반경 안에 주유소가 없으면(바다 등)
  `None`을 돌려주고 화면은 예전처럼 "화면 안에서 주유소가 가장 많은 시군구"로 되돌아간다.

공간 인덱스(PostGIS·KNN)는 없다. `ix_fuel_stations_map_coordinates`(longitude, latitude, 부분) B-tree로 중심 주변 상자만 읽고
그 안에서 거리순 1곳을 고른다. 상자에 내접한 원 안에서 찾은 곳만 받아들여 "상자 밖이 더 가까운" 경우를 배제한다
(측정: docs/fuel-statistics.md "지도 중심 시군구").
"""
from __future__ import annotations

import math
import time
from collections import OrderedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelStation
from app.services.fuel_station_filters import OPINET

# 위도 기준 반경(도). 약 2.2 km → 9 km → 33 km. 대부분 첫 상자에서 끝난다.
SEARCH_RADII = (0.02, 0.08, 0.3)
METERS_PER_DEGREE = 111_320
CACHE_SECONDS = 60
CACHE_SIZE = 256
_cache: OrderedDict[tuple, tuple[float, dict | None]] = OrderedDict()


async def center_sigungu(session: AsyncSession, longitude: float, latitude: float) -> dict | None:
    """중심 좌표에서 가장 가까운 오피넷 주유소의 시도·시군구. 반경 안에 없으면 None."""
    # 약 10 m 격자로 묶어 같은 화면의 재요청(재렌더·되돌아가기)만 재사용한다.
    key = (session.bind, round(longitude, 4), round(latitude, 4))
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        _cache.move_to_end(key)
        return cached[1]
    result = await _nearest(session, longitude, latitude)
    _cache[key] = (time.monotonic() + CACHE_SECONDS, result)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return result


def nearest_statement(longitude: float, latitude: float, radius: float):
    """반경 radius(위도 도) 상자 안에서 거리순 1곳. 벤치마크의 EXPLAIN도 이 문장을 그대로 쓴다."""
    s = FuelStation
    # 경도 1도의 길이는 위도에 따라 줄어든다. 위도 단위로 맞춘 평면 거리(한 시군구 규모에서 충분)를 쓴다.
    scale = _scale(latitude)
    dx = (s.longitude - longitude) * scale
    dy = s.latitude - latitude
    distance2 = (dx * dx + dy * dy).label("distance2")
    half_width = radius / scale
    return select(
        s.sido_value, s.sido_name, s.sigungu_value, s.sigungu_name, distance2,
    ).where(
        s.source == OPINET, s.sido_value != "", s.sigungu_value != "",
        s.longitude.between(max(124.0, longitude - half_width), min(132.0, longitude + half_width)),
        s.latitude.between(max(32.0, latitude - radius), min(39.5, latitude + radius)),
    ).order_by(distance2, s.id).limit(1)


def _scale(latitude: float) -> float:
    return max(math.cos(math.radians(latitude)), 0.2)


async def _nearest(session: AsyncSession, longitude: float, latitude: float) -> dict | None:
    for radius in SEARCH_RADII:
        row = (await session.execute(nearest_statement(longitude, latitude, radius))).first()
        if row is None:
            continue
        distance = math.sqrt(float(row.distance2))
        # 상자에 내접한 원 밖의 결과는 상자 밖 주유소가 더 가까울 수 있어 다음(더 큰) 상자로 넘긴다.
        if distance <= radius:
            return {"sido_value": row.sido_value, "sido_name": row.sido_name or row.sido_value,
                    "sigungu_value": row.sigungu_value, "sigungu_name": row.sigungu_name or row.sigungu_value,
                    "method": "nearest_station", "distance_m": round(distance * METERS_PER_DEGREE)}
    return None
