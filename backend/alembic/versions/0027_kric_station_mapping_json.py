"""KRIC 역 코드 카탈로그와 관리용 JSON 연결표를 저장한다."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0027_kric_station_mapping_json"
down_revision = "0026_transport_map_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kric_station_mapping_registry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("catalog_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("automatic_mappings_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("manual_mappings_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("catalog_sha256", sa.String(length=64), nullable=True),
        sa.Column("catalog_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mappings_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_kric_station_mapping_registry_singleton"),
    )
    op.execute(sa.text("""
        INSERT INTO kric_station_mapping_registry (
            id, catalog_json, automatic_mappings_json, manual_mappings_json,
            catalog_updated_at, updated_at
        )
        SELECT
            1,
            COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'operator_code', operator_code,
                        'operator_name', operator_name,
                        'line_code', line_code,
                        'line_name', line_name,
                        'station_code', station_code,
                        'station_name', station_name
                    ) ORDER BY operator_code, line_code, station_code
                ),
                '[]'::jsonb
            ),
            '[]'::jsonb,
            '[]'::jsonb,
            MAX(last_seen_at),
            CURRENT_TIMESTAMP
        FROM kric_station_codes
        WHERE active IS TRUE
    """))


def downgrade() -> None:
    op.drop_table("kric_station_mapping_registry")
