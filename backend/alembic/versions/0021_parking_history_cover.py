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
            valid = op.get_bind().scalar(sa.text(
                "SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass('ix_parking_snapshots_history_cover')"
            ))
            if valid is False:
                raise RuntimeError("invalid ix_parking_snapshots_history_cover: 해당 index만 정리 후 재실행 필요")
            if valid is None:
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
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '3s'")
        op.execute("SET statement_timeout = '180s'")
        try:
            op.drop_index(INDEX_NAME, table_name="parking_snapshots", postgresql_concurrently=True,
                          if_exists=True)
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE parking_snapshots RESET (autovacuum_analyze_scale_factor)")
