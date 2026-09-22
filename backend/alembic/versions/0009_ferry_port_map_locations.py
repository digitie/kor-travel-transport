"""항구 지도 좌표를 항만가이드라인 공개 파일에서 보관한다."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_ferry_port_map_locations"
down_revision = "0008_transport_route_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ferry_ports", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("ferry_ports", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("ferry_ports", sa.Column("location_source", sa.String(length=80), nullable=True))
    op.add_column("ferry_ports", sa.Column("location_point_count", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("ferry_ports", "location_point_count", server_default=None)
    op.create_index("ix_ferry_ports_coordinates", "ferry_ports", ["latitude", "longitude"])


def downgrade() -> None:
    op.drop_index("ix_ferry_ports_coordinates", table_name="ferry_ports")
    op.drop_column("ferry_ports", "location_point_count")
    op.drop_column("ferry_ports", "location_source")
    op.drop_column("ferry_ports", "longitude")
    op.drop_column("ferry_ports", "latitude")
