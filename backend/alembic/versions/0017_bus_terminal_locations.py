"""버스 터미널의 검증된 지도 좌표와 출처를 저장한다."""

import sqlalchemy as sa
from alembic import op

revision = "0017_bus_terminal_locations"
down_revision = "0016_bus_timetable_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bus_terminal_references", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("bus_terminal_references", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("bus_terminal_references", sa.Column("location_source", sa.String(80), nullable=True))
    op.create_check_constraint(
        "ck_bus_terminal_reference_coordinates",
        "bus_terminal_references",
        "(latitude IS NULL AND longitude IS NULL) OR "
        "(latitude IS NOT NULL AND longitude IS NOT NULL AND "
        "latitude BETWEEN 32 AND 39.5 AND longitude BETWEEN 124 AND 132)",
    )
    op.create_index(
        "ix_bus_terminal_reference_coordinates", "bus_terminal_references", ["latitude", "longitude"]
    )


def downgrade() -> None:
    op.drop_index("ix_bus_terminal_reference_coordinates", table_name="bus_terminal_references")
    op.drop_constraint("ck_bus_terminal_reference_coordinates", "bus_terminal_references", type_="check")
    op.drop_column("bus_terminal_references", "location_source")
    op.drop_column("bus_terminal_references", "longitude")
    op.drop_column("bus_terminal_references", "latitude")
