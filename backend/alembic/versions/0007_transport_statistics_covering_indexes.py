"""Add covering indexes for bounded transport-statistics reads."""

from __future__ import annotations

from alembic import op

revision = "0007_transport_statistics_covering_indexes"
down_revision = "0006_rail_maritime_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The collector continues to write while these indexes are built.  They cover
    # the bounded 1–90 day aggregation API without reading the wide JSON rows.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_highway_traffic_statistics_observed",
            "highway_traffic_snapshots",
            ["observed_at", "route_no", "direction"],
            postgresql_include=["speed", "free_flow_speed"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_highway_incidents_statistics_observed",
            "highway_incident_snapshots",
            ["observed_at", "route_no"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_fuel_prices_statistics_collected",
            "fuel_price_snapshots",
            ["collected_at", "product_code", "fuel_station_id"],
            postgresql_include=["price", "observed_at"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("ix_fuel_prices_statistics_collected", table_name="fuel_price_snapshots", postgresql_concurrently=True)
        op.drop_index("ix_highway_incidents_statistics_observed", table_name="highway_incident_snapshots", postgresql_concurrently=True)
        op.drop_index("ix_highway_traffic_statistics_observed", table_name="highway_traffic_snapshots", postgresql_concurrently=True)
