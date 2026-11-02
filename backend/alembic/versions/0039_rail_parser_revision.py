"""파서 수정 전 실패와 수정 후 요청을 구분하고 원 실패를 초기화하지 않는다."""
from alembic import op
import sqlalchemy as sa

revision = "0039_rail_parser_revision"
down_revision = "0038_rail_attempt_provider"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("kric_timetable_attempts", sa.Column("provider_revision", sa.String(32), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM kric_timetable_attempts WHERE provider_revision IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("파서 버전 호출 이력이 있어 열을 삭제할 수 없습니다.")
    op.drop_column("kric_timetable_attempts", "provider_revision")
