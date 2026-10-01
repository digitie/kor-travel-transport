"""최신 유가 조회를 위한 물질화 뷰와 이력 정렬 인덱스."""

from alembic import op
import sqlalchemy as sa

revision = "0018_fuel_latest_prices"
down_revision = "0017_bus_terminal_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("0018은 concurrent index 검증을 위해 온라인 migration만 지원합니다.")
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '3s'")
        op.execute("SET statement_timeout = '180s'")
        try:
            valid = op.get_bind().scalar(sa.text(
                "SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass('ix_fuel_prices_latest_lookup')"
            ))
            if valid is False:
                raise RuntimeError("invalid ix_fuel_prices_latest_lookup: 해당 index만 정리 후 재실행 필요")
            if valid is None:
                op.create_index(
                    "ix_fuel_prices_latest_lookup", "fuel_price_snapshots",
                    ["fuel_station_id", "product_code", sa.text("collected_at DESC"), sa.text("id DESC")],
                    postgresql_concurrently=True,
                )
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")

    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("SET LOCAL statement_timeout = '180s'")
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
    op.execute("ANALYZE fuel_latest_prices")


def downgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("0018은 concurrent index 검증을 위해 온라인 migration만 지원합니다.")
    # 먼저 원본 테이블의 index를 잠금 상한 안에서 정리한다. 이 단계가 실패하면
    # MV를 건드리지 않아 현재 runtime의 조회 계약이 유지된다.
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '3s'")
        op.execute("SET statement_timeout = '180s'")
        try:
            op.drop_index("ix_fuel_prices_latest_lookup", table_name="fuel_price_snapshots",
                          postgresql_concurrently=True, if_exists=True)
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP MATERIALIZED VIEW fuel_latest_prices")
