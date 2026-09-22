"""Add a route-filtered covering index for transport statistics."""

from __future__ import annotations

from alembic import op


revision = "0008_transport_route_stats"
down_revision = "0007_transport_stats_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # route_no equality plus observed_at range is the selective public statistics
    # access path. Include only aggregate inputs to avoid reading wide raw JSON rows.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_highway_traffic_statistics_route_observed",
            "highway_traffic_snapshots",
            ["route_no", "observed_at", "direction"],
            postgresql_include=["speed", "free_flow_speed"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_highway_traffic_statistics_route_observed",
            table_name="highway_traffic_snapshots",
            postgresql_concurrently=True,
            if_exists=True,
        )
