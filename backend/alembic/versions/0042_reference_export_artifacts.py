"""불변 reference 본문과 유한 cursor handle의 수명을 분리한다."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0042_reference_export_artifacts"
down_revision = "0041_public_parking_lots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table("reference_export_artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("scope_key", sa.String(64), nullable=False),
        sa.Column("input_revision", sa.String(64), nullable=False),
        sa.Column("source_collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("kind", "scope_key", "input_revision", name="uq_reference_artifact_input"),
        sa.CheckConstraint("item_count > 0 AND item_count <= 20000", name="ck_reference_artifact_count"),
        sa.CheckConstraint("byte_count > 0 AND byte_count <= 16777216", name="ck_reference_artifact_bytes"))
    op.create_table("reference_export_artifact_items",
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("reference_export_artifacts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ordinal", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.CheckConstraint("ordinal > 0", name="ck_reference_artifact_ordinal"))
    op.create_table("reference_export_artifact_heads",
        sa.Column("kind", sa.String(40), primary_key=True),
        sa.Column("scope_key", sa.String(64), primary_key=True),
        sa.Column("artifact_id", sa.String(36), sa.ForeignKey("reference_export_artifacts.id", ondelete="RESTRICT"), nullable=False))
    op.create_index("ix_reference_export_artifact_heads_artifact_id", "reference_export_artifact_heads", ["artifact_id"])
    op.add_column("service_export_snapshots", sa.Column("artifact_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_service_export_snapshot_artifact", "service_export_snapshots", "reference_export_artifacts", ["artifact_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_service_export_snapshots_artifact_id", "service_export_snapshots", ["artifact_id"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM reference_export_artifacts LIMIT 1)")):
        raise RuntimeError("본문과 유효 handle을 삭제하는 downgrade는 허용하지 않습니다.")
    op.drop_index("ix_service_export_snapshots_artifact_id", table_name="service_export_snapshots")
    op.drop_constraint("fk_service_export_snapshot_artifact", "service_export_snapshots", type_="foreignkey")
    op.drop_column("service_export_snapshots", "artifact_id")
    op.drop_table("reference_export_artifact_heads")
    op.drop_table("reference_export_artifact_items")
    op.drop_table("reference_export_artifacts")
