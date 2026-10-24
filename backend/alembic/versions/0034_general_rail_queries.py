"""일반철도 기준정보·시간표의 마지막 정상 응답 저장."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0034_general_rail_queries"
down_revision = "0033_parking_current"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("general_rail_query_snapshots",
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_json", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("operation", "request_key"),
        sa.CheckConstraint("operation IN ('catalog', 'stations', 'timetable', 'station_guide')", name="ck_general_rail_operation"))
    op.create_index("ix_general_rail_query_fetched", "general_rail_query_snapshots", ["fetched_at"])


def downgrade():
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("general_rail_query_snapshots")
