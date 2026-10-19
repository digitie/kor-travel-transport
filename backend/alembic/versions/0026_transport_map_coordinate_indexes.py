"""지도 bbox 질의가 좌표를 먼저 찾도록 인덱스를 추가한다."""

import sqlalchemy as sa

from alembic import op

revision = "0026_transport_map_indexes"
down_revision = "0025_reverse_addresses"
branch_labels = None
depends_on = None


_INDEXES = (
    ("ix_fuel_stations_map_coordinates", "fuel_stations", ("longitude", "latitude"), True),
    ("ix_rail_station_reference_map_coordinates", "rail_station_references", ("longitude", "latitude"), True),
    ("ix_highway_incidents_collected_at", "highway_incident_snapshots", ("collected_at",), False),
)


def _create(name: str, table: str, columns: tuple[str, ...], coordinates: bool) -> None:
    options = {}
    if coordinates:
        options = {
            "postgresql_where": sa.text(
                "longitude BETWEEN -180 AND 180 AND latitude BETWEEN -90 AND 90"
            ),
            "sqlite_where": sa.text(
                "longitude BETWEEN -180 AND 180 AND latitude BETWEEN -90 AND 90"
            ),
        }
    if op.get_bind().dialect.name == "postgresql":
        # 지도 운영 중 인덱스를 추가해도 수집 upsert가 테이블 잠금을 기다리지 않게 한다.
        with op.get_context().autocommit_block():
            # CREATE INDEX CONCURRENTLY 실패는 invalid index 이름을 남길 수 있다.
            # 유효한 선행 인덱스는 건너뛰고, invalid 인덱스만 제거해 재시도한다.
            is_valid = op.get_bind().scalar(sa.text(
                "SELECT pg_index.indisvalid FROM pg_index "
                "WHERE pg_index.indexrelid = pg_catalog.to_regclass(:index_name)"
            ), {"index_name": name})
            if is_valid is True:
                return
            if is_valid is False:
                op.drop_index(name, table_name=table, postgresql_concurrently=True, if_exists=True)
            op.create_index(
                name, table, list(columns),
                postgresql_concurrently=True, if_not_exists=True, **options,
            )
        return
    op.create_index(name, table, list(columns), if_not_exists=True, **options)


def _drop(name: str, table: str) -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(name, table_name=table, postgresql_concurrently=True, if_exists=True)
        return
    op.drop_index(name, table_name=table, if_exists=True)


def upgrade() -> None:
    for name, table, columns, coordinates in _INDEXES:
        _create(name, table, columns, coordinates)


def downgrade() -> None:
    for name, table, _, _ in reversed(_INDEXES):
        _drop(name, table)
