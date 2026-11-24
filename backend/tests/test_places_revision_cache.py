"""완전한 입력 vector와 RR/시간 경계가 증명한 장소 페이지 재사용."""
import asyncio
import json
import re
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, event, insert, select, text, update

from app import main
from app.core.time_utils import now_utc
from app.db.session import ALEMBIC_HEAD
from app.models import (
    Airport, BusTerminalReference, FerryPort, FuelLatestPrice, FuelStation,
    HighwayIncidentSnapshot, PublicParkingLot, RailStationReference,
    ReferenceExportInputRevision, RestAreaReference, TransportCollectionState,
)
from app.services import fuel_map_validation as validation, place_map_cache
from app.services.transport_collection import OPINET_SOURCE, FUEL_STALE_AFTER
from test_place_map_validation import _seed_places_and_prices

MODELS = (FuelStation, FuelLatestPrice, RailStationReference, FerryPort,
          BusTerminalReference, Airport, RestAreaReference, PublicParkingLot,
          HighwayIncidentSnapshot, TransportCollectionState)
PATH = "/v1/transport/features/places?limit=5000"


def run(client, action, *, commit=True):
    async def work():
        async with client.app.state.session_factory() as session:
            value = await action(session)
            if commit:
                await session.commit()
            return value
    return asyncio.run(work())


def body(response):
    assert response.status_code == 200, response.text
    data = response.json()
    data.pop("generated_at")
    return data


def builds(response):
    return int(response.headers["server-timing"].split('page_builds;desc="')[1].split('"')[0])


# 장소 지도 transaction은 시작 직후 남은 시한으로 서버 문장 상한을 둔다(place_map_admission.limit_statement_time).
STATEMENT_LIMIT = re.compile(r"SET LOCAL statement_timeout = '([1-9][0-9]*)ms'")


def statement_limit(statement: str) -> bool:
    found = STATEMENT_LIMIT.fullmatch(statement)
    return found is not None and int(found.group(1)) <= 25_000


def canonical(c, monkeypatch, path=PATH):
    async def no_proof(*args, **kwargs):
        return None
    with monkeypatch.context() as m:
        m.setattr(place_map_cache, "snapshot", no_proof)
        return body(c.get(path))


@pytest.fixture
def cached(client, monkeypatch):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL statement trigger/RR")
    async def seed(s):
        await _seed_places_and_prices(s)
        s.add(TransportCollectionState(source=OPINET_SOURCE, last_success_at=now_utc(), updated_at=now_utc()))
    run(client, seed)
    clock = [now_utc()]
    monkeypatch.setattr(main, "now_utc", lambda: clock[0])
    monkeypatch.setattr(validation, "_validated_items", validation.ValidatedFuelMapItems())
    client.app.state.settings.release_sha = "places-revision-regression"
    return client, clock


def test_warm_page_precedes_payload_reads_and_preserves_generated_at(cached, monkeypatch):
    c, clock = cached
    first = c.get(PATH)
    expected = body(first)
    assert builds(first) == 1
    statements = []
    engine = c.app.state.engine.sync_engine
    def seen(conn, cursor, sql, parameters, context, many):
        statements.append(sql)
    event.listen(engine, "before_cursor_execute", seen)
    try:
        clock[0] += timedelta(microseconds=1)
        warm = c.get(PATH)
    finally:
        event.remove(engine, "before_cursor_execute", seen)
    assert body(warm) == expected == canonical(c, monkeypatch)
    assert warm.json()["generated_at"] != first.json()["generated_at"]
    assert builds(warm) == 0 and len(statements) == 2 and statement_limit(statements[0])
    assert "r.versions" in statements[1] and "json_agg(" not in statements[1]


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__tablename__)
@pytest.mark.parametrize("action", ["insert", "update", "delete", "truncate"])
def test_all_input_tables_mutations_rebuild_before_reusing(cached, monkeypatch, model, action):
    c, _ = cached
    table = model.__table__
    async def prepare(s):
        row = (await s.execute(select(table).limit(1))).mappings().one()
        saved = dict(row)
        if action == "insert":
            await s.execute(text(f"TRUNCATE public.{table.name} CASCADE"))
        return saved
    saved = run(c, prepare)
    before = body(c.get(PATH))
    assert builds(c.get(PATH)) == 0

    async def mutate(s):
        clause = [col == saved[col.name] for col in table.primary_key.columns]
        if action == "insert":
            await s.execute(insert(table).values(**saved))
        elif action == "delete":
            await s.execute(delete(table).where(*clause))
        elif action == "truncate":
            await s.execute(text(f"TRUNCATE public.{table.name} CASCADE"))
        else:
            field, value = {
                "fuel_stations": ("name", "수정 주유소"),
                "fuel_latest_prices": ("price", Decimal("1900.25")),
                "rail_station_references": ("raw_item_json", {"스크린도어 설치유무": "없음"}),
                "ferry_ports": ("raw_item_json", {"_manual_location": {"revision": "changed"}}),
                "bus_terminal_references": ("city_name", "수정 도시"),
                "airports": ("name_ko", "수정 공항"),
                "rest_area_references": ("has_gas_station", False),
                "public_parking_lots": ("fee_info", "수정 요금"),
                "highway_incident_snapshots": ("message", "수정 돌발"),
                "transport_collection_states": ("last_error", "실패"),
            }[table.name]
            await s.execute(update(table).where(*clause).values(**{field: value}))
    run(c, mutate)
    changed = c.get(PATH)
    assert builds(changed) == 1
    assert body(changed) == canonical(c, monkeypatch)
    assert body(c.get(PATH)) == body(changed)
    assert builds(c.get(PATH)) == 0

@pytest.mark.parametrize("boundary", ["incident_future", "incident_24h", "fuel_stale"])
def test_clock_alone_expires_at_exact_business_boundaries(cached, monkeypatch, boundary):
    c, clock = cached
    start = clock[0]
    async def seed(s):
        if boundary == "fuel_stale":
            await s.execute(update(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE,
            ).values(last_success_at=start - FUEL_STALE_AFTER + timedelta(seconds=1), last_error=None))
        else:
            s.add(HighwayIncidentSnapshot(
                source="clock-fixture", identity_key=boundary, point_name=boundary,
                longitude=127, latitude=37, observed_at=start,
                collected_at=start + (timedelta(seconds=1) if boundary == "incident_future"
                                      else -timedelta(days=1) + timedelta(seconds=1)),
                raw_item_json={},
            ))
    run(c, seed)
    first = body(c.get(PATH))
    assert builds(c.get(PATH)) == 0
    clock[0] = start + timedelta(seconds=1)
    edge = c.get(PATH)
    assert builds(edge) == 1
    assert body(edge) == canonical(c, monkeypatch)
    clock[0] += timedelta(microseconds=1)
    after = c.get(PATH)
    assert body(after) == canonical(c, monkeypatch)
    if boundary == "fuel_stale":
        assert not first["fuel_prices_stale"] and after.json()["fuel_prices_stale"]
        assert first["items"] == after.json()["items"]
    elif boundary == "incident_future":
        assert first["kind_totals"]["highway_incident"] + 1 == after.json()["kind_totals"]["highway_incident"]
    else:
        assert first["kind_totals"]["highway_incident"] - 1 == after.json()["kind_totals"]["highway_incident"]
    assert body(c.get(PATH)) == body(after) and builds(c.get(PATH)) == 0


def test_clock_rollback_cannot_reuse_a_future_selection(cached, monkeypatch):
    c, clock = cached
    first = body(c.get(PATH))
    clock[0] -= timedelta(seconds=1)
    result = c.get(PATH)
    assert builds(result) == 1 and body(result) == canonical(c, monkeypatch)


def test_success_cohort_and_failure_recovery_are_fresh(cached, monkeypatch):
    from app.public_parking_routes import SOURCE
    c, clock = cached
    first = body(c.get(PATH))
    stamp = clock[0] + timedelta(minutes=1)
    async def new_generation(s):
        row = (await s.execute(select(PublicParkingLot.__table__).limit(1))).mappings().one()
        values = dict(row)
        values.pop("id")
        values.update(source_key="new-cohort", provider_id="new-cohort", name="새 완결 집합", last_seen_at=stamp)
        await s.execute(insert(PublicParkingLot).values(**values))
    run(c, new_generation)
    assert body(c.get(PATH)) == first  # 성공 pointer 교체 전에는 이전 집합.
    async def publish(s):
        await s.execute(update(TransportCollectionState).where(
            TransportCollectionState.source == SOURCE,
        ).values(last_success_at=stamp))
    run(c, publish)
    selected = c.get(PATH)
    assert builds(selected) == 1 and body(selected) == canonical(c, monkeypatch)
    parking = [v for v in selected.json()["items"] if v["kind"] == "public_parking_lot"]
    assert len(parking) == 1 and parking[0]["name"] == "새 완결 집합"
    async def failure(s):
        await s.execute(update(TransportCollectionState).where(
            TransportCollectionState.source == OPINET_SOURCE,
        ).values(last_error="失敗"))
    run(c, failure)
    failed = c.get(PATH)
    assert builds(failed) == 1 and failed.json()["fuel_prices_stale"]
    async def recover(s):
        await s.execute(update(TransportCollectionState).where(
            TransportCollectionState.source == OPINET_SOURCE,
        ).values(last_error=None, last_success_at=clock[0]))
    run(c, recover)
    recovered = c.get(PATH)
    assert builds(recovered) == 1 and not recovered.json()["fuel_prices_stale"]
    assert body(recovered) == canonical(c, monkeypatch)


@pytest.mark.parametrize("key", [
    "환승역 여부", "유실물 취급여부", "안전발판 유무", "스크린도어 설치유무", "승강장 연결여부",
])
def test_all_five_rail_raw_facilities_invalidate(cached, monkeypatch, key):
    c, _ = cached
    first = body(c.get(PATH))
    async def mutate(s):
        rows = (await s.scalars(select(RailStationReference))).all()
        for row in rows:
            row.raw_item_json = {**row.raw_item_json, key: "있음" if key in {"안전발판 유무", "승강장 연결여부"} else "없음"}
    run(c, mutate)
    result = c.get(PATH)
    assert builds(result) == 1 and body(result) == canonical(c, monkeypatch)
    assert body(result)["items"] != first["items"]


@pytest.mark.parametrize("bad", ["columns", "when", "event", "disabled"])
def test_untrusted_trigger_bypasses_and_restored_definition_invalidates(cached, monkeypatch, bad):
    c, _ = cached
    first = body(c.get(PATH))
    async def untrust(s):
        await s.execute(text("DROP TRIGGER kt_places_revision_update ON public.rail_station_references"))
        clause = {
            "columns": "AFTER UPDATE OF station_name",
            "when": "AFTER UPDATE",
            "event": "AFTER INSERT",
            "disabled": "AFTER UPDATE",
        }[bad]
        # WHEN은 statement trigger에서 허용되지 않으므로 실제 row trigger의 제한을 검증한다.
        per = "FOR EACH ROW WHEN (false)" if bad == "when" else "FOR EACH STATEMENT"
        await s.execute(text(f"CREATE TRIGGER kt_places_revision_update {clause} "
            f"ON public.rail_station_references {per} EXECUTE FUNCTION public.kt_places_revision()"))
        if bad == "disabled":
            await s.execute(text("ALTER TABLE public.rail_station_references DISABLE TRIGGER kt_places_revision_update"))
    run(c, untrust)
    try:
        bypass = c.get(PATH)
        assert builds(bypass) == 1 and body(bypass) == first
        async def mutate(s):
            await s.execute(update(RailStationReference).values(raw_item_json={"스크린도어 설치유무": "없음"}))
        run(c, mutate)
        changed = c.get(PATH)
        assert builds(changed) == 1 and body(changed) == canonical(c, monkeypatch)
        assert body(changed)["items"] != first["items"]
    finally:
        async def restore(s):
            await s.execute(text("DROP TRIGGER kt_places_revision_update ON public.rail_station_references"))
            await s.execute(text("CREATE TRIGGER kt_places_revision_update AFTER UPDATE ON "
                "public.rail_station_references FOR EACH STATEMENT EXECUTE FUNCTION public.kt_places_revision()"))
        run(c, restore)
    assert builds(c.get(PATH)) == 1  # 元 revision이 같아도 DDL 복원 anchor가 다르다.
    assert builds(c.get(PATH)) == 0


def test_read_committed_and_own_write_do_not_authorize_reuse(cached):
    c, clock = cached
    async def verify(s):
        await s.execute(text("SELECT 1"))
        assert await place_map_cache.snapshot(s, clock[0], "test-release", True) is None
    run(c, verify, commit=False)
    async def own_write(s):
        await s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        await s.execute(update(RestAreaReference).values(direction="own pending"))
        assert await place_map_cache.snapshot(s, clock[0], "test-release", True) is None
    run(c, own_write, commit=False)
    async def orm_pending(s):
        s.add(RestAreaReference(source="pending", identity_key="pending", name="pending",
              first_seen_at=clock[0], last_seen_at=clock[0], raw_item_json={}))
        assert await place_map_cache.snapshot(s, clock[0], "test-release", True) is None
    run(c, orm_pending, commit=False)


def test_same_rr_racing_writer_cannot_publish_new_rows_under_old_vector(cached, monkeypatch):
    c, _ = cached
    original = place_map_cache.snapshot
    wrote = False
    async def racing_snapshot(*args, **kwargs):
        nonlocal wrote
        result = await original(*args, **kwargs)
        if not wrote:
            wrote = True
            async def writer(s):
                await s.execute(update(RestAreaReference).values(name="동시 writer"))
            # 별도 엔진 connection의 실제 commit. 첫 RR snapshot은 이미 확정됐다.
            async with c.app.state.session_factory() as writer_session:
                await writer(writer_session)
                await writer_session.commit()
        return result
    monkeypatch.setattr(place_map_cache, "snapshot", racing_snapshot)
    first = c.get(PATH)
    assert builds(first) == 1
    assert all(v["name"] != "동시 writer" for v in first.json()["items"])
    next_request = c.get(PATH)
    assert builds(next_request) == 1
    assert any(v["name"] == "동시 writer" for v in next_request.json()["items"])
    assert body(next_request) == canonical(c, monkeypatch)
    assert builds(c.get(PATH)) == 0

def test_missing_vector_member_fails_closed_and_epoch_reset_invalidates(cached, monkeypatch):
    from uuid import uuid4
    c, _ = cached
    first = body(c.get(PATH))
    component = "places.rest_area_references"
    async def remove(s):
        row = await s.get(ReferenceExportInputRevision, component)
        value = (row.epoch, row.revision)
        await s.delete(row)
        return value
    epoch, revision = run(c, remove)
    try:
        assert c.get(PATH).status_code == 503
    finally:
        async def restore(s):
            s.add(ReferenceExportInputRevision(component=component, epoch=str(uuid4()), revision=revision))
        run(c, restore)
    assert builds(c.get(PATH)) == 1
    async def reset(s):
        await s.execute(update(RestAreaReference).values(name="epoch 교체"))
        await s.execute(update(ReferenceExportInputRevision).where(
            ReferenceExportInputRevision.component == component,
        ).values(epoch=str(uuid4()), revision=revision))
    run(c, reset)
    changed = c.get(PATH)
    assert builds(changed) == 1 and body(changed) != first
    assert body(changed) == canonical(c, monkeypatch)


def test_provider_bundle_and_query_namespace_do_not_alias(cached, monkeypatch):
    c, _ = cached
    first = body(c.get(PATH))
    original = main.get_airport_or_none
    def changed_lookup(code):
        value = original(code)
        return value.model_copy(update={"source": value.source + " 수정"}) if value else None
    monkeypatch.setattr(main, "get_airport_or_none", changed_lookup)
    changed = c.get(PATH)
    assert builds(changed) == 1 and body(changed) != first
    assert body(changed) == canonical(c, monkeypatch)
    for path in (
        "/v1/transport/features/places?kind=rail_station&limit=1",
        "/v1/transport/features/places?kinds=rail_station&limit=1",
        "/v1/transport/features/places?kinds=fuel_station,rail_station&limit=1&include_sources=false",
        "/v1/transport/features/places?kinds=rail_station,fuel_station&limit=2&include_unlocated=true",
        "/v1/transport/features/places?kinds=fuel_station,rail_station&product_codes=D047,B027",
        "/v1/transport/features/places?kinds=rail_station,ferry_port&query=%25",
    ):
        assert body(c.get(path)) == canonical(c, monkeypatch, path)


def test_engine_identity_and_shadow_schema_cannot_reuse_public_proof(cached):
    from uuid import uuid4
    from app.db.session import create_engine_and_session_factory
    c, clock = cached
    async def verify(s):
        key = (await place_map_cache.snapshot(s, clock[0], "scope-test", True))[0]
        other, sessions = create_engine_and_session_factory(c.app.state.settings.database_url)
        try:
            async with sessions() as second:
                second_key = (await place_map_cache.snapshot(second, clock[0], "scope-test", True))[0]
                assert key != second_key
        finally:
            await other.dispose()
    run(c, verify, commit=False)
    schema = "places_shadow_" + uuid4().hex
    async def create(s):
        await s.execute(text(f'CREATE SCHEMA "{schema}"'))
        await s.execute(text(f'CREATE TABLE "{schema}".fuel_stations (LIKE public.fuel_stations)'))
    run(c, create)
    try:
        async def shadow(s):
            await s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            await s.execute(text(f'SET LOCAL search_path="{schema}",public'))
            assert await place_map_cache.snapshot(s, clock[0], "scope-test", True) is None
        run(c, shadow, commit=False)
    finally:
        async def drop(s):
            await s.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        run(c, drop)


def test_page_and_input_caches_keep_separate_bounded_capacity_and_copy_safe_bytes(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime
    monkeypatch.setattr(validation, "_MAX_BYTES", 2048)
    monkeypatch.setattr(validation, "_MAX_ENTRIES", 3)
    monkeypatch.setattr(validation, "_MAX_PAGE_BYTES", 2048)
    monkeypatch.setattr(validation, "_MAX_PAGE_ENTRIES", 3)
    cache = validation.ValidatedFuelMapItems()
    now = datetime(2026, 11, 19, tzinfo=UTC)
    def worker(i):
        raw = json.dumps([{"id": i, "kind": "rail_station", "source": "s", "name": str(i),
                          "longitude": 127, "latitude": 37, "updated_at": now.isoformat()}])
        cache.read(raw)
        payload = b'{"items":[],"name":"' + str(i).encode() + b'"}'
        cache.put_page(("engine", i % 4), payload, now, now + timedelta(seconds=1))
        found = cache.get_page(("engine", i % 4), now)
        assert found is None or isinstance(found, bytes)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(40)))
    assert 0 < cache.bytes <= 2048 and 0 < cache.page_bytes <= 2048
    assert 0 < len(cache.entries) <= 3 and 0 < len(cache.pages) <= 3
    cache.put_page("boundary", b"{}", now, now + timedelta(seconds=1))
    assert cache.get_page("boundary", now) == b"{}"
    assert cache.get_page("boundary", now - timedelta(microseconds=1)) is None
    cache.put_page("boundary", b"{}", now, now + timedelta(seconds=1))
    assert cache.get_page("boundary", now + timedelta(seconds=1)) is None
    cache.put_page("oversize", b"x" * 2049, now, None)
    assert cache.get_page("oversize", now) is None

def test_independent_writer_finishes_while_fuel_transaction_is_open(cached, record_property):
    import time
    c, _ = cached
    async def verify():
        async with c.app.state.engine.connect() as a, c.app.state.engine.connect() as b:
            first, second = await a.begin(), await b.begin()
            try:
                await a.execute(text("UPDATE fuel_stations SET name=name WHERE id=(SELECT min(id) FROM fuel_stations)"))
                await b.execute(text("SET LOCAL lock_timeout='200ms'"))
                started = time.perf_counter()
                await b.execute(text("UPDATE airports SET name_ko=name_ko WHERE id=(SELECT min(id) FROM airports)"))
                record_property("independent_writer_ms", (time.perf_counter() - started) * 1000)
                assert first.is_active
            finally:
                await second.rollback()
                await first.rollback()
    asyncio.run(verify())


def migration_step(connection, target):
    from pathlib import Path
    from alembic.config import Config
    from alembic.runtime.environment import EnvironmentContext
    from alembic.script import ScriptDirectory
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == ALEMBIC_HEAD
    planner = script._downgrade_revs if target.startswith("0044") else script._upgrade_revs
    with EnvironmentContext(config, script, fn=lambda revision, _: planner(target, revision)) as context:
        context.configure(connection=connection, transactional_ddl=True, version_table_schema="public")
        context.run_migrations()


@pytest.mark.parametrize("lock_failure", [False, True])
def test_actual_migration_up_down_and_lock_failure_rollback(cached, record_property, lock_failure):
    import time
    from sqlalchemy.exc import DBAPIError
    c, _ = cached
    first = body(c.get(PATH))
    assert builds(c.get(PATH)) == 0

    async def verify():
        engine = c.app.state.engine
        async with engine.connect() as conn:
            async with conn.begin():
                old = (await conn.execute(text("SELECT component,epoch,revision FROM reference_export_input_revisions "
                                               "WHERE component NOT LIKE 'places.%' ORDER BY component"))).all()
                epochs = (await conn.execute(text("SELECT epoch FROM reference_export_input_revisions "
                                                  "WHERE component LIKE 'places.%' ORDER BY component"))).scalars().all()
                started = time.perf_counter()
                await conn.run_sync(lambda sync: migration_step(sync, "0044_places_read_indexes"))
                record_property("downgrade_ms", (time.perf_counter() - started) * 1000)
                assert await conn.scalar(text("SHOW lock_timeout")) == "2s"
            if lock_failure:
                async with engine.connect() as blocker:
                    txn = await blocker.begin()
                    try:
                        await blocker.execute(text("LOCK public.transport_collection_states IN ACCESS EXCLUSIVE MODE"))
                        with pytest.raises(DBAPIError) as exc:
                            async with conn.begin():
                                await conn.run_sync(lambda sync: migration_step(sync, "0045_places_input_revision"))
                        assert getattr(exc.value.orig, "sqlstate", None) == "55P03"
                    finally:
                        await txn.rollback()
                async with conn.begin():
                    assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == "0044_places_read_indexes"
                    assert await conn.scalar(text("SELECT count(*) FROM reference_export_input_revisions "
                                                  "WHERE component LIKE 'places.%'")) == 0
                    assert await conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'kt_places_revision_%'")) == 0
            async with conn.begin():
                started = time.perf_counter()
                await conn.run_sync(lambda sync: migration_step(sync, "0045_places_input_revision"))
                record_property("upgrade_ms", (time.perf_counter() - started) * 1000)
                assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == "0045_places_input_revision"
                after = (await conn.execute(text("SELECT component,epoch,revision FROM reference_export_input_revisions "
                                                 "WHERE component NOT LIKE 'places.%' ORDER BY component"))).all()
                assert old == after
                new = (await conn.execute(text("SELECT epoch FROM reference_export_input_revisions "
                                               "WHERE component LIKE 'places.%' ORDER BY component"))).scalars().all()
                assert len(new) == 10 and new != epochs
                assert await conn.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'kt_places_revision_%'")) == 40
    try:
        asyncio.run(verify())
    finally:
        # 실패해도 다음 독립 fixture를 위해 본래 head를 실제 upgrade한다.
        async def restore():
            async with c.app.state.engine.begin() as conn:
                await conn.run_sync(lambda sync: migration_step(sync, ALEMBIC_HEAD))
        asyncio.run(restore())
    fresh = c.get(PATH)
    assert builds(fresh) == 1 and body(fresh) == first

def test_warm_limit5000_keeps_full_body_with_one_statement_and_no_assembly(
    client, monkeypatch, record_property,
):
    import hashlib
    import time
    from app.models import FuelPriceSnapshot
    from app.services.transport_collection import upsert_latest_fuel_prices
    from test_read_performance import seed_places

    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("대형 PostgreSQL 투영")
    stamp = now_utc()
    async def seed(s):
        await seed_places(s, count=625, raw={"환승역 여부": "가능", "스크린도어 설치유무": "있음"})
        await s.execute(insert(FuelStation), [
            dict(source="large-fixture", identity_key=f"large-{i}", name=f"주유소 {i}",
                 longitude=127.1, latitude=37.5, query_level="sigungu",
                 sido_value="11", sido_name="서울", sigungu_value="110", sigungu_name="검산구",
                 source_kinds=[], first_seen_at=stamp, last_seen_at=stamp)
            for i in range(625)
        ])
        ids = (await s.scalars(select(FuelStation.id))).all()
        values = [dict(fuel_station_id=identity, source="large-fixture", product_code=code,
                       price=Decimal("1700.35"), observed_at=stamp, collected_at=stamp)
                  for identity in ids for code in ("B027", "B034", "D047", "C004", "K015")]
        await s.execute(insert(FuelPriceSnapshot), values)
        await upsert_latest_fuel_prices(s)
        s.add(TransportCollectionState(source=OPINET_SOURCE, last_success_at=stamp, updated_at=stamp))
    run(client, seed)
    client.app.state.settings.release_sha = "places-large-regression"
    monkeypatch.setattr(validation, "_validated_items", validation.ValidatedFuelMapItems())
    first = client.get(PATH)
    expected = body(first)
    work = {"first": first.headers["server-timing"], "warm": []}
    assert builds(first) == 1
    assert len(first.content) > 2_000_000 and len(expected["items"]) > 4000
    engine = client.app.state.engine.sync_engine
    statements = []
    def seen(conn, cursor, sql, parameters, context, many):
        statements.append(sql)
    event.listen(engine, "before_cursor_execute", seen)
    elapsed, cpu = [], []
    try:
        for _ in range(5):
            statements.clear()
            start, cpu_start = time.perf_counter(), time.process_time()
            result = client.get(PATH)
            elapsed.append((time.perf_counter() - start) * 1000)
            cpu.append((time.process_time() - cpu_start) * 1000)
            work["warm"].append(result.headers["server-timing"])
            assert body(result) == expected and builds(result) == 0
            assert statement_limit(statements[0])
            assert len(statements) == 2 and "r.versions" in statements[1]
    finally:
        event.remove(engine, "before_cursor_execute", seen)
    async def no_proof(*args, **kwargs):
        return None
    with monkeypatch.context() as m:
        m.setattr(place_map_cache, "snapshot", no_proof)
        start, cpu_start = time.perf_counter(), time.process_time()
        baseline = client.get(PATH)
        canonical_wall = (time.perf_counter() - start) * 1000
        canonical_cpu = (time.process_time() - cpu_start) * 1000
    assert body(baseline) == expected and builds(baseline) == 1
    work["canonical"] = baseline.headers["server-timing"]
    record_property("work_proof", json.dumps(work))
    record_property("canonical_wall_ms", canonical_wall)
    record_property("canonical_cpu_ms", canonical_cpu)
    record_property("warm_wall_ms", json.dumps(elapsed))
    record_property("warm_cpu_ms", json.dumps(cpu))
    record_property("response_bytes", len(first.content))
    record_property("returned_items", len(expected["items"]))
    record_property("body_sha256", hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest())
