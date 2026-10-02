"""Map 이관용 휴게소 유가 저장소와 돌발 활성 집합 index (ADR-012).

- `rest_area_fuel_prices`: EX `curStateStation` 휴게소 주유소의 현재 유가(휴게소별 1행).
- `ix_highway_incidents_source_collected`: 마지막 성공 수집이 재관측한 돌발 집합을
  `collected_at` 일치로 찾는 service export 경로(약 15만 행, 일반 index로 수 초).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0023_map_service_exports"
down_revision = "0022_fuel_latest_prices_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '300s'")
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "rest_area_fuel_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("service_area_code", sa.String(length=40), nullable=False),
        sa.Column("service_area_code2", sa.String(length=40), nullable=True),
        sa.Column("service_area_name", sa.String(length=160), nullable=True),
        sa.Column("route_code", sa.String(length=40), nullable=True),
        sa.Column("route_name", sa.String(length=160), nullable=True),
        sa.Column("direction", sa.String(length=80), nullable=True),
        sa.Column("oil_company", sa.String(length=80), nullable=True),
        sa.Column("has_lpg", sa.Boolean(), nullable=True),
        sa.Column("phone_number", sa.String(length=80), nullable=True),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("gasoline_price", sa.Integer(), nullable=True),
        sa.Column("diesel_price", sa.Integer(), nullable=True),
        sa.Column("lpg_price", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_item_json", json_type, nullable=True),
        sa.UniqueConstraint("source", "service_area_code", name="uq_rest_area_fuel_price_code"),
    )
    op.create_index("ix_rest_area_fuel_prices_last_seen", "rest_area_fuel_prices", ["last_seen_at"])
    op.create_index(
        "ix_highway_incidents_source_collected", "highway_incident_snapshots", ["source", "collected_at"],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.drop_index("ix_highway_incidents_source_collected", table_name="highway_incident_snapshots")
    op.drop_index("ix_rest_area_fuel_prices_last_seen", table_name="rest_area_fuel_prices")
    op.drop_table("rest_area_fuel_prices")
