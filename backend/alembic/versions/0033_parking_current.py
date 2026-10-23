"""Map 주차장 현재 상태의 유한 typed pointer. 이력 backfill 없음."""

from alembic import op
import sqlalchemy as sa

revision = "0033_parking_current"
down_revision = "0032_reference_export_states"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("parking_current",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("scope_key", sa.String(80), primary_key=True),
        sa.Column("parking_lot_id", sa.Integer(), primary_key=True),
        sa.Column("generation", sa.String(36), nullable=False),
        sa.Column("airport_code", sa.String(10), nullable=False),
        sa.Column("lot_code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("total_spaces", sa.Integer(), nullable=False),
        sa.Column("occupied_spaces", sa.Integer(), nullable=False),
        sa.Column("available_spaces", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("parking_current")
