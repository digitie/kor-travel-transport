"""코드 파일의 역명과 시간표는 위치파일 매핑 없이 조회한다."""
import asyncio
from datetime import UTC, datetime

from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import KricStationCode, KricTimetableSnapshot, RailServiceDay, RailStationReference
from app.services.rail_timetable import stored_rail_timetables


def seed(settings):
    async def run():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        async with factory() as session:
            now = now_utc()
            rows = [KricStationCode(operator_code="00", line_code=line, station_code=code,
                operator_name="공식기관", line_name=f"공식{line}선", station_name=name,
                rail_station_id=None, active=active, last_seen_at=now)
                for line, code, name, active in [("01","001","성복",True),("01","002","광교",True),("02","001","성복",True),("01","003","폐역",False)]]
            session.add_all(rows)
            await session.flush()
            session.add(KricTimetableSnapshot(station_id=rows[0].id, day_code="8", collected_at=now,
                items_json=[{"departure_time":"120000","terminal_station_code":"002","origin_station_code":"001","train_number":"0001"}]))
            await session.commit()
            result=[row.id for row in rows]
        await engine.dispose()
        return result
    return asyncio.run(run())


def test_catalog_and_timetable_do_not_require_a_name_or_place_mapping(client, test_settings):
    ids=seed(test_settings)
    response=client.get("/v1/transport/rail/stations")
    assert response.status_code == 200, response.text
    rows=response.json()["items"]
    assert len(rows) == 3
    assert rows[0]["provider_id"] == "00/01/001" and rows[0]["name"] == "성복"
    assert rows[0]["longitude"] is None and rows[0]["latitude"] is None
    assert rows[0]["source"] == "kric_station_codes"
    assert len({row["id"] for row in rows if row["name"]=="성복"}) == 2
    table=client.get(f"/v1/transport/rail/stations/{ids[0]}/timetable",params={"day_code":"8"})
    assert table.status_code == 200, table.text
    item=table.json()["items"][0]
    assert item["place_id"] is None and item["code_id"]==ids[0]
    assert item["status"] == "stored" and item["station_name"] == "성복"
    assert item["items"][0]["destination_name"] == "광교"
    assert item["items"][0]["origin_name"] == "성복"
    assert client.get(f"/v1/transport/rail/stations/{ids[3]}/timetable").status_code==404
    assert client.get("/v1/transport/rail/stations/0/timetable").status_code==422


def test_direct_code_reader_keeps_today_and_stale_rules(test_settings, monkeypatch):
    now=datetime(2026,10,31,3,0,tzinfo=UTC)
    monkeypatch.setattr("app.services.rail_timetable.now_utc",lambda:now)
    async def run():
        engine,factory=create_engine_and_session_factory(test_settings.database_url)
        await init_database(engine)
        async with factory() as session:
            station=KricStationCode(operator_code="S",line_code="01",station_code="001",operator_name="기관",line_name="노선",station_name="역명",rail_station_id=None,active=True,last_seen_at=now)
            session.add(station);session.add(RailServiceDay(service_date=now.date(),day_code="7",verified_at=now))
            await session.flush()
            session.add(KricTimetableSnapshot(station_id=station.id,day_code="7",collected_at=now,items_json=[{"departure_time":"120100"}]))
            await session.commit()
            result=await stored_rail_timetables(session,[],None,station_codes=[station])
            assert result.basis=="calendar" and result.items[0].next_departure.departure_time=="120100"
        await engine.dispose()
    asyncio.run(run())


def test_catalog_includes_only_sdk_confirmed_station_facilities(client, test_settings):
    ids = seed(test_settings)
    async def link():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        async with factory() as session:
            now = now_utc()
            place = RailStationReference(source="kric_public_file", identity_key="facility-test",
                station_name="성복", first_seen_at=now, last_seen_at=now,
                road_address="시험시 시험로 1", station_phone_number="02-1234-5678",
                raw_item_json={"스크린도어 설치유무":"있음", "유실물 취급여부":"있음", "안전발판 유무":"", "환승역 여부":"가능"})
            session.add(place)
            await session.flush()
            code = await session.get(KricStationCode, ids[0])
            code.rail_station_id = place.id
            await session.commit()
        await engine.dispose()
    asyncio.run(link())
    rows = client.get("/v1/transport/rail/stations").json()["items"]
    target = next(row for row in rows if row["id"] == ids[0])
    assert target["facilities"] == ["환승 가능", "유실물 취급", "스크린도어"]
    assert target["address"] == "시험시 시험로 1" and target["phone"] == "02-1234-5678"
    assert next(row for row in rows if row["id"] == ids[1])["facilities"] == []
