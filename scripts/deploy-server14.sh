#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-192.168.1.14}"
REMOTE_USER="${REMOTE_USER:-digitie}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-airport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.server14}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-airport}"
CUTOVER_RECEIPT_PATH="${CUTOVER_RECEIPT_PATH:-/var/tmp/kor-travel-transport-cutover/shared-db-cutover.receipt}"
CANDIDATE_SHA="$(git rev-parse HEAD)"

if [[ ! "${CANDIDATE_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Refusing deployment: unable to resolve a full git candidate SHA." >&2
  exit 2
fi

if [[ "${REMOTE_HOST}" != "192.168.1.14" ]]; then
  echo "Refusing deployment: this script may run Docker only on 192.168.1.14 (got ${REMOTE_HOST})." >&2
  exit 2
fi
if [[ "${REMOTE_APP_DIR}" != "/home/digitie/apps/kor-travel-airport" ]]; then
  echo "Refusing deployment: only /home/digitie/apps/kor-travel-airport is an approved server14 app directory." >&2
  exit 2
fi
if [[ "${REMOTE_ENV_FILE}" != ".env.server14" ]]; then
  echo "Refusing deployment: only .env.server14 is an approved server14 environment file." >&2
  exit 2
fi
if [[ "${COMPOSE_PROJECT_NAME}" != "kor-travel-airport" ]]; then
  echo "Refusing deployment: this script may update only the kor-travel-airport Compose project." >&2
  exit 2
fi
if [[ "${CUTOVER_RECEIPT_PATH}" != "/var/tmp/kor-travel-transport-cutover/shared-db-cutover.receipt" ]]; then
  echo "Refusing deployment: CUTOVER_RECEIPT_PATH must be the approved n150 receipt path." >&2
  exit 2
fi

ARCHIVE_PATH="$(mktemp -p /tmp kor-travel-airport-server14.XXXXXX.tgz)"
REMOTE_ARCHIVE="/tmp/$(basename "${ARCHIVE_PATH}")"

cleanup() {
  rm -f "${ARCHIVE_PATH}"
}
trap cleanup EXIT

git archive --format=tar.gz --output="${ARCHIVE_PATH}" HEAD

ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_APP_DIR}'"
scp "${ARCHIVE_PATH}" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_ARCHIVE}"
ssh "${REMOTE_USER}@${REMOTE_HOST}" \
  "REMOTE_APP_DIR='${REMOTE_APP_DIR}' REMOTE_ARCHIVE='${REMOTE_ARCHIVE}' REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' COMPOSE_PROJECT_NAME='${COMPOSE_PROJECT_NAME}' CANDIDATE_SHA='${CANDIDATE_SHA}' CUTOVER_RECEIPT_PATH='${CUTOVER_RECEIPT_PATH}' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail
if ! command -v rsync >/dev/null 2>&1; then
  echo "Refusing deployment: rsync is required to remove stale candidate files safely." >&2
  exit 2
fi
if [[ ! -f "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" ]]; then
  echo "Missing ${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}; copy .env.server14.example and add the existing operations values." >&2
  exit 2
fi

REMOTE_STAGE="$(mktemp -d /tmp/kor-travel-airport-release.XXXXXX)"
RUNTIME_ENV_FILE="$(mktemp "${REMOTE_APP_DIR}/.env.server14.runtime.XXXXXX")"
cleanup_remote() {
  rm -rf -- "${REMOTE_STAGE}" "${REMOTE_ARCHIVE}" "${RUNTIME_ENV_FILE}"
}
trap cleanup_remote EXIT
tar -xzf "${REMOTE_ARCHIVE}" -C "${REMOTE_STAGE}"
rsync -a --delete \
  --exclude="${REMOTE_ENV_FILE}" \
  --exclude="backups/" \
  "${REMOTE_STAGE}/" "${REMOTE_APP_DIR}/"
cd "${REMOTE_APP_DIR}"
set -a
source "${REMOTE_ENV_FILE}"
set +a

require_exact() {
  local name="$1"
  local expected="$2"
  local actual="${!name-}"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Refusing server14 deployment: ${name}=${actual@Q}, expected ${expected@Q}." >&2
    exit 2
  fi
}

require_exact PUBLIC_API_PORT 14001
require_exact PUBLIC_WEB_PORT 14002
require_exact ENABLE_SCHEDULER true
require_exact SCHEDULER_MODE dagster
require_exact ENABLE_MANUAL_COLLECT false
require_exact RUN_DB_MIGRATIONS true
require_exact SEED_SAMPLE_DATA false
require_exact USE_SAMPLE_CLIENT_WHEN_NO_KEY false
require_exact COLLECT_INTERVAL_SECONDS 300
if [[ "${SCHEDULER_SAFETY_BUFFER_SECONDS:-}" != "120" ]]; then
	echo "Refusing server14 deployment: SCHEDULER_SAFETY_BUFFER_SECONDS must be explicitly set to 120." >&2
  exit 2
fi
require_exact MANUAL_COLLECT_MIN_INTERVAL_SECONDS 300
require_exact BACKEND_INTERNAL_URL http://127.0.0.1:14001
require_exact BACKUP_DIR /app/backups
if [[ -n "${NEXT_PUBLIC_API_BASE_URL:-}" ]]; then
  echo "Refusing server14 deployment: NEXT_PUBLIC_API_BASE_URL must be empty for same-origin proxying." >&2
  exit 2
fi
if [[ ! "${DATABASE_URL:-}" =~ ^postgresql\+asyncpg://[^@]+@127\.0\.0\.1:11000/kor_travel_transport$ ]]; then
  echo "Refusing server14 deployment: DATABASE_URL must target the Manager shared application DB." >&2
  exit 2
fi
if [[ ! "${DAGSTER_POSTGRES_URL:-}" =~ ^postgresql://[^@]+@127\.0\.0\.1:11000/kor_travel_transport_dagster$ ]]; then
  echo "Refusing server14 deployment: DAGSTER_POSTGRES_URL must target the dedicated Manager metadata DB." >&2
  exit 2
fi
if [[ ! -f "${CUTOVER_RECEIPT_PATH}" || -L "${CUTOVER_RECEIPT_PATH}" ]]; then
  echo "Refusing server14 deployment: missing regular shared DB cutover receipt." >&2
  exit 2
fi
receipt_mode="$(stat -c '%a' "${CUTOVER_RECEIPT_PATH}")"
if [[ "${receipt_mode}" != "600" && "${receipt_mode}" != "400" ]]; then
  echo "Refusing server14 deployment: cutover receipt permissions must be 0600 or 0400." >&2
  exit 2
fi
if ! grep -qx 'format=kor-travel-transport-shared-db-cutover-v1' "${CUTOVER_RECEIPT_PATH}" \
  || ! grep -qx 'verified=true' "${CUTOVER_RECEIPT_PATH}" \
  || ! grep -qx 'target_database=kor_travel_transport' "${CUTOVER_RECEIPT_PATH}" \
  || ! grep -qx 'target_dagster_database=kor_travel_transport_dagster' "${CUTOVER_RECEIPT_PATH}"; then
  echo "Refusing server14 deployment: cutover receipt does not verify both shared databases." >&2
  exit 2
fi
export RELEASE_SHA="${CANDIDATE_SHA}"
# Docker Compose gives an explicit --env-file precedence over the exported shell
# environment.  Build a short-lived copy so the immutable server environment can
# retain its safe `RELEASE_SHA=unknown` default while the running release always
# reports the actual candidate SHA.
awk '!/^RELEASE_SHA=/' "${REMOTE_ENV_FILE}" > "${RUNTIME_ENV_FILE}"
printf 'RELEASE_SHA=%s\n' "${CANDIDATE_SHA}" >> "${RUNTIME_ENV_FILE}"
chmod 600 "${RUNTIME_ENV_FILE}"
# The Manager bootstrap/cutover receipt is intentionally a prerequisite: this deployment never
# creates roles, DBs, buckets, or schema by privileged side effect.
docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml config -q
docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml up -d --build
docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml ps
health_payload=""
for attempt in $(seq 1 30); do
  if health_payload="$(curl -fsS "http://127.0.0.1:${PUBLIC_API_PORT:-14001}/health" 2>/dev/null)"; then
    break
  fi
  if [[ "${attempt}" == "30" ]]; then
    echo "backend did not become ready within 60 seconds" >&2
    exit 1
  fi
  sleep 2
done
if ! grep -Fq "\"release_sha\":\"${CANDIDATE_SHA}\"" <<<"${health_payload}"; then
  echo "deployed health release_sha does not match candidate ${CANDIDATE_SHA}: ${health_payload}" >&2
  exit 1
fi
for attempt in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PUBLIC_WEB_PORT:-14002}/" >/dev/null; then
    break
  fi
  if [[ "${attempt}" == "30" ]]; then
    echo "frontend did not become ready within 60 seconds" >&2
    exit 1
  fi
  sleep 2
done
REMOTE_SCRIPT

echo "192.168.1.14 deployment completed; existing compose projects were not stopped."
