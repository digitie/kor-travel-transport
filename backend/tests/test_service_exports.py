"""내부 서비스 export `/v1/service/exports/*`와 휴게소 수집 (ADR-013)."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.core.time_utils import now_utc
from app.dagster.definitions import definitions
from app.main import create_app
from app.models import FuelPriceSnapshot, FuelStation, TransportCollectionState
from app.services.rest_area_collection import (
    REST_AREA_FUEL_SOURCE,
    REST_AREA_SOURCE,
    EmptyRestAreaCollectionError,
    RestAreaCollectionService,
    rest_area_identity,
)
from app.services.transport_collection import (
    INCIDENT_SOURCE,
    OPINET_SOURCE,
    HighwayPayload,
    upsert_latest_fuel_prices,
)
from fastapi.testclient import TestClient
from krex import Incident, RestArea, RestAreaFuelPrice
from sqlalchemy import select

TOKEN = "s" * 40
HEADERS = {"X-Kor-Travel-Transport-Service-Token": TOKEN}
REPO_ROOT = Path(__file__).resolve().parents[2]


LOOPBACK_CLIENT = ("127.0.0.1", 50123)


@pytest.fixture
def export_client(test_settings: Settings):
    test_settings.transport_service_export_token = TOKEN
    test_settings.trusted_hosts_csv = "testserver,pr-api.example.test,127.0.0.1"
    with TestClient(create_app(test_settings), client=LOOPBACK_CLIENT) as client:
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
def test_exports_hide_without_token_or_from_a_remote_peer(test_settings: Settings, path: str) -> None:
    test_settings.transport_service_export_token = TOKEN
    test_settings.trusted_hosts_csv = "testserver,127.0.0.1,localhost"
    app = create_app(test_settings)
    with TestClient(app, client=LOOPBACK_CLIENT) as local:
        assert local.get(path).status_code == 404
        assert local.get(path, headers={"X-Kor-Travel-Transport-Service-Token": "x" * 40}).status_code == 404
        # 같은 토큰이라도 loopback 밖 peer는 닫힌다 — Host 헤더를 loopback으로 꾸며도 마찬가지다
        # (`curl -H 'Host: 127.0.0.1' http://192.168.1.14:14001/...`).
        assert local.get(path, headers=HEADERS).status_code in {200, 503}
    with TestClient(app, client=("192.168.1.50", 40000)) as remote:
        assert remote.get(path, headers=HEADERS).status_code == 404
        assert remote.get(path, headers={**HEADERS, "Host": "127.0.0.1"}).status_code == 404
        assert remote.get(path, headers={**HEADERS, "Host": "localhost"}).status_code == 404
    with TestClient(app, client=("::ffff:192.168.1.50", 40000)) as mapped:
        assert mapped.get(path, headers={**HEADERS, "Host": "127.0.0.1"}).status_code == 404
    with TestClient(app, client=("::ffff:127.0.0.1", 40000)) as mapped_loopback:
        assert mapped_loopback.get(path, headers=HEADERS).status_code in {200, 503}
    # Starlette TestClient 기본 peer("testclient")처럼 IP가 아닌 값도 닫힌다.
    with TestClient(app) as unknown:
        assert unknown.get(path, headers=HEADERS).status_code == 404


def test_allowed_clients_widen_only_by_cidr(test_settings: Settings) -> None:
    """standalone 개발(Map이 docker bridge에서 host.docker.internal로 접속)은 대역을 명시해 연다."""
    test_settings.transport_service_export_token = TOKEN
    test_settings.service_export_allowed_clients_csv = "127.0.0.1/32,172.16.0.0/12"
    app = create_app(test_settings)
    with TestClient(app, client=("172.18.0.5", 40000)) as bridge:
        assert bridge.get("/v1/service/exports/airports", headers=HEADERS).status_code == 200
    with TestClient(app, client=("192.168.1.50", 40000)) as lan:
        assert lan.get("/v1/service/exports/airports", headers=HEADERS).status_code == 404
    with pytest.raises(ValueError, match="SERVICE_EXPORT_ALLOWED_CLIENTS_CSV"):
        Settings(service_export_allowed_clients_csv="127.0.0.1,not-a-network")


def test_exports_stay_closed_when_the_token_is_short(test_settings: Settings) -> None:
    test_settings.transport_service_export_token = "short"
    with TestClient(create_app(test_settings), client=LOOPBACK_CLIENT) as client:
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


@pytest.mark.parametrize("state", [
    None,
    {"last_success_at": None},
    {"last_error": "collection_failed"},
    {"last_success_at_age": timedelta(hours=25)},
])
def test_fuel_station_export_refuses_without_a_current_collection(export_client: TestClient, state) -> None:
    """이력 없음·실패·24시간 초과면 503 — 빈·낡은 집합을 현재로 주지 않는다(ADR-013)."""
    async def seed(session) -> None:
        if state is None:
            return
        values = dict(state)
        age = values.pop("last_success_at_age", timedelta(0))
        values.setdefault("last_success_at", now_utc() - age)
        await _set_state(session, OPINET_SOURCE, **values)

    _run(export_client, seed)
    response = export_client.get("/v1/service/exports/fuel-stations", headers=HEADERS)
    assert response.status_code == 503


def test_rest_area_export_refuses_once_the_reference_is_older_than_three_days(export_client: TestClient) -> None:
    _run(export_client, lambda session: _set_state(
        session, REST_AREA_SOURCE, last_success_at=now_utc() - timedelta(days=3, minutes=1)))
    assert export_client.get("/v1/service/exports/rest-areas", headers=HEADERS).status_code == 503
    _run(export_client, lambda session: _set_state(session, REST_AREA_SOURCE, last_success_at=now_utc()))
    ok = export_client.get("/v1/service/exports/rest-areas", headers=HEADERS)
    assert ok.status_code == 200 and ok.json()["collection"]["stale"] is False


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
    # 수집이 꺼져 있어 이력이 없으면 빈 200이 아니라 503이다(소비자가 전량 삭제로 읽지 않게).
    for path in ("/v1/service/exports/rest-areas", "/v1/service/exports/rest-area-fuel-prices"):
        assert export_client.get(path, headers=HEADERS).status_code == 503
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
    # 실패한 수집 뒤에는 503이다 — 소비자가 낡은 집합을 현재로, 빈 집합을 삭제로 읽지 않게(ADR-013).
    failed = export_client.get("/v1/service/exports/rest-area-fuel-prices", headers=HEADERS)
    assert failed.status_code == 503
    assert "secret-url" not in failed.text
    status = {row["source"]: row for row in export_client.get("/v1/transport/providers").json()["items"]}
    assert status[REST_AREA_FUEL_SOURCE]["status"] == "failed"
    assert "secret-url" not in export_client.get("/v1/transport/providers").text


def test_an_empty_rest_area_collection_fails_so_the_export_goes_503(export_client: TestClient) -> None:
    """전국 집합이 0건이면 성공이 아니다 — 3일 창이 지난 뒤 빈 200(전량 삭제로 읽힘)을 내지 않게 실패로 남긴다."""
    settings = export_client.app.state.settings
    settings.rest_area_collection_enabled = True
    settings.data_go_kr_service_key = "go-key"
    settings.kex_ex_api_key = "ex-key"
    fake = FakeKrex([_rest_area("행담도휴게소")], [_fuel("A00001", 1700)])
    service = RestAreaCollectionService(settings, client_factory=lambda **_: fake)
    assert _run(export_client, service.collect_references)["stored"] == 1
    assert _run(export_client, service.collect_fuel_prices)["stored"] == 1

    # 0건, 그리고 저장할 수 없는 행만(이름 없음) 온 경우 모두 실패다.
    for rest_areas in ([], [_rest_area("  ")]):
        fake.rest_areas = rest_areas
        with pytest.raises(EmptyRestAreaCollectionError):
            _run(export_client, service.collect_references)
        assert export_client.get("/v1/service/exports/rest-areas", headers=HEADERS).status_code == 503
    fake.fuel = []
    with pytest.raises(EmptyRestAreaCollectionError):
        _run(export_client, service.collect_fuel_prices)
    assert export_client.get("/v1/service/exports/rest-area-fuel-prices", headers=HEADERS).status_code == 503

    async def states(session):
        rows = (await session.scalars(select(TransportCollectionState).where(
            TransportCollectionState.source.in_([REST_AREA_SOURCE, REST_AREA_FUEL_SOURCE])))).all()
        return {row.source: row.last_error for row in rows}
    assert _run(export_client, states) == {
        REST_AREA_SOURCE: "EmptyRestAreaCollectionError",
        REST_AREA_FUEL_SOURCE: "EmptyRestAreaCollectionError",
    }


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
