"""실제 PG의 0044 upgrade/downgrade가 장소 결과와 원자적 rollback을 보존한다."""
import asyncio
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from app.db.session import ALEMBIC_HEAD
from app.models import Base, FuelStation, HighwayIncidentSnapshot
from app.services.place_map_reads import place_queries, read_place_plans
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

OLD = "0043_reference_input_revisions"
NEW = "0044_places_read_indexes"
INDEXES = ("ix_fuel_stations_seen_id", "ix_highway_incidents_recent_cover")
NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
CASES = {
    "all": (False, None, None, None, 625),
    "bbox_edges": (False, (127., 37., 127.1, 37.1), None, None, 625),
    "unlocated": (True, None, None, None, 625),
    "unlocated_bbox": (True, (127., 37., 127.1, 37.1), None, None, 625),
    "source_A": (False, None, "A", None, 625),
    "escaped_query": (False, None, None, "_1%", 625),
    "empty_bbox": (False, (130., 40., 131., 41.), None, None, 625),
    "limit1": (False, None, None, None, 1),
    "all_items": (False, None, None, None, 5000),
}


def _step(connection, schema, direction):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == ALEMBIC_HEAD and script.get_revision(NEW).revision == NEW and len(NEW) <= 32
    target = NEW if direction == "upgrade" else OLD
    planner = script._upgrade_revs if direction == "upgrade" else script._downgrade_revs
    with EnvironmentContext(config, script, fn=lambda revision, _: planner(target, revision),
                            destination_rev=target) as context:
        context.configure(connection=connection, transactional_ddl=True, version_table_schema=schema)
        context.run_migrations()


def _rows():
    fuel, incidents = [], []
    for i in range(1, 2401):
        lon, lat = 127. + (i % 3) * .1, 37. + (i % 4) * .1
        if i % 47 == 0:
            lon = lat = None
        elif i % 53 == 0:
            lat = 95.
        fuel.append({"id": i, "source": "A" if i % 2 else "B", "identity_key": str(i),
            "name": f"station_{i}% literal", "longitude": lon, "latitude": lat, "address": f"address{i}",
            "query_level": "sigungu", "sido_value": "11", "sido_name": "서울", "sigungu_value": "110",
            "sigungu_name": "검산구", "source_kinds": [], "first_seen_at": NOW,
            "last_seen_at": NOW if i <= 1800 else NOW - timedelta(days=1)})
    for group in range(300):
        for rev in range(12):
            collected = NOW - timedelta(hours=3 * rev)
            if group % 31 == 0 and rev == 0:
                collected = NOW + timedelta(microseconds=1)
            lon, lat = 127. + (group % 3) * .1, 37. + (group % 4) * .1
            if group % 7 == 0 and rev == 0:
                lat = 95.
            elif group % 19 == 0 and rev == 0:
                lon = lat = None
            incidents.append({"id": group * 12 + rev + 1, "source": "A" if group % 2 else "B",
                "identity_key": str(group), "observed_at": NOW - timedelta(minutes=rev),
                "collected_at": collected, "longitude": lon, "latitude": lat,
                "point_name": f"point_{group}% literal", "route_name": "road", "message": f"message{group}"})
    for i, delta in enumerate((timedelta(days=-1), timedelta(days=-1, microseconds=-1),
                               timedelta(microseconds=1))):
        incidents.append(dict(incidents[1], id=4000+i, identity_key=f"edge{i}",
                              source="A", observed_at=NOW, collected_at=NOW+delta))
    return fuel, incidents


@pytest.fixture(scope="module")
def pg():
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("전용 PostgreSQL에서 실제 migration/결과 동등성을 검증한다")
    assert os.getenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE") == "1"
    schema = "places_indexes_" + uuid4().hex
    root = create_async_engine(url, poolclass=NullPool)
    engine = create_async_engine(url, poolclass=NullPool, connect_args={
        "command_timeout": 15, "server_settings": {"search_path": f"{schema},public"}})
    fuel, incidents = _rows()

    async def prepare():
        async with root.begin() as c:
            await c.execute(sa.schema.CreateSchema(schema))
        async with engine.begin() as c:
            assert await c.scalar(sa.text("SELECT current_schema()")) == schema
            # 실제 모델의 모든 열/제약/기존 index를 만들고 0044의 두 index만 되돌린 0043 fixture.
            await c.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[
                FuelStation.__table__, HighwayIncidentSnapshot.__table__], checkfirst=False))
            for name in INDEXES:
                await c.execute(sa.text(f'DROP INDEX "{schema}"."{name}"'))
            await c.execute(sa.text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
            await c.execute(sa.text("INSERT INTO alembic_version VALUES (:old)"), {"old": OLD})
            await c.execute(sa.insert(FuelStation), fuel)
            await c.execute(sa.insert(HighwayIncidentSnapshot), incidents)
    async def cleanup():
        try:
            async with root.begin() as c:
                await c.execute(sa.schema.DropSchema(schema, cascade=True))
        finally:
            await engine.dispose()
            await root.dispose()
    try:
        asyncio.run(prepare())
        yield SimpleNamespace(engine=engine, schema=schema, fuel=fuel, incidents=incidents)
    finally:
        asyncio.run(cleanup())


async def _state(c, pg, expected):
    assert await c.scalar(sa.text("SELECT version_num FROM alembic_version")) == expected
    rows = (await c.execute(sa.text("""SELECT x.relname, pg_get_indexdef(i.indexrelid),
        i.indisvalid, i.indisready FROM pg_index i JOIN pg_class x ON x.oid=i.indexrelid
        JOIN pg_namespace n ON n.oid=x.relnamespace
        WHERE n.nspname=:schema AND x.relname IN (:fuel,:incident)"""),
        {"schema": pg.schema, "fuel": INDEXES[0], "incident": INDEXES[1]})).all()
    if expected == OLD:
        assert rows == []
    else:
        definitions = {name: definition for name, definition, valid, ready in rows if valid and ready}
        assert set(definitions) == set(INDEXES)
        assert definitions[INDEXES[0]].endswith("USING btree (last_seen_at DESC, id DESC)")
        assert definitions[INDEXES[1]].endswith(
            "USING btree (collected_at) INCLUDE (id, source, identity_key, observed_at)")


def _matches(row, case, kind):
    include, bounds, source, query, _ = case
    lon, lat = row["longitude"], row["latitude"]
    if not include and not (lon is not None and lat is not None and -180 <= lon <= 180 and -90 <= lat <= 90):
        return False
    if source and row["source"] != source:
        return False
    if query:
        fields = ("name", "address") if kind == "fuel_station" else ("point_name", "route_name", "message")
        if not any(query.casefold() in (row.get(k) or "").casefold() for k in fields):
            return False
    return not bounds or (lon is not None and lat is not None
                         and bounds[0] <= lon <= bounds[2] and bounds[1] <= lat <= bounds[3])


async def _read(c, pg, case):
    include, bounds, source, query, limit = case
    def coordinates(model):
        conditions = [] if include else [model.longitude.between(-180, 180), model.latitude.between(-90, 90)]
        if source:
            conditions.append(model.source == source)
        if query:
            names = ("name", "address") if model is FuelStation else ("point_name", "route_name", "message")
            conditions.append(sa.or_(*[getattr(model, k).icontains(query, autoescape=True) for k in names]))
        if bounds:
            conditions += [model.longitude.between(bounds[0], bounds[2]),
                           model.latitude.between(bounds[1], bounds[3])]
        return conditions
    plans = place_queries(("fuel_station", "highway_incident"), coordinates, include, bool(bounds), NOW, limit)
    rows = await read_place_plans(c, plans)
    result = {kind: (total, [vars(row) for row in items]) for kind, (total, items) in rows.items()}
    latest = {}
    def rank(row):
        return row["observed_at"], row["collected_at"], row["id"]
    for row in pg.incidents:
        if NOW - timedelta(days=1) <= row["collected_at"] <= NOW:
            key = row["source"], row["identity_key"]
            if key not in latest or rank(row) > rank(latest[key]):
                latest[key] = row
    for kind, candidates, field in (("fuel_station", pg.fuel, "last_seen_at"),
                                     ("highway_incident", latest.values(), "observed_at")):
        expected = sorted((r for r in candidates if _matches(r, case, kind)),
                          key=lambda r: (r[field], r["id"]), reverse=True)
        assert result[kind][0] == len(expected)
        assert [r["id"] for r in result[kind][1]] == [r["id"] for r in expected[:limit]]
    return result


@pytest.mark.parametrize("name", CASES)
def test_upgrade_downgrade_preserves_full_items_count_order_and_boundaries(pg, name, record_property):
    async def run():
        async with pg.engine.connect() as c:
            initial = (await c.scalar(sa.text("SHOW lock_timeout")),
                       await c.scalar(sa.text("SHOW statement_timeout")))
            await c.commit()
            async with c.begin():
                await _state(c, pg, OLD)
                before = await _read(c, pg, CASES[name])
                started = time.perf_counter()
                await c.run_sync(lambda sync: _step(sync, pg.schema, "upgrade"))
                record_property("upgrade_seconds", time.perf_counter() - started)
                assert await c.scalar(sa.text("SHOW lock_timeout")) == "2s"
                assert await c.scalar(sa.text("SHOW statement_timeout")) == "2min"
                await _state(c, pg, NEW)
                assert await _read(c, pg, CASES[name]) == before
            assert (await c.scalar(sa.text("SHOW lock_timeout")),
                    await c.scalar(sa.text("SHOW statement_timeout"))) == initial
            await c.commit()
            async with c.begin():
                await _state(c, pg, NEW)  # upgrade와 version이 함께 commit되었다.
                started = time.perf_counter()
                await c.run_sync(lambda sync: _step(sync, pg.schema, "downgrade"))
                record_property("downgrade_seconds", time.perf_counter() - started)
                await _state(c, pg, OLD)
                assert await _read(c, pg, CASES[name]) == before
            async with c.begin():
                await _state(c, pg, OLD)
    asyncio.run(run())


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_second_index_lock_timeout_rolls_back_both_indexes_and_revision(pg, direction, record_property):
    async def run():
        if direction == "downgrade":
            async with pg.engine.begin() as c:
                await c.run_sync(lambda sync: _step(sync, pg.schema, "upgrade"))
        expected = OLD if direction == "upgrade" else NEW
        table = "highway_incident_snapshots" if direction == "upgrade" else "fuel_stations"
        try:
            async with pg.engine.connect() as writer:
                await writer.execute(sa.text(f"UPDATE {table} SET id=id WHERE id=1"))
                started = time.perf_counter()
                with pytest.raises(sa.exc.DBAPIError) as failure:
                    async with pg.engine.begin() as c:
                        await c.run_sync(lambda sync: _step(sync, pg.schema, direction))
                record_property("blocked_seconds", time.perf_counter() - started)
                assert failure.value.orig.sqlstate == "55P03"
                await writer.rollback()
            async with pg.engine.begin() as c:
                await _state(c, pg, expected)
                assert await c.scalar(sa.text(f"SELECT id FROM {table} WHERE id=1")) == 1
        finally:
            if direction == "downgrade":
                async with pg.engine.begin() as c:
                    await c.run_sync(lambda sync: _step(sync, pg.schema, "downgrade"))
    asyncio.run(run())
