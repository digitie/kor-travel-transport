"""장기 유가 추이용 좁은 일별 요약 표와 기존 일별 통계 backfill(2026-11-26).

`fuel_statistics_daily`는 범주·유종·날짜마다 `metrics_json`(가격순 10곳·최저가 주유소 포함, 시군구 하루 약 1MB)을
가진다. 몇 달·몇 년 추이를 그 JSON에서 읽으면 하루치마다 순위 전체를 detoast한다. 그래서 같은 키
`(source, scope, scope_key, product_code, day)`에 평균·최저·최고·주유소 수·세대 시각·이름만 typed 열로 두는
`fuel_statistics_history`를 만든다. 수집 공개(`publish_fuel_statistics`)가 일별 행과 같은 transaction으로 쓰고 영구 보존한다.

backfill은 기존 일별 행의 `metrics_json`에서 같은 값을 옮긴다. 운영(2026-11 기준 하루 약 1,600행·약 40일)은 수만 행이라
한 transaction 안에서 31일 창씩 나눈 INSERT … SELECT로 끝낸다(문장마다 읽는 JSON을 한 달치로 묶어 ODROID 512MiB에서도
작업 메모리가 커지지 않게 한다). 새 표는 이 transaction 밖에서 아무도 읽거나 쓰지 않으므로 수집 공개(일별 delete/insert)와
잠금이 겹치지 않는다 — 일별 표에는 AccessShare만 잡는다. 실패하면 표 생성까지 함께 되돌아가 다시 실행할 수 있다.

배포 중 옛 이미지가 이 migration 뒤에 한 번 더 공개하면 그날 일별 행만 바뀌고 새 표는 그 전 값이다. 새 이미지의 다음
공개가 직전 공개 세대 날짜를 일별 행에서 다시 맞춘다(`publish_fuel_statistics` 참고).

downgrade는 표만 지운다. 값은 모두 일별 표에서 다시 만들 수 있다(그래서 영구 원장과 달리 비어 있지 않아도 지운다).
"""

from datetime import date, timedelta

import sqlalchemy as sa
from alembic import op

revision = "0049_fuel_statistics_history"
down_revision = "0048_states_revision_digest"
branch_labels = None
depends_on = None

#: backfill 한 문장이 읽는 날짜 폭.
BACKFILL_DAYS = 31

_PG_BACKFILL = """
    INSERT INTO fuel_statistics_history
      (source, scope, scope_key, product_code, day, generated_at, label,
       average_price, minimum_price, maximum_price, station_count)
    SELECT source, scope, scope_key, product_code, day, generated_at, label,
      round((metrics_json->>'average_price')::numeric, 2),
      (metrics_json->>'minimum_price')::numeric, (metrics_json->>'maximum_price')::numeric,
      (metrics_json->>'station_count')::integer
    FROM fuel_statistics_daily
    WHERE day >= :start AND day < :end
      AND jsonb_typeof(metrics_json->'average_price') = 'number'
      AND jsonb_typeof(metrics_json->'station_count') = 'number'
      AND (metrics_json->>'average_price')::numeric > 0
      AND (metrics_json->>'station_count')::integer > 0
    ON CONFLICT DO NOTHING
"""

_SQLITE_BACKFILL = """
    INSERT OR IGNORE INTO fuel_statistics_history
      (source, scope, scope_key, product_code, day, generated_at, label,
       average_price, minimum_price, maximum_price, station_count)
    SELECT source, scope, scope_key, product_code, day, generated_at, label,
      round(json_extract(metrics_json, '$.average_price'), 2),
      json_extract(metrics_json, '$.minimum_price'), json_extract(metrics_json, '$.maximum_price'),
      json_extract(metrics_json, '$.station_count')
    FROM fuel_statistics_daily
    WHERE day >= :start AND day < :end
      AND json_extract(metrics_json, '$.average_price') > 0
      AND json_extract(metrics_json, '$.station_count') > 0
"""


def upgrade() -> None:
    bind = op.get_bind()
    postgresql = bind.dialect.name == "postgresql"
    if postgresql:
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '300s'")
    op.create_table(
        "fuel_statistics_history",
        sa.Column("source", sa.String(40), primary_key=True),
        sa.Column("scope", sa.String(24), primary_key=True),
        sa.Column("scope_key", sa.String(512), primary_key=True),
        sa.Column("product_code", sa.String(20), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("average_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("minimum_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("maximum_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("station_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("station_count > 0 AND average_price > 0", name="ck_fuel_statistics_history_values"),
    )
    if op.get_context().as_sql:
        # 오프라인 SQL에는 날짜 범위를 알 수 없다. 한 문장으로 전체를 옮긴다.
        op.execute(sa.text((_PG_BACKFILL if postgresql else _SQLITE_BACKFILL)
                           .replace("day >= :start AND day < :end", "TRUE" if postgresql else "1")))
        return
    first, last = bind.execute(sa.text("SELECT min(day), max(day) FROM fuel_statistics_daily")).one()
    if first is None:
        return
    if isinstance(first, str):  # SQLite는 Date를 문자열로 돌려준다.
        first, last = date.fromisoformat(first), date.fromisoformat(last)
    statement = sa.text(_PG_BACKFILL if postgresql else _SQLITE_BACKFILL)
    start = first
    while start <= last:
        end = start + timedelta(days=BACKFILL_DAYS)
        bind.execute(statement, {"start": start, "end": end})
        start = end


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_table("fuel_statistics_history")
