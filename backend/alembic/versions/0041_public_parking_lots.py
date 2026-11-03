"""전국주차장 기준정보를 Transport 소유로 저장한다."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0041_public_parking_lots"
down_revision = "0040_archive_rail_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    columns = [
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), sa.Identity(), primary_key=True),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
    ]
    columns += [sa.Column(name, sa.Text(), nullable=True) for name in (
        "provider_id", "category", "parking_type", "road_address", "land_address", "fee_info", "operating_days",
        "payment_methods", "notes", "phone", "institution_name", "institution_code", "disabled_parking",
    )]
    columns += [sa.Column(name, sa.Float(), nullable=True) for name in ("longitude", "latitude")]
    columns += [sa.Column("capacity", sa.Integer(), nullable=True)]
    columns += [sa.Column(name, sa.Numeric(10, 3), nullable=True) for name in ("basic_minutes", "additional_minutes", "daily_minutes")]
    columns += [sa.Column(name, sa.BigInteger(), nullable=True) for name in ("basic_fee", "additional_fee", "daily_fee", "monthly_fee")]
    columns += [
        sa.Column("reference_date", sa.Date(), nullable=True),
        sa.Column("opening_hours_json", json_type, nullable=False), sa.Column("raw_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source", "source_key", name="uq_public_parking_lot_source_key"),
        sa.CheckConstraint("capacity IS NULL OR capacity >= 0", name="ck_public_parking_capacity"),
    ]
    op.create_table("public_parking_lots", *columns)
    op.create_index("ix_public_parking_lots_current", "public_parking_lots", ["source", "last_seen_at", "id"])
    op.create_index("ix_public_parking_lots_bbox", "public_parking_lots", ["source", "last_seen_at", "longitude", "latitude"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM public_parking_lots LIMIT 1)")):
        raise RuntimeError("저장된 주차장 기준정보를 삭제하는 downgrade는 허용하지 않습니다.")
    op.drop_table("public_parking_lots")
