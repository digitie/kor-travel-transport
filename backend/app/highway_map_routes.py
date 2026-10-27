"""ITS 공개 화면의 선택 노선 소통 지도. 원문 파싱·좌표 의미는 krits가 소유한다."""
import asyncio
from collections import OrderedDict
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from krits import AsyncTokenBucket, KritsClient

from app.core.time_utils import now_utc, seconds_until_next_seoul_midnight, to_seoul
from app.schemas import HighwayRoad, HighwayRoadCatalog, HighwayRoadTraffic, HighwayTrafficLink


def build_highway_map_router() -> APIRouter:
    router = APIRouter(prefix="/transport/highways")
    # 선택 노선 조회만 허용하고 Chromium은 operation마다 SDK가 정상 종료한다.
    # 전체 전국 수집·스케줄·기존 KREX 관측/통계와는 별개의 작은 worker 캐시다.
    cache: OrderedDict[tuple[str, str], HighwayRoadCatalog | HighwayRoadTraffic] = OrderedDict()
    lock = asyncio.Lock()
    limiter = AsyncTokenBucket(max_rps=1, capacity=1)
    blocked_until = None
    requests_day = None
    attempts = 0

    async def cached(request, key, ttl, fetch, timeout=25):
        nonlocal blocked_until, requests_day, attempts
        saved = cache.get(key)
        if saved and timedelta(0) <= now_utc() - saved.fetched_at < ttl:
            cache.move_to_end(key)
            return saved
        fetching = False
        try:
            # lock/limiter 대기와 Chromium 초기화까지 BFF의 30초 안에서 끝낸다.
            async with asyncio.timeout(timeout):
                async with lock:
                    saved = cache.get(key)
                    if saved and timedelta(0) <= now_utc() - saved.fetched_at < ttl:
                        cache.move_to_end(key)
                        return saved
                    now = now_utc()
                    if requests_day != to_seoul(now).date():
                        requests_day, attempts = to_seoul(now).date(), 0
                    if (blocked_until and now < blocked_until) or attempts >= 96:
                        if saved:
                            return saved.model_copy(update={"stale": True})
                        # 일일 상한은 다음 KST 자정에야 초기화된다. 고정 3600초를 따르면 그때까지 매시간 429를 받는다.
                        waits = [1]
                        if blocked_until and now < blocked_until:
                            waits.append(int((blocked_until - now).total_seconds()))
                        if attempts >= 96:
                            waits.append(seconds_until_next_seoul_midnight(now))
                        raise HTTPException(status_code=429, detail="도로 소통 조회 보호 중입니다. 잠시 후 다시 조회해 주세요.", headers={"Retry-After": str(max(waits))})
                    attempts += 1
                    fetching = True
                    try:
                        async with KritsClient(timeout=25, rate_limiter=limiter,
                            executable_path=request.app.state.settings.its_chromium_executable_path or None) as client:
                            result = await fetch(client)
                    except Exception:
                        blocked_until = now_utc() + timedelta(minutes=15)
                        if saved:
                            return saved.model_copy(update={"stale": True})
                        raise HTTPException(status_code=502, detail="ITS 공개 도로 소통 응답을 확인하지 못했습니다. 잠시 후 다시 조회해 주세요.") from None
                    cache[key] = result
                    cache.move_to_end(key)
                    while len(cache) > 9:
                        cache.popitem(last=False)
                    return result
        except TimeoutError:
            if fetching:
                blocked_until = now_utc() + timedelta(minutes=15)
            if saved:
                return saved.model_copy(update={"stale": True})
            raise HTTPException(status_code=504, detail="도로 소통 조회가 지연되고 있습니다. 잠시 후 다시 조회해 주세요.") from None

    async def road_catalog(request):
        async def fetch(client):
            result = await client.list_roads(road_type="highway")
            return HighwayRoadCatalog(fetched_at=result.collected_at, source_url=result.source_url,
                items=[HighwayRoad(road_id=row.road_id, road_number=row.road_number, name=row.name) for row in result.items])
        return await cached(request, ("catalog", "highway"), timedelta(hours=24), fetch)

    @router.get("/roads", response_model=HighwayRoadCatalog)
    async def roads(request: Request):
        return await road_catalog(request)

    @router.get("/road-traffic", response_model=HighwayRoadTraffic)
    async def road_traffic(request: Request, road_id: str = Query(pattern=r"^[0-9]{4}$"), direction: Literal["1", "2"] = "1"):
        started = asyncio.get_running_loop().time()
        catalog = await road_catalog(request)
        road = next((row for row in catalog.items if row.road_id == road_id), None)
        if road is None:
            raise HTTPException(status_code=422, detail="도로 목록에서 고속도로를 다시 선택해 주세요.")
        async def fetch(client):
            result = await client.get_traffic(road_id, road_type="highway", direction=direction)
            links = [link for section in result.items for link in section.links]
            if len(links) > 5000 or sum(len(link.path) for link in links) > 100_000:
                raise ValueError("selected road exceeds the bounded map response")
            return HighwayRoadTraffic(fetched_at=result.collected_at, source_url=result.source_url,
                road_id=road.road_id, road_number=road.road_number, road_name=road.name, direction=direction,
                items=[HighwayTrafficLink(link_id=link.link_id, section_id=section.section_id, section_name=section.name,
                    direction=link.direction, speed_kmh=link.speed_kmh, length_m=link.length_m, path=list(link.path))
                    for section in result.items for link in section.links])
        remaining = max(.001, 25 - (asyncio.get_running_loop().time() - started))
        return await cached(request, (road_id, direction), timedelta(minutes=5), fetch, timeout=remaining)

    return router
