"""공유 DB의 완결 generation을 한 SELECT로 읽는 독립 초안.

DDL 등록·설치·publisher·API 전환은 없다. source_revision을 모든 writer가 같은 transaction에서
갱신한다는 전제는 아직 설계이며, 실제 trigger/writer 연결 전 운영에 사용할 수 없다.
"""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    String,
    Table,
    and_,
    func,
    select,
)

MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_GENERATION_BYTES = 64 * 1024 * 1024
MAX_PAYLOADS = 8
FORMAT_VERSION = 1
metadata = MetaData()
source = Table("draft_parking_history_source", metadata,
    Column("singleton", Integer, primary_key=True), Column("revision", BigInteger, nullable=False),
    CheckConstraint("singleton = 1 AND revision >= 0"))
generations = Table("draft_parking_history_generations", metadata,
    Column("id", String(36), primary_key=True), Column("source_revision", BigInteger, nullable=False),
    Column("format_version", Integer, nullable=False), Column("complete", Boolean, nullable=False),
    Column("byte_count", BigInteger, nullable=False), Column("payload_count", Integer, nullable=False),
    CheckConstraint(f"byte_count BETWEEN 0 AND {MAX_GENERATION_BYTES}"),
    CheckConstraint(f"payload_count BETWEEN 1 AND {MAX_PAYLOADS}"))
heads = Table("draft_parking_history_heads", metadata,
    Column("singleton", Integer, primary_key=True),
    Column("generation_id", ForeignKey(generations.c.id, ondelete="RESTRICT"), nullable=False),
    CheckConstraint("singleton = 1"))
payloads = Table("draft_parking_history_payloads", metadata,
    Column("generation_id", ForeignKey(generations.c.id, ondelete="CASCADE"), primary_key=True),
    Column("scope", String(80), primary_key=True), Column("days", Integer, primary_key=True),
    Column("encoding", String(8), primary_key=True),
    Column("cutoff_from", DateTime(timezone=True), nullable=False),
    Column("cutoff_through", DateTime(timezone=True), nullable=False),
    Column("item_count", BigInteger, nullable=False), Column("sha256", String(64), nullable=False),
    Column("body", LargeBinary, nullable=False),
    CheckConstraint("days BETWEEN 1 AND 30 AND item_count >= 0"),
    CheckConstraint("encoding IN ('br', 'gzip', 'identity')"),
    CheckConstraint("cutoff_from <= cutoff_through"),
    CheckConstraint(f"length(body) <= {MAX_BODY_BYTES}"))


@dataclass(frozen=True)
class Hit:
    generation: str
    body: bytes
    encoding: str
    item_count: int
    sha256: str
    checked_at: datetime


async def read(session, *, scope: str, days: int, encoding: str,
               cutoff: datetime, checked_at: datetime) -> Hit | None:
    """현재 revision·완결 head·정확한 범위가 모두 맞으면 압축 bytes만 읽는다.

    30초 local reuse/5초 source 확인은 호출자 책임이며 이 함수는 매번 DB를 확인한다.
    이 query 뒤 변경은 기존 최대30초 신선도 계약 안에서 다음 확인이 무효화한다.
    JSON decode·행 객체500k개 재생성·압축·DB 쓰기는 하지 않는다.
    """
    if cutoff.tzinfo is None or checked_at.tzinfo is None:
        raise ValueError("aware 시각이 필요합니다")
    relation = heads.join(generations, heads.c.generation_id == generations.c.id).join(
        source, and_(source.c.singleton == heads.c.singleton,
                     source.c.revision == generations.c.source_revision)).join(
        payloads, payloads.c.generation_id == generations.c.id)
    row = (await session.execute(select(generations.c.id, payloads.c.body, payloads.c.encoding,
        payloads.c.item_count, payloads.c.sha256).select_from(relation).where(
            heads.c.singleton == 1, generations.c.complete.is_(True),
            generations.c.format_version == FORMAT_VERSION, payloads.c.scope == scope,
            payloads.c.days == days, payloads.c.encoding == encoding,
            payloads.c.cutoff_from <= cutoff, payloads.c.cutoff_through >= cutoff,
            func.length(payloads.c.body) <= MAX_BODY_BYTES,
        ))).one_or_none()
    if row is None:
        return None
    return Hit(row.id, bytes(row.body), row.encoding, row.item_count, row.sha256, checked_at)
