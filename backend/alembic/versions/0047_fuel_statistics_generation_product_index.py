"""공개 세대·유종 point를 바로 찾는 인덱스(공개 유가 places·가격 분포, 2026-11-23).

공개 화면은 늘 "한 세대(source, generated_at) + 유종"을 읽는다. 기존 세대 인덱스(source, generated_at)에는 유종이 없어
추정이 맞을 때 계획기가 PostgreSQL 18의 skip scan으로 기본키(source, station_key, product_code, generated_at)를 골랐고
운영에서 9.2초가 걸렸다(EXPLAIN ANALYZE, 1.56M 행·54세대). 세대·유종 순 인덱스로 그 선택지를 이기게 한다.

운영 중 수집 insert가 기다리지 않게 CREATE INDEX CONCURRENTLY로 만든다(0026과 같은 방식). 실패로 남은 invalid 인덱스는
지우고 다시 만든다. 호출자가 연 트랜잭션 안에서 단계 실행할 때(시험의 단계 migration)는 autocommit 블록을 쓸 수 없어
일반 CREATE/DROP INDEX를 쓴다.
"""

import sqlalchemy as sa

from alembic import op

revision = "0047_fuel_points_gen_product"
down_revision = "0046_fuel_manual_refresh"
branch_labels = None
depends_on = None

NAME = "ix_fuel_statistics_points_generation_product"
TABLE = "fuel_statistics_points"
COLUMNS = ["source", "generated_at", "product_code"]


def _concurrent() -> bool:
    return op.get_bind().dialect.name == "postgresql" and not getattr(op.get_context(), "_in_external_transaction", False)


def upgrade() -> None:
    if not _concurrent():
        op.create_index(NAME, TABLE, COLUMNS, if_not_exists=True)
        return
    if op.get_context().as_sql:
        # 오프라인 `alembic upgrade --sql`: 연결이 없어 indisvalid를 읽을 수 없다. 스크립트는 DB가 down_revision에
        # 있다고 가정하므로 남은 인덱스는 실패한 CONCURRENTLY의 invalid 잔재뿐이다. 지우고 다시 만든다(둘 다 쓰기를
        # 막지 않는다). 이미 유효한 인덱스가 있으면 한 번 다시 만든다. autocommit_block은 COMMIT 뒤에 이 두 문장을
        # transaction 밖에서 내고 BEGIN으로 돌아간다(CONCURRENTLY는 transaction 안에서 실행할 수 없다).
        with op.get_context().autocommit_block():
            op.drop_index(NAME, table_name=TABLE, postgresql_concurrently=True, if_exists=True)
            op.create_index(NAME, TABLE, COLUMNS, postgresql_concurrently=True)
        return
    with op.get_context().autocommit_block():
        is_valid = op.get_bind().scalar(sa.text(
            "SELECT pg_index.indisvalid FROM pg_index WHERE pg_index.indexrelid = pg_catalog.to_regclass(:name)"
        ), {"name": NAME})
        if is_valid is True:
            return
        if is_valid is False:
            op.drop_index(NAME, table_name=TABLE, postgresql_concurrently=True, if_exists=True)
        op.create_index(NAME, TABLE, COLUMNS, postgresql_concurrently=True, if_not_exists=True)


def downgrade() -> None:
    if not _concurrent():
        op.drop_index(NAME, table_name=TABLE, if_exists=True)
        return
    with op.get_context().autocommit_block():
        op.drop_index(NAME, table_name=TABLE, postgresql_concurrently=True, if_exists=True)
