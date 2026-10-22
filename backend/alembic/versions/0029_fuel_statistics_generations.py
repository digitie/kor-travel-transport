"""공개 세대와 준비 세대의 지도 통계 행을 분리한다."""
import sqlalchemy as sa
from alembic import op

revision = "0029_fuel_statistics_generations"
down_revision = "0028_fuel_statistics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # table 전체 재생성 없이 PK만 바꾼다. lock 획득은 유한하게 기다린다.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.drop_constraint("fuel_statistics_points_pkey", "fuel_statistics_points", type_="primary")
    op.create_primary_key("fuel_statistics_points_pkey", "fuel_statistics_points",
                          ["source", "station_key", "product_code", "generated_at"])
    op.create_index("ix_fuel_statistics_points_generation", "fuel_statistics_points", ["source", "generated_at"])


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    # 구 코드가 읽을 공개 세대만 남긴다. 원본 가격 이력에는 손대지 않는다.
    op.execute("DELETE FROM fuel_statistics_points p WHERE NOT EXISTS ("
               "SELECT 1 FROM fuel_statistics_states s WHERE s.source=p.source AND s.generated_at=p.generated_at)")
    op.drop_index("ix_fuel_statistics_points_generation", table_name="fuel_statistics_points")
    op.drop_constraint("fuel_statistics_points_pkey", "fuel_statistics_points", type_="primary")
    op.create_primary_key("fuel_statistics_points_pkey", "fuel_statistics_points", ["source", "station_key", "product_code"])
