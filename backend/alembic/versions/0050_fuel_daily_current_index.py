"""일별 유가 통계의 공개 세대 하루 읽기 인덱스(통계 페이지 시군구 2~3초, 2026-11-26).

`GET /v1/transport/fuel/statistics`는 "공개 세대 날짜의 그 scope 모든 범주"를 읽는다. 기본키는
`(source, scope, scope_key, product_code, day)`라 day가 scope_key 뒤에 있다. 범주가 230개인 시군구는 이 읽기가
PostgreSQL 18 skip scan으로 범주마다 기본키를 다시 내려간다(400일 합성 데이터: Index Searches 461·공유 버퍼 3,494).
운영 2~3초가 이 때문이라는 것은 가설이다(운영 EXPLAIN 미확인, 로컬 재현은 수십 ms). 운영에서 응답 없는 유종(product_code=ZZZZ, 158바이트)도 2.6~3.0초였고 같은
요청의 시도·고속도로는 0.15~0.4초였다(2026-11-26 공개 GET 측정). `(source, scope, day, product_code)` 인덱스로 그날 행만 읽는다.

운영 중 수집 공개의 일별 delete/insert가 기다리지 않게 CREATE INDEX CONCURRENTLY로 만든다(0047과 같은 방식). 실패로 남은
invalid 인덱스는 지우고 다시 만든다. 호출자가 연 transaction 안에서 단계 실행할 때(시험의 단계 migration)는 autocommit
블록을 쓸 수 없어 일반 CREATE/DROP INDEX를 쓴다.
"""

import sqlalchemy as sa

from alembic import op

revision = "0050_fuel_daily_current_index"
down_revision = "0049_fuel_statistics_history"
branch_labels = None
depends_on = None

NAME = "ix_fuel_statistics_daily_current"
TABLE = "fuel_statistics_daily"
COLUMNS = ["source", "scope", "day", "product_code"]


def _concurrent() -> bool:
    return op.get_bind().dialect.name == "postgresql" and not getattr(op.get_context(), "_in_external_transaction", False)


def upgrade() -> None:
    if not _concurrent():
        op.create_index(NAME, TABLE, COLUMNS, if_not_exists=True)
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
