"""TAGO 버스 터미널 기준정보를 저장한다.

Revision ID: 0012_tago_bus_reference
Revises: 0011_place_lookup_index
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_tago_bus_reference"
down_revision = "0011_place_lookup_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bus_terminal_references",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("service_type", sa.String(length=20), nullable=False),
        sa.Column("terminal_id", sa.String(length=120), nullable=False),
        sa.Column("terminal_name", sa.String(length=200), nullable=True),
        sa.Column("city_name", sa.String(length=120), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_item_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "service_type", "terminal_id", name="uq_bus_terminal_reference"),
    )
    op.create_index(
        "ix_bus_terminal_reference_lookup",
        "bus_terminal_references",
        ["service_type", "terminal_name"],
    )
    op.create_index(
        "ix_bus_terminal_reference_last_seen",
        "bus_terminal_references",
        ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_bus_terminal_reference_last_seen", table_name="bus_terminal_references")
    op.drop_index("ix_bus_terminal_reference_lookup", table_name="bus_terminal_references")
    op.drop_table("bus_terminal_references")
