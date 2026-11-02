"""주차 보관 범위와 철도·유가 마이그레이션 분기를 통합한다."""
revision = "0040_archive_rail_merge"
down_revision = ("0037_parking_archive_coverage", "0039_rail_parser_revision")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
