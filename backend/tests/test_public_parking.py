from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from datagokr.models import PublicParkingLot as ProviderParking
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory, init_database
from app.models import CollectionRun, PublicParkingLot, RawApiResponse, TransportCollectionState
from app.public_parking_routes import build_public_parking_router, parking_page
from app.service_exports import build_service_export_router
from app.services.public_parking_collection import PublicParkingCollectionService, SOURCE, parking_row, parking_source_key


def provider(identifier="A", **values):
    raw = {"prkplceNo": identifier, "prkplceNm": "시청 주차장", "rdnmadr": "서울 중구 1",
        "latitude": 37.5, "longitude": 127.0, "prkcmprt": 0, "basicCharge": 0, "addUnitTime": "0.5", **values}
    return ProviderParking.model_validate({**raw, "raw": raw})


def client_for(pages, *, fail_after=False):
    async def iterate(**_):
        for index, items in enumerate(pages, 1):
            yield SimpleNamespace(page_no=index, items=items, total_count=sum(map(len, pages)), total_count_known=True)
            if fail_after:
                raise RuntimeError("provider secret must not be stored")

    async def close():
        pass

    return lambda **_: SimpleNamespace(parking=SimpleNamespace(iter_pages=iterate), aclose=close)


def test_identity_and_provider_semantics():
    from app.core.time_utils import now_utc
    first = provider(None, instt_code="CITY", prkplceNm="제1주차장")
    second = provider(None, instt_code="CITY", prkplceNm="제2주차장")
    assert parking_source_key(first) != parking_source_key(second)
    row = parking_row(provider(latitude=26.1, addUnitCharge="200+400"), now_utc())
    assert row["latitude"] is None and row["longitude"] is None
    assert row["capacity"] == row["basic_fee"] == 0
    assert row["additional_minutes"] == 0.5 and row["additional_fee"] is None
    assert row["raw_json"]["addUnitCharge"] == "200+400"


def test_atomic_collection_current_set_cursor_and_public_projection(tmp_path):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/parking.db", seed_sample_data=False,
        enable_scheduler=False, public_parking_collection_enabled=True, public_parking_service_key="fake")
    engine, factory = create_engine_and_session_factory(settings.database_url)

    async def collect(pages, **kw):
        async with factory() as session:
            return await PublicParkingCollectionService(settings, client_factory=client_for(pages, **kw)).collect(session)

    async def run():
        await init_database(engine)
        assert (await collect([[provider("A")], [provider("B")]]))["stored"] == 2
        async with factory() as session:
            first = await parking_page(session, 1, None, None)
            assert first.has_more and first.next_cursor and len(first.items) == 1
            assert "raw" not in first.items[0].model_dump()
            assert "raw_json" not in first.items[0].model_dump()
        sql = []
        def capture(_, __, statement, *args):
            sql.append(statement)
        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        async with factory() as session:
            second = await parking_page(session, 1, first.next_cursor, None)
            assert second.items[0].provider_id == "B" and not second.has_more
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        assert len(sql) == 2 and all("public_parking_lots.raw_json" not in statement for statement in sql)
        async with factory() as session:
            with pytest.raises(HTTPException) as bad:
                await parking_page(session, 1, first.next_cursor, "different")
            assert bad.value.status_code == 422
        result = await collect([[provider("A", prkplceNm="실패 입력")]], fail_after=True)
        assert result["status"] == "failed"
        async with factory() as session:
            current = await parking_page(session, 10, None, None)
            assert len(current.items) == 2 and current.items[0].name == "시청 주차장"
            assert current.collection.last_attempt_failed
            assert await session.scalar(select(func.count()).select_from(RawApiResponse)) == 2
            failed = await session.scalar(select(CollectionRun).where(CollectionRun.status == "failed"))
            assert failed.error_message == "RuntimeError"
        assert (await collect([[provider("A", prkplceNm="시청 새 주차장")]]))["status"] == "success"
        async with factory() as session:
            current = await parking_page(session, 10, None, None)
            assert len(current.items) == 1 and current.items[0].id == first.items[0].id
            assert await session.scalar(select(func.count()).select_from(PublicParkingLot)) == 2
            with pytest.raises(HTTPException) as changed:
                await parking_page(session, 1, first.next_cursor, None)
            assert changed.value.status_code == 409
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("pages", [[], [[provider("A"), provider("A")]]])
def test_incomplete_catalog_is_not_published(tmp_path, pages):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/parking.db", seed_sample_data=False,
        enable_scheduler=False, public_parking_collection_enabled=True, public_parking_service_key="fake")
    engine, factory = create_engine_and_session_factory(settings.database_url)
    async def run():
        await init_database(engine)
        async with factory() as session:
            result = await PublicParkingCollectionService(settings, client_factory=client_for(pages)).collect(session)
            assert result["status"] == "failed"
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(PublicParkingLot)) == 0
            state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == SOURCE))
            assert state.last_success_at is None
        await engine.dispose()
    asyncio.run(run())


def test_public_and_service_api_auth_boundaries(tmp_path):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/parking.db", seed_sample_data=False,
        enable_scheduler=False, transport_service_export_token="x" * 40)
    engine, factory = create_engine_and_session_factory(settings.database_url)
    asyncio.run(init_database(engine))
    async def get_db():
        async with factory() as session:
            yield session
    app = FastAPI()
    app.include_router(build_public_parking_router(get_db), prefix="/v1")
    app.include_router(build_service_export_router(settings, get_db), prefix="/v1")
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.get("/v1/transport/parking-lots").json()["collection"]["stale"]
        assert client.get("/v1/transport/parking-lots/1").status_code == 404
        assert client.get("/v1/transport/parking-lots?cursor=invalid").status_code == 422
        path = "/v1/service/exports/parking-lots"
        assert client.get(path).status_code == 404
        assert client.get(path, headers={"x-kor-travel-transport-service-token": "x" * 40}).status_code == 503
    asyncio.run(engine.dispose())


def test_stored_parking_map_list_detail_and_atomic_refresh(client):
    settings = client.app.state.settings.model_copy(update={
        "public_parking_collection_enabled": True, "public_parking_service_key": "fake",
    })
    async def collect(pages, factory=None):
        async with client.app.state.session_factory() as session:
            service = PublicParkingCollectionService(settings, client_factory=factory or client_for(pages))
            return await service.collect(session)
    initial = [[provider("A"), provider("B", latitude=26), provider("C")]]
    assert asyncio.run(collect(initial))["status"] == "success"
    page = client.get("/v1/transport/parking-lots?limit=2").json()
    assert len(page["items"]) == 2 and page["has_more"]
    first_id = page["items"][0]["id"]
    detail = client.get(f"/v1/transport/parking-lots/{first_id}")
    assert detail.status_code == 200 and detail.json()["is_current"]
    assert "raw_json" not in detail.text and "source_key" not in detail.text
    path = "/v1/transport/features/places"
    response = client.get(path, params={"kind": "public_parking_lot", "include_unlocated": "true"})
    assert response.status_code == 200 and response.json()["total"] == 3
    bounds = {"min_longitude": 124, "max_longitude": 132, "min_latitude": 32, "max_latitude": 39.5}
    response = client.get(path, params={"kind": "public_parking_lot", "zoom": 8, **bounds})
    assert response.status_code == 200 and response.json()["total"] == 2 and response.json()["clustered"]
    assert sum(row["count"] for row in response.json()["clusters"]) == 2
    async def incomplete(**_):
        yield SimpleNamespace(page_no=1, items=[provider("D")], total_count=2, total_count_known=True)
    async def close():
        pass
    bad_factory = lambda **_: SimpleNamespace(parking=SimpleNamespace(iter_pages=incomplete), aclose=close)
    assert asyncio.run(collect([], bad_factory))["status"] == "failed"
    preserved = client.get("/v1/transport/parking-lots").json()
    assert len(preserved["items"]) == 3 and preserved["collection"]["last_attempt_failed"]
    assert asyncio.run(collect([[provider("C")]]))["status"] == "success"
    assert client.get("/v1/transport/parking-lots", params={"cursor": page["next_cursor"]}).status_code == 409
    assert client.get(f"/v1/transport/parking-lots/{first_id}").json()["is_current"] is False


def test_cancelled_collection_keeps_complete_catalog(tmp_path):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/parking.db", seed_sample_data=False,
        enable_scheduler=False, public_parking_collection_enabled=True, public_parking_service_key="fake")
    engine, factory = create_engine_and_session_factory(settings.database_url)
    async def interrupted(**_):
        yield SimpleNamespace(page_no=1, items=[provider("A")], total_count=2, total_count_known=True)
        raise asyncio.CancelledError
    async def close():
        pass
    async def run():
        await init_database(engine)
        async with factory() as session:
            with pytest.raises(asyncio.CancelledError):
                await PublicParkingCollectionService(settings, client_factory=lambda **_: SimpleNamespace(
                    parking=SimpleNamespace(iter_pages=interrupted), aclose=close)).collect(session)
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(PublicParkingLot)) == 0
            assert (await session.scalar(select(CollectionRun))).status == "cancelled"
        await engine.dispose()
    asyncio.run(run())


def test_monthly_job_uses_shared_owner_and_original_cadence():
    from app.dagster.definitions import definitions
    schedule = definitions.get_schedule_def("public_parking_reference_job_schedule")
    assert schedule.cron_schedule == "45 4 4 * *" and schedule.execution_timezone == "Asia/Seoul"
    assert schedule.job.name == "public_parking_reference_job"
