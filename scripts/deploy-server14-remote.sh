#!/usr/bin/env bash
set -euo pipefail

# n150에서만 실행되는 receipt-gated deploy 단계다. 로컬 Git checkout은 필요하지 않으며,
# deploy-server14.sh가 staging한 candidate artifact 또는 cutover 직후의 staged artifact를 쓴다.
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-transport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.server14}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-transport}"
CUTOVER_RECEIPT_PATH="${CUTOVER_RECEIPT_PATH:-/var/tmp/kor-travel-transport-cutover/shared-db-cutover.receipt}"
CANDIDATE_SHA="${CANDIDATE_SHA:?set the staged candidate SHA}"
RELEASE_MANIFEST_FILE="${REMOTE_APP_DIR}/.release-sha"

if [[ "${REMOTE_APP_DIR}" != "/home/digitie/apps/kor-travel-transport" ]]; then
  echo "Refusing n150 deployment: only the approved app directory may be used." >&2
  exit 2
fi
if [[ "${REMOTE_ENV_FILE}" != ".env.server14" || "${COMPOSE_PROJECT_NAME}" != "kor-travel-transport" ]]; then
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
# deploy-server14.sh의 자식이면 FD 9의 열린 파일 설명과 lock을 상속한다.
# 수동 실행이면 여기서 동일 lock을 새로 잡는다. 경로가 다른 FD는 재사용하지 않는다.
release_lock_path="/home/digitie/apps/.kor-travel-transport-deploy.lock"
if [[ "$(readlink -f "/proc/$$/fd/9" 2>/dev/null || true)" != "${release_lock_path}" ]]; then
  exec 9>"${release_lock_path}"
fi
flock -n 9 || { echo "Refusing n150 deployment: shared checkout is being changed." >&2; exit 2; }
if [[ ! -f "${RELEASE_MANIFEST_FILE}" || -L "${RELEASE_MANIFEST_FILE}" ]] \
  || [[ "$(tr -d '\r\n' < "${RELEASE_MANIFEST_FILE}")" != "${CANDIDATE_SHA}" ]]; then
  echo "Refusing n150 deployment: staged release manifest does not match candidate." >&2
  exit 2
fi
bash ./scripts/verify-release-stage.sh "${REMOTE_APP_DIR}" "${CANDIDATE_SHA}"

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
if [[ ! "${DAGSTER_POSTGRES_URL:-}" =~ ^postgresql(\+psycopg2)?://[^@]+@127\.0\.0\.1:11000/kor_travel_transport_dagster$ ]]; then
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
awk '!/^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE)=/' "${REMOTE_ENV_FILE}" > "${RUNTIME_ENV_FILE}"
printf 'RELEASE_SHA=%s\n' "${CANDIDATE_SHA}" >> "${RUNTIME_ENV_FILE}"
chmod 600 "${RUNTIME_ENV_FILE}"
# 백엔드 계열 이미지는 release마다 자기 태그를 받는다. `up --build`가 backend를 이 이름으로 빌드하고
# migrate·Dagster 서비스도 같은 이미지로 뜬다. env 파일에 두면 다음 release가 같은 태그를 덮어써
# 이전 release 이미지가 dangling이 되므로 셸 env로만 준다(셸 env가 --env-file보다 우선한다).
export BACKEND_RUNTIME_IMAGE="kor-travel-transport-backend:rel-${CANDIDATE_SHA:0:12}"
# 위 `set -a; source`는 env 파일의 `RELEASE_SHA=` 줄도 셸 env로 export한다. 셸 env가 --env-file보다
# 우선하므로 runtime env에서 그 줄을 지운 것만으로는 옛 SHA가 이긴다. 셸 env도 candidate로 덮는다.
export RELEASE_SHA="${CANDIDATE_SHA}"

docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml config -q
# 이미지를 만드는 동안에는 기존 수집기를 계속 운영한다. 빌드가 끝난 뒤에만 새
# 실행 예약을 멈추고 worker가 빠질 때까지 기다려 code-server 교체 중 고아 run을 막는다.
docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml build
dagster_daemon="${COMPOSE_PROJECT_NAME}-dagster-daemon-1"
dagster_code_server="${COMPOSE_PROJECT_NAME}-dagster-code-server-1"
dagster_graphql_url="http://127.0.0.1:14004/graphql"
dagster_runs_query='{"query":"{runsOrError(filter:{statuses:[STARTED,STARTING,CANCELING]}){__typename ... on Runs{results{runId jobName status}}}}"}'
in_flight_runs() {
  curl -fsS --max-time 20 -H 'Content-Type: application/json' -d "${dagster_runs_query}" "${dagster_graphql_url}" |
    python3 -c 'import json,sys; value=json.load(sys.stdin)["data"]["runsOrError"]; assert value["__typename"] == "Runs", value; [print(row["runId"], row["jobName"], row["status"]) for row in value["results"]]'
}
in_flight_workers() {
  docker top "${dagster_code_server}" -eo pid,ppid,args |
    python3 -c 'import sys; [print(line.strip()) for line in sys.stdin.readlines()[1:] if "multiprocessing.spawn" in line or "/storage/" in line]'
}
wait_dagster_daemon_health() {
  local daemon_health="" attempt
  for attempt in $(seq 1 36); do
    daemon_health="$(docker inspect -f '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${dagster_daemon}" 2>/dev/null || true)"
    if [[ "${daemon_health}" == "true healthy" ]]; then
      return 0
    fi
    if [[ "${attempt}" == "36" ]]; then
      echo "Dagster daemon이 healthy가 되지 않았다: ${dagster_daemon} (${daemon_health:-missing})" >&2
      return 1
    fi
    sleep 5
  done
}
daemon_stopped=0
daemon_stopping=0
cutover_started=0
old_daemon_container_id=""
old_daemon_image=""
resume_dagster_daemon() {
  local status=$?
  set +e
  trap '' INT TERM HUP PIPE
  if ((cutover_started)); then
    # 코드/DB 일부만 교체됐을 수 있어 이미지 일치 여부와 무관하게 수집을 멈춘다.
    # 이전 daemon만 복구하면 혼합 릴리스에서 수집이 재개된다.
    docker stop "${dagster_daemon}" >/dev/null 2>&1 || true
    daemon_running="$(docker inspect -f '{{.State.Running}}' "${dagster_daemon}" 2>/dev/null || true)"
    if [[ "${daemon_running}" == false ]]; then
      echo "부분 배포 실패: 혼합 릴리스를 막기 위해 daemon을 중지했다. 수동 복구가 필요하다." >&2
    else
      echo "치명적 부분 배포 실패: daemon 중지를 확인하지 못했다 (${daemon_running:-조회 실패}). 수동으로 즉시 중지해야 한다." >&2
    fi
  elif ((daemon_stopped)); then
    ((daemon_stopping)) && docker stop "${dagster_daemon}" >/dev/null 2>&1
    current_daemon_id="$(docker inspect -f '{{.Id}}' "${dagster_daemon}" 2>/dev/null || true)"
    if [[ -n "${old_daemon_container_id}" && "${current_daemon_id}" == "${old_daemon_container_id}" ]]; then
      docker start "${dagster_daemon}" >/dev/null 2>&1
    elif [[ -n "${old_daemon_image}" ]] && docker image inspect "${old_daemon_image}" >/dev/null 2>&1; then
      # compose up이 기존 컨테이너를 교체했다면 docker start는 새 불량 이미지만
      # 재시작한다. 이전 image ID로 daemon 서비스만 되돌리고 건강을 확인한다.
      BACKEND_RUNTIME_IMAGE="${old_daemon_image}" docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml up -d --no-build --no-deps --force-recreate dagster-daemon >/dev/null 2>&1
    fi
    restored_image="$(docker inspect -f '{{.Image}}' "${dagster_daemon}" 2>/dev/null || true)"
    if [[ "${restored_image}" != "${old_daemon_image}" ]] || ! wait_dagster_daemon_health; then
      echo "Dagster daemon을 자동 복구하지 못했다: ${dagster_daemon}" >&2
    fi
  fi
  cleanup_remote
  exit "${status}"
}
trap resume_dagster_daemon EXIT
trap 'trap "" INT TERM HUP PIPE; exit 130' INT
trap 'trap "" INT TERM HUP PIPE; exit 143' TERM
trap 'trap "" INT TERM HUP PIPE; exit 129' HUP
trap 'trap "" INT TERM HUP PIPE; exit 141' PIPE
initial_runs="$(in_flight_runs)" || { echo "Dagster 실행 목록을 읽을 수 없다." >&2; exit 1; }
if docker inspect "${dagster_daemon}" >/dev/null 2>&1; then
  [[ "$(docker inspect -f '{{.State.Running}}' "${dagster_daemon}")" == true ]] || {
    echo "Dagster daemon이 이미 중지됐다. 수집 상태를 확인한 뒤 배포한다." >&2
    exit 1
  }
  old_daemon_container_id="$(docker inspect -f '{{.Id}}' "${dagster_daemon}")"
  old_daemon_image="$(docker inspect -f '{{.Image}}' "${dagster_daemon}")"
  daemon_stopped=1
  daemon_stopping=1
  docker stop "${dagster_daemon}" >/dev/null
  daemon_stopping=0
  drain_deadline=$((SECONDS + 1800))
  while :; do
    if runs="$(in_flight_runs)" && [[ -z "${runs}" ]]; then
      echo "Dagster 실행 중인 작업 0건 — 안전하게 서비스를 교체한다."
      break
    fi
    if ((SECONDS >= drain_deadline)); then
      printf 'Dagster 실행 종료 대기 30분 초과. 배포를 중단한다. 남은 실행:\n%s\n' "${runs:-조회 실패}" >&2
      exit 1
    fi
    sleep 30
  done
  [[ "$(docker inspect -f '{{.State.Running}}' "${dagster_daemon}")" == false ]] || {
    echo "대기 중 Dagster daemon이 다시 시작됐다. 배포를 중단한다." >&2
    exit 1
  }
else
  [[ -z "${initial_runs}" ]] || {
    echo "Dagster daemon이 없지만 활성 실행이 있다. code-server 교체를 중단한다: ${initial_runs}" >&2
    exit 1
  }
  workers="$(in_flight_workers)" || { echo "Dagster worker 목록을 읽을 수 없다." >&2; exit 1; }
  [[ -z "${workers}" ]] || { echo "Dagster daemon이 없지만 worker가 살아 있다: ${workers}" >&2; exit 1; }
fi
runs="$(in_flight_runs)" || { echo "서비스 교체 직전에 Dagster 실행 목록을 읽지 못했다." >&2; exit 1; }
[[ -z "${runs}" ]] || { echo "서비스 교체 직전에 새 Dagster 실행을 발견했다: ${runs}" >&2; exit 1; }
workers="$(in_flight_workers)" || { echo "서비스 교체 직전에 Dagster worker 목록을 읽지 못했다." >&2; exit 1; }
[[ -z "${workers}" ]] || { echo "서비스 교체 직전에 Dagster worker가 살아 있다: ${workers}" >&2; exit 1; }
cutover_started=1
docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml up -d --no-build
docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml ps
# Compose가 컨테이너를 만들었다는 것과 Dagster 수집기가 실제로 healthy인 것은
# 다르다. metadata DB 오류 등으로 새 daemon이 죽으면 성공 배포로 보고하지 않는다.
wait_dagster_daemon_health
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
daemon_stopped=0
cutover_started=0
