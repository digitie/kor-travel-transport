"""수집 완료 시점 유가 통계와 지도용 최신 가격을 분리한다."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0028_fuel_statistics"
down_revision = "0027_kric_station_mapping_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("fuel_statistics_states",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False))
    op.create_table("fuel_statistics_points",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("station_key", sa.String(80), primary_key=True),
        sa.Column("product_code", sa.String(20), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(300)),
        sa.Column("brand_name", sa.String(120)),
        sa.Column("longitude", sa.Float()), sa.Column("latitude", sa.Float()),
        sa.Column("price", sa.Numeric(10, 2), nullable=False))
    op.create_index("ix_fuel_statistics_points_bbox", "fuel_statistics_points", ["longitude", "latitude"])
    op.create_table("fuel_statistics_daily",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("scope", sa.String(24), primary_key=True),
        sa.Column("scope_key", sa.String(512), primary_key=True),
        sa.Column("product_code", sa.String(20), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False))


def downgrade() -> None:
    op.drop_table("fuel_statistics_daily")
    op.drop_table("fuel_statistics_points")
    op.drop_table("fuel_statistics_states")
