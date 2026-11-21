"""Bounded Opinet OpenAPI reads and their separate short-lived price overlay."""
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0046_fuel_manual_refresh"
down_revision = "0045_places_input_revision"
branch_labels = None
depends_on = None

COMPONENT = "places.fuel_refresh_prices"
ACTIONS = ("INSERT", "UPDATE", "DELETE", "TRUNCATE")


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
    op.create_table(
        "fuel_refresh_prices",
        sa.Column("fuel_station_id", sa.Integer(), sa.ForeignKey("fuel_stations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("product_code", sa.String(20), primary_key=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_fuel_refresh_prices_expires_at", "fuel_refresh_prices", ["expires_at"])
    op.create_table(
        "fuel_refresh_station_gates",
        sa.Column("fuel_station_id", sa.Integer(), sa.ForeignKey("fuel_stations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("allowed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "fuel_refresh_budget",
        sa.Column("id", sa.Integer(), autoincrement=False, primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.Column("lease_id", sa.String(32), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.bulk_insert(
        sa.table("reference_export_input_revisions", sa.column("component", sa.String()),
                 sa.column("epoch", sa.String()), sa.column("revision", sa.BigInteger())),
        [{"component": COMPONENT, "epoch": str(uuid4()), "revision": 0}],
    )
    if op.get_bind().dialect.name == "postgresql":
        for action in ACTIONS:
            op.execute(f"CREATE TRIGGER kt_places_revision_{action.lower()} AFTER {action} "
                       "ON public.fuel_refresh_prices FOR EACH STATEMENT EXECUTE FUNCTION public.kt_places_revision()")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
    op.drop_table("fuel_refresh_budget")
    op.drop_table("fuel_refresh_station_gates")
    op.drop_table("fuel_refresh_prices")
    op.execute(sa.text("DELETE FROM reference_export_input_revisions WHERE component = :component")
               .bindparams(component=COMPONENT))
