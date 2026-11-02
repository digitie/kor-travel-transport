"""원천별 시간표 갱신을 구분해 KRIC 자료 없음이 새 공식 원천을 막지 않는다."""
from alembic import op
import sqlalchemy as sa

revision = "0038_rail_attempt_provider"
down_revision = "0037_fuel_regions_rail_daily"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
    with op.batch_alter_table("kric_timetable_attempts") as batch:
        batch.add_column(sa.Column("provider", sa.String(24), nullable=False, server_default="kric"))
        batch.create_check_constraint("ck_rail_attempt_provider", "provider IN ('kric', 'humetro')")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM kric_timetable_attempts WHERE provider <> 'kric' LIMIT 1")).first():
        raise RuntimeError("별도 원천 호출 이력이 있어 provider를 삭제할 수 없습니다.")
    with op.batch_alter_table("kric_timetable_attempts") as batch:
        batch.drop_constraint("ck_rail_attempt_provider", type_="check")
        batch.drop_column("provider")
