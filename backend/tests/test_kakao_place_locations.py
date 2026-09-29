"""카카오 장소 검색의 오매칭·호출 예산·저장 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import BusTerminalReference, FerryPort, RawApiResponse
from app.services.kakao_place_locations import KakaoPlaceCollectionService, URL, choose_kakao_location
from app.services.provider_status import provider_status


def place(name: str, category: str, *, x: str = "126.5", y: str = "36.3",
          address: str = "전남광주통합특별시 여수시") -> dict:
    return {"id": "K1", "place_name": name, "category_name": category,
            "address_name": address, "x": x, "y": y}


def test_kakao_match_requires_exact_name_category_region_and_single_point() -> None:
    correct = place("강릉시외버스터미널", "교통,수송 > 교통시설 > 고속,시외버스터미널",
                    address="강원특별자치도 강릉시", x="128.8", y="37.7")
    assert choose_kakao_location([correct], query="강릉시외버스터미널", kind="bus", city_name="강원도") is not None
    assert choose_kakao_location([correct], query="강릉고속버스터미널", kind="bus", city_name="강원도") is None
    assert choose_kakao_location([correct], query="강릉시외버스터미널", kind="bus",
                                 city_name="강원도", service_type="express") is None
    assert choose_kakao_location([correct], query="강릉시외버스터미널", kind="bus", city_name="경기도") is None
    assert choose_kakao_location([correct, {**correct, "x": "128.9"}],
                                 query="강릉시외버스터미널", kind="bus", city_name="강원도") is None
    assert choose_kakao_location([place("대천항", "관광명소")], query="대천항", kind="port") is None
    assert choose_kakao_location([place("대천항", "교통,수송 > 교통시설 > 항구,포구")],
                                 query="대천항", kind="port") is not None


class FakeKakaoClient:
    calls: list[str] = []
    status_code = 200
    incomplete = False

    def __init__(self, **kwargs) -> None:
        assert kwargs["headers"]["Authorization"].startswith("KakaoAK ")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, *, params: dict):
        assert url == URL and params["page"] == 1
        query = params["query"]
        self.calls.append(query)
        if "시외버스터미널" in query:
            items = [place(query, "교통,수송 > 교통시설 > 고속,시외버스터미널",
                           address="강원특별자치도 강릉시", x="128.8", y="37.7")]
        else:
            items = [place(query, "교통,수송 > 교통시설 > 항구,포구")]
        return httpx.Response(self.status_code, json={"meta": {"is_end": not self.incomplete,
            "total_count": len(items)}, "documents": items}, request=httpx.Request("GET", url))


def test_kakao_collection_persists_only_verified_coordinates_and_reuses_receipts(tmp_path: Path,
                                                                                     monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.services.kakao_place_locations.asyncio.sleep", no_sleep)
    FakeKakaoClient.calls = []
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'kakao.sqlite3'}",
                        seed_sample_data=False, kakao_place_collection_enabled=True,
                        kakao_rest_api_key="test-key")
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with factory() as session:
            session.add(BusTerminalReference(source="data_go_kr_tago", service_type="intercity",
                terminal_id="B1", terminal_name="강릉", city_name="강원도",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            session.add(FerryPort(source="data_go_kr_maritime", port_id="P1", port_name="대천",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            await session.commit()
            first = await KakaoPlaceCollectionService(settings, client_factory=FakeKakaoClient).collect(session)
            assert first["status"] == "success"
            assert (first["provider_calls"], first["bus_locations"], first["port_locations"]) == (2, 1, 1)
            bus = await session.scalar(select(BusTerminalReference))
            port = await session.scalar(select(FerryPort))
            assert bus.location_source == port.location_source == "kakao_place"
            assert bus.latitude == 37.7 and port.longitude == 126.5
            assert (await session.scalar(select(func.count()).select_from(RawApiResponse))) == 2
            catalog = await provider_status(session, settings)
            kakao = next(item for item in catalog.items if item.source == "kakao_place")
            assert kakao.enabled is True and kakao.status == "success"
            assert kakao.job_name == "kakao_place_location_collection_job"
            second = await KakaoPlaceCollectionService(settings, client_factory=FakeKakaoClient).collect(session)
            assert second["provider_calls"] == 0
        await engine.dispose()

    asyncio.run(run())
    assert FakeKakaoClient.calls == ["강릉시외버스터미널", "대천항"]


def test_kakao_quota_stops_before_second_call(tmp_path: Path, monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.services.kakao_place_locations.asyncio.sleep", no_sleep)
    FakeKakaoClient.calls = []
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'quota.sqlite3'}",
                        seed_sample_data=False, kakao_place_collection_enabled=True,
                        kakao_rest_api_key="test-key", kakao_place_max_calls_per_day=1)
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with factory() as session:
            session.add(BusTerminalReference(source="data_go_kr_tago", service_type="intercity",
                terminal_id="B1", terminal_name="강릉", city_name="강원도",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            session.add(FerryPort(source="data_go_kr_maritime", port_id="P1", port_name="대천",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            await session.commit()
            result = await KakaoPlaceCollectionService(settings, client_factory=FakeKakaoClient).collect(session)
            assert result["status"] == "partial_success"
            assert result["provider_calls"] == 1 and result["deferred"] == 1
        await engine.dispose()

    asyncio.run(run())
    assert FakeKakaoClient.calls == ["강릉시외버스터미널"]


@pytest.mark.parametrize("status_code,incomplete", [(200, True), (429, False)])
def test_kakao_incomplete_and_quota_error_never_persist_coordinates(
    tmp_path: Path, monkeypatch, status_code: int, incomplete: bool,
) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.services.kakao_place_locations.asyncio.sleep", no_sleep)
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'incomplete.sqlite3'}",
                        seed_sample_data=False, kakao_place_collection_enabled=True,
                        kakao_rest_api_key="test-key")
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with factory() as session:
            session.add(FerryPort(source="data_go_kr_maritime", port_id="P1", port_name="대천",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            await session.commit()
            FakeKakaoClient.incomplete = incomplete
            FakeKakaoClient.status_code = status_code
            result = await KakaoPlaceCollectionService(settings, client_factory=FakeKakaoClient).collect(session)
            assert result["status"] == ("success" if incomplete else "partial_success")
            assert result["incomplete"] == int(incomplete)
            assert (await session.scalar(select(FerryPort))).latitude is None
            assert (await session.scalar(select(RawApiResponse))).parse_status == (
                "incomplete" if incomplete else "failed"
            )
        await engine.dispose()

    try:
        asyncio.run(run())
    finally:
        FakeKakaoClient.incomplete = False
        FakeKakaoClient.status_code = 200


def test_kakao_429_cools_down_the_key_across_runs(tmp_path: Path, monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.services.kakao_place_locations.asyncio.sleep", no_sleep)
    FakeKakaoClient.calls = []
    FakeKakaoClient.status_code = 429
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'cooldown.sqlite3'}",
                        seed_sample_data=False, kakao_place_collection_enabled=True,
                        kakao_rest_api_key="test-key")
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with factory() as session:
            for port_id, name in (("P1", "대천"), ("P2", "여수")):
                session.add(FerryPort(source="data_go_kr_maritime", port_id=port_id, port_name=name,
                    first_seen_at=now, last_seen_at=now, raw_item_json={}))
            await session.commit()
            service = KakaoPlaceCollectionService(settings, client_factory=FakeKakaoClient)
            first = await service.collect(session)
            second = await service.collect(session)
            assert first["provider_calls"] == 1
            assert second["provider_calls"] == 0 and second["deferred"] == 2
            assert len(FakeKakaoClient.calls) == 1
            FakeKakaoClient.status_code = 200
            rotated = settings.model_copy(update={"kakao_rest_api_key": "rotated-test-key"})
            third = await KakaoPlaceCollectionService(rotated, client_factory=FakeKakaoClient).collect(session)
            assert third["provider_calls"] == third["port_locations"] == 2
            assert len(FakeKakaoClient.calls) == 3
            no_targets = await service.collect(session)
            assert no_targets["status"] == "success" and no_targets["deferred"] == 0
        await engine.dispose()

    try:
        asyncio.run(run())
    finally:
        FakeKakaoClient.status_code = 200


def test_kakao_city_correction_bypasses_old_receipt(tmp_path: Path, monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.services.kakao_place_locations.asyncio.sleep", no_sleep)
    FakeKakaoClient.calls = []
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'city.sqlite3'}",
                        seed_sample_data=False, kakao_place_collection_enabled=True,
                        kakao_rest_api_key="test-key")
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with factory() as session:
            session.add(BusTerminalReference(source="data_go_kr_tago", service_type="intercity",
                terminal_id="B1", terminal_name="강릉", city_name="강원도",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            session.add(RawApiResponse(source="kakao_place", endpoint="kakao:bus:intercity:B1",
                request_params_json={"query": "강릉시외버스터미널", "name": "강릉", "city_name": "경기도"},
                status_code=200, body_text="{}", received_at=now, parse_status="success"))
            await session.commit()
            result = await KakaoPlaceCollectionService(settings, client_factory=FakeKakaoClient).collect(session)
            assert result["provider_calls"] == 1
        await engine.dispose()

    asyncio.run(run())
    assert FakeKakaoClient.calls == ["강릉시외버스터미널"]


def test_kakao_auth_recovery_can_retry_without_waiting_a_day(tmp_path: Path, monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.services.kakao_place_locations.asyncio.sleep", no_sleep)
    FakeKakaoClient.calls = []
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'auth.sqlite3'}",
                        seed_sample_data=False, kakao_place_collection_enabled=True,
                        kakao_rest_api_key="test-key")
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with factory() as session:
            session.add(FerryPort(source="data_go_kr_maritime", port_id="P1", port_name="대천",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            await session.commit()
            FakeKakaoClient.status_code = 401
            first = await KakaoPlaceCollectionService(settings, client_factory=FakeKakaoClient).collect(session)
            FakeKakaoClient.status_code = 200
            second = await KakaoPlaceCollectionService(settings, client_factory=FakeKakaoClient).collect(session)
            assert first["provider_calls"] == second["provider_calls"] == 1
            assert second["port_locations"] == 1
        await engine.dispose()

    try:
        asyncio.run(run())
    finally:
        FakeKakaoClient.status_code = 200
    assert FakeKakaoClient.calls == ["대천항", "대천항"]
