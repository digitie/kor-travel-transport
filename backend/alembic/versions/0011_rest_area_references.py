"""고속도로 휴게소 기준정보 저장소를 추가한다."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0011_rest_area_references"
down_revision = "0010_transport_five_minute_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "rest_area_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("identity_key", sa.String(length=400), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("route_name", sa.String(length=160), nullable=True),
        sa.Column("direction", sa.String(length=80), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("has_gas_station", sa.Boolean(), nullable=True),
        sa.Column("has_lpg_station", sa.Boolean(), nullable=True),
        sa.Column("has_ev_charger", sa.Boolean(), nullable=True),
        sa.Column("phone_number", sa.String(length=80), nullable=True),
        sa.Column("data_reference_date", sa.String(length=40), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_item_json", json_type, nullable=True),
        sa.UniqueConstraint("source", "identity_key", name="uq_rest_area_reference_identity"),
    )
    op.create_index("ix_rest_area_reference_last_seen", "rest_area_references", ["last_seen_at"])
    op.create_index("ix_rest_area_reference_route", "rest_area_references", ["route_name", "direction"])
    op.create_index("ix_rest_area_reference_coordinates", "rest_area_references", ["latitude", "longitude"])


def downgrade() -> None:
    op.drop_index("ix_rest_area_reference_coordinates", table_name="rest_area_references")
    op.drop_index("ix_rest_area_reference_route", table_name="rest_area_references")
    op.drop_index("ix_rest_area_reference_last_seen", table_name="rest_area_references")
    op.drop_table("rest_area_references")
