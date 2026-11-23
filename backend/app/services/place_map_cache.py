"""완전한 입력 revision·RR·실제 시간 경계가 증명된 장소 bytes만 조기 재사용한다."""
from weakref import ref

from fastapi import HTTPException
from krairport import airports as airport_bundle
from pydantic_core import to_json
from sqlalchemy import text

from app.services import fuel_map_validation

# 문장 trigger(0045)가 revision 카운터를 올리는 입력 표.
TABLES = (
    "fuel_stations", "fuel_latest_prices", "fuel_refresh_prices", "rail_station_references", "ferry_ports",
    "bus_terminal_references", "airports", "rest_area_references", "public_parking_lots",
    "highway_incident_snapshots",
)
# 수집 상태 표는 trigger 대신 같은 snapshot 안의 내용 digest로 본다(0048). 모든 수집기가 claim·성공·실패마다 쓰는 표라
# 카운터 행 하나를 갱신하는 trigger가 서로 다른 수집기의 상태 쓰기를 commit까지 줄 세웠다(운영 lock_timeout 38건).
# 수십 행이라 digest 계산은 싸고, 같은 REPEATABLE READ snapshot에서 읽으므로 payload와 어긋나지 않는다.
STATE_TABLE = "transport_collection_states"
# 작은 catalog/counter 조회 하나다. 실제 payload/원본 JSON/가격 조회는 포함하지 않는다.
_STAMP = text("""
SELECT r.versions, r.members,
    (SELECT md5(coalesce(string_agg(row_to_json(s)::text, '|' ORDER BY s.source), ''))
     FROM public.transport_collection_states s) AS states_digest,
    pg_current_xact_id_if_assigned()::text AS own_xid,
    current_setting('transaction_isolation') AS isolation,
    current_setting('session_replication_role') AS replication,
    ARRAY(SELECT to_regclass('public.' || name)::oid
          FROM unnest(CAST(:tables AS text[])) AS x(name) ORDER BY name) AS relations,
    NOT EXISTS (
        SELECT 1 FROM unnest(CAST(:tables AS text[])) AS x(name)
        WHERE to_regclass(name) IS DISTINCT FROM to_regclass('public.' || name)
           OR to_regclass('public.' || name) IS NULL
           OR (SELECT count(*) FROM pg_trigger t
               WHERE t.tgrelid=to_regclass('public.' || name) AND NOT t.tgisinternal
                 AND t.tgname IN ('kt_places_revision_insert','kt_places_revision_update',
                                  'kt_places_revision_delete','kt_places_revision_truncate')
                 AND t.tgenabled='O' AND t.tgattr=''::int2vector AND t.tgqual IS NULL
                 AND t.tgtype = CASE t.tgname
                     WHEN 'kt_places_revision_insert' THEN 4
                     WHEN 'kt_places_revision_update' THEN 16
                     WHEN 'kt_places_revision_delete' THEN 8
                     WHEN 'kt_places_revision_truncate' THEN 32 END
                 AND t.tgnargs=0
                 AND t.tgfoid=to_regprocedure('public.kt_places_revision()')) <> 4
    ) AS trusted,
    ARRAY(SELECT t.tgrelid::text || ':' || t.tgname || ':' || t.xmin::text
          FROM pg_trigger t WHERE t.tgrelid = ANY(ARRAY(
              SELECT to_regclass('public.' || name)::oid
              FROM unnest(CAST(:tables AS text[])) AS x(name)))
            AND t.tgname IN ('kt_places_revision_insert','kt_places_revision_update',
                            'kt_places_revision_delete','kt_places_revision_truncate')
          ORDER BY t.tgrelid,t.tgname) AS trigger_ddl,
    least(
        CASE WHEN :incidents THEN least(
            (SELECT min(collected_at) FROM public.highway_incident_snapshots
             WHERE collected_at > CAST(:at AS timestamptz)),
            (SELECT min(collected_at) + interval '24 hours' FROM public.highway_incident_snapshots
             WHERE collected_at >= CAST(:at AS timestamptz) - interval '24 hours')
        ) END,
        CASE WHEN :fuel THEN (SELECT min(expires_at) FROM public.fuel_refresh_prices
                              WHERE expires_at > CAST(:at AS timestamptz)) END
    ) AS boundary
FROM (
    SELECT jsonb_agg(jsonb_build_array(component, epoch, revision) ORDER BY component) AS versions,
           count(*) AS members
    FROM public.reference_export_input_revisions WHERE component = ANY(CAST(:components AS text[]))
) r
""")


async def snapshot(session, at, release, incidents, *, fuel=True):
    if session.get_bind().dialect.name != "postgresql" or not release or release == "unknown":
        return None
    if session.new or session.dirty or session.deleted:
        return None
    if not session.in_transaction():
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
    row = (await session.execute(_STAMP, {"tables": list(TABLES), "components": ["places." + table for table in TABLES],
                                            "at": at, "incidents": incidents, "fuel": fuel})).one_or_none()
    if row is None or row.members != len(TABLES):
        raise HTTPException(503, "장소 입력 revision 구성이 완전하지 않습니다.")
    if not row.trusted or row.replication != "origin" or row.own_xid is not None or row.isolation not in (
        "repeatable read", "serializable",
    ):
        return None
    return (ref(session.bind), tuple(row.relations), tuple(row.trigger_ddl), release, tuple(tuple(v) for v in row.versions),
            (STATE_TABLE, row.states_digest)), row.boundary


def provider_key(lookup):
    # DB 밖의 고정 provider 번들도 실제 좌표/출처를 namespace에 넣는다.
    values = []
    for code in sorted(airport_bundle.AIRPORTS):
        item = lookup(code)
        coordinate = item.coordinate if item else None
        values.append((code, item.source if item else None,
                       float(coordinate.lon).hex() if coordinate else None, float(coordinate.lat).hex() if coordinate else None))
    return lookup, tuple(values)


def get(key, at):
    return fuel_map_validation._validated_items.get_page(key, at)


def put(key, body, at, boundary, fuel_success, fuel_stale):
    if not fuel_stale and fuel_success is not None:
        from app.services.transport_collection import FUEL_STALE_AFTER
        stale_at = fuel_success + FUEL_STALE_AFTER
        if stale_at >= at:
            boundary = min(boundary, stale_at) if boundary is not None else stale_at
    fuel_map_validation._validated_items.put_page(key, body, at, boundary)


def response_bytes(body, at):
    return b'{"generated_at":' + to_json(at) + b"," + body[1:]
