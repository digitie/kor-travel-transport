from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import ALEMBIC_HEAD
from app.main import create_app
from app.models import Base


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
        "ix_highway_traffic_statistics_observed",
        "ix_highway_traffic_statistics_route_observed",
        "ix_highway_incidents_observed",
        "ix_highway_incidents_statistics_observed",
        "ix_fuel_stations_region",
        "ix_fuel_prices_product_observed",
        "ix_fuel_prices_statistics_collected",
        "ix_transport_collection_states_next_due",
    } <= index_names


def test_postgresql_schema_guard_tracks_alembic_head() -> None:
    """새 migration이 runtime schema guard와 분리되지 않게 한다."""
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))

    assert ScriptDirectory.from_config(config).get_current_head() == ALEMBIC_HEAD


def test_alembic_history_keeps_the_deployed_rest_area_revision() -> None:
    """운영 DB에 적용된 0011을 잃으면 다음 배포의 Alembic 시작 자체가 실패한다."""
    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    script = ScriptDirectory.from_config(config)

    deployed_revision = script.get_revision("0011_rest_area_references")
    head_revision = script.get_revision(ALEMBIC_HEAD)

    assert deployed_revision is not None
    assert head_revision is not None
    # 신규 migration이 여러 개 이어져도, 운영 DB의 0011이 현재 head의 조상으로
    # 남아 있어야 upgrade가 가능한 계보가 된다.
    assert deployed_revision.revision in {
        revision.revision for revision in script.iterate_revisions(ALEMBIC_HEAD, "base")
    }
    assert "rest_area_references" in Base.metadata.tables


def test_committed_openapi_schema_includes_bus_routes_and_runtime_errors() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
    paths = json.loads(schema_path.read_text(encoding="utf-8"))["paths"]

    assert "/v1/transport/bus/terminals" in paths
    assert "/v1/transport/bus/timetable" in paths
    responses = paths["/v1/transport/bus/timetable"]["get"]["responses"]
    for code in ("404", "429", "502", "503"):
        assert responses[code]["content"]["application/problem+json"]["schema"] == {
            "$ref": "#/components/schemas/ProblemDetails"
        }
