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
    if op.get_context().as_sql:
        _offline_upgrade()
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


def _offline_upgrade() -> None:
    """오프라인 `alembic upgrade --sql`: 연결이 없어 indisvalid를 미리 읽을 수 없으므로 판단을 SQL 안에 둔다.

    1. (migration transaction 안) 실패한 CONCURRENTLY의 invalid 잔재면 `<이름>_invalid`로 이름만 바꾼다. 이름 바꾸기는
       SHARE UPDATE EXCLUSIVE(PostgreSQL 12+)라 읽기·쓰기를 막지 않는다. 유효한 인덱스는 그대로 둔다(다시 만들지 않아 느린 계획
       구간이 없다).
    2. (COMMIT 뒤 transaction 밖) 잔재를 `DROP INDEX CONCURRENTLY IF EXISTS`, `CREATE INDEX CONCURRENTLY IF NOT EXISTS`.
    3. (다시 BEGIN 안) 인덱스가 없거나 invalid이거나 `<이름>_invalid` 잔재가 남았으면(DROP 실패) 예외로 그 transaction을
       중단해 `alembic_version`을 올리지 않는다.
       `psql`은 기본(`ON_ERROR_STOP=off`)이면 2의 실패 뒤에도 다음 문장을 계속 실행하므로 이 확인이 버전 전진을 막는다.
       실행은 `psql -v ON_ERROR_STOP=1 -f`를 쓴다.
    """
    old = f"{NAME}_invalid"
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_index WHERE indexrelid = pg_catalog.to_regclass('{NAME}') "
        f"AND NOT indisvalid) THEN IF pg_catalog.to_regclass('{old}') IS NOT NULL THEN RAISE EXCEPTION "
        f"'{old} 가 이미 있다. DROP INDEX CONCURRENTLY {old} 뒤 다시 실행'; END IF; "
        f"ALTER INDEX {NAME} RENAME TO {old}; END IF; END $$"
    )
    with op.get_context().autocommit_block():
        op.drop_index(old, table_name=TABLE, postgresql_concurrently=True, if_exists=True)
        op.create_index(NAME, TABLE, COLUMNS, postgresql_concurrently=True, if_not_exists=True)
    op.execute(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_index WHERE indexrelid = pg_catalog.to_regclass('{NAME}') "
        f"AND indisvalid) THEN RAISE EXCEPTION '{NAME} 인덱스가 없거나 invalid라 버전을 올리지 않는다'; END IF; "
        f"IF pg_catalog.to_regclass('{old}') IS NOT NULL THEN RAISE EXCEPTION "
        f"'{old} 잔재가 남았다(DROP 실패). DROP INDEX CONCURRENTLY {old} 뒤 다시 실행'; END IF; END $$"
    )


def downgrade() -> None:
    if not _concurrent():
        op.drop_index(NAME, table_name=TABLE, if_exists=True)
        return
    with op.get_context().autocommit_block():
        op.drop_index(NAME, table_name=TABLE, postgresql_concurrently=True, if_exists=True)
