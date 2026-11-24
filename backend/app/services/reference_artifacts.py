"""완료 본문은 한 번 저장하고, 유한 HTTP handle은 작은 FK만 발급한다."""
from __future__ import annotations

import hashlib
import json
from time import monotonic
from uuid import uuid4

from asyncpg import InterfaceError, PostgresError
from sqlalchemy import (
    Text,
    bindparam,
    cast,
    delete,
    exists,
    func,
    insert,
    literal,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DBAPIError

from app.core.problems import ProblemCode, unavailable
from app.core.read_timing import observe_fingerprint, observe_native_statement
from app.core.time_utils import now_utc, serialize_utc
from app.models import (
    ReferenceExportArtifact,
    ReferenceExportArtifactHead,
    ReferenceExportArtifactItem,
    ServiceExportSnapshot,
)
from app.services.export_current import (
    BATCH_SIZE,
    MAX_SNAPSHOT_BYTES,
    MAX_SNAPSHOT_ITEMS,
    SnapshotRace,
    budget_exceeded,
)


def _budget(started, limit=None):
    # 요청 경로의 `started`는 첫 시도의 시작이다(`export_current.build_started`, 재시도와 예산 공유).
    # 오프라인 준비만 `limit`(그 준비 전체 예산의 끝까지 남은 초)을 넘긴다.
    exceeded = budget_exceeded(started) if limit is None else monotonic() - started > limit
    if exceeded:
        raise unavailable(ProblemCode.EXPORT_PREPARE_TIMEOUT, "reference 본문 구성 시간 상한을 초과했습니다.")


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


async def _store_items(session, artifact_id, encoded, started, *, budget_seconds=None):
    table = ReferenceExportArtifactItem.__table__
    for offset in range(0, len(encoded), BATCH_SIZE):
        _budget(started, budget_seconds)
        bodies = encoded[offset:offset + BATCH_SIZE]
        if session.bind.dialect.name == "postgresql" and session.bind.dialect.driver == "asyncpg":
            # 같은 SQLAlchemy transaction의 공개 driver API를 쓴다. JSONB codec에는
            # 검산한 canonical JSON 문자열을 전달하며 다시 loads/dumps하지 않는다.
            connection = await session.connection()
            raw = await connection.get_raw_connection()
            records = [(artifact_id, offset + i + 1, body.decode("utf-8"))
                       for i, body in enumerate(bodies)]
            try:
                with observe_native_statement():
                    status = await raw.driver_connection.copy_records_to_table(
                        table.name, records=records, columns=("artifact_id", "ordinal", "payload"),
                        schema_name=table.schema,
                    )
            except PostgresError as exc:
                # 같은 reader의 40001/55P03 재시도와 rollback 경계를 유지한다. 끊긴 연결(08003 등)도 SQLSTATE로 분류된다.
                raise DBAPIError(None, None, exc) from exc
            except (InterfaceError, OSError) as exc:
                # SQLSTATE 없는 driver 연결 오류(닫힌 연결·소켓 끊김)는 SQLAlchemy의 asyncpg disconnect 판정과 같게
                # 연결 무효로 표시해 export 경로의 503 TRANSIENT_DB로 가른다. 그 밖의 InterfaceError는 그대로 500이다.
                if isinstance(exc, InterfaceError) and "connection is closed" not in str(exc):
                    raise
                raise DBAPIError(None, None, exc, connection_invalidated=True) from exc
            if status != f"COPY {len(bodies)}":
                raise unavailable(ProblemCode.EXPORT_SOURCE_INCONSISTENT, "reference 본문 저장 수량이 일치하지 않습니다.")
        elif session.bind.dialect.name == "postgresql":
            # 다른 PostgreSQL driver는 기존 한 bind JSON 배열 경로를 유지한다.
            rows = func.jsonb_array_elements(cast(bindparam("bodies", type_=Text), JSONB)).table_valued(
                "value", with_ordinality="ordinal").render_derived(name="reference_rows")
            stmt = insert(table).from_select(["artifact_id", "ordinal", "payload"],
                select(literal(artifact_id), rows.c.ordinal + offset, rows.c.value))
            result = await session.execute(stmt, {"bodies": (b"[" + b",".join(bodies) + b"]").decode("utf-8")})
            if result.rowcount != len(bodies):
                raise unavailable(ProblemCode.EXPORT_SOURCE_INCONSISTENT, "reference 본문 저장 수량이 일치하지 않습니다.")
        else:
            await session.execute(insert(table), [{"artifact_id": artifact_id, "ordinal": offset + i + 1,
                "payload": json.loads(body)} for i, body in enumerate(bodies)])
        _budget(started, budget_seconds)


async def prepare_artifact(session, heads, spec, input_revision, *, started=None, budget_seconds=None):
    """`budget_seconds`가 None이면 요청 경로 예산(`export_current.BUILD_BUDGET_SECONDS`, 재시도와 공유)이다."""
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
    observe_fingerprint()
    encoded = [];size = count = 0;digest = hashlib.sha256()
    async for batch in spec.payload_batches(session, heads):
        _budget(started, budget_seconds)
        for item in batch:
            body = json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            size += len(body);count += 1
            if size > MAX_SNAPSHOT_BYTES or count > MAX_SNAPSHOT_ITEMS:
                raise unavailable(ProblemCode.EXPORT_TOO_LARGE, "reference 본문 크기 상한을 초과했습니다.")
            digest.update(body + b"\n");encoded.append(body)
    if not count:
        raise unavailable(ProblemCode.EXPORT_SOURCE_INCONSISTENT, "빈 reference 본문을 승인하지 않습니다.")
    table = ReferenceExportArtifact.__table__
    factory = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    artifact_id = str(uuid4())
    admitted = await session.scalar(factory(table).values(id=artifact_id, kind=spec.kind, scope_key=spec.scope,
        input_revision=input_revision, source_collected_at=min(serialize_utc(h.confirmed_at) for h in heads),
        created_at=now_utc(), item_count=count, byte_count=size, content_digest=digest.hexdigest())
        .on_conflict_do_nothing(index_elements=["kind", "scope_key", "input_revision"]).returning(table.c.id))
    if admitted is None:
        raise SnapshotRace()
    await _store_items(session, artifact_id, encoded, started, budget_seconds=budget_seconds)
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
