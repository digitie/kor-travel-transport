"""참조 입력만 바뀔 때 transaction과 함께 증가하는 statement revision."""
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0043_reference_input_revisions"
down_revision = "0042_reference_export_artifacts"
branch_labels = None
depends_on = None

_ADDRESS_PROVIDER_ID = "vworld-kakao-reverse-v1"

_COMPONENTS = {
    "bus_source": ("bus_terminal_references", "id source service_type terminal_id terminal_name city_name location_source first_seen_at last_seen_at", True),
    "ferry_source": ("ferry_ports", "id source port_id port_name location_source location_point_count first_seen_at last_seen_at", True),
    "rail_source": ("rail_station_references", "id source identity_key rail_operator_name operating_line_name station_type station_number station_name english_name lot_address road_address station_phone_number data_reference_date first_seen_at last_seen_at", False),
    "parking_source": ("parking_current", "source scope_key parking_lot_id generation airport_code lot_code name total_spaces occupied_spaces available_spaces observed_at collected_at", False),
    "rail_codes": ("kric_station_codes", "id operator_code line_code station_code operator_name line_name station_name rail_station_id active last_seen_at", False),
    "rail_registry": ("kric_station_mapping_registry", "id catalog_sha256 automatic_mappings_json manual_mappings_json", False),
}
for _kind in ("bus_terminal", "ferry_port", "rail_station"):
    _COMPONENTS["address_" + _kind] = ("reverse_address_entries",
        "provider_id target_key coordinate_key status payload resolved_at", False)


def _projection(component, fields, manual):
    columns = [f't."{name}"::jsonb' if name in {"payload", "automatic_mappings_json", "manual_mappings_json"}
               else f't."{name}"' for name in fields.split()]
    if component in {"bus_source", "ferry_source", "rail_source"}:
        columns += [f"encode(pg_catalog.float8send(t.{name}), 'hex')" for name in ("latitude", "longitude")]
    if manual:
        columns.append("t.raw_item_json #>> '{_manual_location,revision}'")
    return ", ".join(columns)


def _predicate(component):
    if component.startswith("address_"):
        kind = component.removeprefix("address_")
        return (f"t.provider_id = '{_ADDRESS_PROVIDER_ID}' AND t.status IN ('ok', 'error') "
                f"AND left(t.target_key, {len(kind) + 1}) = '{kind}:'")
    if component == "rail_codes":
        return "t.active AND t.rail_station_id IS NOT NULL"
    if component == "rail_registry":
        return "t.id = 1"
    return "TRUE"


def upgrade():
    op.create_table("reference_export_input_revisions",
        sa.Column("component", sa.String(40), primary_key=True),
        sa.Column("epoch", sa.String(36), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False, server_default="0"))
    op.bulk_insert(sa.table("reference_export_input_revisions", sa.column("component", sa.String()),
                            sa.column("epoch", sa.String())),
                   [{"component": component, "epoch": str(uuid4())} for component in sorted(_COMPONENTS)])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("SET LOCAL lock_timeout = '2s'")
    op.execute("SET LOCAL statement_timeout = '30s'")
    for component, (table, fields, manual) in sorted(_COMPONENTS.items()):
        projection, predicate = _projection(component, fields, manual), _predicate(component)
        old = f"SELECT {projection} FROM old_rows t WHERE {predicate}"
        new = f"SELECT {projection} FROM new_rows t WHERE {predicate}"
        function = f"kt_reference_revision_{component}"
        op.execute(f"""CREATE FUNCTION public.{function}() RETURNS trigger
            LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
            DECLARE changed boolean; affected integer;
            BEGIN
                IF TG_OP = 'INSERT' THEN
                    SELECT EXISTS(SELECT 1 FROM new_rows t WHERE {predicate}) INTO changed;
                ELSIF TG_OP = 'DELETE' THEN
                    SELECT EXISTS(SELECT 1 FROM old_rows t WHERE {predicate}) INTO changed;
                ELSIF TG_OP = 'UPDATE' THEN
                    SELECT EXISTS(({old} EXCEPT ALL {new}) UNION ALL ({new} EXCEPT ALL {old})) INTO changed;
                ELSE
                    changed := TRUE;
                END IF;
                IF changed THEN
                    UPDATE public.reference_export_input_revisions SET revision = revision + 1
                        WHERE component = '{component}';
                    GET DIAGNOSTICS affected = ROW_COUNT;
                    IF affected <> 1 THEN
                        RAISE EXCEPTION 'reference input revision component missing';
                    END IF;
                END IF;
                RETURN NULL;
            END $$""")
        for action, transition in (
            ("INSERT", "REFERENCING NEW TABLE AS new_rows"),
            ("DELETE", "REFERENCING OLD TABLE AS old_rows"),
            ("UPDATE", "REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows"),
            ("TRUNCATE", ""),
        ):
            op.execute(f"CREATE TRIGGER {function}_{action.lower()} AFTER {action} ON public.{table} "
                       f"{transition} FOR EACH STATEMENT EXECUTE FUNCTION public.{function}()")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '2s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
        for component, (table, _fields, _manual) in sorted(_COMPONENTS.items()):
            function = f"kt_reference_revision_{component}"
            for action in ("insert", "delete", "update", "truncate"):
                op.execute(f"DROP TRIGGER {function}_{action} ON public.{table}")
            op.execute(f"DROP FUNCTION public.{function}()")
    op.drop_table("reference_export_input_revisions")
