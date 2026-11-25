"""장소 지도 200 응답의 `X-Limit-Applied`(실제로 적용한 limit) 계약.

공개 gateway(12301·12307)는 limit을 생략·초과하면 900으로 바꿔 upstream query 끝에 붙인다. backend가 받은 값이
곧 적용 값이므로 backend가 모든 200 응답(재사용 페이지·축척 요약·상세)에 같은 header를 붙인다.
gateway 쪽 통과·CORS 노출은 scripts/gateway-probe.py와 test_fuel_public_gateway_contract.py가 본다.
"""
import asyncio

import pytest

from app import main
from app.core.time_utils import now_utc
from app.models import TransportCollectionState
from app.services import fuel_map_validation as validation
from app.services.transport_collection import OPINET_SOURCE
from test_place_map_validation import _seed_places_and_prices

PLACES = "/v1/transport/features/places"
BOUNDS = "min_longitude=126&min_latitude=36&max_longitude=128&max_latitude=38"


def applied(response):
    assert response.status_code == 200, response.text
    return response.headers.get_list(main.PLACES_LIMIT_APPLIED_HEADER)


def test_header_reports_backend_default_when_limit_is_omitted(client):
    # 12302 직접 호출(관리 BFF)이 limit을 생략하면 backend 기본 1000이 적용된다.
    assert applied(client.get(PLACES)) == ["1000"]


@pytest.mark.parametrize("limit", ["1", "300", "900", "5000"])
def test_header_reports_the_limit_backend_received(client, limit):
    assert applied(client.get(f"{PLACES}?limit={limit}&kind=fuel_station")) == [limit]


def test_header_uses_the_last_repeated_limit_like_the_gateway_rewrite(client):
    # gateway는 판정 값을 query 끝에 붙인다. Starlette는 마지막 값을 쓰고 header도 그 값을 말한다.
    assert applied(client.get(f"{PLACES}?limit=5000&limit=900")) == ["900"]


def test_clustered_summary_response_carries_header(client):
    # 낮은 축척은 지역·셀 요약(items=[])을 따로 만든다. 그 반환 경로에도 header가 있어야 한다.
    response = client.get(f"{PLACES}?kind=fuel_station&{BOUNDS}&zoom=5&limit=300")
    assert applied(response) == ["300"]
    assert response.json()["clustered"] is True


def test_request_header_cannot_spoof_the_applied_limit(client):
    response = client.get(f"{PLACES}?limit=10", headers={"X-Limit-Applied": "5000"})
    assert applied(response) == ["10"]


@pytest.mark.parametrize("query", ["limit=0", "limit=5001", "limit=abc", "kind=unknown"])
def test_validation_errors_do_not_carry_header(client, query):
    response = client.get(f"{PLACES}?{query}")
    assert response.status_code == 422
    assert main.PLACES_LIMIT_APPLIED_HEADER.lower() not in {key.lower() for key in response.headers}


def test_openapi_documents_header_on_places_200(client):
    schema = client.get("/openapi.json").json()
    responses = schema["paths"][PLACES]["get"]["responses"]
    header = responses["200"]["headers"]["X-Limit-Applied"]
    assert header["schema"] == {"type": "integer", "minimum": 1, "maximum": 5000}
    assert "900" in header["description"] and "truncated" in header["description"]
    # 오류 응답에는 문서화하지 않는다(실제로도 붙이지 않는다).
    assert "X-Limit-Applied" not in responses["422"].get("headers", {})


def test_reused_page_carries_header_for_its_own_limit(client, monkeypatch):
    # 재사용 페이지(place_map_cache)는 저장 bytes를 다시 내보내는 별도 반환 경로다. 키에 limit이 들어 있어
    # 다른 limit 요청이 같은 페이지를 받지 않으므로 header도 요청마다 맞다.
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("재사용 페이지 증명은 PostgreSQL RR snapshot이 필요하다")

    async def seed():
        async with client.app.state.session_factory() as session:
            await _seed_places_and_prices(session)
            session.add(TransportCollectionState(source=OPINET_SOURCE, last_success_at=now_utc(), updated_at=now_utc()))
            await session.commit()
    asyncio.run(seed())
    monkeypatch.setattr(validation, "_validated_items", validation.ValidatedFuelMapItems())
    client.app.state.settings.release_sha = "places-limit-applied"

    def page_builds(response):
        return int(response.headers["server-timing"].split('page_builds;desc="')[1].split('"')[0])

    first = client.get(f"{PLACES}?limit=7")
    second = client.get(f"{PLACES}?limit=7")
    other = client.get(f"{PLACES}?limit=8")
    assert applied(first) == applied(second) == ["7"]
    assert page_builds(second) == 0, "두 번째 요청은 재사용 페이지여야 이 반환 경로를 시험한다"
    assert applied(other) == ["8"]
