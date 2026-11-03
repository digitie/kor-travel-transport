from __future__ import annotations

import asyncio
import json
from itertools import permutations
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
from app.services.public_parking_collection import (
    IncompletePublicParkingCollection, PublicParkingCollectionService, SOURCE, parking_row, parking_source_key,
)


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

    return lambda **_: SimpleNamespace(parking=SimpleNamespace(iter_file_pages=iterate), aclose=close)


def test_official_file_collection_needs_no_service_key(client):
    settings = client.app.state.settings.model_copy(update={
        "public_parking_collection_enabled": True,
        "public_parking_service_key": None, "data_go_kr_service_key": None,
    })
    def factory(**kwargs):
        assert "api_key" not in kwargs
        return client_for([[provider("KEYLESS")]])(**kwargs)

    async def collect():
        async with client.app.state.session_factory() as session:
            result = await PublicParkingCollectionService(settings, client_factory=factory).collect(session)
            assert result["status"] == "success" and result["stored"] == 1
            raw = await session.scalar(select(RawApiResponse).where(RawApiResponse.collection_run_id == result["run_id"]))
            assert raw.endpoint == "datagokr:parking.iter_file_pages"
            assert (await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == SOURCE))).last_success_at is not None
    asyncio.run(collect())


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


def test_number_is_bound_to_normalized_facility_and_unidentified_rows_are_rejected():
    original = provider("P-1", instt_code="CITY", prkplceNm="A 주차장", rdnmadr="서울 중구 1")
    normalized = provider("Ｐ－１", instt_code="ＣＩＴＹ", prkplceNm="Ａ　주차장", rdnmadr=" 서울　중구  １ ")
    assert parking_source_key(original) == parking_source_key(normalized)
    for changes in [{"prkplceNm": "B 주차장"}, {"rdnmadr": "서울 중구 2"}, {"instt_code": "OTHER"}]:
        assert parking_source_key(original) != parking_source_key(provider("P-1", **{
            "instt_code": "CITY", "prkplceNm": "A 주차장", "rdnmadr": "서울 중구 1", **changes,
        }))
    for number in [None, "P-1"]:
        for missing in [{"prkplceNm": ""}, {"rdnmadr": "", "lnmadr": ""}]:
            with pytest.raises(IncompletePublicParkingCollection) as error:
                parking_source_key(provider(number, instt_code="CITY", **missing))
            assert str(error.value) == "missing_identity"


def test_sdk_aliases_bind_raw_institution_to_identity():
    first = provider("SAME", insttCode="CITY", insttNm="시청")
    second = provider("SAME", insttCode="OTHER", insttNm="다른 기관")
    assert first.instt_code == "CITY" and first.instt_nm == "시청"
    assert parking_source_key(first) != parking_source_key(second)


def conflict_variants():
    common = {"insttCode": "CITY", "insttNm": "시청", "weekdayOperColseHhmm": "18:00"}
    return [
        provider("CONFLICT", **common, prkcmprt="176", monthCmmtkt="50000", pwdbsPpkZoneYn="Y",
                 spcmnt="공통 메모", weekdayOperOpenHhmm="09:00", referenceDate="2026-09-22"),
        provider("CONFLICT", **common, prkcmprt="177", monthCmmtkt="60000", pwdbsPpkZoneYn="N",
                 spcmnt="다른 메모", weekdayOperOpenHhmm="09:00", phoneNumber="02-111", referenceDate="2026-09-22"),
        provider("CONFLICT", **common, prkcmprt="176", monthCmmtkt="50000", pwdbsPpkZoneYn="Y",
                 spcmnt="공통 메모", weekdayOperOpenHhmm=None, phoneNumber="02-111", referenceDate=None, latitude=37.6),
    ]


def test_conflicting_variants_keep_only_common_fields_independent_of_page_and_order(client):
    settings = client.app.state.settings.model_copy(update={
        "public_parking_collection_enabled": True, "public_parking_service_key": "fake",
    })
    async def collect_and_read(pages):
        async with client.app.state.session_factory() as session:
            result = await PublicParkingCollectionService(settings, client_factory=client_for(pages)).collect(session)
            assert result["status"] == "success"
            assert result["received"] == 3 and result["stored"] == 1 and result["conflicts"] == 1
            row = await session.scalar(select(PublicParkingLot).where(PublicParkingLot.provider_id == "CONFLICT"))
            assert row.capacity is None and row.monthly_fee is None and row.disabled_parking is None
            assert row.phone is None and row.reference_date is None and row.basic_fee == 0
            assert row.latitude is None and row.longitude is None
            assert row.opening_hours_json["weekday_open"] is None
            assert row.opening_hours_json["weekday_close"] == "18:00"
            assert row.notes == "원천의 중복 자료가 서로 달라 일부 항목을 확인할 수 없습니다."
            assert row.raw_json["conflicting_fields"] == sorted([
                "capacity", "monthly_fee", "disabled_parking", "notes", "phone", "reference_date",
                "opening_hours_json.weekday_open", "latitude", "longitude",
            ])
            assert len(row.raw_json["source_records"]) == 3
            assert sorted(json.dumps(raw, sort_keys=True) for raw in row.raw_json["source_records"]) == sorted(
                json.dumps(item.raw, sort_keys=True) for item in conflict_variants())
            responses = (await session.scalars(select(RawApiResponse).where(
                RawApiResponse.collection_run_id == result["run_id"],
            ).order_by(RawApiResponse.id))).all()
            assert [raw for response in responses for raw in json.loads(response.body_text)] == [
                item.raw for page in pages for item in page]
            return row.id, row.raw_json
    expected = None
    for index, items in enumerate(permutations(conflict_variants())):
        pages = [list(items)] if index % 2 == 0 else [[item] for item in items]
        value = asyncio.run(collect_and_read(pages))
        expected = value if expected is None else expected
        assert value == expected
    response = client.get(f"/v1/transport/parking-lots/{expected[0]}")
    assert response.status_code == 200 and response.json()["capacity"] is None
    assert "raw_json" not in response.text and "source_records" not in response.text


def test_repeated_raw_after_conflicting_variant_rolls_back_whole_run(client):
    settings = client.app.state.settings.model_copy(update={
        "public_parking_collection_enabled": True, "public_parking_service_key": "fake",
    })
    async def run():
        async with client.app.state.session_factory() as session:
            baseline = await PublicParkingCollectionService(settings, client_factory=client_for([[provider("OLD")]])).collect(session)
            first, second, _ = conflict_variants()
            failed = await PublicParkingCollectionService(settings, client_factory=client_for([[first], [second], [first]])).collect(session)
            assert failed["status"] == "failed" and failed["error_code"] == "duplicate_identity"
            rows = (await session.scalars(select(PublicParkingLot))).all()
            assert len(rows) == 1 and rows[0].provider_id == "OLD"
            assert await session.scalar(select(func.count()).select_from(RawApiResponse).where(
                RawApiResponse.collection_run_id == failed["run_id"],
            )) == 0
            state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == SOURCE))
            assert state.last_error == "duplicate_identity" and state.last_success_at is not None
            assert (await session.get(CollectionRun, baseline["run_id"])).status == "success"
    asyncio.run(run())


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
            assert len(current.items) == 1 and current.items[0].id != first.items[0].id
            assert await session.scalar(select(func.count()).select_from(PublicParkingLot)) == 3
            with pytest.raises(HTTPException) as changed:
                await parking_page(session, 1, first.next_cursor, None)
            assert changed.value.status_code == 409
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("pages, code", [([], "empty_catalog"), ([[provider("A"), provider("A")]], "duplicate_identity")])
def test_incomplete_catalog_is_not_published(tmp_path, pages, code):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path}/parking.db", seed_sample_data=False,
        enable_scheduler=False, public_parking_collection_enabled=True, public_parking_service_key="fake")
    engine, factory = create_engine_and_session_factory(settings.database_url)
    async def run():
        await init_database(engine)
        async with factory() as session:
            result = await PublicParkingCollectionService(settings, client_factory=client_for(pages)).collect(session)
            assert result["status"] == "failed"
            assert result["error_code"] == code
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(PublicParkingLot)) == 0
            state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == SOURCE))
            assert state.last_success_at is None and state.last_error == code
            assert (await session.scalar(select(CollectionRun))).error_message == code
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
    bad_factory = lambda **_: SimpleNamespace(parking=SimpleNamespace(iter_file_pages=incomplete), aclose=close)
    incomplete_result = asyncio.run(collect([], bad_factory))
    assert incomplete_result["status"] == "failed" and incomplete_result["error_code"] == "total_count_mismatch"
    preserved = client.get("/v1/transport/parking-lots").json()
    assert len(preserved["items"]) == 3 and preserved["collection"]["last_attempt_failed"]
    assert asyncio.run(collect([[provider("C")]]))["status"] == "success"
    assert client.get("/v1/transport/parking-lots", params={"cursor": page["next_cursor"]}).status_code == 409
    assert client.get(f"/v1/transport/parking-lots/{first_id}").json()["is_current"] is False


def test_same_number_facilities_survive_and_exact_duplicate_rolls_back(client):
    settings = client.app.state.settings.model_copy(update={
        "public_parking_collection_enabled": True, "public_parking_service_key": "fake",
    })
    async def collect(pages):
        async with client.app.state.session_factory() as session:
            return await PublicParkingCollectionService(settings, client_factory=client_for(pages)).collect(session)
    facilities = [
        provider("SAME", instt_code="CITY", prkplceNm="제1주차장"),
        provider("SAME", instt_code="CITY", prkplceNm="제2주차장"),
        provider("SAME", instt_code="CITY", prkplceNm="제1주차장", rdnmadr="서울 중구 2"),
        provider("SAME", instt_code="OTHER", prkplceNm="제1주차장"),
    ]
    result = asyncio.run(collect([facilities[:2], facilities[2:]]))
    assert result["status"] == "success" and result["stored"] == 4
    current = client.get("/v1/transport/parking-lots").json()["items"]
    assert len(current) == 4 and len({row["id"] for row in current}) == 4
    assert {row["provider_id"] for row in current} == {"SAME"}
    old_id = current[0]["id"]
    edited = provider("SAME", instt_code="CITY", prkplceNm="변경된 주차장")
    assert asyncio.run(collect([[edited]]))["status"] == "success"
    assert client.get(f"/v1/transport/parking-lots/{old_id}").json()["is_current"] is False
    duplicate = asyncio.run(collect([[facilities[0]], [facilities[0]]]))
    assert duplicate["status"] == "failed" and duplicate["error_code"] == "duplicate_identity"
    preserved = client.get("/v1/transport/parking-lots").json()
    assert [row["name"] for row in preserved["items"]] == ["변경된 주차장"]
    async def check_preserved():
        async with client.app.state.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(PublicParkingLot)) == 5
            failed = await session.get(CollectionRun, duplicate["run_id"])
            assert failed.error_message == "duplicate_identity"
            state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == SOURCE))
            assert state.last_error == "duplicate_identity"
            assert await session.scalar(select(func.count()).select_from(RawApiResponse).where(
                RawApiResponse.collection_run_id == duplicate["run_id"],
            )) == 0
    asyncio.run(check_preserved())


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
                    parking=SimpleNamespace(iter_file_pages=interrupted), aclose=close)).collect(session)
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
