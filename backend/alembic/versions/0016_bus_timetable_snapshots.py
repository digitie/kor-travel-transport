"""버스 시간표 성공 응답을 프로세스 재시작과 호출 보호에 독립적으로 저장한다."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_bus_timetable_snapshots"
down_revision = "0015_fuel_statistics_priced"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bus_timetable_snapshots",
        sa.Column("service_type", sa.Text(), nullable=False),
        sa.Column("departure_terminal_id", sa.Text(), nullable=False),
        sa.Column("arrival_terminal_id", sa.Text(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("bus_grade_id", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("service_type", "departure_terminal_id", "arrival_terminal_id", "service_date", "bus_grade_id"),
        sa.CheckConstraint("service_type IN ('express', 'intercity')", name="ck_bus_timetable_service_type"),
    )
    op.create_index("ix_bus_timetable_service_date", "bus_timetable_snapshots", ["service_date"])


def downgrade() -> None:
    op.drop_index("ix_bus_timetable_service_date", table_name="bus_timetable_snapshots")
    op.drop_table("bus_timetable_snapshots")
