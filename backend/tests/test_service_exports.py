"""내부 서비스 export `/v1/service/exports/*`와 휴게소 수집 (ADR-012)."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from krex import Incident, RestArea, RestAreaFuelPrice
from sqlalchemy import select

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.dagster.definitions import definitions
from app.main import create_app
from app.models import FuelPriceSnapshot, FuelStation, TransportCollectionState
from app.services.rest_area_collection import (
    REST_AREA_FUEL_SOURCE,
    REST_AREA_SOURCE,
    RestAreaCollectionService,
    rest_area_identity,
)
from app.services.transport_collection import (
    INCIDENT_SOURCE,
    OPINET_SOURCE,
    HighwayPayload,
    upsert_latest_fuel_prices,
)

TOKEN = "s" * 40
HEADERS = {"X-Kor-Travel-Transport-Service-Token": TOKEN}
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def export_client(test_settings: Settings):
    test_settings.transport_service_export_token = TOKEN
    test_settings.service_export_allowed_hosts_csv = "testserver"
    test_settings.trusted_hosts_csv = "testserver,pr-api.example.test"
    with TestClient(create_app(test_settings)) as client:
        yield client


def _run(client: TestClient, action):
    async def wrapper():
        async with client.app.state.session_factory() as session:
            result = await action(session)
            await session.commit()
            return result
    return asyncio.run(wrapper())


async def _set_state(session, source: str, **values) -> None:
    state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == source))
    if state is None:
        state = TransportCollectionState(source=source, updated_at=now_utc())
        session.add(state)
    for key, value in values.items():
        setattr(state, key, value)


@pytest.mark.parametrize("path", [
    "/v1/service/exports/fuel-stations",
    "/v1/service/exports/rest-areas",
    "/v1/service/exports/rest-area-fuel-prices",
    "/v1/service/exports/highway-incidents/active",
    "/v1/service/exports/airports",
])
def test_exports_hide_without_token_or_from_a_public_host(export_client: TestClient, path: str) -> None:
    assert export_client.get(path).status_code == 404
    assert export_client.get(path, headers={"X-Kor-Travel-Transport-Service-Token": "x" * 40}).status_code == 404
    # 토큰이 맞아도 외부 reverse proxy의 Host로 들어오면 닫힌다.
    public = export_client.get(path, headers={**HEADERS, "Host": "pr-api.example.test"})
    assert public.status_code == 404
    assert export_client.get(path, headers=HEADERS).status_code in {200, 503}


def test_exports_stay_closed_when_the_token_is_short(test_settings: Settings) -> None:
    test_settings.transport_service_export_token = "short"
    test_settings.service_export_allowed_hosts_csv = "testserver"
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/v1/service/exports/airports",
                              headers={"X-Kor-Travel-Transport-Service-Token": "short"})
    assert response.status_code == 404


def test_public_proxies_never_forward_service_exports() -> None:
    gateway = (REPO_ROOT / "deploy/transport-admin/api-gateway.conf.template").read_text(encoding="utf-8")
    proxy = (REPO_ROOT / "frontend/src/app/api/backend/[...path]/route.ts").read_text(encoding="utf-8")
    assert "service" not in gateway
    assert "service/" not in proxy and '"service' not in proxy


def test_fuel_station_export_pages_stable_ids_with_latest_prices(export_client: TestClient) -> None:
    async def seed(session) -> None:
        now = now_utc()
        for index, station_id in enumerate(["A0000001", "A0000002", None]):
            station = FuelStation(
                source=OPINET_SOURCE, identity_key=f"station:{station_id or index}", source_station_id=station_id,
                name=f"주유소{index}", query_level="sigungu", sido_value="11", sido_name="서울",
                sigungu_value="110", sigungu_name="종로", source_kinds=["station"], latitude=37.5,
                longitude=127.0, first_seen_at=now, last_seen_at=now, raw_item_json={"UNI_ID": station_id},
            )
            session.add(station)
            await session.flush()
            session.add(FuelPriceSnapshot(fuel_station_id=station.id, source=OPINET_SOURCE, product_code="B027",
                                          price=1700 + index, observed_at=now, collected_at=now))
        await session.flush()
        await upsert_latest_fuel_prices(session)
        await _set_state(session, OPINET_SOURCE, last_success_at=now)

    _run(export_client, seed)
    first = export_client.get("/v1/service/exports/fuel-stations", params={"limit": 1}, headers=HEADERS).json()
    assert first["has_more"] is True and first["collection"]["stale"] is False
    assert [item["natural_key"] for item in first["items"]] == ["A0000001"]
    assert first["items"][0]["prices"][0] == {**first["items"][0]["prices"][0], "product_code": "B027", "price": 1700.0}
    assert first["items"][0]["raw"] == {"UNI_ID": "A0000001"}
    second = export_client.get("/v1/service/exports/fuel-stations",
                               params={"limit": 1, "cursor": first["next_cursor"]}, headers=HEADERS).json()
    # 안정 ID가 없는 행(fallback identity)은 자연키가 될 수 없어 내보내지 않는다.
    assert [item["natural_key"] for item in second["items"]] == ["A0000002"]
    assert second["has_more"] is False and second["next_cursor"] is None
    bad = export_client.get("/v1/service/exports/fuel-stations", params={"cursor": "abc"}, headers=HEADERS)
    assert bad.status_code == 422


def _rest_area(name: str, *, lat: float = 36.9) -> RestArea:
    return RestArea(name=name, route_name="서해안고속도로", direction="목포방향", lat=lat, lon=126.8,
                    has_gas_station=True, has_lpg_station=False, has_ev_charger=True, phone_number="031-000-0000",
                    reference_date=date(2026, 9, 1), raw={"restAreaNm": name})


def _fuel(code: str, gasoline: int) -> RestAreaFuelPrice:
    return RestAreaFuelPrice(route_code="0150", service_area_code=code, route_name="서해안선", direction="목포",
                             oil_company="SK", has_lpg=False, service_area_name="행담도", phone_number=None,
                             gasoline_price=gasoline, diesel_price=1600, lpg_price=None,
                             raw={"serviceAreaCode": code, "gasolinePrice": f"{gasoline}원"})


class FakeKrex:
    def __init__(self, rest_areas, fuel) -> None:
        self.rest_areas, self.fuel = rest_areas, fuel
        self.restarea = self
        self.closed = False

    async def list_all(self, *, num_of_rows: int, page_no: int):
        return SimpleNamespace(items=tuple(self.rest_areas), total_count=len(self.rest_areas), num_of_rows=num_of_rows)

    async def fuel_prices(self, *, num_of_rows: int, page_no: int):
        return SimpleNamespace(items=tuple(self.fuel), total_count=len(self.fuel), num_of_rows=num_of_rows)

    async def aclose(self) -> None:
        self.closed = True


def test_rest_area_collection_and_exports(export_client: TestClient) -> None:
    settings = export_client.app.state.settings
    assert _run(export_client, RestAreaCollectionService(settings).collect_references)["status"] == "skipped"
    settings.rest_area_collection_enabled = True
    settings.data_go_kr_service_key = "go-key"
    settings.kex_ex_api_key = "ex-key"
    fake = FakeKrex([_rest_area(" 행담도휴게소 "), _rest_area("행담도휴게소")], [_fuel("A00001", 1700)])
    service = RestAreaCollectionService(settings, client_factory=lambda **_: fake)
    assert _run(export_client, service.collect_references)["stored"] == 1
    assert _run(export_client, service.collect_fuel_prices)["stored"] == 1
    assert fake.closed

    areas = export_client.get("/v1/service/exports/rest-areas", headers=HEADERS).json()
    assert [item["natural_key"] for item in areas["items"]] == ["행담도휴게소::서해안고속도로::목포방향"]
    assert areas["items"][0]["natural_key"] == rest_area_identity("행담도휴게소", "서해안고속도로", "목포방향")
    assert areas["collection"] == {**areas["collection"], "source": REST_AREA_SOURCE, "stale": False, "failed": False}
    prices = export_client.get("/v1/service/exports/rest-area-fuel-prices", headers=HEADERS).json()
    assert prices["items"][0]["service_area_code"] == "A00001"
    assert prices["items"][0]["gasoline_price"] == 1700
    assert prices["items"][0]["raw"] == {"serviceAreaCode": "A00001", "gasolinePrice": "1700원"}
    assert prices["collection"]["source"] == REST_AREA_FUEL_SOURCE

    # 같은 코드의 다음 수집은 현재값을 덮는다. 실패는 상태에만 남고 기존 행은 유지된다.
    fake.fuel = [_fuel("A00001", 1750)]
    _run(export_client, service.collect_fuel_prices)
    assert export_client.get("/v1/service/exports/rest-area-fuel-prices",
                             headers=HEADERS).json()["items"][0]["gasoline_price"] == 1750

    async def boom(**_):
        raise RuntimeError("secret-url?serviceKey=ex-key")
    fake.fuel_prices = boom
    with pytest.raises(RuntimeError):
        _run(export_client, service.collect_fuel_prices)
    failed = export_client.get("/v1/service/exports/rest-area-fuel-prices", headers=HEADERS).json()
    assert failed["collection"]["failed"] is True and failed["collection"]["stale"] is True
    assert len(failed["items"]) == 1
    status = {row["source"]: row for row in export_client.get("/v1/transport/providers").json()["items"]}
    assert status[REST_AREA_FUEL_SOURCE]["status"] == "failed"
    assert "secret-url" not in export_client.get("/v1/transport/providers").text


class IncidentProvider:
    mode = "fixture"
    enabled_sources = (INCIDENT_SOURCE,)

    def __init__(self) -> None:
        self.incidents: list[Incident] = []

    async def collect_highway(self, *, sources=()) -> HighwayPayload:
        return HighwayPayload(traffic=None, incidents=tuple(self.incidents))

    async def collect_fuel(self):
        return None

    def next_fuel_interval(self) -> timedelta:
        return timedelta(hours=8)

    async def aclose(self) -> None:
        return None


def _incident(series: int, point: str) -> Incident:
    return Incident(occurred_date="2026.10.02", occurred_time="09:00:00", incident_type="작업",
                    incident_type_code="03", direction="부산방향", message=f"{point} 작업", point_name=point,
                    route_no="0010", route_name="경부선", process_status="진행", process_status_code="1",
                    latitude=37.0, longitude=127.0, congestion_length=None, series_no=series,
                    raw={"seriesNM": str(series), "accPointNM": point})


def test_active_incident_set_reflects_only_the_last_successful_collection(export_client: TestClient) -> None:
    path = "/v1/service/exports/highway-incidents/active"
    assert export_client.get(path, headers=HEADERS).status_code == 503
    service = export_client.app.state.transport_collection_service
    provider = IncidentProvider()
    service.provider = provider

    async def collect(session):
        await _set_state(session, INCIDENT_SOURCE, next_due_at=None)
        return await service.collect(session, scope="highway", trigger="export_test")

    provider.incidents = [_incident(1, "서울IC"), _incident(2, "수원IC")]
    assert _run(export_client, collect)["status"] == "success"
    first = export_client.get(path, headers=HEADERS).json()
    assert sorted(item["point_name"] for item in first["items"]) == ["서울IC", "수원IC"]
    assert first["items"][0]["raw"]["seriesNM"] in {"1", "2"}

    # 다음 수집에서 사라진 사건은 활성 집합에서 빠진다(소비자의 종료 판단 근거).
    provider.incidents = [_incident(1, "서울IC")]
    _run(export_client, collect)
    second = export_client.get(path, headers=HEADERS).json()
    assert [item["point_name"] for item in second["items"]] == ["서울IC"]
    assert second["collected_at"] > first["collected_at"]

    provider.incidents = []
    _run(export_client, collect)
    assert export_client.get(path, headers=HEADERS).json()["items"] == []

    _run(export_client, lambda session: _set_state(session, INCIDENT_SOURCE, last_error="provider failed"))
    assert export_client.get(path, headers=HEADERS).status_code == 503
    _run(export_client, lambda session: _set_state(
        session, INCIDENT_SOURCE, last_error=None, last_success_at=now_utc() - timedelta(hours=1)))
    assert export_client.get(path, headers=HEADERS).status_code == 503


def test_airport_export_covers_every_active_bundled_airport(export_client: TestClient) -> None:
    payload = export_client.get("/v1/service/exports/airports", headers=HEADERS).json()
    by_code = {item["code"]: item for item in payload["items"]}
    assert "KPO" in by_code and "ICN" in by_code
    assert by_code["ICN"]["icao_code"] == "RKSI"
    assert by_code["ICN"]["latitude"] is not None and by_code["ICN"]["municipality"]
    assert by_code["KPO"]["has_parking_data"] is False
    assert by_code["GMP"]["has_parking_data"] is True


def test_rest_area_jobs_are_scheduled_and_running() -> None:
    for job_name, cron in [("rest_area_reference_collection_job", "40 3 * * *"),
                           ("rest_area_fuel_price_collection_job", "25 */4 * * *")]:
        assert definitions.get_job_def(job_name).name == job_name
        schedule = definitions.get_schedule_def(f"{job_name}_schedule")
        assert schedule.cron_schedule == cron
        assert schedule.execution_timezone == "Asia/Seoul"
        assert schedule.default_status.name == "RUNNING"
