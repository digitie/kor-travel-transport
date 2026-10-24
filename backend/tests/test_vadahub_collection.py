import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import CollectionRun, FerryReferenceSnapshot
from app.schemas import FerryReferenceData, FerryReferenceRow
from app.services.vadahub_collection import SOURCES, VadaHubCollectionService


def payload(key):
    return FerryReferenceData(dataset=key, title=SOURCES[key][0], source="vadahub:test",
        source_url="https://vadahub.go.kr/renew/spaceData/index.do", source_version="2019-12-10",
        source_sha256="a" * 64, collected_at=now_utc(),
        items=[FerryReferenceRow(record_id="001", kind="route", departure="목포", arrival="제주")])


async def database(tmp_path):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'ferry.sqlite'}",
        vadahub_collection_enabled=True, vadahub_archive_directory=str(tmp_path / "archive"))
    engine, factory = create_engine_and_session_factory(settings.database_url)
    await init_database(engine)
    return settings, engine, factory


def test_partial_failure_retries_only_failed_source_and_preserves_previous(tmp_path):
    async def run():
        settings, engine, factory = await database(tmp_path)
        calls = []
        async def fetch(key):
            calls.append(key)
            if key == "ferry_routes":
                raise RuntimeError("upstream failure")
            return payload(key)
        async with factory() as session:
            service = VadaHubCollectionService(settings, fetcher=fetch)
            first = await service.collect(session)
            assert first["status"] == "partial_success"
            assert len(calls) == 4
            old = await session.get(FerryReferenceSnapshot, "passenger_routes")
            old.last_attempt_at = now_utc() - timedelta(days=8)
            await session.commit()
            previous = old.response_json
            calls.clear()
            async def retry(key):
                calls.append(key)
                if key == "passenger_routes":
                    raise RuntimeError("still failed")
                return payload(key)
            second = await VadaHubCollectionService(settings, fetcher=retry).collect(session)
            assert second["status"] == "partial_success"
            assert calls == ["passenger_routes", "ferry_routes"]
            await session.refresh(old)
            assert old.response_json == previous
            assert old.last_error == "RuntimeError"
            calls.clear()
            third = await VadaHubCollectionService(settings, fetcher=lambda key: fixed(key, calls)).collect(session)
            assert third["status"] == "success"
            assert calls == ["passenger_routes"]
        await engine.dispose()
    asyncio.run(run())


async def fixed(key, calls):
    calls.append(key)
    return payload(key)


@pytest.mark.parametrize("failure", ["empty", "duplicate", "wrong_dataset"])
def test_invalid_or_incomplete_dataset_is_not_promoted(tmp_path, failure):
    async def run():
        settings, engine, factory = await database(tmp_path)
        async def fetch(key):
            value = payload(key)
            if failure == "empty":
                value.items = []
            elif failure == "duplicate":
                value.items *= 2
            else:
                value.dataset = "official_terminals" if key != "official_terminals" else "passenger_routes"
            return value
        async with factory() as session:
            result = await VadaHubCollectionService(settings, fetcher=fetch).collect(session)
            assert result["failed_datasets"] == list(SOURCES)
            assert all(row.response_json is None for row in (await session.scalars(select(FerryReferenceSnapshot))).all())
            assert (await session.scalar(select(CollectionRun))).status == "partial_success"
        await engine.dispose()
    asyncio.run(run())


def test_cancel_keeps_committed_source_and_releases_lock(tmp_path):
    async def run():
        settings, engine, factory = await database(tmp_path)
        async def fetch(key):
            if key == "ferry_routes":
                raise asyncio.CancelledError()
            return payload(key)
        async with factory() as session:
            with pytest.raises(asyncio.CancelledError):
                await VadaHubCollectionService(settings, fetcher=fetch).collect(session)
            assert (await session.get(FerryReferenceSnapshot, "passenger_routes")).response_json
            assert (await session.scalar(select(CollectionRun))).status == "failed"
            calls = []
            result = await VadaHubCollectionService(settings, fetcher=lambda key: fixed(key, calls)).collect(session)
            assert result["status"] == "success"
            assert "passenger_routes" not in calls
        await engine.dispose()
    asyncio.run(run())


def test_ferry_reference_api_reads_saved_data_without_provider(client):
    async def seed():
        async with client.app.state.session_factory() as session:
            session.add(FerryReferenceSnapshot(dataset="passenger_routes", response_json=payload("passenger_routes").model_dump(mode="json"),
                last_attempt_at=now_utc(), last_error="NetworkError"))
            await session.commit()
    asyncio.run(seed())
    response = client.get("/v1/transport/ferry/reference")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 4
    assert items[0]["data"]["items"][0]["record_id"] == "001"
    assert items[0]["last_error"] == "NetworkError"
    assert items[1]["data"] is None


def test_native_job_reports_failure_after_committing_healthy_sources(tmp_path, monkeypatch):
    from app.dagster import definitions as dagster_definitions

    async def prepare():
        settings, engine, _ = await database(tmp_path)
        await engine.dispose()
        return settings
    settings = asyncio.run(prepare())

    async def fetch(key):
        if key == "passenger_routes":
            raise RuntimeError("upstream unavailable")
        return payload(key)
    service = VadaHubCollectionService(settings, fetcher=fetch)
    monkeypatch.setattr(dagster_definitions, "_settings", lambda: settings)
    monkeypatch.setattr(dagster_definitions, "VadaHubCollectionService", lambda _settings: service)
    result = dagster_definitions.vadahub_reference_collection_job.execute_in_process(raise_on_error=False)
    assert not result.success
    failure = result.failure_data_for_node("collect_vadahub_reference")
    assert "일부 배편 기준자료" in failure.user_failure_data.description

    async def verify():
        engine, factory = create_engine_and_session_factory(settings.database_url)
        async with factory() as session:
            rows = (await session.scalars(select(FerryReferenceSnapshot))).all()
            assert sum(row.response_json is not None for row in rows) == 3
            run = await session.scalar(select(CollectionRun))
            assert run.status == "partial_success" and run.finished_at is not None
            assert run.orchestrator_run_id == result.run_id
        await engine.dispose()
    asyncio.run(verify())
