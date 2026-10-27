"""원본과 수명이 독립적인 영구 주차 통계. 기존 관측 삭제·backfill은 하지 않는다."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0036_parking_statistics_archive"
down_revision = "0035_ferry_reference"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "parking_statistics_buckets",
        sa.Column("airport_id", sa.Integer(), nullable=False),
        sa.Column("bucket_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bucket_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("raw_count", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("max_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("raw_sha256", sa.Text(), nullable=False),
        sa.Column("statistics_sha256", sa.Text(), nullable=False),
        sa.Column("statistics_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("airport_id", "bucket_at"),
        sa.ForeignKeyConstraint(["airport_id"], ["airports.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("raw_count > 0 AND selected_count > 0 AND selected_count <= raw_count",
                           name="ck_parking_statistics_counts"),
        sa.CheckConstraint("bucket_end > bucket_at", name="ck_parking_statistics_window"),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM parking_statistics_buckets LIMIT 1")).first():
        raise RuntimeError("영구 주차 통계가 있으므로 이 migration을 downgrade할 수 없습니다.")
    op.drop_table("parking_statistics_buckets")
