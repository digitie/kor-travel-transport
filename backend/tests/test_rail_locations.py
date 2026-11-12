"""#179: 같은 상세 주소만 채택하고 source 재수집·범위·기존 페이지 계약을 보존한다."""

# ruff: noqa: F811

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from app.core.config import Settings
from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import BusTerminalReference, RailStationReference, RawApiResponse
from app.services.place_locations import PlaceLocationCollectionService, _province
from app.services.rail_locations import (
    choose_rail_address,
    preserve_rail_address_location,
    rail_address_query,
    rail_address_signature,
)
from sqlalchemy import select
from test_service_exports import HEADERS, _run, export_client  # noqa: F401

ADDRESS = "전남광주 여수시 망양로 2"


def response():
    return {"status": "OK", "refined": {"text": "전남광주통합특별시 여수시 망양로 2 (덕충동)",
        "structure": {"level1": "전남광주통합특별시", "level2": "여수시", "level4L": "망양로", "level5": "2"}},
        "result": {"crs": "EPSG:4326", "point": {"x": "127.74889", "y": "34.75311"}}}


def test_complete_road_address_and_province_aliases():
    point = choose_rail_address(response(), address=ADDRESS, address_type="road", province=_province)
    assert point["latitude"] == 34.75311 and point["longitude"] == 127.74889
    assert rail_address_query(SimpleNamespace(road_address=ADDRESS, lot_address=None)) == (ADDRESS, "road")
    assert rail_address_query(SimpleNamespace(road_address="전남광주 여수시 덕충동", lot_address=None)) is None
    for short, full in [("경북", "경상북도"), ("전북", "전북특별자치도"), ("충남", "충청남도")]:
        assert _province(short) == _province(full)


@pytest.mark.parametrize("change", [
    lambda v: v.update(status="NOT_FOUND"),
    lambda v: v["result"].update(crs="EPSG:3857"),
    lambda v: v["result"]["point"].update(x="NaN"),
    lambda v: v["result"]["point"].update(y="Infinity"),
    lambda v: v["result"]["point"].update(x="1"),
    lambda v: v["refined"]["structure"].update(level1="전북특별자치도"),
    lambda v: v["refined"]["structure"].update(level2="순천시"),
    lambda v: v["refined"]["structure"].update(level4L="망양길"),
    lambda v: v["refined"]["structure"].update(level5="20"),
    lambda v: v["refined"]["structure"].pop("level5"),
    lambda v: v.pop("refined"),
])
def test_incomplete_wrong_building_or_ambiguous_location_is_rejected(change):
    value = response();change(value)
    assert choose_rail_address(value, address=ADDRESS, address_type="road", province=_province) is None


def test_verified_enrichment_survives_only_unchanged_source_identity():
    point = choose_rail_address(response(), address=ADDRESS, address_type="road", province=_province)
    row = SimpleNamespace(latitude=point["latitude"], longitude=point["longitude"], raw_item_json={
        "_vworld_address": {**point, "version": 1,
            "input_signature": rail_address_signature("여수엑스포", ADDRESS, None)}})
    incoming = {"station_name": "여수엑스포", "road_address": ADDRESS, "lot_address": None,
                "latitude": None, "longitude": None, "raw_item_json": {"source": "official"}}
    values = deepcopy(incoming);preserve_rail_address_location(row, values)
    assert values["latitude"] == point["latitude"]
    assert values["raw_item_json"]["source"] == "official"
    for field, new in [("station_name", "다른 역"), ("road_address", ADDRESS + "0"), ("lot_address", "새 지번")]:
        values = {**deepcopy(incoming), field: new};preserve_rail_address_location(row, values)
        assert values["latitude"] is None and "_vworld_address" not in values["raw_item_json"]
    values = {**deepcopy(incoming), "latitude": 35.1, "longitude": 127.1}
    preserve_rail_address_location(row, values)
    assert values["latitude"] == 35.1 and "_vworld_address" not in values["raw_item_json"]


def test_rail_only_stores_and_reuses_receipt_without_bus_calls(tmp_path, monkeypatch):
    calls = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def get_coord(self, address, address_type):
            calls.append((address, address_type));return {"response": response()}
        async def search_place(self, *_args, **_kwargs):
            raise AssertionError("rail-only run must not collect other place kinds")
    async def no_sleep(_): pass
    monkeypatch.setattr("app.services.place_locations.asyncio.sleep", no_sleep)
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path/'rail.sqlite'}", seed_sample_data=False,
                        place_location_collection_enabled=True, vworld_api_key="test-key")
    engine, factory = create_engine_and_session_factory(settings.database_url)
    async def run():
        await init_database(engine)
        async with factory() as session:
            now = now_utc()
            rail = RailStationReference(source="kric_general_portal", identity_key="kric_general_portal:korail:10279779",
                station_name="여수엑스포", road_address=ADDRESS, first_seen_at=now, last_seen_at=now, raw_item_json={"original": True})
            session.add_all([rail, BusTerminalReference(source="test", service_type="intercity", terminal_id="B1",
                terminal_name="여수", first_seen_at=now, last_seen_at=now, raw_item_json={})]);await session.commit()
            collector = PlaceLocationCollectionService(settings, client_factory=Client)
            result = await collector.collect(session, kinds={"rail"})
            assert result["rail_locations"] == result["provider_calls"] == 1
            assert result["bus_locations"] == result["port_locations"] == 0
            await session.refresh(rail)
            assert (rail.latitude, rail.longitude) == (34.75311, 127.74889)
            assert rail.last_seen_at.replace(tzinfo=now.tzinfo) == now
            assert rail.raw_item_json["original"] is True
            assert (await session.scalar(select(BusTerminalReference))).latitude is None
            assert (await collector.collect(session, kinds={"rail"}))["provider_calls"] == 0
            assert len((await session.scalars(select(RawApiResponse))).all()) == 1
        await engine.dispose()
    asyncio.run(run())
    assert calls == [(ADDRESS, "road")]


def test_coordinate_enrichment_invalidates_new_export_and_preserves_old_cursor(export_client, monkeypatch):
    from dataclasses import replace

    from test_general_rail_reference import service, station
    from test_rail_export import PATH, seed

    c = export_client
    collector, train = service(c)
    _run(c, seed)
    train.rows = [station("0001", "앞역"), replace(station("0002", "여수엑스포"), address=ADDRESS)]
    assert _run(c, collector.collect)["status"] == "success"
    first = c.get(PATH, headers=HEADERS, params={"limit": 10});assert first.status_code == 200
    old_page = c.get(PATH, headers=HEADERS, params={"limit": 3}).json();assert old_page["next_cursor"]

    class Client:
        def __init__(self, **_): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def get_coord(self, address, kind):
            assert (address, kind) == (ADDRESS, "road")
            return {"response": response()}
    async def no_sleep(_): pass
    monkeypatch.setattr("app.services.place_locations.asyncio.sleep", no_sleep)
    c.app.state.settings.place_location_collection_enabled = True
    c.app.state.settings.vworld_api_key = "test-key"
    async def enrich(s):
        return await PlaceLocationCollectionService(c.app.state.settings, client_factory=Client).collect(s, kinds={"rail"})
    assert _run(c, enrich)["rail_locations"] == 1
    changed = c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["etag"]}, params={"limit": 10})
    assert changed.status_code == 200
    located = next(v for v in changed.json()["items"] if v["name"] == "여수엑스포")
    assert (located["latitude"], located["longitude"]) == (34.75311, 127.74889)
    assert changed.json()["snapshot_id"] != first.json()["snapshot_id"]
    old_next = c.get(PATH, headers=HEADERS, params={"limit": 3, "cursor": old_page["next_cursor"]})
    assert old_next.status_code == 200
    assert old_next.json()["items"][0]["name"] == "여수엑스포"
    assert old_next.json()["items"][0]["latitude"] is None


def test_existing_job_accepts_rail_only_without_changing_schedules(monkeypatch):
    from app.dagster import definitions as d
    scopes = []
    class Collector:
        def __init__(self, _): pass
        async def collect(self, session, *, kinds=None):
            scopes.append(kinds)
            return {"status": "success", "rail_locations": 1}
    async def run_session(_settings, callback):
        return await callback(None)
    monkeypatch.setattr(d, "_settings", lambda: None)
    monkeypatch.setattr(d, "PlaceLocationCollectionService", Collector)
    monkeypatch.setattr(d, "_run_with_session", run_session)
    result = d.place_location_collection_job.execute_in_process(op_selection=["collect_place_locations"],
        run_config={"ops": {"collect_place_locations": {"config": {"rail_only": True}}}})
    assert result.success and scopes == [{"rail"}]
