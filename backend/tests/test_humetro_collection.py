"""기관 정본의 세 운행 기준을 실제 호출 예산 안에서 저장하고 원천을 구분한다."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from kric import HUMETRO_PARSER_REVISION, HumetroTimetableEntry, HumetroTimetablePage, HumetroSchemaError, StationCodeInfo
from sqlalchemy import func,select

from app.db.session import create_engine_and_session_factory,init_database
from app.models import CollectionRun,KricTimetableAttempt,KricTimetableSnapshot
from app.services.kric_collection import KricTimetableCollectionService
from app.services.rail_timetable import stored_rail_timetables


class NoKric:
    async def __aenter__(self):return self
    async def __aexit__(self,*_):pass
    async def get_station_timetable(self,**_):raise AssertionError("부산 정본 경로에서 KRIC를 반복 호출하면 안 됩니다.")


class FakeHumetro:
    def __init__(self,fail_second=False):self.calls=[];self.fail_second=fail_second
    async def __aenter__(self):return self
    async def __aexit__(self,*_):pass
    async def get_station_page(self,*,line_code,station_code,direction=None):
        self.calls.append(direction)
        if direction=="1" and self.fail_second:raise HumetroSchemaError("invalid second page")
        chosen=direction or "0"
        rows=tuple(HumetroTimetableEntry("BS",line_code,station_code,"동매",day,time,"00:24" if time=="24:24" else time,"다대포해수욕장","95",chosen) for day in ("7","8","9") for time in ("09:03","24:24"))
        return HumetroTimetablePage(line_code,station_code,"동매",chosen,("0","1"),rows,"a"*64)


def service(settings,fake):
    codes=(StationCodeInfo(rail_operator_code="BS",rail_operator_name="부산교통공사",line_code="1",line_name="1호선",station_code="100",station_name="동매"),)
    value=KricTimetableCollectionService(settings,client_factory=lambda *a,**kw:NoKric(),humetro_client_factory=lambda **kw:fake,code_fetcher=AsyncMock(return_value=(codes,None)),sleep=AsyncMock())
    value._sync_calendar=AsyncMock()
    return value,codes


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_provider,prior_revision", [("kric", None), ("humetro", None), ("humetro", "20261101-script-text")])
async def test_provider_change_retries_recent_kric_no_data_once_then_stores_all_days(test_settings, prior_provider, prior_revision):
    settings=test_settings.model_copy(update={"kric_timetable_collection_enabled":True,"kric_service_key":"fake","kric_timetable_max_calls":2})
    engine,factory=create_engine_and_session_factory(settings.database_url);await init_database(engine)
    fake=FakeHumetro();collector,codes=service(settings,fake)
    async with factory() as session:
        station=(await collector._sync_codes(session,codes))[0]
        for day in ("7","8","9"):session.add(KricTimetableAttempt(station_id=station.id,day_code=day,attempted_at=datetime.now(UTC)-timedelta(minutes=10),outcome="no_data" if prior_provider=="kric" else "error",provider=prior_provider,provider_revision=prior_revision))
        if prior_provider=="humetro":session.add(CollectionRun(started_at=datetime.now(UTC),status="failed",trigger="dagster_kric_timetable"))
        await session.commit()
        result=await collector.collect(session)
        assert result['status']=='success' and result['provider_call_count']==2 and result['humetro_provider_call_count']==2
        assert result['stored_snapshot_count']==result['humetro_stored_snapshot_count']==3
        assert result['attempted_snapshot_count']==3 and result['deferred_snapshot_count']==0
        assert fake.calls==[None,"1"]
        attempts=(await session.scalars(select(KricTimetableAttempt))).all()
        assert all(row.provider=='humetro' and row.outcome=='stored' and row.provider_revision==HUMETRO_PARSER_REVISION for row in attempts)
        snapshots=(await session.scalars(select(KricTimetableSnapshot))).all()
        assert len(snapshots)==3 and all(len(row.items_json)==4 for row in snapshots)
        table=await stored_rail_timetables(session,[],"9",station_codes=[station])
        assert table.items[0].source_name=='부산교통공사' and table.items[0].time_precision=='minute'
        assert table.items[0].items[-1].departure_time=='24:24'
        assert table.items[0].items[0].destination_name=='다대포해수욕장'
        await collector.collect(session)
        assert fake.calls==[None,"1"]
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,fail_second",[(1,False),(2,True)])
async def test_no_partial_direction_publish_or_budget_overrun(test_settings,budget,fail_second):
    settings=test_settings.model_copy(update={"kric_timetable_collection_enabled":True,"kric_service_key":"fake","kric_timetable_max_calls":budget})
    engine,factory=create_engine_and_session_factory(settings.database_url);await init_database(engine)
    fake=FakeHumetro(fail_second);collector,codes=service(settings,fake)
    async with factory() as session:
        station=(await collector._sync_codes(session,codes))[0]
        old=datetime.now(UTC)-timedelta(days=2)
        session.add(KricTimetableSnapshot(station_id=station.id,day_code="9",collected_at=old,items_json=[{"train_number":"last-good","departure_time":"090000"}]))
        await session.commit()
        result=await collector.collect(session)
        assert len(fake.calls)<=budget
        assert result['stored_snapshot_count']==0
        assert await session.scalar(select(func.count()).select_from(KricTimetableSnapshot))==1
        stored=await session.scalar(select(KricTimetableSnapshot));assert stored.items_json[0]['train_number']=='last-good'
        if fail_second:
            assert result['status']=='failed' and result['failed_snapshot_count']==3
            assert all(row.outcome=='error' for row in (await session.scalars(select(KricTimetableAttempt))).all())
        else:
            assert not fake.calls and result['provider_call_count']==0
            assert await session.scalar(select(func.count()).select_from(KricTimetableAttempt))==0
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("auth_error", [None, "HumetroAuthError", "HumetroRateLimitError"])
async def test_current_parser_error_or_recent_auth_failure_does_not_retry(test_settings, auth_error):
    from app.models import CollectionRun
    settings=test_settings.model_copy(update={"kric_timetable_collection_enabled":True,"kric_service_key":"fake","kric_timetable_max_calls":2})
    engine,factory=create_engine_and_session_factory(settings.database_url);await init_database(engine)
    fake=FakeHumetro();collector,codes=service(settings,fake)
    async with factory() as session:
        station=(await collector._sync_codes(session,codes))[0]
        for day in ("7","8","9"):
            session.add(KricTimetableAttempt(station_id=station.id,day_code=day,attempted_at=datetime.now(UTC)-timedelta(minutes=10),outcome="error",provider="humetro",provider_revision=None if auth_error else HUMETRO_PARSER_REVISION))
        session.add(CollectionRun(started_at=datetime.now(UTC),status="failed",trigger="dagster_kric_timetable",error_message=auth_error))
        await session.commit()
        result=await collector.collect(session)
        assert not fake.calls
        if auth_error:assert result["status"]=="skipped"
    await engine.dispose()
