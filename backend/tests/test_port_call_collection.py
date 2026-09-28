"""공식 기항지 연결과 호출 예약/캐시의 회귀 테스트."""

import asyncio
import json
from datetime import timedelta

import pytest
from kric import DomesticFerryPort, KricRateLimitError, PortCall
from sqlalchemy import func, select

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import CollectionRun, FerryPort, RawApiResponse
from app.services.rail_maritime_collection import PORT_CALL_SOURCE, RailMaritimeCollectionService, _unique_port_call

TARGET = ("인천", "인천광역시")
LOCATION = PortCall("D000", *TARGET[:1], "28", TARGET[1], "제물포구", 37.4557, 126.598,
                    {"portcl_cd": "D000", "portcl_nm": "인천", "lat": "37.4557", "lot": "126.598"})


@pytest.mark.parametrize("same_port", [True, False])
def test_postgres_concurrent_reservation_protects_identity_and_budget(test_settings, same_port):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("명시적으로 허용한 전용 PostgreSQL 테스트 DB가 필요합니다")

    async def run():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        service = RailMaritimeCollectionService(test_settings)
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0

        class Client:
            async def get_port_calls(self, **_kwargs):
                nonlocal calls
                calls += 1
                started.set()
                await release.wait()
                return (LOCATION,)

        try:
            async with factory() as session:
                job = CollectionRun(started_at=now_utc(), status="running", trigger="test")
                session.add(job)
                await session.flush()
                run_id = job.id
                if not same_port:
                    for index in range(79):
                        session.add(RawApiResponse(collection_run_id=run_id, source=PORT_CALL_SOURCE,
                            endpoint=f"previous:{index}", status_code=0, body_text="null",
                            received_at=now_utc(), parse_status="failed"))
                await session.commit()
            async with factory() as first, factory() as second:
                pending = asyncio.create_task(service._port_call_location(first, run_id, Client(), "SEA10100", TARGET))
                try:
                    await asyncio.wait_for(started.wait(), timeout=5)
                    # 첫 HTTP 요청이 대기 중에도 두 번째 DB 검사는 끝나야 한다.
                    result = await asyncio.wait_for(service._port_call_location(second, run_id, Client(),
                        "SEA10100" if same_port else "SEA30010", TARGET), timeout=5)
                    assert result == (None, False)
                    assert calls == 1
                finally:
                    release.set()
                    await pending
            async with factory() as check:
                count = await check.scalar(select(func.count()).select_from(RawApiResponse)
                    .where(RawApiResponse.source == PORT_CALL_SOURCE))
                assert count == (1 if same_port else 80)
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("rows,target,found", [
    ((LOCATION,), TARGET, True), ((), TARGET, False), ((LOCATION, LOCATION), TARGET, False),
    ((LOCATION,), ("인", TARGET[1]), False), ((LOCATION,), (TARGET[0], "전라남도"), False),
    ((PortCall("bad", *TARGET[:1], "28", TARGET[1], None, None, 126.598),), TARGET, False),
    ((PortCall("bad", *TARGET[:1], "28", TARGET[1], None, 37.4, 0),), TARGET, False),
])
def test_exact_identity_and_domestic_bounds(rows, target, found):
    assert (_unique_port_call(rows, target) is not None) is found


@pytest.mark.parametrize("outcome", ["success", "empty", "failure"])
def test_durable_reservation_and_positive_negative_failure_cache(tmp_path, outcome):
    async def run():
        settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'cache.db'}", seed_sample_data=False)
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        calls = 0
        class Client:
            async def get_port_calls(self, **kwargs):
                nonlocal calls
                calls += 1
                assert kwargs == {"name": TARGET[0], "province": TARGET[1]}
                async with factory() as check:
                    reservation = await check.scalar(select(RawApiResponse).order_by(RawApiResponse.id.desc()).limit(1))
                    assert reservation.parse_status == "pending"
                    assert reservation.status_code == 0
                if outcome == "failure":
                    raise KricRateLimitError("must-not-store-test-key")
                return (LOCATION,) if outcome == "success" else ()
        service = RailMaritimeCollectionService(settings)
        async with factory() as session:
            job = CollectionRun(started_at=now_utc(), status="running", trigger="test")
            session.add(job)
            await session.commit()
            first = await service._port_call_location(session, job.id, Client(), "SEA10100", TARGET)
            second = await service._port_call_location(session, job.id, Client(), "SEA10100", TARGET)
            assert (first[0] is not None) is (outcome == "success")
            assert first[1] is (outcome != "failure")
            assert second == first
            assert calls == 1
            saved = await session.scalar(select(RawApiResponse))
            assert "test-key" not in json.dumps(saved.request_params_json) + saved.body_text + (saved.parse_error or "")
            saved.received_at = now_utc() - timedelta(days=31)
            await session.commit()
            refreshed = await service._port_call_location(session, job.id, Client(), "SEA10100", TARGET)
            assert (refreshed[0] is not None) is (outcome == "success")
            assert refreshed[1] is (outcome != "failure")
            assert calls == 2
        await engine.dispose()
    asyncio.run(run())


def test_daily_budget_includes_failed_and_pending_attempts(tmp_path):
    async def run():
        settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'budget.db'}", seed_sample_data=False)
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = RailMaritimeCollectionService(settings)
        async with factory() as session:
            job = CollectionRun(started_at=now_utc(), status="running", trigger="test")
            session.add(job)
            await session.flush()
            for index in range(80):
                session.add(RawApiResponse(collection_run_id=job.id, source=PORT_CALL_SOURCE, endpoint=f"test:{index}",
                    status_code=0, body_text="null", received_at=now_utc(), parse_status="pending" if index % 2 else "failed"))
            await session.commit()
            assert await service._port_call_location(session, job.id, object(), "SEA10100", TARGET) == (None, False)
            assert await session.scalar(select(func.count()).select_from(RawApiResponse)) == 80
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("previous_source", ["data_go_kr_port_guideline", PORT_CALL_SOURCE])
def test_remove_only_guideline_coordinates_and_preserve_good_data_on_failure(tmp_path, previous_source):
    async def run():
        settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'upsert.db'}", seed_sample_data=False)
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = RailMaritimeCollectionService(settings)
        async with factory() as session:
            now = now_utc()
            row = FerryPort(source="data_go_kr_maritime", port_id="SEA10100", port_name="인천", first_seen_at=now,
                last_seen_at=now, latitude=37.4557, longitude=126.598, location_source=previous_source,
                location_point_count=1, raw_item_json={"_komsa_port_call": {"portcl_cd": "D000"}})
            session.add(row)
            await session.commit()
            item = DomesticFerryPort("SEA10100", "인천", {"nodeId": "SEA10100"})
            await service._upsert_port(session, item, now, None)
            await session.commit()
            assert row.latitude == (None if previous_source == "data_go_kr_port_guideline" else 37.4557)
            await service._upsert_port(session, item, now, LOCATION)
            await session.commit()
            assert (row.latitude, row.longitude, row.location_source, row.location_point_count) == (37.4557, 126.598, PORT_CALL_SOURCE, 1)
            assert row.raw_item_json["nodeId"] == "SEA10100"
            assert row.raw_item_json["_komsa_port_call"]["portcl_cd"] == "D000"
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("candidates", [
    (), (LOCATION, LOCATION),
    (PortCall("D000", "인천", "28", "인천광역시", None, None, None),),
    (PortCall("D000", "인천", "28", "인천광역시", None, 37.4, 0),),
    (PortCall("D000", "인천", "46", "전라남도", None, 37.4, 126.5),),
])
def test_successful_revalidation_clears_invalidated_location_including_cached_result(tmp_path, candidates):
    async def run():
        settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'revalidation.db'}", seed_sample_data=False)
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        service = RailMaritimeCollectionService(settings)
        calls = 0

        class Client:
            async def get_port_calls(self, **_kwargs):
                nonlocal calls
                calls += 1
                return candidates

        try:
            async with factory() as session:
                job = CollectionRun(started_at=now_utc(), status="running", trigger="test")
                session.add(job)
                await session.commit()
                item = DomesticFerryPort("SEA10100", "인천", {"nodeId": "SEA10100"})
                for _attempt in range(2):
                    # 최초 재조회와 30일 음성 캐시 모두 이전 연결을 해제해야 한다.
                    await service._upsert_port(session, item, now_utc(), LOCATION)
                    await session.commit()
                    location, verified = await service._port_call_location(session, job.id, Client(), "SEA10100", TARGET)
                    assert location is None and verified
                    await service._upsert_port(session, item, now_utc(), location, location_verified=verified)
                    await session.commit()
                    row = await session.scalar(select(FerryPort))
                    assert (row.latitude, row.longitude, row.location_source, row.location_point_count) == (None, None, None, 0)
                    assert "_komsa_port_call" not in row.raw_item_json
                assert calls == 1
        finally:
            await engine.dispose()

    asyncio.run(run())
