"""유가 읽기 모델 갱신과 원본 커밋 사이의 세대를 추적한다."""

from alembic import op
import sqlalchemy as sa

revision = "0019_fuel_read_model_generation"
down_revision = "0018_fuel_latest_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column(
        "transport_collection_states",
        sa.Column("refresh_generation", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    op.drop_column("transport_collection_states", "refresh_generation")
