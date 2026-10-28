"""전국 동시각 통계·보류 상태·현재 요약. 원본 삭제는 계속 비활성이다."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0037_parking_archive_coverage"
down_revision = "0036_parking_statistics_archive"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "parking_global_statistics_buckets",
        sa.Column("bucket_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("raw_count", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("max_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("raw_sha256", sa.Text(), nullable=False),
        sa.Column("statistics_sha256", sa.Text(), nullable=False),
        sa.Column("statistics_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("airport_proofs_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bucket_at"),
        sa.CheckConstraint("raw_count > 0 AND selected_count > 0 AND selected_count <= raw_count",
                           name="ck_parking_global_statistics_counts"),
        sa.CheckConstraint("bucket_end > bucket_at", name="ck_parking_global_statistics_window"),
    )
    op.create_table(
        "parking_archive_issues",
        sa.Column("scope_key", sa.String(80), nullable=False),
        sa.Column("bucket_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(60), nullable=False),
        sa.Column("max_seen_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scope_key", "bucket_at"),
    )
    op.create_table(
        "parking_latest_states",
        sa.Column("parking_lot_id", sa.Integer(), nullable=False),
        sa.Column("airport_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_order", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occupied_spaces", sa.Integer(), nullable=False),
        sa.Column("total_spaces", sa.Integer(), nullable=False),
        sa.Column("available_spaces", sa.Integer(), nullable=False),
        sa.Column("congestion_label", sa.String(40), nullable=True),
        sa.Column("congestion_ratio", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("parking_lot_id"),
        sa.ForeignKeyConstraint(["parking_lot_id", "airport_id"], ["parking_lots.id", "parking_lots.airport_id"],
                                ondelete="RESTRICT", name="fk_parking_latest_lot_airport"),
        sa.CheckConstraint("occupied_spaces >= 0 AND total_spaces >= 0 AND available_spaces >= 0 "
                           "AND available_spaces <= total_spaces", name="ck_parking_latest_spaces"),
        sa.CheckConstraint("congestion_ratio IS NULL OR (congestion_ratio >= 0 AND congestion_ratio <= 100)",
                           name="ck_parking_latest_congestion"),
    )


def downgrade():
    bind = op.get_bind()
    tables = ("parking_archive_issues", "parking_global_statistics_buckets", "parking_latest_states")
    if bind.dialect.name == "postgresql":
        # 빈 상태 검사부터 DROP/버전 변경 commit까지 신규 writer를 막는다. 잠금 순서는 고정한다.
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("LOCK TABLE " + ", ".join(tables) + " IN ACCESS EXCLUSIVE MODE")
    for table in tables:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("주차 영구 통계·현재 요약·보류 상태가 있어 이 migration을 downgrade할 수 없습니다.")
    op.drop_table("parking_latest_states")
    op.drop_table("parking_archive_issues")
    op.drop_table("parking_global_statistics_buckets")
