"""실제 PostgreSQL에서 준비의 종류별 격리와 제한 정리(만료 handle → 미사용 본문)를 본다(감사 T23-12·T23 missed)."""
# ruff: noqa: F811
from datetime import timedelta

from sqlalchemy import func, select, text, update
from test_reference_export_reuse import _get, _prepare
from test_service_exports import _run, export_client  # noqa: F401

from app.core.time_utils import now_utc
from app.models import RailStationReference
from app.models import ReferenceExportArtifact as Artifact
from app.models import ReferenceExportArtifactHead as Head
from app.models import ServiceExportSnapshot as Snapshot
from app.services import export_current
from app.services import reference_export_preparation as prep


def _prepare_all(client):
    async def prepare(session):
        return await prep.prepare_reference_exports(session, settings=client.app.state.settings)
    return _run(client, prepare)


def test_preparation_collects_expired_handles_before_their_unused_bodies(export_client, monkeypatch):
    c = export_client;_prepare(c);moment = now_utc()
    assert _get(c).status_code == 200
    async def change(s):await s.execute(update(RailStationReference).values(station_name="갱신 역"))
    _run(c, change)
    assert _get(c).status_code == 200
    async def counts(s):
        return [await s.scalar(select(func.count()).select_from(model)) for model in (Artifact, Snapshot)]
    assert _run(c, counts) == [2, 2]
    # 만료 handle이 옛 본문을 붙들고 있다. 요청 경로가 아니라 준비가 handle부터 정리해 옛 본문을 놓아 준다.
    monkeypatch.setattr(export_current, "now_utc", lambda: moment + timedelta(days=2))
    result = _prepare_all(c)
    assert result["status"] == "success"
    rail = next(row for row in result["kinds"] if row["kind"] == "rail-stations-v1")
    assert rail["status"] == "reused" and rail["duration_ms"] >= 0
    assert result["gc"]["expired_handles"] == 2 and result["gc"]["unused_artifacts"] == 1
    assert "error" not in result["gc"]
    async def remaining(s):
        head = await s.scalar(select(Head).where(Head.kind == "rail-stations-v1"))
        return await s.get(Artifact, head.artifact_id) is not None, await counts(s)
    assert _run(c, remaining) == (True, [1, 0])
    again = _prepare_all(c)
    assert again["gc"]["expired_handles"] == 0 and again["gc"]["unused_artifacts"] == 0


def test_a_kind_that_fails_in_the_database_does_not_poison_the_next_kind(export_client, monkeypatch):
    c = export_client;_prepare(c)
    original = prep.reference_payload_revision
    async def broken(session, heads, kind, revision):
        if kind == "rail-stations-v1":
            await session.execute(text("SELECT * FROM reference_prepare_missing_table"))
        return await original(session, heads, kind, revision)
    monkeypatch.setattr(prep, "reference_payload_revision", broken)
    result = _prepare_all(c)
    rail = next(row for row in result["kinds"] if row["kind"] == "rail-stations-v1")
    assert rail["status"] == "failed" and rail["sqlstate"] == "42P01"
    # 실패 뒤 종류(parking)도 새 transaction에서 판정되고, 정리도 같은 session으로 끝난다.
    assert [row["kind"] for row in result["kinds"]][-1] == "parking-current-v1"
    assert result["kinds"][-1]["status"] != "failed"
    assert "error" not in result["gc"]
    assert result["status"] == "failed"  # 준비·재사용한 종류가 없다
    monkeypatch.setattr(prep, "reference_payload_revision", original)
    recovered = _prepare_all(c)
    assert recovered["status"] == "success" and recovered["prepared"] == 1


def test_preparing_the_same_body_as_another_builder_is_busy_then_reused(export_client, monkeypatch):
    """배포 직후 준비가 5분 공항 수집의 준비와 같은 본문을 두고 겹친 경우(Dagster run_group·owner 밖).

    다른 준비가 admission 행을 commit하지 않고 쥔 동안 짧은 잠금 상한의 준비는 55P03을 두 번 보고 `busy`로 끝난다
    (예외로 step을 실패시키지 않는다). 상대가 commit한 뒤의 준비는 그 본문을 재사용한다.
    """
    import asyncio

    from app.db.session import create_engine_and_session_factory
    from app.services.export_current import _snapshot_transaction
    from app.services.export_references import _reference_heads, reference_specs
    from app.services.reference_artifacts import prepare_artifact
    from app.services.reference_export_revision import reference_payload_revision

    c = export_client;_prepare(c)
    settings = c.app.state.settings
    monkeypatch.setattr(prep, "CONTENTION_RETRY_DELAY_SECONDS", (0.01, 0.02))

    async def scenario():
        engine, factory = create_engine_and_session_factory(settings.database_url, collector=True)
        try:
            async with factory() as holder, factory() as contender:
                spec = next(s for s in reference_specs(settings) if s.kind == "rail-stations-v1")
                await _snapshot_transaction(holder, lock_timeout_ms=5_000, statement_timeout_ms=60_000)
                heads = await _reference_heads(holder, spec)
                revision = await reference_payload_revision(holder, heads, spec.kind, settings.release_sha)
                _artifact, created = await prepare_artifact(holder, heads, spec, revision, budget_seconds=120)
                assert created
                busy = await prep.prepare_reference_exports(
                    contender, settings=settings, kinds=("rail-stations-v1",), collect_garbage=False,
                    lock_timeout_ms=200,
                )
                await holder.commit()
                reused = await prep.prepare_reference_exports(
                    contender, settings=settings, kinds=("rail-stations-v1",), collect_garbage=False,
                )
                return busy, reused
        finally:
            await engine.dispose()

    busy, reused = asyncio.run(scenario())
    assert busy["status"] == "deferred" and (busy["busy"], busy["failed"]) == (1, 0)  # 경합은 실패가 아니다
    assert busy["kinds"][0]["status"] == "busy" and busy["kinds"][0]["sqlstate"] == "55P03"
    assert reused["kinds"][0]["status"] == "reused" and reused["status"] == "success"


def test_request_path_gc_never_fails_a_read_after_a_concurrent_bulk_gc(export_client, monkeypatch):
    """요청이 RR snapshot을 잡은 뒤 준비의 대량 정리가 같은 만료 handle을 지우고 commit하면, 요청 경로의
    `expire_snapshots`(FOR UPDATE)는 40001을 낸다. 요청 경로 정리는 savepoint 안에서 그 경합만 버리고 읽기를 잇는다."""
    import asyncio

    import pytest
    from sqlalchemy.exc import DBAPIError

    from app.db.session import create_engine_and_session_factory
    from app.services.export_current import _snapshot_transaction, gc_quietly

    c = export_client;_prepare(c);moment = now_utc()
    assert _get(c).status_code == 200  # 만료될 handle 하나
    monkeypatch.setattr(export_current, "now_utc", lambda: moment + timedelta(days=2))
    settings = c.app.state.settings

    async def scenario(quiet):
        engine, factory = create_engine_and_session_factory(settings.database_url, collector=True)
        try:
            async with factory() as reader, factory() as bulk:
                await _snapshot_transaction(reader)
                assert await reader.scalar(select(func.count()).select_from(Snapshot)) >= 1  # RR snapshot 확정
                await _snapshot_transaction(bulk)
                assert await export_current.expire_snapshots(bulk, limit=2) >= 1
                await bulk.commit()
                if not quiet:
                    with pytest.raises(DBAPIError) as caught:
                        await export_current.expire_snapshots(reader)
                    await reader.rollback()
                    return getattr(caught.value.orig, "sqlstate", None)
                deleted = await gc_quietly(reader, export_current.expire_snapshots)
                # 같은 transaction이 계속 쓸 수 있다(읽기·handle 발급).
                still = await reader.scalar(select(func.count()).select_from(Artifact))
                await reader.commit()
                return deleted, still
        finally:
            await engine.dispose()

    assert asyncio.run(scenario(False)) == "40001"  # 재현: 감싸지 않으면 읽기 transaction이 실패한다
    assert _get(c).status_code == 200  # 다음 epoch handle
    monkeypatch.setattr(export_current, "now_utc", lambda: moment + timedelta(days=4))
    deleted, still = asyncio.run(scenario(True))
    assert deleted == 0 and still >= 1
