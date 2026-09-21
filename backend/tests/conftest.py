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
    database_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not database_url:
        database_url = f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}"
    if database_url.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://")):
        os.environ["PARKING_RADAR_TEST_DATABASE"] = "1"
        engine, _session_factory = create_engine_and_session_factory(database_url)

        async def reset_postgres() -> None:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "TRUNCATE TABLE ferry_ship_type_references, ferry_terminal_references, "
                        "ferry_ports, rail_station_references, "
                        "fuel_price_snapshots, highway_incident_snapshots, "
                        "highway_traffic_snapshots, transport_collection_states, raw_api_responses, "
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
