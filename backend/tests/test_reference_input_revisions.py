"""실제 PostgreSQL trigger가 정확한 입력 변경만 무효화한다."""
# ruff: noqa: F811
import asyncio
from uuid import uuid4

import pytest
from app.models import (
    RailStationReference,
    ReferenceExportInputRevision,
    ReferenceExportState,
)
from sqlalchemy import event, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from test_rail_export import PATH
from test_reference_export_reuse import _get, _prepare
from test_service_exports import HEADERS, _run, export_client  # noqa: F401


def _trace(client, action):
    statements = []
    engine = client.app.state.engine.sync_engine
    def seen(conn, cursor, sql, parameters, context, many):
        statements.append(sql)
    event.listen(engine, "before_cursor_execute", seen)
    try:
        response = action()
    finally:
        event.remove(engine, "before_cursor_execute", seen)
    return response, sum("string_agg" in sql for sql in statements)


def test_unrelated_database_commits_compute_zero_fingerprints_and_head_change_once(export_client):
    c = export_client
    _prepare(c)
    first = _get(c)
    assert first.status_code == 200, first.text
    # 같은 PG cluster의 다른 DB에서 실제 XID를 발급·commit한다. 사용자 데이터는 쓰지 않는다.
    async def unrelated_commit():
        url = make_url(c.app.state.settings.database_url).set(database="postgres")
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.scalar(text("SELECT pg_current_xact_id()"))
        finally:
            await engine.dispose()
    for _ in range(3):
        asyncio.run(unrelated_commit())
        result, calls = _trace(c, lambda: c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["ETag"]}, params={"limit": 1}))
        assert result.status_code == 304, result.text
        assert calls == 0
    async def change_head(s):
        await s.execute(update(ReferenceExportState).values(generation=str(uuid4())))
    _run(c, change_head)
    changed, calls = _trace(c, lambda: _get(c))
    assert changed.status_code == 200, changed.text
    assert calls == 1
    repeated, calls = _trace(c, lambda: _get(c))
    assert repeated.status_code == 200 and calls == 0


def test_same_head_source_update_recomputes_once_and_ignored_updates_never_do(export_client):
    c = export_client
    _prepare(c)
    first = _get(c)
    assert first.status_code == 200
    async def ignored(s):
        await s.execute(update(RailStationReference).values(station_name=RailStationReference.station_name))
        await s.execute(update(RailStationReference).values(raw_item_json={"not_used_in_export": "new"}))
        await s.execute(update(RailStationReference).where(RailStationReference.id == -1).values(station_name="none"))
    _run(c, ignored)
    same, calls = _trace(c, lambda: _get(c))
    assert same.status_code == 200 and calls == 0
    async def changed(s):
        await s.execute(update(RailStationReference).values(station_name="수동 SQL 변경"))
    _run(c, changed)
    changed, calls = _trace(c, lambda: _get(c))
    assert changed.status_code == 200 and calls == 1
    assert changed.json()["items"][0]["name"] == "수동 SQL 변경"
    again, calls = _trace(c, lambda: _get(c))
    assert again.status_code == 200 and calls == 0


def test_statement_revision_is_once_for_many_rows_and_rolls_back_atomically(export_client):
    c = export_client
    _prepare(c)
    async def verify(s):
        query = select(ReferenceExportInputRevision.revision).where(ReferenceExportInputRevision.component == "rail_source")
        before = await s.scalar(query)
        async with s.begin_nested():
            await s.execute(update(RailStationReference).values(station_name="모든 행"))
            assert await s.scalar(query) == before + 1
        revision = await s.scalar(query)
        with pytest.raises(RuntimeError):
            async with s.begin_nested():
                await s.execute(update(RailStationReference).values(station_name="rollback"))
                assert await s.scalar(query) == revision + 1
                raise RuntimeError("rollback")
        assert await s.scalar(query) == revision
    _run(c, verify)


def test_revision_rows_missing_fail_closed(export_client):
    c = export_client
    _prepare(c)
    first = _get(c)
    assert first.status_code == 200
    async def missing(s):
        await s.execute(text("DELETE FROM reference_export_input_revisions WHERE component='rail_source'"))
    _run(c, missing)
    try:
        response = _get(c)
        assert response.status_code == 503, response.text
    finally:
        async def restore(s):
            await s.execute(text("INSERT INTO reference_export_input_revisions(component,epoch,revision) VALUES ('rail_source',:epoch,1000000000)"), {"epoch": str(uuid4())})
        _run(c, restore)


def test_revision_epoch_reset_does_not_reuse_a_previous_cache_key(export_client):
    c = export_client
    _prepare(c)
    assert _get(c).status_code == 200
    async def change_and_reset(s):
        version = await s.scalar(select(ReferenceExportInputRevision.revision).where(ReferenceExportInputRevision.component == "rail_source"))
        await s.execute(update(RailStationReference).values(station_name="새 revision epoch"))
        await s.execute(update(ReferenceExportInputRevision).where(ReferenceExportInputRevision.component == "rail_source").values(revision=version, epoch=str(uuid4())))
    _run(c, change_and_reset)
    changed, calls = _trace(c, lambda: _get(c))
    assert changed.status_code == 200 and calls == 1
    assert changed.json()["items"][0]["name"] == "새 revision epoch"


@pytest.mark.parametrize("action", ["delete", "truncate"])
def test_deleted_or_truncated_source_cannot_serve_old_snapshot(export_client, action):
    c = export_client
    _prepare(c)
    first = _get(c)
    assert first.status_code == 200
    async def change(s):
        if action == "delete":
            await s.execute(text("DELETE FROM rail_station_references"))
        else:
            await s.execute(text("TRUNCATE rail_station_references CASCADE"))
    _run(c, change)
    result = c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["ETag"]}, params={"limit": 1})
    assert result.status_code == 503, result.text


def test_frozen_migration_tracks_all_fingerprint_source_columns_and_provider():
    import importlib.util
    from pathlib import Path

    from app.models import (
        BusTerminalReference,
        FerryPort,
        KricStationCode,
        ParkingCurrent,
    )
    from kortravelcommon.address_providers import VworldKakaoAddressResolver
    path = Path(__file__).parents[1] / "alembic/versions/0043_reference_input_revisions.py"
    spec = importlib.util.spec_from_file_location("revision_contract", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration._ADDRESS_PROVIDER_ID == VworldKakaoAddressResolver.provider_id
    for component, model in {"bus_source": BusTerminalReference, "ferry_source": FerryPort,
                             "rail_source": RailStationReference, "parking_source": ParkingCurrent,
                             "rail_codes": KricStationCode}.items():
        table, fields, _manual = migration._COMPONENTS[component]
        watched = set(fields.split())
        if component in {"bus_source", "ferry_source", "rail_source"}:
            watched |= {"latitude", "longitude"}
        assert table == model.__tablename__
        assert watched == {column.name for column in model.__table__.columns if column.name != "raw_item_json"}
