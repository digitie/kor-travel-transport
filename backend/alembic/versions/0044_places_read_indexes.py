"""장소 최신 주유소 정렬과 최근 돌발 winner 후보의 읽기 인덱스."""

import sqlalchemy as sa
from alembic import op

revision = "0044_places_read_indexes"
down_revision = "0043_reference_input_revisions"
branch_labels = None
depends_on = None


def _set_timeouts():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
        op.execute("SET LOCAL statement_timeout = '120s'")


def upgrade():
    _set_timeouts()
    op.create_index("ix_fuel_stations_seen_id", "fuel_stations",
                    [sa.text("last_seen_at DESC"), sa.text("id DESC")])
    op.create_index("ix_highway_incidents_recent_cover", "highway_incident_snapshots",
                    ["collected_at"], postgresql_include=["id", "source", "identity_key", "observed_at"])


def downgrade():
    _set_timeouts()
    op.drop_index("ix_highway_incidents_recent_cover", table_name="highway_incident_snapshots")
    op.drop_index("ix_fuel_stations_seen_id", table_name="fuel_stations")
