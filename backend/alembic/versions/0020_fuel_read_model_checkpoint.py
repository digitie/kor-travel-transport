"""구버전 수집기의 늦은 커밋을 감지할 유가 원본 체크포인트."""

from alembic import op
import sqlalchemy as sa

revision = "0020_fuel_read_model_checkpoint"
down_revision = "0019_fuel_read_model_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column(
        "transport_collection_states",
        sa.Column("last_refreshed_snapshot_id", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_column("transport_collection_states", "last_refreshed_snapshot_id")
