"""휴게소 표준 코드(KREX 0615)와 휴게소 푸드메뉴(KREX 0502) 저장소를 추가한다."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0051_rest_area_food"
down_revision = "0050_fuel_daily_current_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.create_table(
        "rest_area_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("std_rest_code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("facility_class", sa.String(length=20), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=True),
        sa.Column("route_code", sa.String(length=20), nullable=True),
        sa.Column("route_name", sa.String(length=160), nullable=True),
        sa.Column("service_area_code", sa.String(length=20), nullable=True),
        sa.Column("address", sa.String(length=300), nullable=True),
        sa.Column("phone_number", sa.String(length=80), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_item_json", json_type, nullable=True),
        sa.UniqueConstraint("source", "std_rest_code", name="uq_rest_area_code"),
    )
    op.create_index("ix_rest_area_codes_last_seen", "rest_area_codes", ["last_seen_at"])
    op.create_table(
        "rest_area_food_menus",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("std_rest_code", sa.String(length=20), nullable=False),
        sa.Column("seq", sa.String(length=20), nullable=False),
        sa.Column("food_name", sa.String(length=200), nullable=False),
        sa.Column("price", sa.Integer(), nullable=True),
        sa.Column("is_best", sa.Boolean(), nullable=True),
        sa.Column("is_premium", sa.Boolean(), nullable=True),
        sa.Column("is_recommended", sa.Boolean(), nullable=True),
        sa.Column("season", sa.String(length=20), nullable=True),
        sa.Column("app_listed", sa.Boolean(), nullable=True),
        sa.Column("menu_updated_on", sa.Date(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_item_json", json_type, nullable=True),
        sa.UniqueConstraint("source", "std_rest_code", "seq", name="uq_rest_area_food_menu"),
    )
    op.create_index("ix_rest_area_food_menus_code", "rest_area_food_menus", ["std_rest_code"])
    op.create_index("ix_rest_area_food_menus_last_seen", "rest_area_food_menus", ["last_seen_at"])


def downgrade() -> None:
    op.drop_index("ix_rest_area_food_menus_last_seen", table_name="rest_area_food_menus")
    op.drop_index("ix_rest_area_food_menus_code", table_name="rest_area_food_menus")
    op.drop_table("rest_area_food_menus")
    op.drop_index("ix_rest_area_codes_last_seen", table_name="rest_area_codes")
    op.drop_table("rest_area_codes")
