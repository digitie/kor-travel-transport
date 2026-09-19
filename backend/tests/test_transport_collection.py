from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from krex import CongestionLevel, Direction, Incident, TrafficFlow
from opinet import ProductCode, StationType
from opinet.experimental import (
    BrowserFuelPrice,
    BrowserRegion,
    BrowserStation,
    OpinetBrowserSnapshot,
)
from sqlalchemy import select

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.main import create_app
from app.models import FuelPriceSnapshot, FuelStation
from app.services.transport_collection import (
    HighwayPayload,
    INCIDENT_SOURCE,
    OPINET_SOURCE,
    TRAFFIC_SOURCE,
    TransportCollectionService,
)


class FakeTransportProvider:
    mode = "fixture"
    enabled_sources = (TRAFFIC_SOURCE, INCIDENT_SOURCE, OPINET_SOURCE)

    def __init__(self) -> None:
        self.observed_at = now_utc()

    async def collect_highway(self) -> HighwayPayload:
        return HighwayPayload(
            traffic=(
                TrafficFlow(
                    conzone_id="1001",
                    conzone_name="테스트 구간",
                    route_no="001",
                    route_name="테스트고속도로",
                    direction=Direction.EAST,
                    speed=82.0,
                    free_flow_speed=100.0,
                    congestion_level=CongestionLevel.SMOOTH,
                    updated_at=self.observed_at.strftime("%Y%m%d%H%M%S"),
                    raw={"routeNo": "001"},
                ),
            ),
            incidents=(
                Incident(
                    occurred_date=self.observed_at.strftime("%Y%m%d"),
                    occurred_time=self.observed_at.strftime("%H%M"),
                    incident_type="사고",
                    incident_type_code="01",
                    direction="서울방향",
                    message="테스트 돌발",
                    point_name="테스트 IC",
                    route_no="001",
                    route_name="테스트고속도로",
                    process_status="처리중",
                    process_status_code="01",
                    latitude=37.4,
                    longitude=127.1,
                    congestion_length=1.2,
                    series_no=10,
                    raw={"seriesNM": "10"},
                ),
            ),
        )

    async def collect_fuel(self) -> OpinetBrowserSnapshot:
        region = BrowserRegion(
            sido_value="11",
            sido_name="서울",
            sigungu_value="110",
            sigungu_name="테스트구",
        )
        station = BrowserStation(
            region=region,
            query_level="sigungu",
            source_kinds=("station",),
            station_id="S-1",
            name="테스트주유소",
            brand_code="SKE",
            brand_name="테스트",
            phone="02-000-0000",
            address="서울 테스트구",
            business_number="123-45-67890",
            cb_code="CB-1",
            station_type=StationType.GAS_STATION,
            katec_x=950000.0,
            katec_y=1950000.0,
            lon=127.1,
            lat=37.4,
            prices=(
                BrowserFuelPrice(
                    product_code=ProductCode.GASOLINE,
                    price=1700.5,
                    updated_at=self.observed_at,
                ),
            ),
            is_illegal=False,
            is_self=True,
            is_24h=True,
            is_kpetro=True,
            is_electronic=True,
            is_good=False,
            is_good_strong=False,
            is_region_franchise=False,
            has_carwash=True,
            has_maintenance=False,
            has_cvs=True,
            cs_yn=True,
            discount_info=None,
            save_event_info=None,
            representative_event_info=None,
            on_event_info=None,
            other_business_info=None,
            raw={"UNI_ID": "S-1"},
        )
        return OpinetBrowserSnapshot(
            collected_at=self.observed_at,
            source_url="https://www.opinet.co.kr/searRgSelect.do",
            regions=(region,),
            stations=(station,),
        )

    def next_fuel_interval(self) -> timedelta:
        return timedelta(hours=10)

    async def aclose(self) -> None:
        return None


def build_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'transport.sqlite3'}",
        seed_sample_data=False,
        enable_scheduler=False,
        transport_collection_enabled=True,
        use_sample_client_when_no_key=True,
        transport_collect_interval_seconds=300,
    )


def test_transport_collection_stores_and_deduplicates_snapshots(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    provider = FakeTransportProvider()

    async def run() -> tuple[dict, dict]:
        await init_database(engine)
        service = TransportCollectionService(settings, provider)
        async with session_factory() as session:
            first = await service.collect(session, trigger="test")
        async with session_factory() as session:
            second = await service.collect(session, trigger="test")
        await service.close()
        await engine.dispose()
        return first, second

    first, second = asyncio.run(run())

    assert first["status"] == "success"
    assert first["traffic_snapshot_count"] == 1
    assert first["incident_snapshot_count"] == 1
    assert first["fuel_station_count"] == 1
    assert first["fuel_price_count"] == 1
    assert second["traffic_snapshot_count"] == 0
    assert second["incident_snapshot_count"] == 0
    assert second["fuel_station_count"] == 0
    assert second["fuel_price_count"] == 0


def test_transport_openapi_returns_stored_data_and_statistics(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        service = client.app.state.transport_collection_service
        provider = FakeTransportProvider()
        service.provider = provider

        async def collect() -> None:
            async with client.app.state.session_factory() as session:
                await service.collect(session, trigger="test")

        asyncio.run(collect())

        traffic = client.get("/v1/transport/highways/traffic", params={"route_no": "001"})
        incidents = client.get("/v1/transport/highways/incidents", params={"route_no": "001"})
        fuel = client.get("/v1/transport/fuel/stations", params={"sido_value": "11"})
        statistics = client.get("/v1/transport/statistics", params={"route_no": "001"})
        status = client.get("/v1/transport/collector-status")

    assert traffic.status_code == 200
    assert traffic.json()["items"][0]["route_no"] == "001"
    assert incidents.status_code == 200
    assert incidents.json()["items"][0]["occurred_time"] == provider.observed_at.strftime("%H%M")
    assert fuel.status_code == 200
    assert fuel.json()["items"][0]["prices"][0]["product_code"] == "B027"
    assert statistics.status_code == 200
    assert statistics.json()["traffic"][0]["observations"] == 1
    assert statistics.json()["fuel_prices"][0]["average_price"] == 1700.5
    assert status.status_code == 200
    assert {item["source"] for item in status.json()["sources"]} == {
        TRAFFIC_SOURCE,
        INCIDENT_SOURCE,
        OPINET_SOURCE,
    }


def test_fuel_openapi_returns_only_the_latest_price_per_product(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        service = client.app.state.transport_collection_service
        provider = FakeTransportProvider()
        service.provider = provider

        async def collect_and_add_history() -> None:
            async with client.app.state.session_factory() as session:
                await service.collect(session, trigger="test")
                station = await session.scalar(select(FuelStation))
                assert station is not None
                session.add_all(
                    [
                        FuelPriceSnapshot(
                            fuel_station_id=station.id,
                            source=OPINET_SOURCE,
                            product_code="B027",
                            price=1600,
                            provider_updated_at=provider.observed_at - timedelta(hours=1),
                            observed_at=provider.observed_at - timedelta(hours=1),
                            collected_at=provider.observed_at,
                        ),
                        FuelPriceSnapshot(
                            fuel_station_id=station.id,
                            source=OPINET_SOURCE,
                            product_code="B027",
                            price=1800,
                            provider_updated_at=provider.observed_at + timedelta(minutes=1),
                            observed_at=provider.observed_at + timedelta(minutes=1),
                            collected_at=provider.observed_at,
                        ),
                    ]
                )
                await session.commit()

        asyncio.run(collect_and_add_history())
        fuel = client.get("/v1/transport/fuel/stations", params={"sido_value": "11"})

    assert fuel.status_code == 200
    assert fuel.json()["items"][0]["prices"] == [
        {
            "product_code": "B027",
            "price": 1800.0,
            "provider_updated_at": (provider.observed_at + timedelta(minutes=1)).isoformat().replace(
                "+00:00", "Z"
            ),
            "observed_at": (provider.observed_at + timedelta(minutes=1)).isoformat().replace(
                "+00:00", "Z"
            ),
            "collected_at": provider.observed_at.isoformat().replace("+00:00", "Z"),
        }
    ]
