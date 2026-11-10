"""완료 본문은 한 번 저장하고, 유한 HTTP handle은 작은 FK만 발급한다."""
from __future__ import annotations

import hashlib
import json
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Text, bindparam, cast, delete, exists, insert, literal, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy import func
from sqlalchemy.exc import DBAPIError

from app.core.time_utils import now_utc, serialize_utc
from app.models import ReferenceExportArtifact, ReferenceExportArtifactHead, ReferenceExportArtifactItem, ServiceExportSnapshot
from app.services.export_current import BATCH_SIZE, MAX_SNAPSHOT_BYTES, MAX_SNAPSHOT_ITEMS, SnapshotRace


def _budget(started):
    if monotonic() - started > 15:
        raise HTTPException(503, "reference 본문 구성 시간 상한을 초과했습니다.")


async def _pin_current(session, artifact):
    table = ReferenceExportArtifactHead.__table__
    head = await session.get(ReferenceExportArtifactHead, (artifact.kind, artifact.scope_key))
    if head is not None and head.artifact_id == artifact.id:
        return
    if head is None:
        factory = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        row = await session.scalar(factory(table).values(kind=artifact.kind, scope_key=artifact.scope_key,
            artifact_id=artifact.id).on_conflict_do_nothing(index_elements=["kind", "scope_key"]).returning(table.c.artifact_id))
        if row is None:
            raise SnapshotRace()
    else:
        changed = await session.execute(update(table).where(table.c.kind == artifact.kind,
            table.c.scope_key == artifact.scope_key, table.c.artifact_id == head.artifact_id).values(artifact_id=artifact.id))
        if changed.rowcount != 1:
            raise SnapshotRace()
        session.expire(head)


async def _store_items(session, artifact_id, encoded, started):
    table = ReferenceExportArtifactItem.__table__
    for offset in range(0, len(encoded), BATCH_SIZE):
        _budget(started)
        bodies = encoded[offset:offset + BATCH_SIZE]
        if session.bind.dialect.name == "postgresql":
            # canonical JSON을 다시 loads/dumps하지 않고 한 bind의 JSON 배열로 전달한다.
            rows = func.jsonb_array_elements(cast(bindparam("bodies", type_=Text), JSONB)).table_valued(
                "value", with_ordinality="ordinal").render_derived(name="reference_rows")
            stmt = insert(table).from_select(["artifact_id", "ordinal", "payload"],
                select(literal(artifact_id), rows.c.ordinal + offset, rows.c.value))
            result = await session.execute(stmt, {"bodies": (b"[" + b",".join(bodies) + b"]").decode("utf-8")})
            if result.rowcount != len(bodies):
                raise HTTPException(503, "reference 본문 저장 수량이 일치하지 않습니다.")
        else:
            await session.execute(insert(table), [{"artifact_id": artifact_id, "ordinal": offset + i + 1,
                "payload": json.loads(body)} for i, body in enumerate(bodies)])
        _budget(started)


async def prepare_artifact(session, heads, spec, input_revision, *, started=None):
    started = monotonic() if started is None else started
    q = select(ReferenceExportArtifact).where(
        ReferenceExportArtifact.kind == spec.kind, ReferenceExportArtifact.scope_key == spec.scope,
        ReferenceExportArtifact.input_revision == input_revision)
    if session.bind.dialect.name == "postgresql":
        # FK를 pin하기 전 GC가 본문을 삭제하지 못하게 공유 key lock만 잡는다.
        q = q.with_for_update(read=True, key_share=True)
    artifact = await session.scalar(q)
    if artifact is not None:
        await _pin_current(session, artifact)
        return artifact, False
    encoded = [];size = count = 0;digest = hashlib.sha256()
    async for batch in spec.payload_batches(session, heads):
        _budget(started)
        for item in batch:
            body = json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            size += len(body);count += 1
            if size > MAX_SNAPSHOT_BYTES or count > MAX_SNAPSHOT_ITEMS:
                raise HTTPException(503, "reference 본문 크기 상한을 초과했습니다.")
            digest.update(body + b"\n");encoded.append(body)
    if not count:
        raise HTTPException(503, "빈 reference 본문을 승인하지 않습니다.")
    table = ReferenceExportArtifact.__table__
    factory = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    artifact_id = str(uuid4())
    admitted = await session.scalar(factory(table).values(id=artifact_id, kind=spec.kind, scope_key=spec.scope,
        input_revision=input_revision, source_collected_at=min(serialize_utc(h.confirmed_at) for h in heads),
        created_at=now_utc(), item_count=count, byte_count=size, content_digest=digest.hexdigest())
        .on_conflict_do_nothing(index_elements=["kind", "scope_key", "input_revision"]).returning(table.c.id))
    if admitted is None:
        raise SnapshotRace()
    await _store_items(session, artifact_id, encoded, started)
    artifact = await session.get(ReferenceExportArtifact, artifact_id)
    await _pin_current(session, artifact)
    return artifact, True


async def collect_unused_artifact(session):
    """현재 본문과 하나라도 남은 handle은 보존한다. 한 번에 불필요 본문 하나만 정리한다."""
    artifact = ReferenceExportArtifact
    q = select(artifact.id).where(
        ~exists(select(1).where(ReferenceExportArtifactHead.artifact_id == artifact.id)),
        ~exists(select(1).where(ServiceExportSnapshot.artifact_id == artifact.id)),
    ).order_by(artifact.created_at, artifact.id).limit(1)
    if session.bind.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    victim = await session.scalar(q)
    if victim is not None:
        try:
            async with session.begin_nested():
                await session.execute(delete(ReferenceExportArtifactItem).where(ReferenceExportArtifactItem.artifact_id == victim))
                await session.execute(delete(artifact).where(artifact.id == victim))
        except DBAPIError as exc:
            # 오래된 RR 뒤 새 handle/head가 pin했으면 FK가 보호한다. 현재 읽기를 실패시키지 않는다.
            if getattr(exc.orig, "sqlstate", None) != "23503":
                raise
            return 0
    return int(victim is not None)
