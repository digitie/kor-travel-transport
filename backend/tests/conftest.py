from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory
from app.main import create_app


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    force_temp_sqlite = os.getenv("PARKING_RADAR_TEST_SQLITE_TEMP") == "1"
    # 테스트는 운영 DATABASE_URL을 절대 상속하지 않는다. PostgreSQL 통합 검증은
    # TEST_DATABASE_URL과 명시적인 안전 표지를 함께 준 경우에만 허용한다.
    database_url = None if force_temp_sqlite else os.getenv("TEST_DATABASE_URL")
    if not database_url:
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}"
    if database_url.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://")):
        if os.getenv("PARKING_RADAR_TEST_DATABASE") != "1":
            raise RuntimeError("PostgreSQL 테스트에는 PARKING_RADAR_TEST_DATABASE=1이 필요합니다.")
        engine, _session_factory = create_engine_and_session_factory(database_url)

        async def reset_postgres() -> None:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "TRUNCATE TABLE bus_terminal_references, ferry_ship_type_references, ferry_terminal_references, "
                        "ferry_ports, rail_station_references, rest_area_references, "
                        "fuel_price_snapshots, highway_incident_snapshots, "
                        "highway_traffic_five_minute_statistics, highway_traffic_snapshots, "
                        "transport_collection_states, raw_api_responses, "
                        "parking_snapshots, parking_fee_rules, analytics_caches, collection_runs, "
                        "fuel_stations, parking_lots, airports RESTART IDENTITY CASCADE"
                    )
                )
            await engine.dispose()

        asyncio.run(reset_postgres())
    return Settings(
        database_url=database_url,
        seed_sample_data=True,
        enable_scheduler=False,
        manual_collect_enabled=True,
        collect_interval_seconds=300,
        manual_collect_min_interval_seconds=300,
        data_go_kr_service_key=None,
        use_sample_client_when_no_key=True,
        airport_codes_csv="GMP,PUS,CJU",
        cors_origins_csv="http://localhost:3000",
    )


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    app = create_app(test_settings)
    with TestClient(app) as test_client:
        yield test_client
