"""Map 교통 current의 작은 source/filter 포인터. 이력 backfill 없음."""

import sqlalchemy as sa
from alembic import op

revision = "0030_traffic_current"
down_revision = "0029_fuel_statistics_generations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "highway_traffic_current_states",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("scope_key", sa.String(64), primary_key=True),
        sa.Column("generation", sa.String(36), nullable=False),
        sa.Column("attempt_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_order", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
    )
    op.create_table(
        "highway_traffic_current",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("scope_key", sa.String(64), primary_key=True),
        sa.Column("identity_key", sa.String(240), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("highway_traffic_snapshots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generation", sa.String(36), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_no", sa.String(40)),
        sa.Column("route_name", sa.String(120)),
        sa.Column("conzone_id", sa.String(80)),
        sa.Column("conzone_name", sa.String(160)),
        sa.Column("direction", sa.String(20)),
        sa.Column("speed", sa.Float()),
        sa.Column("free_flow_speed", sa.Float()),
        sa.Column("congestion_level", sa.String(20)),
    )
    op.create_index(
        "ix_highway_traffic_current_members",
        "highway_traffic_current",
        ["source", "scope_key", "generation", "identity_key"],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_index(
        "ix_highway_traffic_current_members", table_name="highway_traffic_current"
    )
    op.drop_table("highway_traffic_current")
    op.drop_table("highway_traffic_current_states")
