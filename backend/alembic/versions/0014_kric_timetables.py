"""KRIC 인증 역사 코드와 요일별 예정 시간표 저장."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_kric_timetables"
down_revision = "0013_ferry_timetable_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rail_service_days",
        sa.Column("service_date", sa.Date(), primary_key=True),
        sa.Column("day_code", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("day_code IN ('7', '8', '9')", name="ck_rail_service_day"),
    )
    op.create_table(
        "kric_station_codes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("operator_code", sa.Text(), nullable=False),
        sa.Column("line_code", sa.Text(), nullable=False),
        sa.Column("station_code", sa.Text(), nullable=False),
        sa.Column("operator_name", sa.Text(), nullable=False),
        sa.Column("line_name", sa.Text(), nullable=False),
        sa.Column("station_name", sa.Text(), nullable=False),
        sa.Column("rail_station_id", sa.Integer(), sa.ForeignKey("rail_station_references.id", ondelete="SET NULL")),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("operator_code", "line_code", "station_code", name="uq_kric_station_code"),
        sa.UniqueConstraint("rail_station_id", name="uq_kric_station_place"),
    )
    op.create_table(
        "kric_timetable_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("station_id", sa.BigInteger(), sa.ForeignKey("kric_station_codes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day_code", sa.Text(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("items_json", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("station_id", "day_code", name="uq_kric_timetable_station_day"),
        sa.CheckConstraint("day_code IN ('7', '8', '9')", name="ck_kric_timetable_day"),
    )
    op.create_index("ix_kric_timetable_collected", "kric_timetable_snapshots", ["collected_at"])


def downgrade() -> None:
    op.drop_index("ix_kric_timetable_collected", table_name="kric_timetable_snapshots")
    op.drop_table("kric_timetable_snapshots")
    op.drop_table("kric_station_codes")
    op.drop_table("rail_service_days")
