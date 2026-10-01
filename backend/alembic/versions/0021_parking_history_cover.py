"""공항별 장기 주차 이력 조회를 위한 covering index와 통계 갱신."""

from alembic import op
import sqlalchemy as sa

revision = "0021_parking_history_cover"
down_revision = "0020_fuel_read_model_checkpoint"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_parking_snapshots_history_cover"


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("0021은 concurrent index 검증을 위해 온라인 migration만 지원합니다.")
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '3s'")
        op.execute("SET statement_timeout = '180s'")
        try:
            matching = op.get_bind().scalar(sa.text("""
                SELECT i.indisvalid AND t.relname = 'parking_snapshots' AND am.amname = 'btree'
                    AND i.indnkeyatts = 2 AND
                    (SELECT array_agg(pg_get_indexdef(i.indexrelid, n, true) ORDER BY n)
                     FROM generate_series(1, i.indnatts) AS n) = ARRAY[
                        'airport_id', 'observed_at', 'parking_lot_id', 'id',
                        'collected_at', 'source', 'occupied_spaces',
                        'total_spaces', 'available_spaces'
                    ]
                FROM pg_index AS i
                JOIN pg_class AS t ON t.oid = i.indrelid
                JOIN pg_class AS c ON c.oid = i.indexrelid
                JOIN pg_am AS am ON am.oid = c.relam
                WHERE i.indexrelid = to_regclass('ix_parking_snapshots_history_cover')
            """))
            if matching is False:
                raise RuntimeError("invalid or unexpected ix_parking_snapshots_history_cover: 해당 index만 확인 후 재실행 필요")
            if matching is None:
                op.create_index(
                    INDEX_NAME,
                    "parking_snapshots",
                    ["airport_id", "observed_at"],
                    postgresql_include=[
                        "parking_lot_id", "id", "collected_at", "source",
                        "occupied_spaces", "total_spaces", "available_spaces",
                    ],
                    postgresql_concurrently=True,
                )
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")

    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '60s'")
    op.execute("ALTER TABLE parking_snapshots SET (autovacuum_analyze_scale_factor = 0.02)")
    op.execute("ANALYZE parking_snapshots")


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("0021은 concurrent index 검증을 위해 온라인 migration만 지원합니다.")
    # 잠금 실패가 나더라도 index와 0021 revision이 서로 어긋나지 않도록
    # 트랜잭션형 테이블 설정 변경을 먼저 끝낸 뒤 비트랜잭션 index 삭제를 한다.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE parking_snapshots RESET (autovacuum_analyze_scale_factor)")
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '3s'")
        op.execute("SET statement_timeout = '180s'")
        try:
            op.drop_index(INDEX_NAME, table_name="parking_snapshots", postgresql_concurrently=True,
                          if_exists=True)
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")
