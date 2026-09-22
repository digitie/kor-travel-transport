"""사전 집계로 저장 교통 통계의 cold read를 제한한다."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0010_transport_five_minute_stats"
down_revision = "0009_ferry_port_map_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "highway_traffic_five_minute_statistics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bucket_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_no_key", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("direction_key", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("observations", sa.BigInteger(), nullable=False),
        sa.Column("speed_observations", sa.BigInteger(), nullable=False),
        sa.Column("speed_sum", sa.Float(), nullable=True),
        sa.Column("minimum_speed", sa.Float(), nullable=True),
        sa.Column("maximum_speed", sa.Float(), nullable=True),
        sa.Column("free_flow_speed_observations", sa.BigInteger(), nullable=False),
        sa.Column("free_flow_speed_sum", sa.Float(), nullable=True),
        sa.Column("latest_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "bucket_start", "route_no_key", "direction_key",
            name="uq_highway_traffic_five_minute_statistics",
        ),
    )
    op.create_index(
        "ix_highway_traffic_five_minute_statistics_bucket_route",
        "highway_traffic_five_minute_statistics",
        ["bucket_start", "route_no_key", "direction_key"],
    )

    # PostgreSQL 운영 데이터는 한 번만 backfill한다. SQLite test DB에는 원본 fallback을 쓴다.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            INSERT INTO highway_traffic_five_minute_statistics (
                bucket_start, route_no_key, direction_key, observations,
                speed_observations, speed_sum, minimum_speed, maximum_speed,
                free_flow_speed_observations, free_flow_speed_sum, latest_observed_at
            )
            SELECT
                date_bin(INTERVAL '5 minutes', observed_at, TIMESTAMPTZ '2000-01-01 00:00:00+00'),
                COALESCE(route_no, ''), COALESCE(direction, ''), COUNT(*),
                COUNT(speed), SUM(speed), MIN(speed), MAX(speed),
                COUNT(free_flow_speed), SUM(free_flow_speed), MAX(observed_at)
            FROM highway_traffic_snapshots
            GROUP BY 1, 2, 3
            """
        )


def downgrade() -> None:
    op.drop_index(
        "ix_highway_traffic_five_minute_statistics_bucket_route",
        table_name="highway_traffic_five_minute_statistics",
    )
    op.drop_table("highway_traffic_five_minute_statistics")
