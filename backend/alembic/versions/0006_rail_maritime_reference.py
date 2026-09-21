"""Add rail and maritime reference-data collection tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_rail_maritime_reference"
down_revision = "0005_transport_query_indexes"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "rail_station_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("identity_key", sa.String(length=400), nullable=False),
        sa.Column("rail_operator_name", sa.String(length=120), nullable=True),
        sa.Column("operating_line_name", sa.String(length=160), nullable=True),
        sa.Column("station_type", sa.String(length=80), nullable=True),
        sa.Column("station_number", sa.String(length=80), nullable=True),
        sa.Column("station_name", sa.String(length=160), nullable=True),
        sa.Column("english_name", sa.String(length=160), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("lot_address", sa.String(length=300), nullable=True),
        sa.Column("road_address", sa.String(length=300), nullable=True),
        sa.Column("station_phone_number", sa.String(length=80), nullable=True),
        sa.Column("data_reference_date", sa.String(length=40), nullable=True),
        sa.Column("first_seen_at", UTC, nullable=False),
        sa.Column("last_seen_at", UTC, nullable=False),
        sa.Column("raw_item_json", JSONB, nullable=True),
        sa.UniqueConstraint("source", "identity_key", name="uq_rail_station_reference_identity"),
    )
    op.create_index("ix_rail_station_reference_operator_line", "rail_station_references", ["rail_operator_name", "operating_line_name"])
    op.create_index("ix_rail_station_reference_last_seen", "rail_station_references", ["last_seen_at"])
    op.create_table(
        "ferry_ports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("port_id", sa.String(length=120), nullable=False),
        sa.Column("port_name", sa.String(length=160), nullable=True),
        sa.Column("first_seen_at", UTC, nullable=False),
        sa.Column("last_seen_at", UTC, nullable=False),
        sa.Column("raw_item_json", JSONB, nullable=True),
        sa.UniqueConstraint("source", "port_id", name="uq_ferry_port_source_id"),
    )
    op.create_index("ix_ferry_ports_last_seen", "ferry_ports", ["last_seen_at"])
    for table, id_column, name_column, extras in (
        ("ferry_terminal_references", "terminal_id", "terminal_name", (sa.Column("address", sa.String(length=300), nullable=True), sa.Column("telephone", sa.String(length=80), nullable=True))),
        ("ferry_ship_type_references", "ship_type_id", "ship_type_name", ()),
    ):
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.String(length=40), nullable=False),
            sa.Column(id_column, sa.String(length=120), nullable=False),
            sa.Column(name_column, sa.String(length=200 if table.endswith("terminal_references") else 160), nullable=True),
            *extras,
            sa.Column("first_seen_at", UTC, nullable=False),
            sa.Column("last_seen_at", UTC, nullable=False),
            sa.Column("raw_item_json", JSONB, nullable=True),
            sa.UniqueConstraint("source", id_column, name=f"uq_{'ferry_terminal' if table.endswith('terminal_references') else 'ferry_ship_type'}_source_id"),
        )


def downgrade() -> None:
    op.drop_table("ferry_ship_type_references")
    op.drop_table("ferry_terminal_references")
    op.drop_index("ix_ferry_ports_last_seen", table_name="ferry_ports")
    op.drop_table("ferry_ports")
    op.drop_index("ix_rail_station_reference_last_seen", table_name="rail_station_references")
    op.drop_index("ix_rail_station_reference_operator_line", table_name="rail_station_references")
    op.drop_table("rail_station_references")
