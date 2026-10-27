import asyncio
from datetime import timedelta

import pytest
from types import SimpleNamespace
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


@pytest.mark.parametrize("previous_failure", [True, False])
@pytest.mark.parametrize("publication_failure", [True, False])
def test_failed_archive_is_refetched_but_storage_only_resume_reuses_it(tmp_path, monkeypatch, previous_failure, publication_failure):
    from app.services import vadahub_collection as module
    now = now_utc()
    layer = SimpleNamespace(layer_id="500059", table_name="psnr_rute_l", history_date="2019-12-10")
    cached = SimpleNamespace(local_path=tmp_path / "cached.zip", collected_at=now,
        source_url="https://vadahub.go.kr/renew/spaceData/index.do", sha256="b" * 64)
    latest = [cached]
    downloads = []
    class Store:
        def __init__(self, root): pass
        async def recover(self): pass
        async def versions(self, _layer): return (SimpleNamespace(receipt=latest[0]),)
        async def put(self, receipt):
            latest[0] = receipt
            return SimpleNamespace(receipt=receipt)
    class Client:
        def __init__(self, **options): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def list_datasets(self): return (SimpleNamespace(dataset_id="63"),)
        async def list_layers(self, dataset): return (layer,)
        async def download(self, _layer, destination):
            downloads.append(destination)
            return SimpleNamespace(local_path=destination, collected_at=now,
                source_url=cached.source_url, sha256="a" * 64)
        async def load_file(self, path, **options):
            if previous_failure and path == cached.local_path:
                raise ValueError("cached archive still contains the broken schema")
            return [SimpleNamespace(record_id="001", layer=layer,
                attributes={"strpnt_nm": "목포", "dstntn_nm": "제주"})]
    monkeypatch.setattr(module, "LocalArchiveStore", Store)
    monkeypatch.setattr(module, "VadaHubFileClient", Client)

    async def run():
        settings, engine, factory = await database(tmp_path)
        async with factory() as session:
            for key in SOURCES:
                if key != "passenger_routes":
                    session.add(FerryReferenceSnapshot(dataset=key, response_json=payload(key).model_dump(mode="json"), last_attempt_at=now))
            if previous_failure:
                session.add(FerryReferenceSnapshot(dataset="passenger_routes", response_json=None, last_attempt_at=now, last_error="SchemaError"))
            await session.commit()
            original_commit = session.commit
            fail_publication = publication_failure
            async def commit():
                nonlocal fail_publication
                if fail_publication and any(isinstance(row, FerryReferenceSnapshot) and row.dataset == "passenger_routes"
                    and row.response_json is not None and row.last_error is None for row in session.new.union(session.dirty)):
                    fail_publication = False
                    raise ConnectionError("database publication interrupted after parsing")
                await original_commit()
            monkeypatch.setattr(session, "commit", commit)
            service = VadaHubCollectionService(settings)
            if publication_failure:
                with pytest.raises(ConnectionError):
                    await service.collect(session)
                assert len(downloads) == int(previous_failure)
            result = await service.collect(session)
            assert result["status"] == "success"
            assert len(downloads) == int(previous_failure)
            row = await session.get(FerryReferenceSnapshot, "passenger_routes")
            assert row.last_error is None
            assert row.response_json["source_sha256"] == ("a" if previous_failure else "b") * 64
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("previous_error", [None, "SchemaError"])
def test_due_refresh_downloads_a_fresh_archive_but_a_failed_retry_reuses_it(tmp_path, monkeypatch, previous_error):
    """정상 게시본의 7일 갱신은 새 원본을 받는다. due(다운로드 전 시도 시각)와 보관 시각이 어긋나도 지난 ZIP을 쓰지 않는다."""
    from app.services import vadahub_collection as module
    attempted = now_utc() - timedelta(days=8)
    now = attempted + timedelta(days=7, seconds=30)
    monkeypatch.setattr(module, "now_utc", lambda: now)
    layer = SimpleNamespace(layer_id="500059", table_name="psnr_rute_l", history_date="2019-12-10")
    # 지난 다운로드는 시도 60초 뒤에 보관됐다 — 보관 수명으로는 아직 7일 안이다.
    cached = SimpleNamespace(local_path=tmp_path / "cached.zip", collected_at=attempted + timedelta(seconds=60),
        source_url="https://vadahub.go.kr/renew/spaceData/index.do", sha256="b" * 64)
    downloads = []
    class Store:
        def __init__(self, root): pass
        async def recover(self): pass
        async def versions(self, _layer): return (SimpleNamespace(receipt=cached),)
        async def put(self, receipt): return SimpleNamespace(receipt=receipt)
    class Client:
        def __init__(self, **options): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def list_datasets(self): return (SimpleNamespace(dataset_id="63"),)
        async def list_layers(self, dataset): return (layer,)
        async def download(self, _layer, destination):
            downloads.append(destination)
            return SimpleNamespace(local_path=destination, collected_at=now, source_url=cached.source_url, sha256="a" * 64)
        async def load_file(self, path, **options):
            return [SimpleNamespace(record_id="001", layer=layer, attributes={"strpnt_nm": "목포", "dstntn_nm": "제주"})]
    monkeypatch.setattr(module, "LocalArchiveStore", Store)
    monkeypatch.setattr(module, "VadaHubFileClient", Client)

    async def run():
        settings, engine, factory = await database(tmp_path)
        async with factory() as session:
            for key in SOURCES:
                if key != "passenger_routes":
                    session.add(FerryReferenceSnapshot(dataset=key, response_json=payload(key).model_dump(mode="json"), last_attempt_at=now))
            session.add(FerryReferenceSnapshot(dataset="passenger_routes", response_json=payload("passenger_routes").model_dump(mode="json"),
                                               last_attempt_at=attempted, last_error=previous_error))
            await session.commit()
            result = await VadaHubCollectionService(settings).collect(session)
            assert result["status"] == "success"
            row = await session.get(FerryReferenceSnapshot, "passenger_routes")
            assert len(downloads) == (1 if previous_error is None else 0)
            assert row.response_json["source_sha256"] == ("a" if previous_error is None else "b") * 64
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("recording_step", ["rollback", "get", "commit"])
def test_cancel_survives_failure_recording_errors_and_releases_lock(tmp_path, monkeypatch, recording_step):
    async def run():
        settings, engine, factory = await database(tmp_path)
        cancellation = asyncio.CancelledError("original cancellation")
        cancelled = False
        async def fetch(key):
            nonlocal cancelled
            if key == "ferry_routes":
                cancelled = True
                raise cancellation
            return payload(key)
        async with factory() as session:
            original = getattr(session, recording_step)
            injected = False
            async def fail_recording(*args, **kwargs):
                nonlocal injected
                if cancelled and not injected:
                    injected = True
                    raise ConnectionError("failure recording unavailable")
                return await original(*args, **kwargs)
            with monkeypatch.context() as patch:
                patch.setattr(session, recording_step, fail_recording)
                with pytest.raises(asyncio.CancelledError) as caught:
                    await VadaHubCollectionService(settings, fetcher=fetch).collect(session)
                assert caught.value is cancellation
                assert injected
            assert (await session.get(FerryReferenceSnapshot, "passenger_routes")).response_json
            calls = []
            result = await VadaHubCollectionService(settings, fetcher=lambda key: fixed(key, calls)).collect(session)
            assert result["status"] == "success"
            assert "passenger_routes" not in calls
        await engine.dispose()
    asyncio.run(run())
