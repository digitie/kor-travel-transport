"""성공 공개 세대·거리/집계 SQL·인증·실제 JSON-RPC/lifespan 계약."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from kortravelcommon.address_providers import VworldKakaoAddressResolver
from kortravelcommon.reverse_address import AddressTarget, reverse_address_tables
from sqlalchemy import event, func, insert, select, text, update

from app.main import create_app
from app.models import Base, FuelStation, FuelLatestPrice, FuelPriceSnapshot, FuelStatisticsState, TransportCollectionState
from app.schemas import NearbyFuelQuery, RegionalFuelQuery
from app.services.fuel_search import begin_fuel_search, nearby_fuel, regional_fuel
from app.services.fuel_statistics import OPINET, publish_fuel_statistics

TOKEN = "fixture-service-token-" * 3
HEADERS = {"x-kor-travel-transport-service-token": TOKEN,
           "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"}


def rpc(client, method, arguments=None, **kwargs):
    return client.post("/mcp", headers=kwargs.pop("headers", HEADERS), json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": arguments or {},
    }, **kwargs)


def call(client, tool, query):
    response = rpc(client, "tools/call", {"name": tool, "arguments": {"query": query}})
    assert response.status_code == 200
    result = response.json()["result"]
    assert not result.get("isError"), result
    return result["structuredContent"]


@pytest.fixture
def fuel_mcp(test_settings):
    settings = test_settings.model_copy(update={
        "transport_fuel_mcp_enabled": True, "transport_service_export_token": TOKEN,
        "vworld_api_key": None, "kakao_rest_api_key": None,
    })
    with TestClient(create_app(settings), client=("127.0.0.1", 50000)) as client:
        stamp = datetime.now(timezone.utc) - timedelta(minutes=1)
        old = stamp - timedelta(days=2)
        async def seed():
            async with client.app.state.session_factory() as session:
                for index, longitude in enumerate([127.0, 127.001, 127.1, 127.0], 1):
                    session.add(FuelStation(id=index, source=OPINET, identity_key=str(index), name=f"주유소{index}",
                        address=f"서울 도로{index}", brand_name="검증상표", query_level="sigungu", source_kinds=[],
                        sido_value="01", sido_name="서울", sigungu_value="0101", sigungu_name="종로구",
                        longitude=longitude, latitude=37.5, first_seen_at=old, last_seen_at=stamp))
                await session.flush()
                values = [
                    {"B027": 1500, "B034": 1700, "D047": 1400, "C004": 0, "K015": None},
                    {"B027": 1500, "B034": 1750, "D047": 1450, "C004": 1000, "K015": 900},
                    {"B027": 1800}, {"B027": 110},
                ]
                for index, prices in enumerate(values, 1):
                    when = old if index == 4 else stamp
                    for code, price in prices.items():
                        snapshot = FuelPriceSnapshot(fuel_station_id=index, source=OPINET, product_code=code,
                            price=price, observed_at=when, collected_at=when)
                        session.add(snapshot)
                        await session.flush()
                        session.add(FuelLatestPrice(fuel_station_id=index, product_code=code, snapshot_id=snapshot.id,
                            price=price, observed_at=when, collected_at=when))
                session.add(TransportCollectionState(source=OPINET, last_success_at=stamp, updated_at=stamp))
                await session.flush()
                await publish_fuel_statistics(session, OPINET, stamp)
                await session.commit()
        asyncio.run(seed())
        yield client, stamp


def test_initialize_discover_tools_and_same_api_lifespan(fuel_mcp):
    client, _ = fuel_mcp
    initialized = rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
        "clientInfo": {"name": "transport-test", "version": "1"}})
    assert initialized.status_code == 200
    assert initialized.json()["result"]["protocolVersion"] == "2025-11-25"
    notified = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notified.status_code in (200, 202)
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == {"search_nearby_fuel", "get_regional_fuel_prices"}
    assert all(tool["annotations"]["readOnlyHint"] and tool["outputSchema"] for tool in tools)
    discover = rpc(client, "server/discover", {"_meta": {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }}, headers={**HEADERS, "MCP-Protocol-Version": "2026-07-28", "MCP-Method": "server/discover"})
    assert discover.status_code == 200 and "result" in discover.json()
    assert client.get("/health").status_code == 200


def test_radius_all_products_sql_distance_ties_and_old_price_exclusion(fuel_mcp):
    client, _ = fuel_mcp
    statements = []
    def capture(_, __, statement, *args):
        statements.append(statement.lower())
    engine = client.app.state.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = call(client, "search_nearby_fuel", {"latitude": 37.5, "longitude": 127, "radius_m": 500,
            "limit_per_product": 1})
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    products = {row["product_code"]: row for row in result["products"]}
    assert len(products) == 5 and result["radius_m"] == 500 and result["price_unit"] == "KRW/L"
    gas = products["B027"]
    assert gas["station_count"] == 2 and gas["average_price"] == gas["minimum_price"] == 1500
    assert gas["cheapest_station_count"] == 2 and gas["truncated"]
    assert gas["cheapest_stations"][0]["station_key"] == "1"
    assert gas["cheapest_stations"][0]["distance_m"] == 0
    assert products["C004"]["station_count"] == 1 and products["C004"]["minimum_price"] == 1000
    assert products["K015"]["station_count"] == 1 and products["K015"]["minimum_price"] == 900
    unlimited = call(client, "search_nearby_fuel", {"latitude": 37.5, "longitude": 127, "radius_m": 500})
    ties = unlimited["products"][0]["cheapest_stations"]
    assert [row["station_key"] for row in ties] == ["1", "2"]
    assert 87 < ties[1]["distance_m"] < 89
    assert any("asin" in sql and "avg(" in sql and "row_number()" in sql for sql in statements)
    assert not any("fuel_price_snapshots" in sql or "raw_item_json" in sql for sql in statements)
    async def original_kept():
        async with client.app.state.session_factory() as session:
            assert float((await session.get(FuelLatestPrice, (4, "B027"))).price) == 110
            assert await session.scalar(select(func.count()).select_from(FuelPriceSnapshot)) == 12
    asyncio.run(original_kept())


def test_regions_use_published_permanent_cohort_and_explicit_codes(fuel_mcp):
    client, stamp = fuel_mcp
    result = call(client, "get_regional_fuel_prices", {})
    gas = result["products"][0]
    assert gas["station_count"] == 3 and gas["average_price"] == 1600
    assert gas["minimum_price"] == 1500 and gas["cheapest_station_count"] == 2
    assert gas["cheapest_stations"][0]["station_key"] == "1" and gas["truncated"]
    result = call(client, "get_regional_fuel_prices", {"scope": "sigungu", "sido_value": "01", "sigungu_value": "0101",
        "latitude": 37.5, "longitude": 127})
    assert result["region"]["status"] == "resolved" and result["region"]["label"] == "서울 종로구"
    assert result["products"][0]["average_price"] == 1600
    assert result["products"][0]["cheapest_stations"][0]["distance_m"] == 0
    async def advance():
        async with client.app.state.session_factory() as session:
            state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == OPINET))
            state.last_success_at = stamp + timedelta(minutes=1)
            state.last_error = "fixture_failure"
            await session.commit()
    asyncio.run(advance())
    pending = call(client, "get_regional_fuel_prices", {})
    assert pending["collection"]["update_pending"] and pending["collection"]["last_attempt_failed"]
    assert pending["products"][0] == gas


def test_coordinate_district_uses_stored_address_without_provider(fuel_mcp):
    client, stamp = fuel_mcp
    target = AddressTarget("test-location", 127, 37.5)
    entries, _ = reverse_address_tables(Base.metadata)
    async def cached():
        async with client.app.state.session_factory() as session:
            await session.execute(insert(entries).values(provider_id=VworldKakaoAddressResolver.provider_id,
                target_key=target.key, coordinate_key=target.coordinate_key, longitude=127, latitude=37.5,
                refresh_id="test", payload={"provider": "vworld", "address": {"legal_dong_code": "1111010100"},
                    "region": {"sido": "서울특별시", "sigungu": "종로구"}}, status="ok", checked_at=stamp,
                resolved_at=stamp, next_refresh_at=stamp + timedelta(days=1), failures=0))
            await session.commit()
    asyncio.run(cached())
    with patch.object(VworldKakaoAddressResolver, "reverse", side_effect=AssertionError("no provider call")):
        result = call(client, "get_regional_fuel_prices", {"scope": "sigungu", "latitude": 37.5, "longitude": 127})
    assert result["region"]["status"] == "resolved" and result["region"]["method"] == "stored_address"
    assert result["region"]["sido_value"] == "01" and result["region"]["sigungu_value"] == "0101"


def test_unknown_region_and_empty_radius_distinguish_missing_from_zero(fuel_mcp):
    client, _ = fuel_mcp
    result = call(client, "get_regional_fuel_prices", {"scope": "sigungu", "latitude": 37, "longitude": 126})
    assert result["region"]["status"] == "unavailable" and result["region"]["reason"] == "address_not_configured"
    assert all(row["station_count"] is None and row["average_price"] is None for row in result["products"])
    empty = call(client, "search_nearby_fuel", {"latitude": 35, "longitude": 129, "radius_m": 1})
    assert all(row["station_count"] == 0 and row["average_price"] is None for row in empty["products"])
    from app.services.fuel_search_location import FuelLocationResolver
    with patch.object(FuelLocationResolver, "address", return_value=({"provider": "vworld",
            "address": {"legal_dong_code": "9999910100"},
            "region": {"sido": "확인불가", "sigungu": "확인불가"}}, "coordinate_address")):
        missing = call(client, "get_regional_fuel_prices", {"scope": "sigungu", "latitude": 37.5, "longitude": 127})
    assert missing["region"]["reason"] == "region_not_matched"
    assert all(row["station_count"] is None for row in missing["products"])


@pytest.mark.parametrize("query", [{"radius_m": 0}, {"radius_m": 50001}, {"latitude": 91}, {"product_codes": ["BAD"]}])
def test_invalid_arguments_rejected(fuel_mcp, query):
    client, _ = fuel_mcp
    response = rpc(client, "tools/call", {"name": "search_nearby_fuel", "arguments": {"query": {
        "latitude": 37.5, "longitude": 127, **query}}})
    assert response.status_code == 200
    body = response.json()
    assert "error" in body or body.get("result", {}).get("isError")


def test_token_peer_and_origin_not_host_forwarded_headers(fuel_mcp):
    client, _ = fuel_mcp
    assert rpc(client, "tools/list", headers={"Accept": HEADERS["Accept"]}).status_code == 404
    assert rpc(client, "tools/list", headers={**HEADERS, "Origin": "https://invalid.example"}).status_code == 403
    settings = client.app.state.settings
    with TestClient(create_app(settings), client=("198.51.100.7", 50000)) as outside:
        assert rpc(outside, "tools/list", headers={**HEADERS, "X-Forwarded-For": "127.0.0.1"}).status_code == 404


def test_tool_failure_hides_exception_and_no_generation_is_unavailable(fuel_mcp, caplog):
    client, _ = fuel_mcp
    with patch("app.fuel_mcp.nearby_fuel", side_effect=RuntimeError("fixture-private-value")):
        response = rpc(client, "tools/call", {"name": "search_nearby_fuel", "arguments": {"query": {"latitude": 37.5, "longitude": 127}}})
    assert response.json()["result"]["isError"]
    assert "fixture-private-value" not in response.text and "fixture-private-value" not in caplog.text
    async def clear_pointer():
        async with client.app.state.session_factory() as session:
            pointer = await session.get(FuelStatisticsState, OPINET)
            await session.delete(pointer)
            await session.commit()
    asyncio.run(clear_pointer())
    unavailable = call(client, "search_nearby_fuel", {"latitude": 37.5, "longitude": 127})
    assert unavailable["collection"]["reason"] == "no_published_generation"
    assert all(row["station_count"] is None for row in unavailable["products"])


def test_disabled_mcp_keeps_api_available(test_settings):
    with TestClient(create_app(test_settings), client=("127.0.0.1", 50000)) as client:
        assert client.get("/health").status_code == 200
        assert rpc(client, "tools/list").status_code == 404


def test_postgres_read_only_snapshot_does_not_mix_publication_generations(fuel_mcp):
    client, stamp = fuel_mcp
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("native PostgreSQL transaction snapshot")
    from app.services import fuel_search
    original = fuel_search.collection_metadata
    async def exercise():
        async def advance_after_snapshot(session):
            metadata = await original(session)
            assert await session.scalar(text("SHOW transaction_read_only")) == "on"
            async with client.app.state.session_factory() as writer:
                new = stamp + timedelta(seconds=1)
                await writer.execute(update(FuelLatestPrice).values(price=333, collected_at=new))
                await writer.execute(update(TransportCollectionState).where(TransportCollectionState.source == OPINET).values(last_success_at=new))
                await publish_fuel_statistics(writer, OPINET, new)
                await writer.commit()
            return metadata
        async with client.app.state.session_factory() as session:
            await begin_fuel_search(session)
            with patch.object(fuel_search, "collection_metadata", side_effect=advance_after_snapshot):
                prior = await regional_fuel(session, RegionalFuelQuery())
            assert prior.products[0].average_price == 1600
        async with client.app.state.session_factory() as session:
            await begin_fuel_search(session)
            current = await regional_fuel(session, RegionalFuelQuery())
            assert current.products[0].average_price == 333
    asyncio.run(exercise())
