"""Store ten-day ferry timetable snapshots."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0013_ferry_timetable_snapshots"
down_revision = "0012_tago_bus_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ferry_timetable_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("departure_port_id", sa.String(length=120), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("items_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source", "departure_port_id", "service_date",
            name="uq_ferry_timetable_snapshot_port_date",
        ),
    )
    op.create_index(
        "ix_ferry_timetable_snapshot_lookup",
        "ferry_timetable_snapshots",
        ["source", "departure_port_id", "service_date"],
    )
    op.create_index(
        "ix_ferry_timetable_snapshot_service_date",
        "ferry_timetable_snapshots",
        ["service_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_ferry_timetable_snapshot_service_date", table_name="ferry_timetable_snapshots")
    op.drop_index("ix_ferry_timetable_snapshot_lookup", table_name="ferry_timetable_snapshots")
    op.drop_table("ferry_timetable_snapshots")
