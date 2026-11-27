"""Transport API와 같은 프로세스·포트에서 제공하는 읽기 전용 MCP 도구."""
from pathlib import Path

from anyio import CapacityLimiter, fail_after
from fastapi import HTTPException, Request
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse

from app.schemas import FuelSearchResponse, NearbyFuelQuery, RegionalFuelQuery, NearbyFuelListQuery, FuelRankedSearchResponse, FuelSearchCollection
from app.service_exports import require_service_access
from app.services.fuel_search import begin_fuel_search, nearby_fuel, regional_fuel
from app.services.fuel_search_location import FuelLocationResolver, published_region, region_for_address


FUEL_WIDGET_URI = "ui://transport-fuel/v1.html"


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

    @server.tool(annotations=annotations)
    async def list_nearby_fuel_stations(query: NearbyFuelListQuery) -> FuelRankedSearchResponse:
        """반경 안 주유소를 유종별 가격순/직선거리순으로 최대20곳씩 조회합니다. 평균·최저는 전체 반경 모집단입니다."""
        try:
            with fail_after(20):
                async with calls, session_factory() as session:
                    await begin_fuel_search(session)
                    result = await nearby_fuel(session, query, ranked=True, sort_by=query.sort_by)
                    return FuelRankedSearchResponse.model_validate(result.model_dump())
        except Exception:
            raise ToolError("fuel_search_unavailable") from None

    @server.tool(annotations=annotations, meta={"ui": {"visibility": ["app"]}})
    async def query_fuel_widget(query: NearbyFuelListQuery) -> FuelRankedSearchResponse:
        """내 주변 유가 UI의 갱신용 데이터 도구. UI를 다시 마운트하지 않고 같은 공개 세대 목록을 조회합니다."""
        return await list_nearby_fuel_stations(query)

    @server.tool(annotations=annotations, meta={"ui": {"resourceUri": FUEL_WIDGET_URI}})
    async def render_fuel_widget(query: NearbyFuelListQuery | None = None) -> FuelRankedSearchResponse:
        """사용자가 제공한 좌표 주변 유가를 지도·목록 UI로 엽니다. 좌표를 추측하지 마세요.

        위치를 모르면 query를 생략해 위치 동의·직접 입력 화면부터 엽니다.
        데이터만 필요하면 list_nearby_fuel_stations를 사용하세요. UI 내부 갱신은 데이터 도구를 직접
        호출하므로 UI를 다시 열 필요가 없습니다. 수집·가격 갱신은 하지 않습니다.
        """
        if query is None:
            return FuelRankedSearchResponse(scope="radius", collection=FuelSearchCollection(
                status="unavailable", reason="location_required"), products=[])
        return await list_nearby_fuel_stations(query)

    @server.resource(FUEL_WIDGET_URI, name="nearby-fuel", title="내 주변 유가",
                     mime_type="text/html;profile=mcp-app", meta={"ui": {
                         "prefersBorder": True, "permissions": {"geolocation": {}},
                         "csp": {"connectDomains": ["https://tile.openstreetmap.org"],
                                 "resourceDomains": ["https://tile.openstreetmap.org"]},
                     }})
    def fuel_widget() -> str:
        """토큰·좌표·사용자 데이터가 없는 공용 UI 번들. 리소스 읽기도 기존 서비스 인증을 적용한다."""
        try:
            return (Path(__file__).parent / "fuel_widget" / "index.html").read_text(encoding="utf-8")
        except OSError:
            raise ToolError("fuel_ui_unavailable") from None

    hosts = [host for item in settings.trusted_hosts for host in (item, item + ":*")]
    http = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True,
        json_response=True, max_request_body_size=16384,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=hosts, allowed_origins=settings.cors_origins))
    return server, http, ServiceTokenGate(http, settings)
