import argparse
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text

from app.models import Airport, ParkingLot, ParkingSnapshot, ParkingStatisticsBucket
from app.services.legacy_parking_guard import ensure_legacy_import_allowed
from app.services.parking_statistics_archive import archive_parking_statistics
from test_parking_statistics_archive import AT, NOW, database, snapshot


def script(name):
    path = Path(__file__).parents[2] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def seed_archive(factory):
    async with factory() as session:
        session.add(snapshot(1, 0, 50))
        await session.commit()
        result = await archive_parking_statistics(session, checked_at=NOW)
        await session.commit()
        assert result["archived_buckets"] == 1


def legacy_source(path, module):
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection:
            for model in module.TABLES:
                model.__table__.create(connection)
            connection.execute(Airport.__table__.insert(), {"id": 1, "code": "CJU", "name_ko": "다른 공항",
                               "source": "kac", "created_at": AT, "updated_at": AT})
            connection.execute(ParkingLot.__table__.insert(), {"id": 1, "airport_id": 1, "source_lot_id": "OTHER",
                               "name": "다른 주차장", "is_active": True, "created_at": AT, "updated_at": AT})
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_empty_archive_allows_legacy_write_but_existing_archive_refuses(tmp_path, test_settings):
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as session:
            await ensure_legacy_import_allowed(session)
        await seed_archive(factory)
        async with factory() as session:
            with pytest.raises(RuntimeError, match="영구 주차 통계"):
                await ensure_legacy_import_allowed(session)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_legacy_entry_refuses_before_overwriting_existing_identities(tmp_path, test_settings, monkeypatch):
    engine, factory = await database(tmp_path, test_settings)
    try:
        await seed_archive(factory)
        source = tmp_path / "old.sqlite3"
        module = script("migrate_sqlite_to_postgres.py")
        legacy_source(source, module)
        monkeypatch.setattr(module, "Settings", lambda: test_settings.model_copy(
            update={"database_url": engine.url.render_as_string(hide_password=False)}))
        with pytest.raises(RuntimeError, match="영구 주차 통계"):
            await module.migrate(source)
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == 1
            assert await session.scalar(select(func.count()).select_from(ParkingStatisticsBucket)) == 1
            assert (await session.get(Airport, 1)).name_ko == "김포"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_legacy_entry_still_imports_and_sets_sequences_when_archive_is_empty(tmp_path, test_settings, monkeypatch):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("SQLite→PostgreSQL 이관의 실제 목적 DB 전용")
    engine, factory = await database(tmp_path, test_settings)
    try:
        module = script("migrate_sqlite_to_postgres.py")
        source = tmp_path / "old.sqlite3"
        legacy_source(source, module)
        monkeypatch.setattr(module, "Settings", lambda: test_settings)
        assert await module.migrate(source) == 0
        async with factory() as session:
            assert (await session.get(Airport, 1)).code == "CJU"
            assert (await session.get(ParkingLot, 1)).source_lot_id == "OTHER"
            assert await session.scalar(select(func.count()).select_from(ParkingStatisticsBucket)) == 0
            assert await session.scalar(text("SELECT nextval(pg_get_serial_sequence('parking_lots', 'id'))")) > 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_http_legacy_entry_refuses_before_fetching_any_history(tmp_path, test_settings, monkeypatch):
    engine, factory = await database(tmp_path, test_settings)
    calls = []
    try:
        await seed_archive(factory)
        module = script("migrate_http_history.py")
        monkeypatch.setattr(module, "Settings", lambda: test_settings.model_copy(
            update={"database_url": engine.url.render_as_string(hide_password=False)}))

        async def forbidden(*args, **kwargs):
            calls.append(args)
            raise AssertionError("금지된 이관의 외부 조회")

        monkeypatch.setattr(module, "fetch_json", forbidden)
        with pytest.raises(RuntimeError, match="영구 주차 통계"):
            await module.import_history(argparse.Namespace(source_base_url="https://legacy.invalid"))
        assert calls == []
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_archive_created_during_http_fetch_is_rechecked_before_reference_write(tmp_path, test_settings, monkeypatch):
    engine, factory = await database(tmp_path, test_settings)
    try:
        module = script("migrate_http_history.py")
        monkeypatch.setattr(module, "Settings", lambda: test_settings.model_copy(
            update={"database_url": engine.url.render_as_string(hide_password=False)}))

        async def fetch(*args, **kwargs):
            # preflight가 DB lock을 반환한 뒤 별도 통계 발행이 성공하는 실제 경합을 만든다.
            await seed_archive(factory)
            return [{"code": "GMP", "name_ko": "덮어쓸 이름", "parking_lots": []}]

        monkeypatch.setattr(module, "fetch_json", fetch)
        args = argparse.Namespace(source_base_url="https://legacy.invalid", concurrency=1, days=7, source="migration_http")
        with pytest.raises(RuntimeError, match="영구 주차 통계"):
            await module.import_history(args)
        async with factory() as session:
            assert (await session.get(Airport, 1)).name_ko == "김포"
            assert await session.scalar(select(func.count()).select_from(ParkingStatisticsBucket)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_legacy_import_refuses_while_collector_or_archive_holds_lease(tmp_path, test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("실제 PostgreSQL advisory lock 전용")
    engine, factory = await database(tmp_path, test_settings)
    try:
        async with factory() as lease:
            await lease.execute(text("SELECT pg_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"))
            async with factory() as session:
                with pytest.raises(RuntimeError, match="주차 수집·통계 작업 중"):
                    await ensure_legacy_import_allowed(session)
    finally:
        await engine.dispose()
