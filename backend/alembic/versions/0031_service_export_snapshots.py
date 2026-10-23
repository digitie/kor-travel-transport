"""Map current의 유한 수명 고정 DTO snapshot. 원천/이력 backfill 없음."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "0031_service_export_snapshots"
down_revision = "0030_traffic_current"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "service_export_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("generation", sa.String(36), nullable=False),
        sa.Column("source_collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("kind", "scope_key", "generation", name="uq_service_export_snapshot_generation"),
    )
    op.create_index("ix_service_export_snapshot_expires", "service_export_snapshots", ["expires_at"])
    op.create_index("ix_service_export_snapshot_generation", "service_export_snapshots",
                    ["kind", "scope_key", "generation", "expires_at"])
    op.create_table(
        "service_export_snapshot_items",
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("service_export_snapshots.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("service_export_snapshot_items")
    op.drop_index("ix_service_export_snapshot_generation", table_name="service_export_snapshots")
    op.drop_index("ix_service_export_snapshot_expires", table_name="service_export_snapshots")
    op.drop_table("service_export_snapshots")
