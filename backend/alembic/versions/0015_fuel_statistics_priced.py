"""가격이 있는 행만 유가 통계 인덱스에 유지한다."""

from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa

revision = "0015_fuel_statistics_priced"
down_revision = "0014_kric_timetables"
branch_labels = None
depends_on = None


@contextmanager
def _bounded_concurrent_ddl():
    # asyncpg는 libpq PGOPTIONS를 사용하지 않으므로 실제 연결에서 제한한다.
    if op.get_context().as_sql:
        raise RuntimeError("0015는 invalid index 검증을 위해 온라인 migration만 지원합니다.")
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '3s'")
        op.execute("SET statement_timeout = '180s'")
        try:
            yield
        finally:
            op.execute("RESET statement_timeout")
            op.execute("RESET lock_timeout")


def _ensure_index(name: str, *, priced: bool) -> None:
    # 중단된 concurrent DDL의 invalid index를 정상으로 오인하지 않는다.
    valid = op.get_bind().scalar(sa.text(
        "SELECT indisvalid FROM pg_index WHERE indexrelid=to_regclass(:name)"
    ), {"name": name})
    if valid is False:
        raise RuntimeError(f"invalid index {name}: 해당 index만 DROP INDEX CONCURRENTLY 후 재실행 필요")
    if valid is None:
        options = {"postgresql_where": sa.text("price IS NOT NULL")} if priced else {}
        op.create_index(name, "fuel_price_snapshots", ["collected_at", "product_code", "fuel_station_id"],
                        postgresql_include=["price", "observed_at"], postgresql_concurrently=True, **options)


def upgrade() -> None:
    with _bounded_concurrent_ddl():
        _ensure_index("ix_fuel_prices_statistics_priced", priced=True)
        op.drop_index("ix_fuel_prices_statistics_collected", table_name="fuel_price_snapshots",
                      postgresql_concurrently=True, if_exists=True)
    # 전체 DB 설정을 바꾸지 않고 배치 upsert가 잦은 유가 테이블만 정비 빈도를 높인다.
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE fuel_price_snapshots SET (autovacuum_vacuum_scale_factor=0.02, "
               "autovacuum_vacuum_insert_scale_factor=0.02, autovacuum_analyze_scale_factor=0.02)")


def downgrade() -> None:
    with _bounded_concurrent_ddl():
        _ensure_index("ix_fuel_prices_statistics_collected", priced=False)
        op.drop_index("ix_fuel_prices_statistics_priced", table_name="fuel_price_snapshots",
                      postgresql_concurrently=True, if_exists=True)
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE fuel_price_snapshots RESET (autovacuum_vacuum_scale_factor, "
               "autovacuum_vacuum_insert_scale_factor, autovacuum_analyze_scale_factor)")
