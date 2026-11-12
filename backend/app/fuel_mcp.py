"""Transport API와 같은 프로세스·포트에서 제공하는 읽기 전용 MCP 도구."""
from anyio import CapacityLimiter, fail_after
from fastapi import HTTPException, Request
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse

from app.schemas import FuelSearchResponse, NearbyFuelQuery, RegionalFuelQuery
from app.service_exports import require_service_access
from app.services.fuel_search import begin_fuel_search, nearby_fuel, regional_fuel
from app.services.fuel_search_location import FuelLocationResolver, published_region, region_for_address


class ServiceTokenGate:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            try:
                require_service_access(Request(scope), self.settings)
            except HTTPException:
                await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_fuel_mcp(settings, session_factory):
    server = MCPServer("kor-travel-transport-fuel", version="1.0.0", instructions=(
        "저장된 Opinet 성공 공개 세대의 유가를 조회합니다. 위치는 WGS84 인자로만 받습니다. "
        "가격은 원/L, 반경·직선거리는 m입니다. unavailable/미제공을 0으로 해석하지 마세요. "
        "전국·시군구의 최저 동률은 영구 통계의 안정 대표 1곳과 전체 동률수를 제공합니다. "
        "stale와 update_pending 및 시각을 함께 설명하세요. 수집·원본 변경 도구는 없습니다."
    ))
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)
    calls = CapacityLimiter(4)
    location = FuelLocationResolver(settings, session_factory)

    @server.tool(annotations=annotations)
    async def search_nearby_fuel(query: NearbyFuelQuery) -> FuelSearchResponse:
        """반경 내 전5유종의 양수 가격 평균·건수와 최저가 동률 주유소·직선거리(m)를 조회합니다."""
        try:
            with fail_after(20):
                async with calls, session_factory() as session:
                    await begin_fuel_search(session)
                    return await nearby_fuel(session, query)
        except Exception:
            raise ToolError("fuel_search_unavailable") from None

    @server.tool(annotations=annotations)
    async def get_regional_fuel_prices(query: RegionalFuelQuery) -> FuelSearchResponse:
        """전국/현재 좌표 시군구의 평균·최저가·대표 주유소를 같은 영구 공개 세대로 조회합니다.

        시군구는 좌표 또는 명시 Opinet 시도/시군구 코드를 받습니다. 주소 판정 실패는 unavailable이며
        가까운 주유소 지역을 대신 쓰지 않습니다. 좌표를 주면 대표 최저가의 직선거리(m)도 제공합니다.
        """
        try:
            with fail_after(20):
                async with calls:
                    payload, method = (None, "explicit")
                    if query.scope == "sigungu" and query.sido_value is None:
                        payload, method = await location.address(query.latitude, query.longitude)
                    async with session_factory() as session:
                        await begin_fuel_search(session)
                        region = None
                        if query.scope == "sigungu":
                            region = await published_region(session, query.sido_value, query.sigungu_value, "explicit") if query.sido_value is not None else await region_for_address(session, payload, method)
                        return await regional_fuel(session, query, region)
        except Exception:
            raise ToolError("fuel_search_unavailable") from None

    hosts = [host for item in settings.trusted_hosts for host in (item, item + ":*")]
    http = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True,
        json_response=True, max_request_body_size=16384,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=hosts, allowed_origins=settings.cors_origins))
    return server, http, ServiceTokenGate(http, settings)
