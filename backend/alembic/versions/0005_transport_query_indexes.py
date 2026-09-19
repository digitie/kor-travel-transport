"""Add collection-time indexes for current fuel-price queries."""

from __future__ import annotations

from alembic import op

revision = "0005_transport_query_indexes"
down_revision = "0004_transport_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_fuel_prices_station_collected",
        "fuel_price_snapshots",
        ["fuel_station_id", "collected_at"],
    )
    op.create_index(
        "ix_fuel_prices_product_collected",
        "fuel_price_snapshots",
        ["product_code", "collected_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_fuel_prices_product_collected", table_name="fuel_price_snapshots")
    op.drop_index("ix_fuel_prices_station_collected", table_name="fuel_price_snapshots")
