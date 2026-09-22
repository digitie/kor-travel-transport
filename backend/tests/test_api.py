from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.main import create_app
from kric import KricRateLimitError
from app.models import AnalyticsCache, Airport, CollectionRun, FerryPort, FuelPriceSnapshot, FuelStation, ParkingLot, ParkingSnapshot, RailStationReference


def assert_is_utc_iso(value: str | None) -> None:
    assert value is not None
    assert value.endswith("Z") or value.endswith("+00:00")


def build_client(tmp_path: Path, *, raise_server_exceptions: bool = True, **overrides) -> TestClient:
    settings = Settings(
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
    app = create_app(settings)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


async def insert_collection_run(
    client: TestClient,
    *,
    status: str,
    trigger: str,
    error_message: str | None,
    started_at: datetime | None = None,
) -> None:
    session_factory = client.app.state.session_factory
    started_at = started_at or (now_utc() - timedelta(minutes=1))
    finished_at = started_at + timedelta(seconds=1)
    async with session_factory() as session:
        session.add(
            CollectionRun(
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                trigger=trigger,
                error_message=error_message,
            )
        )
        await session.commit()


async def insert_isolated_snapshot(client: TestClient, *, airport_code: str, observed_at: datetime) -> None:
    """Adds one extra snapshot at an exact timestamp, for tests that need a snapshot at a
    controlled instant (e.g. to create a deliberate trailing gap before a range's end)."""
    session_factory = client.app.state.session_factory
    async with session_factory() as session:
        airport = await session.scalar(select(Airport).where(Airport.code == airport_code))
        assert airport is not None
        lot = await session.scalar(select(ParkingLot).where(ParkingLot.airport_id == airport.id))
        assert lot is not None
        session.add(
            ParkingSnapshot(
                airport_id=airport.id,
                parking_lot_id=lot.id,
                source="kac_parking",
                observed_at=observed_at,
                collected_at=observed_at,
                occupied_spaces=10,
                total_spaces=100,
                available_spaces=90,
            )
        )
        await session.commit()


async def replace_default_timeseries_cache(client: TestClient) -> None:
    session_factory = client.app.state.session_factory
    async with session_factory() as session:
        cached = await session.scalar(
            select(AnalyticsCache).where(
                AnalyticsCache.metric == "timeseries",
                AnalyticsCache.scope_key == "GMP:*",
                AnalyticsCache.days == 7,
                AnalyticsCache.interval_minutes == 10,
                AnalyticsCache.future_hours == 0,
            )
        )
        assert cached is not None
        cached.payload_json = {
            "generated_at": "2030-01-01T00:00:00+00:00",
            "airport_code": "GMP",
            "parking_lot_id": None,
            "days": 7,
            "interval_minutes": 10,
            "future_hours": 0,
            "items": [],
        }
        await session.commit()


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["seeded"] is True
    assert payload["release_sha"] == "unknown"


def test_transport_place_features_exposes_saved_map_markers_and_rejects_unknown_kind(client) -> None:
    async def seed() -> None:
        now = now_utc()
        async with client.app.state.session_factory() as session:
            fuel = FuelStation(source="opinet", identity_key="station-1", source_station_id="S1", name="테스트주유소", brand_code="SK", brand_name="SK에너지", phone=None, address="서울 테스트로", business_number=None, cb_code=None, station_type="A", query_level="sigungu", sido_value="11", sido_name="서울", sigungu_value="110", sigungu_name="테스트", dong_value=None, dong_name=None, katec_x=None, katec_y=None, longitude=127.1, latitude=37.5, source_kinds=[], is_illegal=None, is_self=None, is_24h=None, is_kpetro=None, is_electronic=None, is_good=None, is_good_strong=None, is_region_franchise=None, has_carwash=None, has_maintenance=None, has_cvs=None, cs_yn=None, discount_info=None, save_event_info=None, representative_event_info=None, on_event_info=None, other_business_info=None, first_seen_at=now, last_seen_at=now, raw_item_json=None)
            session.add(fuel)
            await session.flush()
            session.add(FuelPriceSnapshot(fuel_station_id=fuel.id, source="opinet", product_code="B027", price=1700, provider_updated_at=now, observed_at=now, collected_at=now, raw_item_json=None, collection_run_id=None))
            session.add(RailStationReference(source="kric_public_file", identity_key="line|101|테스트역", rail_operator_name="테스트운영사", operating_line_name="테스트선", station_type=None, station_number="101", station_name="테스트역", english_name=None, longitude=127.2, latitude=37.6, lot_address=None, road_address="서울 테스트길", station_phone_number=None, data_reference_date=None, first_seen_at=now, last_seen_at=now, raw_item_json=None))
            session.add(FerryPort(source="data_go_kr_maritime", port_id="P1", port_name="테스트항", latitude=129.1, longitude=35.1, location_source="data_go_kr_port_guideline", location_point_count=2, first_seen_at=now, last_seen_at=now, raw_item_json=None))
            await session.commit()
    asyncio.run(seed())

    response = client.get("/v1/transport/features/places")
    assert response.status_code == 200
    payload = response.json()
    by_kind = {item["kind"]: item for item in payload["items"]}
    assert payload["total"] == 3
    assert payload["truncated"] is False
    assert by_kind["fuel_station"]["latest_price"] == 1700
    assert by_kind["rail_station"]["line_names"] == ["테스트선"]
    assert by_kind["ferry_port"]["location_point_count"] == 2
    bounded = client.get("/v1/transport/features/places?kind=fuel_station&min_longitude=127.0&min_latitude=37.4&max_longitude=127.15&max_latitude=37.55")
    assert bounded.status_code == 200
    assert bounded.json()["total"] == 1
    assert [item["name"] for item in bounded.json()["items"]] == ["테스트주유소"]
    assert client.get("/v1/transport/features/places?kind=unknown").status_code == 422
    assert client.get("/v1/transport/features/places?kind=fuel_station&min_longitude=127.0").status_code == 422
    assert client.get("/v1/transport/ports/P1/timetable").status_code == 503
    assert client.get("/v1/transport/ports/P1/timetable?date=2000-01-01").status_code == 422


def test_transport_port_timetable_caches_one_live_provider_call(tmp_path: Path) -> None:
    class FakeMaritimeClient:
        calls = 0

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get_domestic_ship_operations(self, *, departure_port_id: str, departure_date: date):
            type(self).calls += 1
            assert departure_port_id == "P1"
            assert departure_date == now_utc().astimezone(ZoneInfo("Asia/Seoul")).date()
            return (
                SimpleNamespace(
                    vessel_name="테스트호",
                    departure_port_name="테스트항",
                    arrival_port_name="도착항",
                    departure_planned_time="09:00",
                    arrival_planned_time="10:00",
                    fare="10000",
                ),
            )

    with build_client(tmp_path, data_go_kr_service_key="test-key") as client:
        async def seed() -> None:
            now = now_utc()
            async with client.app.state.session_factory() as session:
                session.add(FerryPort(source="data_go_kr_maritime", port_id="P1", port_name="테스트항", latitude=129.1, longitude=35.1, location_source="data_go_kr_port_guideline", location_point_count=1, first_seen_at=now, last_seen_at=now, raw_item_json=None))
                await session.commit()

        asyncio.run(seed())
        with patch("app.main.DataGoKrMaritimeClient", FakeMaritimeClient):
            first = client.get("/v1/transport/ports/P1/timetable")
            second = client.get("/v1/transport/ports/P1/timetable")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["items"] == [{"vessel_name": "테스트호", "departure_port_name": "테스트항", "arrival_port_name": "도착항", "departure_planned_time": "09:00", "arrival_planned_time": "10:00", "fare": "10000"}]
    assert FakeMaritimeClient.calls == 1


def test_transport_port_timetable_rate_limit_uses_provider_wide_backoff(tmp_path: Path) -> None:
    class RateLimitedMaritimeClient:
        calls: list[str] = []

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get_domestic_ship_operations(self, *, departure_port_id: str, **_kwargs):
            type(self).calls.append(departure_port_id)
            if departure_port_id == "P1":
                return (
                    SimpleNamespace(
                        vessel_name="테스트호",
                        departure_port_name="테스트항",
                        arrival_port_name="도착항",
                        departure_planned_time="09:00",
                        arrival_planned_time="10:00",
                        fare="10000",
                    ),
                )
            raise KricRateLimitError("provider quota reached")

    with build_client(tmp_path, data_go_kr_service_key="test-key", upstream_rate_limit_backoff_seconds=60) as client:
        async def seed() -> None:
            now = now_utc()
            async with client.app.state.session_factory() as session:
                session.add(FerryPort(source="data_go_kr_maritime", port_id="P1", port_name="테스트항", latitude=129.1, longitude=35.1, location_source="data_go_kr_port_guideline", location_point_count=1, first_seen_at=now, last_seen_at=now, raw_item_json=None))
                session.add(FerryPort(source="data_go_kr_maritime", port_id="P2", port_name="제한항", latitude=129.2, longitude=35.2, location_source="data_go_kr_port_guideline", location_point_count=1, first_seen_at=now, last_seen_at=now, raw_item_json=None))
                await session.commit()

        asyncio.run(seed())
        with patch("app.main.DataGoKrMaritimeClient", RateLimitedMaritimeClient):
            cached_before_limit = client.get("/v1/transport/ports/P1/timetable")
            client.app.state.ferry_timetable_last_provider_call_at = now_utc() - timedelta(seconds=61)
            first = client.get("/v1/transport/ports/P2/timetable")
            second = client.get("/v1/transport/ports/P1/timetable")

    assert cached_before_limit.status_code == 200
    assert first.status_code == 429
    assert second.status_code == 200
    assert first.headers["retry-after"]
    assert RateLimitedMaritimeClient.calls == ["P1", "P2"]


def test_transport_port_timetable_applies_provider_wide_minimum_interval(tmp_path: Path) -> None:
    class FakeMaritimeClient:
        calls = 0

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def get_domestic_ship_operations(self, **_kwargs):
            type(self).calls += 1
            return ()

    with build_client(tmp_path, data_go_kr_service_key="test-key", ferry_timetable_min_interval_seconds=30) as client:
        async def seed() -> None:
            now = now_utc()
            async with client.app.state.session_factory() as session:
                for port_id in ("P1", "P2"):
                    session.add(FerryPort(source="data_go_kr_maritime", port_id=port_id, port_name=port_id, latitude=35.1, longitude=129.1, location_source=None, location_point_count=1, first_seen_at=now, last_seen_at=now, raw_item_json=None))
                await session.commit()

        asyncio.run(seed())
        with patch("app.main.DataGoKrMaritimeClient", FakeMaritimeClient):
            first = client.get("/v1/transport/ports/P1/timetable")
            second = client.get("/v1/transport/ports/P2/timetable")

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) >= 1
    assert FakeMaritimeClient.calls == 1


def test_security_headers(client) -> None:
    response = client.get("/health", headers={"x-forwarded-proto": "https"})
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_api_docs_can_be_disabled(tmp_path: Path) -> None:
    with build_client(tmp_path, enable_api_docs=False) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_openapi_declares_rfc7807_validation_errors(tmp_path: Path) -> None:
    with build_client(tmp_path, enable_api_docs=True) as client:
        schema = client.get("/openapi.json").json()
        response = client.get("/v1/transport/highways/traffic", params={"days": 0})

    validation_response = schema["paths"]["/v1/transport/highways/traffic"]["get"]["responses"]["422"]
    assert validation_response["content"]["application/problem+json"]["schema"] == {
        "$ref": "#/components/schemas/ProblemDetails"
    }
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 422
    collect_responses = schema["paths"]["/v1/admin/collect"]["post"]["responses"]
    for code in ("404", "409", "429", "502"):
        assert collect_responses[code]["content"]["application/problem+json"]["schema"] == {
            "$ref": "#/components/schemas/ProblemDetails"
        }


def test_unhandled_exception_returns_sanitized_problem_json(tmp_path: Path) -> None:
    test_client = build_client(tmp_path, raise_server_exceptions=False)

    @test_client.app.get("/v1/test-unhandled-error")
    async def unhandled_error() -> None:
        raise RuntimeError("synthetic-secret exception-body SELECT private_column FROM private_table")

    with test_client as client:
        response = client.get("/v1/test-unhandled-error?key=synthetic-query-secret")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "서버 내부 오류가 발생했습니다.",
        "instance": "/v1/test-unhandled-error",
    }
    for private_value in ("synthetic-secret", "synthetic-query-secret", "exception-body", "SELECT"):
        assert private_value not in response.text


def test_transport_database_error_returns_sanitized_problem_json(tmp_path: Path) -> None:
    error = OperationalError(
        "SELECT private_column FROM highway_traffic_snapshots WHERE api_key = :key",
        {"key": "synthetic-db-secret"},
        RuntimeError("synthetic-driver-error postgresql://private-user:private-password@private-host"),
    )
    with build_client(tmp_path, raise_server_exceptions=False) as client:
        with patch("app.main.AsyncSession.execute", new=AsyncMock(side_effect=error)) as execute:
            response = client.get("/v1/transport/highways/traffic?route_no=0010")
            execute.assert_awaited_once()
        assert client.get("/v1/transport/highways/traffic").status_code == 200

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "about:blank",
        "title": "Internal Server Error",
        "status": 500,
        "detail": "서버 내부 오류가 발생했습니다.",
        "instance": "/v1/transport/highways/traffic",
    }
    for private_value in (
        "SELECT", "private_column", "highway_traffic_snapshots", "synthetic-db-secret",
        "synthetic-driver-error", "private-password", "OperationalError", "RuntimeError",
    ):
        assert private_value not in response.text


def test_openapi_declares_rfc7807_internal_server_errors(tmp_path: Path) -> None:
    with build_client(tmp_path, enable_api_docs=True) as client:
        schema = client.get("/openapi.json").json()

    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            error_response = operation["responses"]["500"]
            assert error_response["content"] == {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ProblemDetails"}
                }
            }


def test_trusted_host_rejects_unexpected_hosts(tmp_path: Path) -> None:
    with build_client(tmp_path, trusted_hosts_csv="parking.local") as client:
        rejected = client.get("/health", headers={"host": "unexpected.local"})
        accepted = client.get("/health", headers={"host": "parking.local"})

    assert rejected.status_code == 400
    assert accepted.status_code == 200


def test_airports(client) -> None:
    response = client.get("/v1/airports")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) >= 4

    airports = {airport["code"]: airport for airport in payload}
    assert len(airports["PUS"]["parking_lots"]) == 3
    assert len(airports["GMP"]["parking_lots"]) >= 4
    assert any(lot["name"].startswith("P1") for lot in airports["PUS"]["parking_lots"])


def test_dashboard_aggregate_endpoints(client) -> None:
    bootstrap = client.get("/v1/dashboard/bootstrap")
    assert bootstrap.status_code == 200
    bootstrap_payload = bootstrap.json()
    assert bootstrap_payload["airports"]
    assert bootstrap_payload["current"]["items"]
    assert bootstrap_payload["collector"]["latest_snapshot_observed_at"]
    assert "sentence" in bootstrap_payload["holidays"]

    analytics = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
    assert analytics.status_code == 200
    analytics_payload = analytics.json()
    assert analytics_payload["time_series"]["items"]
    assert analytics_payload["weekday_hour_patterns"]
    assert "threshold_events" in analytics_payload


def test_current_and_analytics(client) -> None:
    current = client.get("/v1/parking/current", params={"airport_code": "GMP"})
    assert current.status_code == 200
    current_payload = current.json()
    assert current_payload["items"]
    assert_is_utc_iso(current_payload["generated_at"])
    assert_is_utc_iso(current_payload["items"][0]["observed_at"])
    assert_is_utc_iso(current_payload["items"][0]["collected_at"])

    hourly = client.get("/v1/parking/analytics/by-hour", params={"airport_code": "GMP"})
    weekday = client.get("/v1/parking/analytics/by-weekday", params={"airport_code": "GMP"})
    weekday_hour = client.get("/v1/parking/analytics/by-weekday-hour", params={"airport_code": "GMP"})
    timeseries = client.get(
        "/v1/parking/analytics/timeseries",
        params={"airport_code": "GMP", "days": 7},
    )
    holiday_summary = client.get(
        "/v1/holidays/summary",
        params={"start_date": "2026-05-01", "end_date": "2026-05-31"},
    )
    holiday_patterns = client.get("/v1/parking/analytics/holiday-patterns", params={"airport_code": "GMP"})
    thresholds = client.get("/v1/parking/analytics/threshold-events", params={"airport_code": "GMP"})
    threshold_insights = client.get(
        "/v1/parking/analytics/threshold-insights",
        params={"airport_code": "GMP", "days": 21, "interval_minutes": 10},
    )
    assert hourly.status_code == 200
    assert weekday.status_code == 200
    assert weekday_hour.status_code == 200
    assert timeseries.status_code == 200
    assert holiday_summary.status_code == 200
    assert holiday_patterns.status_code == 200
    assert thresholds.status_code == 200
    assert threshold_insights.status_code == 200
    assert hourly.json()
    assert weekday.json()
    weekday_hour_payload = weekday_hour.json()
    assert weekday_hour_payload
    assert weekday_hour_payload[0]["hourly_buckets"]
    assert len(weekday_hour_payload[0]["hourly_buckets"]) == 24

    timeseries_payload = timeseries.json()
    assert_is_utc_iso(timeseries_payload["generated_at"])
    assert timeseries_payload["days"] == 7
    assert timeseries_payload["interval_minutes"] == 10
    assert timeseries_payload["future_hours"] == 0
    assert len(timeseries_payload["items"]) == 1008
    assert max(point["lot_observations"] for point in timeseries_payload["items"]) >= 1
    assert_is_utc_iso(timeseries_payload["items"][0]["bucket_at"])
    latest_observed_point = next(
        point for point in reversed(timeseries_payload["items"]) if point["lot_observations"] > 0
    )
    assert latest_observed_point["available_spaces"] == sum(
        item["available_spaces"] for item in current_payload["items"]
    )
    assert timeseries_payload["items"][-1]["available_spaces"] == sum(
        item["available_spaces"] for item in current_payload["items"]
    )

    holiday_summary_payload = holiday_summary.json()
    assert holiday_summary_payload["status"] == "sample"
    assert "5/5 (화) 어린이날" in holiday_summary_payload["sentence"]
    assert any(item["name"] == "부처님오신 날" for item in holiday_summary_payload["items"])

    holiday_patterns_payload = holiday_patterns.json()
    assert holiday_patterns_payload["items"]
    assert len(holiday_patterns_payload["items"][0]["hourly_buckets"]) == 24
    assert {item["day_type"] for item in holiday_patterns_payload["items"]} & {"saturday", "sunday"}

    threshold_payload = thresholds.json()
    assert threshold_payload
    assert_is_utc_iso(threshold_payload[0]["crossed_at"])

    threshold_insights_payload = threshold_insights.json()
    assert_is_utc_iso(threshold_insights_payload["generated_at"])
    assert threshold_insights_payload["interval_minutes"] == 10
    assert len(threshold_insights_payload["weekday_items"]) == 14
    assert "sample_count" in threshold_insights_payload["weekday_items"][0]


def test_default_time_series_uses_precomputed_cache(client) -> None:
    asyncio.run(replace_default_timeseries_cache(client))

    response = client.get(
        "/v1/parking/analytics/timeseries",
        params={"airport_code": "GMP", "days": 7},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["generated_at"].startswith("2030-01-01T00:00:00")
    assert payload["items"] == []


def test_time_series_explicit_date_range_returns_data(client) -> None:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    start = today - timedelta(days=2)

    response = client.get(
        "/v1/parking/analytics/timeseries",
        params={"airport_code": "GMP", "start_date": start.isoformat(), "end_date": today.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["start_date"] == start.isoformat()
    assert payload["end_date"] == today.isoformat()
    assert payload["days"] == 3
    assert payload["future_hours"] == 0
    assert payload["items"]
    assert max(point["lot_observations"] for point in payload["items"]) >= 1


def test_time_series_explicit_date_range_with_no_data_returns_empty_items(client) -> None:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    start = today + timedelta(days=30)
    end = today + timedelta(days=32)

    response = client.get(
        "/v1/parking/analytics/timeseries",
        params={"airport_code": "GMP", "start_date": start.isoformat(), "end_date": end.isoformat()},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []


def test_time_series_rejects_reversed_date_range(client) -> None:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    response = client.get(
        "/v1/parking/analytics/timeseries",
        params={
            "airport_code": "GMP",
            "start_date": today.isoformat(),
            "end_date": (today - timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 400
    assert "end_date" in response.json()["detail"]


def test_time_series_requires_both_dates_together(client) -> None:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    response = client.get(
        "/v1/parking/analytics/timeseries",
        params={"airport_code": "GMP", "start_date": today.isoformat()},
    )
    assert response.status_code == 400
    assert "함께 지정" in response.json()["detail"]


def test_time_series_rejects_range_exceeding_cap(client) -> None:
    end = date(2026, 6, 1)
    start = end - timedelta(days=120)
    response = client.get(
        "/v1/parking/analytics/timeseries",
        params={"airport_code": "GMP", "start_date": start.isoformat(), "end_date": end.isoformat()},
    )
    assert response.status_code == 400
    assert "90일" in response.json()["detail"]


def test_time_series_rejects_unscoped_date_range(client) -> None:
    response = client.get(
        "/v1/parking/analytics/timeseries",
        params={"start_date": "2026-05-01", "end_date": "2026-05-07"},
    )
    assert response.status_code == 400
    assert "airport_code" in response.json()["detail"]


def test_time_series_rejects_invalid_date_format(client) -> None:
    response = client.get(
        "/v1/parking/analytics/timeseries",
        params={"airport_code": "GMP", "start_date": "2026/06/01", "end_date": "2026-06-02"},
    )
    assert response.status_code == 400
    assert "YYYY-MM-DD" in response.json()["detail"]


def test_time_series_range_stays_pinned_to_requested_end_despite_trailing_gap(client) -> None:
    # Isolated far-past date so this test's single snapshot never overlaps the sample
    # fixture's own "last 7 days ending now" data.
    asyncio.run(
        insert_isolated_snapshot(
            client,
            airport_code="GMP",
            observed_at=datetime(2026, 1, 1, 1, 0, tzinfo=ZoneInfo("UTC")),
        )
    )

    response = client.get(
        "/v1/parking/analytics/timeseries",
        params={
            "airport_code": "GMP",
            "start_date": "2026-01-01",
            "end_date": "2026-01-05",
            "interval_minutes": 60,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["start_date"] == "2026-01-01"
    assert payload["end_date"] == "2026-01-05"
    assert payload["items"]

    first_bucket = datetime.fromisoformat(payload["items"][0]["bucket_at"].replace("Z", "+00:00"))
    last_bucket = datetime.fromisoformat(payload["items"][-1]["bucket_at"].replace("Z", "+00:00"))
    range_start_seoul = datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    range_end_exclusive_seoul = datetime(2026, 1, 6, 0, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    # The window must stay pinned to the *requested* range even though the only real
    # snapshot is on day 1 - not silently shift back to wherever that snapshot happens
    # to be (hostile-review P0: build_time_series previously anchored on the latest
    # *observed* snapshot instead of the requested end_date).
    assert first_bucket >= range_start_seoul
    assert last_bucket < range_end_exclusive_seoul
    # The tail (days 2-5, after the only snapshot) must be honestly reported as
    # no-observation, not fabricated and not silently dropped from the response.
    assert any(point["lot_observations"] == 0 for point in payload["items"])


def test_collector_status_reports_earliest_snapshot(client) -> None:
    response = client.get("/v1/admin/collector-status")
    assert response.status_code == 200
    payload = response.json()
    assert_is_utc_iso(payload["earliest_snapshot_observed_at"])
    assert_is_utc_iso(payload["latest_snapshot_observed_at"])
    assert payload["earliest_snapshot_observed_at"] <= payload["latest_snapshot_observed_at"]


def test_flight_status_returns_sample_markers(client) -> None:
    response = client.get("/v1/flights/status", params={"airport_code": "GMP", "local_date": "2026-04-25"})
    assert response.status_code == 200
    payload = response.json()

    assert payload["airport_code"] == "GMP"
    assert payload["local_date"] == "2026-04-25"
    assert payload["status"] == "sample"
    assert payload["items"]
    assert {item["direction"] for item in payload["items"]} >= {"departure", "arrival"}
    assert_is_utc_iso(payload["generated_at"])
    assert_is_utc_iso(payload["items"][0]["marker_at"])
    assert payload["items"][0]["flight_number"]
    assert payload["items"][0]["origin_airport"]
    assert payload["items"][0]["destination_airport"]


def test_flight_status_rejects_invalid_local_date(client) -> None:
    response = client.get("/v1/flights/status", params={"airport_code": "GMP", "local_date": "2026/04/25"})
    assert response.status_code == 400
    assert "YYYY-MM-DD" in response.json()["detail"]


def test_fee_calculation(client) -> None:
    entry = datetime(2026, 4, 24, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    exit_at = entry + timedelta(hours=2)
    response = client.post(
        "/v1/fees/calculate",
        json={
            "airport_code": "GMP",
            "vehicle_size": "small",
            "entry_at": entry.isoformat(),
            "exit_at": exit_at.isoformat(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["supported"] is True
    assert payload["total_fee"] == 3000


def test_incheon_fee_calculation_is_supported(client) -> None:
    entry = datetime(2026, 4, 24, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    response = client.post(
        "/v1/fees/calculate",
        json={
            "airport_code": "ICN",
            "vehicle_size": "small",
            "entry_at": entry.isoformat(),
            "exit_at": (entry + timedelta(hours=1)).isoformat(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["supported"] is True
    assert payload["total_fee"] == 1000


def test_admin_collect_returns_cooldown_error(tmp_path: Path) -> None:
    with build_client(tmp_path, manual_collect_min_interval_seconds=999999999) as client:
        response = client.post("/v1/admin/collect")
        assert response.status_code == 409
        assert response.json()["detail"]


def test_admin_collect_is_disabled_without_explicit_enablement(tmp_path: Path) -> None:
    with build_client(tmp_path, manual_collect_enabled=False) as client:
        response = client.post("/v1/admin/collect")

    assert response.status_code == 404


def test_admin_restore_requires_a_scheduler_maintenance_window(tmp_path: Path) -> None:
    with build_client(tmp_path, enable_scheduler=True, seed_sample_data=False) as client:
        response = client.post(
            "/v1/admin/backups/restore",
            files={"file": ("restore.dump", b"dump", "application/octet-stream")},
        )

    assert response.status_code == 409
    assert "scheduler" in response.json()["detail"]


def test_admin_collect_succeeds_when_cooldown_is_disabled(tmp_path: Path) -> None:
    with build_client(tmp_path, manual_collect_min_interval_seconds=0) as client:
        response = client.post("/v1/admin/collect")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] in {"success", "partial_success"}
        assert payload["client_mode"] == "sample"
        assert payload["raw_response_count"] >= 1


def test_admin_collector_status(client) -> None:
    response = client.get("/v1/admin/collector-status")
    assert response.status_code == 200
    payload = response.json()

    assert payload["scheduler_enabled"] is False
    assert payload["collect_interval_seconds"] == 300
    assert payload["manual_collect_enabled"] is True
    assert payload["manual_collect_min_interval_seconds"] == 300
    assert payload["client_mode"] == "sample"
    assert payload["enabled_sources"] == ["kac_parking", "incheon_parking"]
    assert payload["data_go_kr_service_key_configured"] is False
    assert payload["supported_airport_codes"] == ["GMP", "PUS", "CJU"]
    assert_is_utc_iso(payload["latest_snapshot_observed_at"])
    assert_is_utc_iso(payload["latest_snapshot_collected_at"])
    assert isinstance(payload["manual_collect_blocked"], bool)
    if payload["manual_collect_available_at"] is not None:
        assert_is_utc_iso(payload["manual_collect_available_at"])
    assert payload["upstream_rate_limited"] is False
    assert payload["upstream_rate_limited_until"] is None
    assert payload["recent_runs"] == []


def test_admin_collector_status_reports_upstream_rate_limit(tmp_path: Path) -> None:
    with build_client(
        tmp_path,
        data_go_kr_service_key="test-key",
        use_sample_client_when_no_key=False,
        seed_sample_data=False,
    ) as client:
        asyncio.run(
            insert_collection_run(
                client,
                status="failed",
                trigger="scheduler",
                error_message="kac_parking API error 99: LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.",
            )
        )

        response = client.get("/v1/admin/collector-status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["upstream_rate_limited"] is True
        assert_is_utc_iso(payload["upstream_rate_limited_until"])


def test_admin_collect_returns_upstream_rate_limit_error(tmp_path: Path) -> None:
    with build_client(
        tmp_path,
        data_go_kr_service_key="test-key",
        use_sample_client_when_no_key=False,
        seed_sample_data=False,
        enable_incheon_collection=False,
        enable_incheon_fee_collection=False,
    ) as client:
        asyncio.run(
            insert_collection_run(
                client,
                status="failed",
                trigger="scheduler",
                error_message="kac_parking API error 99: LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.",
            )
        )

        response = client.post("/v1/admin/collect")
        assert response.status_code == 429
        assert "공공데이터 API 요청 한도" in response.json()["detail"]


def test_admin_collect_continues_incheon_when_kac_rate_limited(tmp_path: Path) -> None:
    with build_client(
        tmp_path,
        seed_sample_data=False,
        enable_incheon_collection=True,
        enable_incheon_fee_collection=False,
    ) as client:
        service = client.app.state.collection_service
        blocked_state = type(
            "State",
            (),
            {
                "is_blocked": True,
                "blocked_until": now_utc() + timedelta(hours=1),
                "source": "kac_parking",
                "error_message": "kac_parking API error 99: LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.",
            },
        )()

        with patch.object(
            service,
            "get_upstream_rate_limit_state",
            new=AsyncMock(return_value=blocked_state),
        ):
            response = client.post("/v1/admin/collect")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "partial_success"
        assert payload["raw_response_count"] == 1
        assert payload["snapshot_count"] >= 1
        assert "LIMITED NUMBER OF SERVICE REQUESTS" in payload["errors"][0]


def test_admin_collector_status_does_not_extend_rate_limit_from_skipped_runs(tmp_path: Path) -> None:
    with build_client(
        tmp_path,
        data_go_kr_service_key="test-key",
        use_sample_client_when_no_key=False,
        seed_sample_data=False,
    ) as client:
        expired_failed_at = now_utc() - timedelta(days=2)
        recent_skipped_at = now_utc() - timedelta(minutes=5)
        asyncio.run(
            insert_collection_run(
                client,
                status="failed",
                trigger="scheduler",
                error_message="kac_parking API error 99: LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR.",
                started_at=expired_failed_at,
            )
        )
        asyncio.run(
            insert_collection_run(
                client,
                status="skipped",
                trigger="scheduler",
                error_message=(
                    "kac_parking upstream rate limit active until 2099-01-01T00:05:00Z: "
                    "kac_parking API error 99: LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR."
                ),
                started_at=recent_skipped_at,
            )
        )

        response = client.get("/v1/admin/collector-status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["upstream_rate_limited"] is False
        assert payload["upstream_rate_limited_until"] is None


def test_admin_collect_raises_429_when_collection_fails_due_to_rate_limit(tmp_path: Path) -> None:
    with build_client(
        tmp_path,
        data_go_kr_service_key="test-key",
        use_sample_client_when_no_key=False,
        seed_sample_data=False,
    ) as client:
        service = client.app.state.collection_service
        unblocked_state = type(
            "State",
            (),
            {
                "is_blocked": False,
                "blocked_until": None,
            },
        )()
        blocked_state = type(
            "State",
            (),
            {
                "is_blocked": True,
                "blocked_until": now_utc() + timedelta(hours=1),
            },
        )()
        with patch.object(
            service,
            "collect",
            new=AsyncMock(
                return_value={
                    "collection_run_id": 1,
                    "status": "failed",
                    "client_mode": "live",
                    "raw_response_count": 1,
                    "snapshot_count": 0,
                    "fee_rule_count": 0,
                    "errors": ["kac_parking API error 99: LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR."],
                }
            ),
        ), patch.object(
            service,
            "get_upstream_rate_limit_state",
            new=AsyncMock(side_effect=[unblocked_state, blocked_state]),
        ):
            response = client.post("/v1/admin/collect")

        assert response.status_code == 429
        assert "공공데이터 API 요청 한도" in response.json()["detail"]
