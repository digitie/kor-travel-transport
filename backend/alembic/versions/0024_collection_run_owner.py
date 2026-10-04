"""Dagster 수집 소유권과 heartbeat. 기존 무소유 행은 자동 회수하지 않는다."""

import sqlalchemy as sa

from alembic import op

revision = "0024_collection_run_owner"
down_revision = "0023_map_service_exports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column(
        "collection_runs",
        sa.Column("orchestrator_run_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "collection_runs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_collection_runs_orchestrator_run_id",
        "collection_runs",
        ["orchestrator_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_collection_runs_orchestrator_run_id", table_name="collection_runs"
    )
    op.drop_column("collection_runs", "heartbeat_at")
    op.drop_column("collection_runs", "orchestrator_run_id")
