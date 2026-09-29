"""장소 좌표 보강의 오매칭 방지·호출 예산·저장 회귀."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select
from pydantic import ValidationError
import pytest

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import BusTerminalReference, FerryPort, RawApiResponse
from app.services.place_locations import PlaceLocationCollectionService, choose_bus_location, choose_port_location
from vworld import VworldNoDataError


def test_location_collection_rate_contract_allows_one_full_reference_pass() -> None:
    settings = Settings()
    assert settings.place_location_max_calls_per_day == 10000
    assert settings.place_location_request_interval_seconds == 0.01
    with pytest.raises(ValidationError):
        Settings(place_location_max_calls_per_day=10001)
    with pytest.raises(ValidationError):
        Settings(place_location_request_interval_seconds=0.009)


@pytest.mark.parametrize("lock_acquired", [True, False])
def test_postgres_location_collection_lease_uses_dedicated_connection(lock_acquired: bool) -> None:
    class LockConnection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def scalar(self, statement):
            self.statements.append(str(statement))
            return lock_acquired

    async def run() -> None:
        connection = LockConnection()
        session = SimpleNamespace(bind=SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"), connect=lambda: connection,
        ))
        service = PlaceLocationCollectionService(Settings())
        async with service._postgres_collection_lease(session) as acquired:
            assert acquired is lock_acquired
            assert len(connection.statements) == 1
        assert len(connection.statements) == (2 if lock_acquired else 1)
        assert "pg_try_advisory_lock" in connection.statements[0]
        if lock_acquired:
            assert "pg_advisory_unlock" in connection.statements[1]

    asyncio.run(run())


def place(title: str, category: str, *, x: str = "128.8788", y: str = "37.7546", address: str = "강원특별자치도 강릉시") -> dict:
    return {"title": title, "category": category, "point": {"x": x, "y": y},
            "address": {"parcel": address}}


def test_bus_match_rejects_business_stop_wrong_region_and_ambiguous() -> None:
    correct = place("강릉시외버스터미널", "도로시설 > 버스터미널/정류장 > 시외버스터미널")
    business = place("강릉시외버스터미널", "회사 > 통신판매업")
    stop = place("강릉시외버스터미널", "도로시설 > 버스터미널/정류장 > 버스정류장")
    result = choose_bus_location([business, stop, correct], name="강릉", service_type="intercity", city_name="강원도")
    assert result is not None and result["latitude"] == 37.7546
    assert choose_bus_location([correct, correct], name="강릉", service_type="intercity", city_name="강원도") is not None
    assert choose_bus_location([correct, place("강릉시외버스터미널",
        "도로시설 > 버스터미널/정류장 > 시외버스터미널", x="128.9")],
        name="강릉", service_type="intercity", city_name="강원도") is None
    assert choose_bus_location([correct], name="강릉", service_type="express", city_name="강원도") is None
    assert choose_bus_location([correct], name="강릉", service_type="intercity", city_name="경기도") is None
    assert choose_bus_location([correct], name="강릉", service_type="intercity", city_name="강원도") is not None
    assert choose_bus_location([correct], name="강릉시외버스터미널", service_type="intercity", city_name="강원도") is not None
    combined = place("강릉종합버스터미널", "도로시설 > 버스터미널/정류장 > 종합버스터미널")
    assert choose_bus_location([combined], name="강릉", service_type="express", city_name="강원도") is not None
    generic = place("강릉시외버스터미널", "도로시설 > 버스터미널/정류장", x="128.9")
    assert choose_bus_location([generic, correct], name="강릉", service_type="intercity", city_name="강원도") == choose_bus_location(
        [correct], name="강릉", service_type="intercity", city_name="강원도")


def test_port_match_rejects_island_centroid_duplicate_and_unverified_coord() -> None:
    island = place("백야도", "자연지명 > 섬 > 섬(해양)")
    harbor = place("백야도항", "항만시설 > 페리/해운", x="127.641", y="34.621")
    assert choose_port_location([island, harbor], name="백야도") == {
        "title": "백야도항", "category": "항만시설 > 페리/해운",
        "address": "강원특별자치도 강릉시", "longitude": 127.641, "latitude": 34.621,
    }
    assert choose_port_location([island], name="백야도") is None
    assert choose_port_location([harbor, harbor], name="백야도") is not None
    assert choose_port_location([harbor, place("백야도항", "항만시설 > 페리/해운", x="127.9")], name="백야도") is None
    assert choose_port_location([place("백야도항", "항만시설 > 페리/해운", x="NaN")], name="백야도") is None
    assert choose_port_location([harbor], name="제주_백야도") is None


class FakeVworld:
    calls: list[str] = []

    def __init__(self, **kwargs) -> None:
        assert kwargs["max_rps"] == 100.0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def search_place(self, query: str, *, size: int):
        assert size == 100
        self.calls.append(query)
        item = (place("강릉시외버스터미널", "도로시설 > 버스터미널/정류장 > 시외버스터미널")
                if "강릉" in query else place("대천항", "항만시설 > 페리/해운", x="126.5", y="36.3"))
        return {"response": {"status": "OK", "record": {"total": "1"},
                             "result": {"items": [item]}}}


def test_location_collection_persists_verified_bus_and_port_and_reuses_receipts(tmp_path: Path, monkeypatch) -> None:
    async def no_sleep(_seconds: int) -> None:
        return None

    monkeypatch.setattr("app.services.place_locations.asyncio.sleep", no_sleep)
    FakeVworld.calls = []
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'places.sqlite3'}",
                        seed_sample_data=False, place_location_collection_enabled=True,
                        vworld_api_key="test-key", place_location_max_calls_per_day=2)
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
            first = await PlaceLocationCollectionService(settings, client_factory=FakeVworld).collect(session)
            assert first["status"] == "success"
            assert (first["provider_calls"], first["bus_locations"], first["port_locations"]) == (2, 1, 1)
        async with factory() as session:
            second = await PlaceLocationCollectionService(settings, client_factory=FakeVworld).collect(session)
            assert second["provider_calls"] == 0
            bus = await session.scalar(select(BusTerminalReference))
            port = await session.scalar(select(FerryPort))
            assert bus.location_source == port.location_source == "vworld_place"
            assert (bus.latitude, port.longitude) == (37.7546, 126.5)
            assert bus.raw_item_json["_vworld_place"]["title"] == "강릉시외버스터미널"
            assert await session.scalar(select(func.count()).select_from(RawApiResponse)) == 2
        await engine.dispose()

    asyncio.run(run())
    assert FakeVworld.calls == ["강릉시외버스터미널", "대천항"]


def test_location_collection_counts_reserved_calls_and_does_not_retry_failed_provider(tmp_path: Path, monkeypatch) -> None:
    async def no_sleep(_seconds: int) -> None:
        return None

    class FailingVworld(FakeVworld):
        async def search_place(self, query: str, *, size: int):
            self.calls.append(query)
            raise TimeoutError("provider details must not be stored")

    monkeypatch.setattr("app.services.place_locations.asyncio.sleep", no_sleep)
    FailingVworld.calls = []
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'failed.sqlite3'}",
                        seed_sample_data=False, place_location_collection_enabled=True,
                        vworld_api_key="test-key", place_location_max_calls_per_day=1)
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with factory() as session:
            session.add(BusTerminalReference(source="data_go_kr_tago", service_type="intercity",
                terminal_id="B1", terminal_name="강릉", city_name="강원도",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            await session.commit()
            first = await PlaceLocationCollectionService(settings, client_factory=FailingVworld).collect(session)
            assert first["status"] == "partial_success"
            assert first["provider_calls"] == first["provider_failed"] == 1
            second = await PlaceLocationCollectionService(settings, client_factory=FailingVworld).collect(session)
            assert second["provider_calls"] == 0
            receipt = await session.scalar(select(RawApiResponse))
            assert receipt.parse_status == "failed"
            assert receipt.parse_error == "TimeoutError"
            assert "provider details" not in receipt.body_text
        await engine.dispose()

    asyncio.run(run())
    assert FailingVworld.calls == ["강릉시외버스터미널"]


def test_location_collection_treats_not_found_as_normal_unmatched_result(tmp_path: Path, monkeypatch) -> None:
    async def no_sleep(_seconds: int) -> None:
        return None

    class NoDataVworld(FakeVworld):
        async def search_place(self, query: str, *, size: int):
            self.calls.append(query)
            raise VworldNoDataError("not found")

    monkeypatch.setattr("app.services.place_locations.asyncio.sleep", no_sleep)
    NoDataVworld.calls = []
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'no-data.sqlite3'}",
                        seed_sample_data=False, place_location_collection_enabled=True,
                        vworld_api_key="test-key", place_location_max_calls_per_day=2)
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def run() -> None:
        await init_database(engine)
        now = now_utc()
        async with factory() as session:
            session.add(BusTerminalReference(source="data_go_kr_tago", service_type="intercity",
                terminal_id="B1", terminal_name="강릉", city_name="강원도",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            session.add(FerryPort(source="data_go_kr_maritime", port_id="P1", port_name="백야도",
                first_seen_at=now, last_seen_at=now, raw_item_json={}))
            await session.commit()
            result = await PlaceLocationCollectionService(settings, client_factory=NoDataVworld).collect(session)
            assert result["status"] == "success"
            assert result["provider_calls"] == result["unmatched"] == 2
            assert result["provider_failed"] == 0
        await engine.dispose()

    asyncio.run(run())
    assert NoDataVworld.calls == ["강릉시외버스터미널", "백야도항"]
