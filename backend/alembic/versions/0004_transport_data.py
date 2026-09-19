"""Add highway traffic and Opinet fuel collection tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_transport_data"
down_revision = "0003_legacy_source_identity"
branch_labels = None
depends_on = None

UTC = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "highway_traffic_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collection_run_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("identity_key", sa.String(length=240), nullable=False),
        sa.Column("observed_at", UTC, nullable=False),
        sa.Column("collected_at", UTC, nullable=False),
        sa.Column("route_no", sa.String(length=40), nullable=True),
        sa.Column("route_name", sa.String(length=120), nullable=True),
        sa.Column("conzone_id", sa.String(length=80), nullable=True),
        sa.Column("conzone_name", sa.String(length=160), nullable=True),
        sa.Column("direction", sa.String(length=20), nullable=True),
        sa.Column("speed", sa.Float(), nullable=True),
        sa.Column("free_flow_speed", sa.Float(), nullable=True),
        sa.Column("congestion_level", sa.String(length=20), nullable=True),
        sa.Column("raw_item_json", JSONB, nullable=True),
        sa.ForeignKeyConstraint(["collection_run_id"], ["collection_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source", "identity_key", "observed_at", name="uq_highway_traffic_snapshot"),
    )
    op.create_index("ix_highway_traffic_observed", "highway_traffic_snapshots", ["observed_at"])
    op.create_index(
        "ix_highway_traffic_route_observed",
        "highway_traffic_snapshots",
        ["route_no", "observed_at"],
    )
    op.create_index(
        "ix_highway_traffic_conzone_observed",
        "highway_traffic_snapshots",
        ["conzone_id", "observed_at"],
    )
    op.create_index(
        "ix_highway_traffic_collection_run_id",
        "highway_traffic_snapshots",
        ["collection_run_id"],
    )

    op.create_table(
        "highway_incident_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collection_run_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("identity_key", sa.String(length=240), nullable=False),
        sa.Column("observed_at", UTC, nullable=False),
        sa.Column("collected_at", UTC, nullable=False),
        sa.Column("occurred_date", sa.String(length=20), nullable=True),
        sa.Column("occurred_time", sa.String(length=20), nullable=True),
        sa.Column("incident_type", sa.String(length=120), nullable=True),
        sa.Column("incident_type_code", sa.String(length=40), nullable=True),
        sa.Column("direction", sa.String(length=120), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("point_name", sa.String(length=160), nullable=True),
        sa.Column("route_no", sa.String(length=40), nullable=True),
        sa.Column("route_name", sa.String(length=120), nullable=True),
        sa.Column("process_status", sa.String(length=120), nullable=True),
        sa.Column("process_status_code", sa.String(length=40), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("congestion_length", sa.Float(), nullable=True),
        sa.Column("series_no", sa.Integer(), nullable=True),
        sa.Column("raw_item_json", JSONB, nullable=True),
        sa.ForeignKeyConstraint(["collection_run_id"], ["collection_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source", "identity_key", "observed_at", name="uq_highway_incident_snapshot"),
    )
    op.create_index("ix_highway_incidents_observed", "highway_incident_snapshots", ["observed_at"])
    op.create_index(
        "ix_highway_incidents_route_observed",
        "highway_incident_snapshots",
        ["route_no", "observed_at"],
    )
    op.create_index(
        "ix_highway_incidents_collection_run_id",
        "highway_incident_snapshots",
        ["collection_run_id"],
    )

    op.create_table(
        "fuel_stations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("identity_key", sa.String(length=300), nullable=False),
        sa.Column("source_station_id", sa.String(length=80), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("brand_code", sa.String(length=20), nullable=True),
        sa.Column("brand_name", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("business_number", sa.String(length=40), nullable=True),
        sa.Column("cb_code", sa.String(length=40), nullable=True),
        sa.Column("station_type", sa.String(length=20), nullable=True),
        sa.Column("query_level", sa.String(length=20), nullable=False),
        sa.Column("sido_value", sa.String(length=40), nullable=False),
        sa.Column("sido_name", sa.String(length=80), nullable=False),
        sa.Column("sigungu_value", sa.String(length=80), nullable=False),
        sa.Column("sigungu_name", sa.String(length=120), nullable=False),
        sa.Column("dong_value", sa.String(length=80), nullable=True),
        sa.Column("dong_name", sa.String(length=120), nullable=True),
        sa.Column("katec_x", sa.Float(), nullable=True),
        sa.Column("katec_y", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("source_kinds", JSONB, nullable=False),
        sa.Column("is_illegal", sa.Boolean(), nullable=True),
        sa.Column("is_self", sa.Boolean(), nullable=True),
        sa.Column("is_24h", sa.Boolean(), nullable=True),
        sa.Column("is_kpetro", sa.Boolean(), nullable=True),
        sa.Column("is_electronic", sa.Boolean(), nullable=True),
        sa.Column("is_good", sa.Boolean(), nullable=True),
        sa.Column("is_good_strong", sa.Boolean(), nullable=True),
        sa.Column("is_region_franchise", sa.Boolean(), nullable=True),
        sa.Column("has_carwash", sa.Boolean(), nullable=True),
        sa.Column("has_maintenance", sa.Boolean(), nullable=True),
        sa.Column("has_cvs", sa.Boolean(), nullable=True),
        sa.Column("cs_yn", sa.Boolean(), nullable=True),
        sa.Column("discount_info", sa.Text(), nullable=True),
        sa.Column("save_event_info", sa.Text(), nullable=True),
        sa.Column("representative_event_info", sa.Text(), nullable=True),
        sa.Column("on_event_info", sa.Text(), nullable=True),
        sa.Column("other_business_info", sa.Text(), nullable=True),
        sa.Column("first_seen_at", UTC, nullable=False),
        sa.Column("last_seen_at", UTC, nullable=False),
        sa.Column("raw_item_json", JSONB, nullable=True),
        sa.UniqueConstraint("source", "identity_key", name="uq_fuel_station_identity"),
    )
    op.create_index("ix_fuel_stations_last_seen", "fuel_stations", ["last_seen_at"])
    op.create_index("ix_fuel_stations_region", "fuel_stations", ["sido_value", "sigungu_value"])

    op.create_table(
        "fuel_price_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("collection_run_id", sa.Integer(), nullable=True),
        sa.Column("fuel_station_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("product_code", sa.String(length=20), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("provider_updated_at", UTC, nullable=True),
        sa.Column("observed_at", UTC, nullable=False),
        sa.Column("collected_at", UTC, nullable=False),
        sa.Column("raw_item_json", JSONB, nullable=True),
        sa.ForeignKeyConstraint(["collection_run_id"], ["collection_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fuel_station_id"], ["fuel_stations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "fuel_station_id",
            "source",
            "product_code",
            "observed_at",
            name="uq_fuel_price_snapshot",
        ),
        sa.CheckConstraint("price IS NULL OR price >= 0", name="ck_fuel_price_nonnegative"),
    )
    op.create_index(
        "ix_fuel_prices_station_observed",
        "fuel_price_snapshots",
        ["fuel_station_id", "observed_at"],
    )
    op.create_index(
        "ix_fuel_prices_product_observed",
        "fuel_price_snapshots",
        ["product_code", "observed_at"],
    )
    op.create_index(
        "ix_fuel_prices_collection_run_id",
        "fuel_price_snapshots",
        ["collection_run_id"],
    )

    op.create_table(
        "transport_collection_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("last_started_at", UTC, nullable=True),
        sa.Column("last_success_at", UTC, nullable=True),
        sa.Column("next_due_at", UTC, nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", UTC, nullable=False),
        sa.UniqueConstraint("source", name="uq_transport_collection_state_source"),
    )
    op.create_index(
        "ix_transport_collection_states_next_due",
        "transport_collection_states",
        ["next_due_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_transport_collection_states_next_due", table_name="transport_collection_states")
    op.drop_table("transport_collection_states")
    op.drop_index("ix_fuel_prices_collection_run_id", table_name="fuel_price_snapshots")
    op.drop_index("ix_fuel_prices_product_observed", table_name="fuel_price_snapshots")
    op.drop_index("ix_fuel_prices_station_observed", table_name="fuel_price_snapshots")
    op.drop_table("fuel_price_snapshots")
    op.drop_index("ix_fuel_stations_region", table_name="fuel_stations")
    op.drop_index("ix_fuel_stations_last_seen", table_name="fuel_stations")
    op.drop_table("fuel_stations")
    op.drop_index("ix_highway_incidents_collection_run_id", table_name="highway_incident_snapshots")
    op.drop_index("ix_highway_incidents_route_observed", table_name="highway_incident_snapshots")
    op.drop_index("ix_highway_incidents_observed", table_name="highway_incident_snapshots")
    op.drop_table("highway_incident_snapshots")
    op.drop_index("ix_highway_traffic_collection_run_id", table_name="highway_traffic_snapshots")
    op.drop_index("ix_highway_traffic_conzone_observed", table_name="highway_traffic_snapshots")
    op.drop_index("ix_highway_traffic_route_observed", table_name="highway_traffic_snapshots")
    op.drop_index("ix_highway_traffic_observed", table_name="highway_traffic_snapshots")
    op.drop_table("highway_traffic_snapshots")
