"""조회 밖에서 canonical 본문을 준비한다. provider 호출·source head 갱신은 하지 않는다."""
import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.time_utils import now_utc, serialize_utc
from app.services.export_current import SnapshotRace, _snapshot_transaction
from app.services.export_references import (
    _reference_heads,
    _valid_heads,
    reference_specs,
)
from app.services.reference_artifacts import collect_unused_artifact, prepare_artifact
from app.services.reference_export_revision import reference_payload_revision

logger = logging.getLogger(__name__)


async def warm_rail_reference_revision(session_factory, *, settings):
    """HTTP 요청과 같은 워커의 철도 입력 지문을 한 번 읽는다."""
    try:
        spec = next(spec for spec in reference_specs(settings) if spec.kind == "rail-stations-v1")
        async with asyncio.timeout(10), session_factory() as session:
            await _snapshot_transaction(session)
            await session.execute(text("SET TRANSACTION READ ONLY"))
            heads = await _reference_heads(session, spec)
            if _valid_heads(heads, spec):
                await reference_payload_revision(session, heads, spec.kind, settings.release_sha)
    except Exception as exc:  # noqa: BLE001 - 선택적 기동 작업의 실패가 종료를 방해하지 않는다.
        logger.warning("rail reference warmup failed error_type=%s", type(exc).__name__)


async def prepare_reference_exports_for_settings(settings):
    """동기 주소 갱신 job의 완료 뒤 사용하는 같은 canonical 준비 경로."""
    from app.db.session import create_engine_and_session_factory
    engine, factory = create_engine_and_session_factory(settings.database_url, collector=True)
    try:
        async with factory() as session:
            return await prepare_reference_exports(session, settings=settings)
    finally:
        await engine.dispose()


async def prepare_reference_exports(session, *, settings):
    if not settings.transport_map_current_enabled:
        return {"status": "disabled", "prepared": 0, "reused": 0, "kinds": []}
    results = []
    for spec in reference_specs(settings):
        for attempt in range(2):
            try:
                await _snapshot_transaction(session)
                heads = await _reference_heads(session, spec)
                if not _valid_heads(heads, spec):
                    await session.rollback()
                    results.append({"kind": spec.kind, "status": "source_unavailable"})
                    break
                revision = await reference_payload_revision(session, heads, spec.kind, settings.release_sha)
                if revision is None:
                    await session.rollback()
                    results.append({"kind": spec.kind, "status": "unsupported_revision"})
                    break
                source_status = "stale" if any(h.last_error is not None or now_utc() - serialize_utc(h.confirmed_at) > spec.max_age for h in heads) else "ok"
                artifact, created = await prepare_artifact(session, heads, spec, revision)
                await collect_unused_artifact(session)
                result = {"kind": spec.kind, "status": "prepared" if created else "reused", "artifact_id": artifact.id,
                          "item_count": artifact.item_count, "source_status": source_status}
                await session.commit()
                results.append(result)
                break
            except (SnapshotRace, DBAPIError) as exc:
                await session.rollback()
                if (isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) not in {"40001", "55P03"}) or attempt:
                    raise
            except BaseException:
                await session.rollback()
                raise
    prepared = sum(r["status"] == "prepared" for r in results)
    reused = sum(r["status"] == "reused" for r in results)
    return {"status": "success" if prepared + reused else "not_ready", "prepared": prepared, "reused": reused, "kinds": results}
