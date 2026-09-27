from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from kric import StationCodeInfo
from sqlalchemy import func, select

from app.db.session import create_engine_and_session_factory, init_database
from app.models import CollectionRun, KricStationCode, KricTimetableSnapshot, RailServiceDay, RailStationReference
from app.services.kric_collection import KricTimetableCollectionService, TRIGGER
from app.services.rail_timetable import stored_rail_timetables


def code(station="0312", name="테스트역", line="03"):
    return StationCodeInfo(rail_operator_code="S1", rail_operator_name="운영기관", line_code=line,
        line_name="3호선", station_code=station, station_name=name)


def place(now, name="테스트역", operator="운영기관"):
    return RailStationReference(source="kric_public_file", identity_key=f"{operator}/{name}",
        rail_operator_name=operator, operating_line_name="3호선", station_name=name,
        first_seen_at=now, last_seen_at=now)


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.fail_at = None
        self.wrong_identity = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def get_station_timetable(self, **params):
        self.calls.append(params)
        if self.fail_at == len(self.calls):
            raise RuntimeError("do-not-persist-test-secret")
        if self.wrong_identity:
            return [SimpleNamespace(rail_operator_code="OTHER", line_code="03", station_code="0312", day_code=params["day_code"])]
        return []


@pytest.mark.asyncio
@pytest.mark.parametrize("run_status", ["success", "failed", "running"])
async def test_48_hour_guard_includes_failed_and_abandoned_runs(test_settings, monkeypatch, run_status):
    now = datetime(2026, 9, 27, 3, tzinfo=UTC)
    monkeypatch.setattr("app.services.kric_collection.now_utc", lambda: now)
    settings = test_settings.model_copy(update={"kric_timetable_collection_enabled": True, "kric_service_key": "fake"})
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    fetch = AsyncMock(return_value=((code(),), None))
    async with factory() as session:
        session.add(CollectionRun(trigger=TRIGGER, started_at=now - timedelta(hours=47, minutes=59), status=run_status))
        await session.commit()
        result = await KricTimetableCollectionService(settings, code_fetcher=fetch).collect(session)
    assert result["status"] == "skipped"
    fetch.assert_not_awaited()
    await engine.dispose()


@pytest.mark.asyncio
async def test_budget_empty_success_mapping_and_no_request_on_second_run(test_settings):
    settings = test_settings.model_copy(update={"kric_timetable_collection_enabled": True, "kric_service_key": "fake", "kric_timetable_max_calls": 2})
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    fake, sleep = FakeClient(), AsyncMock()
    fetch = AsyncMock(return_value=((code(), code("0313", "다른역")), None))
    service = KricTimetableCollectionService(settings, code_fetcher=fetch, client_factory=lambda *a, **kw: fake, sleep=sleep)
    async with factory() as session:
        session.add_all([place(datetime.now(UTC)), place(datetime.now(UTC), "다른역", "다른기관")])
        await session.commit()
        result = await service.collect(session)
        assert result["stored_snapshot_count"] == 2
        assert result["deferred_snapshot_count"] == 4
        assert result["linked_station_count"] == 1
        assert await session.scalar(select(func.count()).select_from(KricTimetableSnapshot)) == 2
        assert all(row.items_json == [] for row in (await session.scalars(select(KricTimetableSnapshot))).all())
        assert (await service.collect(session))["status"] == "skipped"
    assert len(fake.calls) == 2
    sleep.assert_awaited_once_with(5)
    fetch.assert_awaited_once()
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_identity", [False, True])
async def test_failure_keeps_previous_success_and_blocks_retry(test_settings, wrong_identity):
    settings = test_settings.model_copy(update={"kric_timetable_collection_enabled": True, "kric_service_key": "fake", "kric_timetable_max_calls": 3})
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    fake = FakeClient()
    fake.fail_at = 2
    fake.wrong_identity = wrong_identity
    service = KricTimetableCollectionService(settings, code_fetcher=AsyncMock(return_value=((code(),), None)), client_factory=lambda *a, **kw: fake, sleep=AsyncMock())
    async with factory() as session:
        with pytest.raises(RuntimeError) as raised:
            await service.collect(session)
        import traceback
        assert "do-not-persist-test-secret" not in "".join(traceback.format_exception(raised.value))
        assert await session.scalar(select(func.count()).select_from(KricTimetableSnapshot)) == (0 if wrong_identity else 1)
        run = await session.scalar(select(CollectionRun).where(CollectionRun.trigger == TRIGGER))
        assert run.status == "failed"
        assert "secret" not in run.error_message
        assert (await service.collect(session))["status"] == "skipped"
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [(), (code(), code()), (code(station=""),)])
async def test_bad_code_file_cannot_clear_existing_mapping(test_settings, rows):
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    await init_database(engine)
    async with factory() as session:
        service = KricTimetableCollectionService(test_settings)
        await service._sync_codes(session, (code(),))
        await session.commit()
        with pytest.raises(ValueError):
            await service._sync_codes(session, rows)
        assert (await session.scalar(select(KricStationCode))).active
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("period,status,source,hour,stale,expected", [
    (None, "success", "kasi_holiday_info", 3, False, "calendar"),
    ("8", "success", "kasi_holiday_info", 3, False, "selected_period"),
    (None, "sample", "sample_holiday_info", 3, False, "calendar_unavailable"),
    (None, "upstream_error", "kasi_holiday_info", 3, False, "calendar_unavailable"),
    (None, "success", "kasi_holiday_info", 17, False, "overnight_unresolved"),
    (None, "success", "kasi_holiday_info", 3, True, "calendar"),
])
async def test_read_models_avoid_invented_next_train(test_settings, monkeypatch, period, status, source, hour, stale, expected):
    now = datetime(2026, 9, 27, hour, tzinfo=UTC)
    monkeypatch.setattr("app.services.rail_timetable.now_utc", lambda: now)
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    await init_database(engine)
    async with factory() as session:
        if status == "success" and source == "kasi_holiday_info":
            session.add(RailServiceDay(service_date=(now + timedelta(hours=9)).date(), day_code="9", verified_at=now))
        target = place(now)
        session.add(target)
        await session.flush()
        station = KricStationCode(operator_code="S1", line_code="03", station_code="0312", operator_name="운영기관", line_name="3호선", station_name="테스트역", rail_station_id=target.id, active=True, last_seen_at=now)
        session.add(station)
        await session.flush()
        session.add(KricTimetableSnapshot(station_id=station.id, day_code=period or "9", collected_at=now - timedelta(hours=49 if stale else 1), items_json=[
            {"departure_time": "000030", "train_number": "0001"},
            {"departure_time": "235960", "train_number": "bad"},
            {"departure_time": "140030", "train_number": "0012"},
        ]))
        await session.commit()
        result = await stored_rail_timetables(session, [target], period)
        assert result.basis == expected
        if expected in {"calendar_unavailable", "overnight_unresolved"}:
            assert result.items[0].status == "day_unresolved"
        next_train = result.items[0].next_departure
        if expected == "calendar" and not stale:
            assert next_train.train_number == "0012"
        else:
            assert next_train is None
        if period or expected == "calendar":
            assert result.items[0].items[0].departure_time == "000030"
            assert result.items[0].stale == stale
    await engine.dispose()


def test_rail_api_input_boundaries_and_missing_place(client):
    for ids in ["", "-1", "0", "a", "1,2,3,4,5,6", "١", "2147483648", "999999999999999999999999"]:
        assert client.get("/v1/transport/rail/timetables", params={"place_ids": ids}).status_code == 422
    assert client.get("/v1/transport/rail/timetables", params={"place_ids": "999999"}).status_code == 404
    assert client.get("/v1/transport/rail/timetables", params={"place_ids": "2147483647"}).status_code == 404
    assert client.get("/v1/transport/rail/timetables", params={"place_ids": "1", "day_code": "0"}).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("status,source", [("success", "kasi_holiday_info"), ("sample", "sample_holiday_info"), ("upstream_error", "kasi_holiday_info")])
async def test_verified_calendar_only_and_preservation(test_settings, monkeypatch, status, source):
    now = datetime(2026, 9, 28, 3, tzinfo=UTC)  # 월요일을 공휴일 표본으로 지정한다.
    monkeypatch.setattr("app.services.kric_collection.now_utc", lambda: now)
    response = SimpleNamespace(status=status, source=source, items=[SimpleNamespace(local_date=now.date(), is_holiday=True)])
    lookup = AsyncMock(return_value=response)
    monkeypatch.setattr("app.services.kric_collection.HolidayService.get_holidays", lookup)
    settings = test_settings.model_copy(update={"data_go_kr_service_key": "fake"})
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    old = now - timedelta(days=3)
    async with factory() as session:
        session.add(RailServiceDay(service_date=now.date(), day_code="9", verified_at=old))
        await session.commit()
        await KricTimetableCollectionService(settings)._sync_calendar(session)
        await session.commit()
        rows = (await session.scalars(select(RailServiceDay).order_by(RailServiceDay.service_date))).all()
        assert rows[0].day_code == "9"
        if status == "success":
            assert len(rows) == 32
            assert rows[1].day_code == "8"
            assert rows[5].day_code == "7"
            assert rows[6].day_code == "9"
        else:
            assert len(rows) == 1
            assert rows[0].verified_at.replace(tzinfo=UTC) == old
    await engine.dispose()


@pytest.mark.asyncio
async def test_exact_48_hours_allows_one_batch_and_ambiguous_names_stay_unlinked(test_settings, monkeypatch):
    now = datetime(2026, 9, 27, 3, tzinfo=UTC)
    monkeypatch.setattr("app.services.kric_collection.now_utc", lambda: now)
    settings = test_settings.model_copy(update={"kric_timetable_collection_enabled": True, "kric_service_key": "fake", "kric_timetable_max_calls": 1})
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    fake = FakeClient()
    service = KricTimetableCollectionService(settings, code_fetcher=AsyncMock(return_value=((code(), code("different")), None)), client_factory=lambda *a, **kw: fake)
    async with factory() as session:
        session.add_all([place(now), CollectionRun(trigger=TRIGGER, started_at=now - timedelta(hours=48), status="failed")])
        await session.commit()
        result = await service.collect(session)
        assert result["status"] == "success"
        assert result["linked_station_count"] == 0
        assert len(fake.calls) == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_lease_survives_commits_and_releases(test_settings):
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    if engine.dialect.name != "postgresql":
        await engine.dispose()
        pytest.skip("PostgreSQL advisory lock 통합 검증")
    service = KricTimetableCollectionService(test_settings)
    async with factory() as first, factory() as second:
        async with service._lease(first) as acquired:
            assert acquired
            await first.commit()
            async with service._lease(second) as other:
                assert not other
        async with service._lease(second) as released:
            assert released
    await engine.dispose()


@pytest.mark.asyncio
async def test_incomplete_calendar_cannot_overwrite_saved_holiday(test_settings, monkeypatch):
    from app.services.holidays import HolidaySourceResponse
    now = datetime(2026, 9, 28, 3, tzinfo=UTC)
    old = now - timedelta(days=3)
    monkeypatch.setattr("app.services.kric_collection.now_utc", lambda: now)
    monkeypatch.setattr("app.services.holidays.KasiHolidayClient.fetch_month", AsyncMock(return_value=HolidaySourceResponse(
        source="kasi_holiday_info", endpoint="mock", request_params={}, status_code=200,
        body_text='[{"locdate":"20260928","isHoliday":"Y"}]',
    )))
    settings = test_settings.model_copy(update={"data_go_kr_service_key": "fake"})
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    async with factory() as session:
        session.add(RailServiceDay(service_date=now.date(), day_code="9", verified_at=old))
        await session.commit()
        await KricTimetableCollectionService(settings)._sync_calendar(session)
        await session.commit()
        saved = await session.get(RailServiceDay, now.date())
        assert saved.day_code == "9"
        assert saved.verified_at.replace(tzinfo=UTC) == old
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("count,items", [
    (None, []), ("bad", []), (0.0, []), (False, []),
    (0, [{"locdate": "20260928", "dateName": "휴일", "isHoliday": "Y"}]),
])
async def test_actual_kasi_parser_cannot_turn_unverified_month_into_weekday(
    test_settings, monkeypatch, count, items,
):
    from kasi._http import KasiHttpResult
    now = datetime(2026, 9, 28, 3, tzinfo=UTC)
    old = now - timedelta(days=3)
    monkeypatch.setattr("app.services.kric_collection.now_utc", lambda: now)
    body = {"items": {"item": items}, "pageNo": 1, "numOfRows": 50}
    if count is not None:
        body["totalCount"] = count
    # Page를 가짜로 만들지 않고 고정 provider의 _get_page/모델 변환을 그대로 통과한다.
    monkeypatch.setattr("kasi._http.KasiHttp.get_result", AsyncMock(return_value=KasiHttpResult(
        body=body, request={}, response={"status_code": 200},
    )))
    settings = test_settings.model_copy(update={"data_go_kr_service_key": "fake"})
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    async with factory() as session:
        session.add(RailServiceDay(service_date=now.date(), day_code="9", verified_at=old))
        await session.commit()
        await KricTimetableCollectionService(settings)._sync_calendar(session)
        await session.commit()
        saved = await session.get(RailServiceDay, now.date())
        assert saved.day_code == "9"
        assert saved.verified_at.replace(tzinfo=UTC) == old
    await engine.dispose()


@pytest.mark.asyncio
async def test_wait_cannot_start_request_after_batch_deadline(test_settings, monkeypatch):
    start = datetime(2026, 9, 27, 3, tzinfo=UTC)
    clock = [start]
    monkeypatch.setattr("app.services.kric_collection.now_utc", lambda: clock[0])
    settings = test_settings.model_copy(update={"kric_timetable_collection_enabled": True, "kric_service_key": "fake"})
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    fake = FakeClient()
    original = fake.get_station_timetable
    async def fetch(**params):
        result = await original(**params)
        clock[0] = start + timedelta(hours=3, seconds=-1)
        return result
    async def sleep(seconds):
        clock[0] += timedelta(seconds=seconds)
    fake.get_station_timetable = fetch
    service = KricTimetableCollectionService(settings, code_fetcher=AsyncMock(return_value=((code(),), None)), client_factory=lambda *a, **kw: fake, sleep=sleep)
    async with factory() as session:
        result = await service.collect(session)
        assert result["stored_snapshot_count"] == 1
        assert len(fake.calls) == 1
    await engine.dispose()


def test_provider_coverage_counts_active_codes_and_freshness(client):
    import asyncio
    async def seed():
        now = datetime.now(UTC)
        async with client.app.state.session_factory() as session:
            target = place(now)
            session.add(target)
            await session.flush()
            for index in range(3):
                station = KricStationCode(operator_code="S1", line_code="03", station_code=str(index), operator_name="운영기관", line_name="3호선", station_name=f"역{index}", rail_station_id=target.id if index == 0 else None, active=index < 2, last_seen_at=now)
                session.add(station)
                await session.flush()
                session.add(KricTimetableSnapshot(station_id=station.id, day_code="9", collected_at=now - timedelta(hours=49 if index == 1 else 1), items_json=[]))
            await session.commit()
    asyncio.run(seed())
    coverage = client.get("/v1/transport/providers").json()["kric_coverage"]
    assert coverage["station_count"] == 2
    assert coverage["linked_station_count"] == 1
    assert coverage["expected_snapshots"] == 6
    assert coverage["stored_snapshots"] == 2
    assert coverage["fresh_snapshots"] == 1
    assert coverage["oldest_collected_at"]


@pytest.mark.asyncio
@pytest.mark.parametrize("age,status", [(1, "throttled"), (49, "not_collected")])
async def test_skipped_kric_guard_is_visible_without_claiming_collection(test_settings, monkeypatch, age, status):
    from app.services.provider_status import provider_status
    now = datetime(2026, 9, 27, 4, tzinfo=UTC)
    monkeypatch.setattr("app.services.provider_status.now_utc", lambda: now)
    settings = test_settings.model_copy(update={"kric_timetable_collection_enabled": True, "kric_service_key": "fake"})
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    async with factory() as session:
        session.add(CollectionRun(started_at=now - timedelta(hours=age), finished_at=now, trigger=TRIGGER, status="skipped"))
        await session.commit()
        response = await provider_status(session, settings)
        item = next(item for item in response.items if item.source == "kric_timetable")
        assert item.status == status
        assert item.last_success_at is None
        assert item.last_started_at is None
        assert item.next_due_at == (now + timedelta(hours=48 - age))
        assert item.error_code is None
    await engine.dispose()
