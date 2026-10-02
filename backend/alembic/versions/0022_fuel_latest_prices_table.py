"""최신 유가 읽기 모델을 materialized view에서 증분 upsert 테이블로 바꾼다.

MV는 갱신(`REFRESH ... CONCURRENTLY`)과 원본 대조가 모두 전 이력(`fuel_price_snapshots`)을
다시 읽는다. 2026-10-02 n150에서 이력이 73만 행·987MB가 되자 두 질의가 60초
statement timeout을 넘겨 매 고속도로 job마다 실패했고, `fuel_prices_stale`이 영구히
참으로 굳었다. 최신 행은 원본과 같은 트랜잭션에서 upsert하면 수집 한 번의 크기만큼만
일하고, 원본과 어긋날 수 없으므로 세대·체크포인트·대조 장치도 필요 없다.
"""

from alembic import op
import sqlalchemy as sa

revision = "0022_fuel_latest_prices_table"
down_revision = "0021_parking_history_cover"
branch_labels = None
depends_on = None

LATEST_ROWS_SQL = """
    SELECT DISTINCT ON (fuel_station_id, product_code)
        fuel_station_id, product_code, id, price,
        provider_updated_at, observed_at, collected_at
    FROM fuel_price_snapshots
    ORDER BY fuel_station_id, product_code, collected_at DESC, id DESC
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # 1회성 backfill은 전 이력을 한 번 읽는다(n150 실측 약 60초).
    op.execute("SET LOCAL statement_timeout = '900s'")
    op.execute("DROP MATERIALIZED VIEW fuel_latest_prices")
    op.create_table(
        "fuel_latest_prices",
        sa.Column("fuel_station_id", sa.Integer(), nullable=False),
        sa.Column("product_code", sa.String(length=20), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["fuel_station_id"], ["fuel_stations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["fuel_price_snapshots.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("fuel_station_id", "product_code"),
    )
    op.execute(
        "INSERT INTO fuel_latest_prices (fuel_station_id, product_code, snapshot_id, price, "
        "provider_updated_at, observed_at, collected_at) " + LATEST_ROWS_SQL
    )
    op.create_index("ix_fuel_latest_prices_snapshot_id", "fuel_latest_prices", ["snapshot_id"])
    op.execute("DELETE FROM transport_collection_states WHERE source = 'fuel_latest_prices'")
    op.drop_column("transport_collection_states", "last_refreshed_snapshot_id")
    op.drop_column("transport_collection_states", "refresh_generation")
    op.execute("ANALYZE fuel_latest_prices")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '900s'")
    op.add_column(
        "transport_collection_states",
        sa.Column("refresh_generation", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "transport_collection_states",
        sa.Column("last_refreshed_snapshot_id", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.drop_table("fuel_latest_prices")
    op.execute("""
        CREATE MATERIALIZED VIEW fuel_latest_prices AS
        SELECT DISTINCT ON (fuel_station_id, product_code)
            id, fuel_station_id, product_code, price,
            provider_updated_at, observed_at, collected_at
        FROM fuel_price_snapshots
        ORDER BY fuel_station_id, product_code, collected_at DESC, id DESC
    """)
    op.create_index(
        "uq_fuel_latest_prices_station_product", "fuel_latest_prices",
        ["fuel_station_id", "product_code"], unique=True,
    )
