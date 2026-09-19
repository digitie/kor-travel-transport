from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def build_settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        **{
            "database_url": f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}",
            "seed_sample_data": True,
            "enable_scheduler": False,
            "manual_collect_enabled": True,
            "collect_interval_seconds": 300,
            "manual_collect_min_interval_seconds": 300,
            "data_go_kr_service_key": None,
            "use_sample_client_when_no_key": True,
            "airport_codes_csv": "GMP,PUS,CJU",
            "cors_origins_csv": "http://localhost:3000",
            **overrides,
        }
    )


def test_sample_seed_runs_in_sample_mode(tmp_path: Path) -> None:
    settings = build_settings(tmp_path)

    with patch("app.main.seed_sample_database", new=AsyncMock()) as seed_mock:
        with TestClient(create_app(settings)):
            pass

    seed_mock.assert_awaited_once()


def test_sample_seed_is_skipped_in_live_mode(tmp_path: Path) -> None:
    settings = build_settings(
        tmp_path,
        data_go_kr_service_key="test-key",
        use_sample_client_when_no_key=False,
    )

    with patch("app.main.seed_sample_database", new=AsyncMock()) as seed_mock:
        with TestClient(create_app(settings)):
            pass

    seed_mock.assert_not_awaited()


def test_database_startup_creates_query_indexes(tmp_path: Path) -> None:
    database_path = tmp_path / "test.sqlite3"
    settings = build_settings(tmp_path, database_url=f"sqlite+aiosqlite:///{database_path}")

    with TestClient(create_app(settings)):
        pass

    with sqlite3.connect(database_path) as connection:
        index_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }

    assert {
        "ix_parking_snapshots_airport_lot_observed",
        "ix_parking_snapshots_airport_lot_observed_desc",
        "ix_parking_snapshots_collected_at",
        "ix_parking_snapshots_collection_run_id",
        "ix_raw_api_responses_collection_run_id",
        "ix_highway_traffic_observed",
        "ix_highway_incidents_observed",
        "ix_fuel_stations_region",
        "ix_fuel_prices_product_observed",
        "ix_transport_collection_states_next_due",
    } <= index_names
