"""원천별 배편 기준자료의 마지막 정상 저장본."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0035_ferry_reference"
down_revision = "0034_general_rail_queries"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("ferry_reference_snapshots",
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("response_json", postgresql.JSONB(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("dataset"),
        sa.CheckConstraint("dataset IN ('passenger_routes', 'ferry_routes', 'ferry_facilities', 'official_terminals')", name="ck_ferry_reference_dataset"))


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("ferry_reference_snapshots")
