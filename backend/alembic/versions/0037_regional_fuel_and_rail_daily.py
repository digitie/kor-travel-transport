"""영구 지역 유가 요약과 역별 일일 시간표 호출 원장."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0037_fuel_regions_rail_daily"
down_revision = "0036_parking_statistics_archive"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table("fuel_region_summaries",
        sa.Column("source", sa.Text(), primary_key=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("scope", sa.Text(), primary_key=True),
        sa.Column("region_key", sa.Text(), primary_key=True),
        sa.Column("product_code", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("average_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("station_count", sa.Integer(), nullable=False),
        sa.Column("metrics_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.CheckConstraint("scope IN ('sido', 'sigungu')", name="ck_fuel_region_scope"),
        sa.CheckConstraint("station_count > 0 AND average_price > 0", name="ck_fuel_region_values"),
    )
    op.create_table("kric_timetable_attempts",
        sa.Column("station_id", sa.BigInteger(), sa.ForeignKey("kric_station_codes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day_code", sa.String(1), primary_key=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.CheckConstraint("day_code IN ('7', '8', '9')", name="ck_kric_attempt_day"),
        sa.CheckConstraint("outcome IN ('pending', 'stored', 'no_data', 'error')", name="ck_kric_attempt_outcome"),
    )
    # 마지막 공개 가격 세대만 요약해 새 지도 읽기를 연결한다. 새 수집으로 기록하지 않는다.
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            INSERT INTO fuel_region_summaries
              (source, generated_at, scope, region_key, product_code, label,
               longitude, latitude, average_price, station_count, metrics_json)
            SELECT p.source, p.generated_at, r.scope,
              concat_ws(':', p.source, s.sido_value, CASE WHEN r.scope='sigungu' THEN s.sigungu_value ELSE NULL END),
              p.product_code,
              max(s.sido_name) || CASE WHEN r.scope='sigungu' THEN ' ' || max(s.sigungu_name) ELSE '' END,
              avg(CASE WHEN s.longitude BETWEEN -180 AND 180 AND s.latitude BETWEEN -90 AND 90 THEN s.longitude END),
              avg(CASE WHEN s.longitude BETWEEN -180 AND 180 AND s.latitude BETWEEN -90 AND 90 THEN s.latitude END),
              avg(p.price), count(*), jsonb_build_object('minimum_price', min(p.price), 'maximum_price', max(p.price))
            FROM fuel_statistics_points p
            JOIN fuel_statistics_states g ON g.source=p.source AND g.generated_at=p.generated_at
            JOIN fuel_stations s ON s.source=p.source AND s.id::text=p.station_key
            CROSS JOIN (VALUES ('sido'), ('sigungu')) AS r(scope)
            WHERE s.sido_value<>'' AND p.price>0 AND (r.scope='sido' OR s.sigungu_value<>'')
            GROUP BY p.source, p.generated_at, r.scope, s.sido_value,
              CASE WHEN r.scope='sigungu' THEN s.sigungu_value ELSE NULL END, p.product_code
        """)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM fuel_region_summaries LIMIT 1")).first():
        raise RuntimeError("영구 유가 통계가 있으므로 downgrade할 수 없습니다.")
    op.drop_table("kric_timetable_attempts")
    op.drop_table("fuel_region_summaries")
