#!/usr/bin/env bash
set -euo pipefail

# n150에서만 실행되는 receipt-gated deploy 단계다. 로컬 Git checkout은 필요하지 않으며,
# deploy-server14.sh가 staging한 candidate artifact 또는 cutover 직후의 staged artifact를 쓴다.
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-airport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.server14}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-airport}"
CUTOVER_RECEIPT_PATH="${CUTOVER_RECEIPT_PATH:-/var/tmp/kor-travel-transport-cutover/shared-db-cutover.receipt}"
CANDIDATE_SHA="${CANDIDATE_SHA:?set the staged candidate SHA}"
RELEASE_MANIFEST_FILE="${REMOTE_APP_DIR}/.release-sha"

if [[ "${REMOTE_APP_DIR}" != "/home/digitie/apps/kor-travel-airport" ]]; then
  echo "Refusing n150 deployment: only the approved app directory may be used." >&2
  exit 2
fi
if [[ "${REMOTE_ENV_FILE}" != ".env.server14" || "${COMPOSE_PROJECT_NAME}" != "kor-travel-airport" ]]; then
  echo "Refusing n150 deployment: unexpected environment file or Compose project." >&2
  exit 2
fi
if [[ "${CUTOVER_RECEIPT_PATH}" != "/var/tmp/kor-travel-transport-cutover/shared-db-cutover.receipt" ]]; then
  echo "Refusing n150 deployment: unexpected cutover receipt path." >&2
  exit 2
fi
if [[ ! "${CANDIDATE_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Refusing n150 deployment: candidate SHA must be a full Git SHA." >&2
  exit 2
fi
if [[ "$(pwd -P)" != "${REMOTE_APP_DIR}" || ! -f "${REMOTE_ENV_FILE}" ]]; then
  echo "Refusing n150 deployment: run from the staged approved app directory with its environment file." >&2
  exit 2
fi
if [[ ! -f "${RELEASE_MANIFEST_FILE}" || -L "${RELEASE_MANIFEST_FILE}" ]] \
  || [[ "$(tr -d '\r\n' < "${RELEASE_MANIFEST_FILE}")" != "${CANDIDATE_SHA}" ]]; then
  echo "Refusing n150 deployment: staged release manifest does not match candidate." >&2
  exit 2
fi

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

RUNTIME_ENV_FILE="$(mktemp "${REMOTE_APP_DIR}/.env.server14.runtime.XXXXXX")"
cleanup_remote() {
  rm -f -- "${RUNTIME_ENV_FILE}"
}
trap cleanup_remote EXIT
awk '!/^RELEASE_SHA=/' "${REMOTE_ENV_FILE}" > "${RUNTIME_ENV_FILE}"
printf 'RELEASE_SHA=%s\n' "${CANDIDATE_SHA}" >> "${RUNTIME_ENV_FILE}"
chmod 600 "${RUNTIME_ENV_FILE}"

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
