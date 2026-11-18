"""일반 장소 지도 입력 전체의 같은 transaction statement revision."""
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0045_places_input_revision"
down_revision = "0044_places_read_indexes"
branch_labels = None
depends_on = None

# 전체 행/모든 UPDATE를 보수적으로 추적한다. raw 시설·성공 집합 선택도 생략하지 않는다.
TABLES = (
    "fuel_stations", "fuel_latest_prices", "rail_station_references", "ferry_ports",
    "bus_terminal_references", "airports", "rest_area_references", "public_parking_lots",
    "highway_incident_snapshots", "transport_collection_states",
)


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
        op.execute("SET LOCAL statement_timeout = '120s'")
    op.bulk_insert(sa.table("reference_export_input_revisions",
        sa.column("component", sa.String()), sa.column("epoch", sa.String()),
        sa.column("revision", sa.BigInteger())),
        [{"component": "places." + table, "epoch": str(uuid4()), "revision": 0} for table in TABLES])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""CREATE FUNCTION public.kt_places_revision() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        DECLARE affected integer;
        BEGIN
            UPDATE public.reference_export_input_revisions
                SET revision = revision + 1 WHERE component = 'places.' || TG_TABLE_NAME;
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'places input revision missing';
            END IF;
            RETURN NULL;
        END $$""")
    for table in TABLES:
        for action in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            op.execute(f"CREATE TRIGGER kt_places_revision_{action.lower()} AFTER {action} "
                       f"ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.kt_places_revision()")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
        op.execute("SET LOCAL statement_timeout = '120s'")
        for table in TABLES:
            for action in ("insert", "update", "delete", "truncate"):
                op.execute(f"DROP TRIGGER kt_places_revision_{action} ON public.{table}")
        op.execute("DROP FUNCTION public.kt_places_revision()")
    for table in TABLES:
        op.execute(sa.text("DELETE FROM reference_export_input_revisions WHERE component = :component")
                   .bindparams(component="places." + table))
