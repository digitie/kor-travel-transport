"""기준정보의 source별 성공 membership. backfill하지 않는다."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "0032_reference_export_states"
down_revision = "0031_service_export_snapshots"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("reference_export_states",
        sa.Column("kind", sa.String(40), primary_key=True),
        sa.Column("scope_key", sa.String(80), primary_key=True),
        sa.Column("generation", sa.String(36), nullable=False),
        sa.Column("attempt_order", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("member_ids", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("proof", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(120), nullable=True),
    )


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("reference_export_states")
