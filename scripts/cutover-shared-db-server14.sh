#!/usr/bin/env bash
set -euo pipefail

# 공용 PostgreSQL 전환은 이력 보존을 우선한다. 이 스크립트는 n150에서만, 운영자가
# 명시적으로 확인한 maintenance window 안에서 실행한다. 기본 실행은 절대 허용하지 않는다.
REMOTE_HOST="${REMOTE_HOST:-192.168.1.14}"
LEGACY_DATABASE_URL="${LEGACY_DATABASE_URL:?set the current legacy application DB DSN}"
TARGET_DATABASE_URL="${DATABASE_URL:?set the new shared application DB DSN}"
TARGET_DAGSTER_DATABASE_URL="${DAGSTER_POSTGRES_URL:?set the new shared Dagster metadata DB DSN}"
LEGACY_HOST_DATABASE_URL="${LEGACY_HOST_DATABASE_URL:?set the legacy DB DSN reachable from the n150 host network}"
LEGACY_DAGSTER_DATABASE_URL="${LEGACY_DAGSTER_DATABASE_URL:-}"
LEGACY_DAGSTER_HOST_DATABASE_URL="${LEGACY_DAGSTER_HOST_DATABASE_URL:-}"
DAGSTER_METADATA_RESET_CONFIRM="${DAGSTER_METADATA_RESET_CONFIRM:-}"
LEGACY_ENV_FILE="${LEGACY_ENV_FILE:-.env.server14.legacy}"
LEGACY_PROJECT_NAME="${LEGACY_PROJECT_NAME:-kor-travel-airport}"
CUTOVER_WORK_DIR="${CUTOVER_WORK_DIR:-/var/tmp/kor-travel-transport-cutover}"
CUTOVER_RECEIPT_PATH="${CUTOVER_RECEIPT_PATH:-${CUTOVER_WORK_DIR}/shared-db-cutover.receipt}"
TARGET_ENV_FILE="${TARGET_ENV_FILE:-.env.server14}"
CONFIRMATION="MOVE_KOR_TRAVEL_TRANSPORT_HISTORY_TO_SHARED_DB"
METADATA_RESET_CONFIRMATION="START_FRESH_DAGSTER_METADATA_WITH_NO_LEGACY_STORE"
legacy_backend_quiesced=false
legacy_dagster_quiesced=false
cutover_accepted=false
legacy_dagster_services=()

# Runtime containers use host.docker.internal while this script runs on n150 itself.
# PostgreSQL clients are deliberately run in a disposable host-network container: n150 does
# not install psql/pg_dump locally, and this keeps the operating-system package set untouched.
PG_CLIENT_IMAGE="${PG_CLIENT_IMAGE:-postgres:16-alpine}"
TARGET_HOST_DATABASE_URL="${TARGET_DATABASE_URL/postgresql+asyncpg:/postgresql:}"
TARGET_HOST_DATABASE_URL="${TARGET_HOST_DATABASE_URL/host.docker.internal:11000/127.0.0.1:11000}"
TARGET_DAGSTER_HOST_DATABASE_URL="${TARGET_DAGSTER_DATABASE_URL/host.docker.internal:11000/127.0.0.1:11000}"

if [[ "${REMOTE_HOST}" != "192.168.1.14" ]]; then
  echo "Refusing cutover outside 192.168.1.14." >&2
  exit 2
fi
if [[ "${CUTOVER_RECEIPT_PATH}" != "/var/tmp/kor-travel-transport-cutover/shared-db-cutover.receipt" ]]; then
  echo "Refusing cutover: receipt path must be the approved n150 path." >&2
  exit 2
fi
if [[ "${CUTOVER_CONFIRM:-}" != "${CONFIRMATION}" ]]; then
  echo "Refusing cutover. Set CUTOVER_CONFIRM=${CONFIRMATION} after the runbook checks." >&2
  exit 2
fi
if [[ "${LEGACY_DATABASE_URL}" == "${TARGET_DATABASE_URL}" ]]; then
  echo "Refusing cutover: legacy and target DSNs must differ." >&2
  exit 2
fi
if [[ "${TARGET_DATABASE_URL}" == "${TARGET_DAGSTER_DATABASE_URL}" ]]; then
  echo "Refusing cutover: application and Dagster metadata DSNs must differ." >&2
  exit 2
fi
if [[ ! "${TARGET_DATABASE_URL}" =~ ^postgresql\+asyncpg://[^@]+@host\.docker\.internal:11000/kor_travel_transport$ ]]; then
  echo "Refusing cutover: application target must be the exact shared Manager database." >&2
  exit 2
fi
if [[ ! "${TARGET_DAGSTER_DATABASE_URL}" =~ ^postgresql://[^@]+@host\.docker\.internal:11000/kor_travel_transport_dagster$ ]]; then
  echo "Refusing cutover: Dagster target must be the exact dedicated shared metadata database." >&2
  exit 2
fi
if [[ ! "${LEGACY_HOST_DATABASE_URL}" =~ ^postgresql://[^@]+@127\.0\.0\.1:14000/[^/]+$ ]]; then
  echo "Refusing cutover: legacy host DB DSN must use the approved n150 loopback PostgreSQL port." >&2
  exit 2
fi
if [[ -n "${LEGACY_DAGSTER_DATABASE_URL}" && -z "${LEGACY_DAGSTER_HOST_DATABASE_URL}" ]]; then
  echo "Refusing cutover: legacy Dagster metadata requires LEGACY_DAGSTER_HOST_DATABASE_URL." >&2
  exit 2
fi
if [[ -n "${LEGACY_DAGSTER_HOST_DATABASE_URL}" && ! "${LEGACY_DAGSTER_HOST_DATABASE_URL}" =~ ^postgresql://[^@]+@127\.0\.0\.1:14000/[^/]+$ ]]; then
  echo "Refusing cutover: legacy Dagster host DB DSN must use the approved n150 loopback PostgreSQL port." >&2
  exit 2
fi
for command in docker; do
  command -v "${command}" >/dev/null || { echo "Missing required command: ${command}" >&2; exit 2; }
done
if [[ ! -f "${LEGACY_ENV_FILE}" ]]; then
  echo "Missing preserved legacy environment file: ${LEGACY_ENV_FILE}" >&2
  exit 2
fi
if [[ ! -f "${TARGET_ENV_FILE}" ]]; then
  echo "Missing target environment file: ${TARGET_ENV_FILE}" >&2
  exit 2
fi

mkdir -p "${CUTOVER_WORK_DIR}"
chmod 700 "${CUTOVER_WORK_DIR}"
BASE_DUMP="${CUTOVER_WORK_DIR}/legacy-base.dump"
FINAL_DUMP="${CUTOVER_WORK_DIR}/legacy-final.dump"
PGPASS_FILE="${CUTOVER_WORK_DIR}/.pgpass"

database_identity() {
  local dsn="$1"
  local database="${dsn##*/}"
  printf '%s' "${database%%\?*}"
}

if [[ "$(database_identity "${LEGACY_DATABASE_URL}")" != "$(database_identity "${LEGACY_HOST_DATABASE_URL}")" ]]; then
  echo "Refusing cutover: legacy runtime and host DSNs must name the same database." >&2
  exit 2
fi
if [[ -n "${LEGACY_DAGSTER_DATABASE_URL}" ]] && [[ "$(database_identity "${LEGACY_DAGSTER_DATABASE_URL}")" != "$(database_identity "${LEGACY_DAGSTER_HOST_DATABASE_URL}")" ]]; then
  echo "Refusing cutover: legacy Dagster runtime and host DSNs must name the same database." >&2
  exit 2
fi

umask 077
: > "${PGPASS_FILE}"
chmod 600 "${PGPASS_FILE}"
cleanup_pgpass() {
  rm -f "${PGPASS_FILE}"
}
trap cleanup_pgpass EXIT

prepare_client_dsn() {
  local dsn="$1"
  # The Manager-generated credentials are URL-safe. Requiring the same restricted form
  # here avoids lossy URL decoding while keeping passwords out of docker inspect/argv.
  if [[ ! "${dsn}" =~ ^postgresql://([^:@/]+):([A-Za-z0-9_-]+)@([A-Za-z0-9.]+):([0-9]+)/([A-Za-z0-9_-]+)$ ]]; then
    echo "Refusing cutover: host client DSNs must be passworded, URL-safe PostgreSQL URIs." >&2
    exit 2
  fi
  local username="${BASH_REMATCH[1]}"
  local password="${BASH_REMATCH[2]}"
  local host="${BASH_REMATCH[3]}"
  local port="${BASH_REMATCH[4]}"
  local database="${BASH_REMATCH[5]}"
  printf '%s:%s:%s:%s:%s\n' "${host}" "${port}" "${database}" "${username}" "${password}" >> "${PGPASS_FILE}"
  printf 'postgresql://%s@%s:%s/%s' "${username}" "${host}" "${port}" "${database}"
}

LEGACY_HOST_DATABASE_PSQL_URL="$(prepare_client_dsn "${LEGACY_HOST_DATABASE_URL}")"
TARGET_HOST_DATABASE_PSQL_URL="$(prepare_client_dsn "${TARGET_HOST_DATABASE_URL}")"
TARGET_DAGSTER_HOST_DATABASE_PSQL_URL="$(prepare_client_dsn "${TARGET_DAGSTER_HOST_DATABASE_URL}")"
if [[ -n "${LEGACY_DAGSTER_HOST_DATABASE_URL}" ]]; then
  LEGACY_DAGSTER_HOST_DATABASE_PSQL_URL="$(prepare_client_dsn "${LEGACY_DAGSTER_HOST_DATABASE_URL}")"
fi

restart_legacy_backend_on_failure() {
  status=$?
  rm -f "${PGPASS_FILE}"
  if [[ "${status}" -ne 0 && "${legacy_backend_quiesced}" == "true" && "${cutover_accepted}" != "true" ]]; then
    echo "Cutover failed after legacy writer quiescence; restoring the legacy backend." >&2
    docker compose --project-name "${LEGACY_PROJECT_NAME}" --env-file "${TARGET_ENV_FILE}" \
      -f docker-compose.yml -f docker-compose.shared.yml \
      stop backend dagster-code-server dagster-webserver dagster-daemon dagster-gateway 2>/dev/null || true
    docker compose --project-name "${LEGACY_PROJECT_NAME}" --env-file "${LEGACY_ENV_FILE}" \
      -f docker-compose.yml up -d backend || true
    # multi-service stop이 중간에 실패해도 앞쪽 service는 이미 멈췄을 수 있다.
    # 성공 플래그가 아니라 사전에 확인한 service 목록을 rollback 근거로 쓴다.
    if [[ "${#legacy_dagster_services[@]}" -gt 0 ]]; then
      docker compose --project-name "${LEGACY_PROJECT_NAME}" --env-file "${LEGACY_ENV_FILE}" \
        -f docker-compose.yml -f docker-compose.shared.yml up -d "${legacy_dagster_services[@]}" || true
    fi
  fi
  exit "${status}"
}
trap restart_legacy_backend_on_failure EXIT

postgres_client() {
  docker run --rm --network host -v "${CUTOVER_WORK_DIR}:/cutover" \
    -v "${PGPASS_FILE}:/run/secrets/pgpass:ro" -e PGPASSFILE=/run/secrets/pgpass \
    "${PG_CLIENT_IMAGE}" "$@"
}

psql_client() {
  postgres_client psql "$@"
}

pg_dump_client() {
  postgres_client pg_dump "$@"
}

pg_restore_client() {
  postgres_client pg_restore "$@"
}

assert_ready() {
  local label="$1"
  local dsn="$2"
  psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c 'SELECT 1' >/dev/null || {
    echo "${label} database is not reachable." >&2
    exit 1
  }
}

table_counts() {
  local dsn="$1"
  # Relation names come from PostgreSQL catalog identifiers and are quoted with %I;
  # no operator-provided SQL is interpolated.
  local relation_queries
  relation_queries="$(psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c "
    SELECT format(
      'SELECT %L || ''|'' || count(*)::text FROM %I.%I',
      n.nspname || '.' || c.relname,
      n.nspname,
      c.relname
    )
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
    ORDER BY n.nspname, c.relname;")"
  while IFS= read -r query; do
    [[ -n "${query}" ]] || continue
    psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c "${query}"
  done <<< "${relation_queries}" | sort
}

snapshot_watermark() {
  local dsn="$1"
  psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c "SELECT coalesce(max(observed_at)::text, '') FROM public.parking_snapshots"
}

database_name() {
  psql_client "$1" -v ON_ERROR_STOP=1 -qAt -c 'SELECT current_database()'
}

assert_ready legacy "${LEGACY_HOST_DATABASE_PSQL_URL}"
assert_ready target "${TARGET_HOST_DATABASE_PSQL_URL}"
assert_ready target-dagster "${TARGET_DAGSTER_HOST_DATABASE_PSQL_URL}"

assert_empty_bootstrap_only() {
  local label="$1"
  local dsn="$2"
  local user_schema_count relation_count routine_count type_count other_object_count migration_count
  user_schema_count="$(psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c "SELECT count(*) FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname <> 'information_schema' AND nspname <> 'public'")"
  relation_count="$(psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f') AND c.relname <> 'alembic_version'")"
  routine_count="$(psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public'")"
  type_count="$(psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'public' AND t.typrelid = 0 AND t.typelem = 0")"
  other_object_count="$(psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c "SELECT (SELECT count(*) FROM pg_operator o JOIN pg_namespace n ON n.oid = o.oprnamespace WHERE n.nspname = 'public') + (SELECT count(*) FROM pg_collation c JOIN pg_namespace n ON n.oid = c.collnamespace WHERE n.nspname = 'public') + (SELECT count(*) FROM pg_conversion c JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = 'public') + (SELECT count(*) FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE n.nspname = 'public') + (SELECT count(*) FROM pg_ts_config t JOIN pg_namespace n ON n.oid = t.cfgnamespace WHERE n.nspname = 'public') + (SELECT count(*) FROM pg_ts_dict t JOIN pg_namespace n ON n.oid = t.dictnamespace WHERE n.nspname = 'public') + (SELECT count(*) FROM pg_ts_template t JOIN pg_namespace n ON n.oid = t.tmplnamespace WHERE n.nspname = 'public')")"
  if psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c "SELECT to_regclass('public.alembic_version')" | grep -qx 'alembic_version'; then
    migration_count="$(psql_client "${dsn}" -v ON_ERROR_STOP=1 -qAt -c 'SELECT count(*) FROM public.alembic_version')"
  else
    migration_count=0
  fi
  if [[ "${user_schema_count}" != "0" || "${relation_count}" != "0" || "${routine_count}" != "0" || "${type_count}" != "0" || "${other_object_count}" != "0" || "${migration_count}" != "0" ]]; then
    echo "Refusing cutover: ${label} DB is not an empty/bootstrap-only database." >&2
    exit 2
  fi
}

assert_empty_bootstrap_only target "${TARGET_HOST_DATABASE_PSQL_URL}"
assert_empty_bootstrap_only target-dagster "${TARGET_DAGSTER_HOST_DATABASE_PSQL_URL}"

echo "Creating recoverable base dump at ${BASE_DUMP}"
pg_dump_client --format=custom --no-owner --no-privileges --file "/cutover/$(basename "${BASE_DUMP}")" "${LEGACY_HOST_DATABASE_PSQL_URL}"
pg_restore_client --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname "${TARGET_HOST_DATABASE_PSQL_URL}" "/cutover/$(basename "${BASE_DUMP}")"

echo "Quiescing the legacy backend writer; old DB and its volume remain intact for rollback."
docker compose --project-name "${LEGACY_PROJECT_NAME}" --env-file "${LEGACY_ENV_FILE}" -f docker-compose.yml stop backend
legacy_backend_quiesced=true

if [[ -n "${LEGACY_DAGSTER_DATABASE_URL}" ]]; then
  assert_ready legacy-dagster "${LEGACY_DAGSTER_HOST_DATABASE_PSQL_URL}"
  for service in dagster-code-server dagster-webserver dagster-daemon dagster-gateway; do
    if docker compose --project-name "${LEGACY_PROJECT_NAME}" --env-file "${LEGACY_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml ps -q "${service}" | grep -q .; then
      legacy_dagster_services+=("${service}")
    fi
  done
  if [[ "${#legacy_dagster_services[@]}" -gt 0 ]]; then
    docker compose --project-name "${LEGACY_PROJECT_NAME}" --env-file "${LEGACY_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml stop "${legacy_dagster_services[@]}"
    legacy_dagster_quiesced=true
  fi
fi

echo "Creating final quiesced snapshot and replacing target contents."
pg_dump_client --format=custom --no-owner --no-privileges --file "/cutover/$(basename "${FINAL_DUMP}")" "${LEGACY_HOST_DATABASE_PSQL_URL}"
pg_restore_client --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname "${TARGET_HOST_DATABASE_PSQL_URL}" "/cutover/$(basename "${FINAL_DUMP}")"

if [[ -n "${LEGACY_DAGSTER_DATABASE_URL}" ]]; then
  LEGACY_DAGSTER_DUMP="${CUTOVER_WORK_DIR}/legacy-dagster-metadata-final.dump"
  pg_dump_client --format=custom --no-owner --no-privileges --file "/cutover/$(basename "${LEGACY_DAGSTER_DUMP}")" "${LEGACY_DAGSTER_HOST_DATABASE_PSQL_URL}"
  pg_restore_client --no-owner --no-privileges --exit-on-error --dbname "${TARGET_DAGSTER_HOST_DATABASE_PSQL_URL}" "/cutover/$(basename "${LEGACY_DAGSTER_DUMP}")"
  legacy_dagster_metadata=migrated-after-writer-quiescence
else
  if [[ "${DAGSTER_METADATA_RESET_CONFIRM}" != "${METADATA_RESET_CONFIRMATION}" ]]; then
    echo "Refusing cutover: set DAGSTER_METADATA_RESET_CONFIRM=${METADATA_RESET_CONFIRMATION} only when no legacy Dagster metadata store exists." >&2
    exit 2
  fi
  legacy_dagster_metadata=reset-confirmed-no-legacy-store
fi

legacy_counts="${CUTOVER_WORK_DIR}/legacy-counts.txt"
target_counts="${CUTOVER_WORK_DIR}/target-counts.txt"
table_counts "${LEGACY_HOST_DATABASE_PSQL_URL}" > "${legacy_counts}"
table_counts "${TARGET_HOST_DATABASE_PSQL_URL}" > "${target_counts}"
diff -u "${legacy_counts}" "${target_counts}"
legacy_watermark="$(snapshot_watermark "${LEGACY_HOST_DATABASE_PSQL_URL}")"
target_watermark="$(snapshot_watermark "${TARGET_HOST_DATABASE_PSQL_URL}")"
[[ "${legacy_watermark}" == "${target_watermark}" ]] || {
  echo "Refusing cutover: latest parking snapshot watermark differs." >&2
  exit 1
}

{
  printf 'format=kor-travel-transport-shared-db-cutover-v1\n'
  printf 'verified=true\n'
  printf 'legacy_database=%s\n' "$(database_name "${LEGACY_HOST_DATABASE_PSQL_URL}")"
  printf 'target_database=%s\n' "$(database_name "${TARGET_HOST_DATABASE_PSQL_URL}")"
  printf 'target_dagster_database=%s\n' "$(database_name "${TARGET_DAGSTER_HOST_DATABASE_PSQL_URL}")"
  printf 'legacy_dagster_metadata=%s\n' "${legacy_dagster_metadata}"
  printf 'legacy_watermark=%s\n' "${legacy_watermark}"
  printf 'target_watermark=%s\n' "${target_watermark}"
  while IFS= read -r count; do printf 'legacy_count=%s\n' "${count}"; done < "${legacy_counts}"
  while IFS= read -r count; do printf 'target_count=%s\n' "${count}"; done < "${target_counts}"
  printf 'legacy_counts_sha256=%s\n' "$(sha256sum "${legacy_counts}" | awk '{print $1}')"
  printf 'target_counts_sha256=%s\n' "$(sha256sum "${target_counts}" | awk '{print $1}')"
} > "${CUTOVER_RECEIPT_PATH}"
chmod 600 "${CUTOVER_RECEIPT_PATH}"

echo "Data copy verified; starting target through the receipt-gated deployment."
CUTOVER_RECEIPT_PATH="${CUTOVER_RECEIPT_PATH}" ./scripts/deploy-server14.sh
cutover_accepted=true
echo "Keep ${LEGACY_ENV_FILE}, ${BASE_DUMP}, ${FINAL_DUMP}, and the legacy DB volume until post-deploy E2E acceptance."
