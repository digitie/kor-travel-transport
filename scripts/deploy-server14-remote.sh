#!/usr/bin/env bash
set -euo pipefail

# n150에서만 실행되는 deploy 단계다. 공용 DB 대상은 아래 DSN 검사가 고정한다(한 번짜리 cutover
# receipt 게이트는 cutover가 끝나 ADR-011에서 걷어냈다). 로컬 Git checkout은 필요하지 않으며,
# deploy-server14.sh가 staging한 candidate artifact 또는 cutover 직후의 staged artifact를 쓴다.
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-transport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.server14}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-transport}"
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

# 공용 Dagster 제어 평면(kor-travel-docker-manager ADR-54). 이 프로젝트의 Dagster 프로세스는 code-server
# 하나이고, 공용 daemon·webserver가 그것을 location `kor-travel-transport`로 싣는다. 비밀번호는 Manager의
# `x-dagster-shared-control-env`와 같은 규칙이다 — URL에 그대로 들어가므로 URI unreserved 문자만 받는다.
if [[ ! "${KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD:-}" =~ ^[A-Za-z0-9._~-]+$ ]]; then
  echo "Refusing server14 deployment: KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD must be the Manager shared Dagster password (URI-unreserved characters)." >&2
  exit 2
fi
# DEPLOY_MODE=prepare-shared-dagster-cutover: 이미지만 빌드하고, Manager의 전환 스크립트
# (`dagster-shared-cutover.sh transport forward`)가 `EXTERNAL_ENV_FILE`로 쓸 env 파일을 남긴 뒤 끝난다.
# 컨테이너는 바꾸지 않는다 — code-server를 공용 instance로 옮기는 일은 옛 daemon을 먼저 멈추는 전환
# 스크립트만 한다(이중 발화 방지).
DEPLOY_MODE="${DEPLOY_MODE:-deploy}"
if [[ "${DEPLOY_MODE}" != "deploy" && "${DEPLOY_MODE}" != "prepare-shared-dagster-cutover" ]]; then
  echo "Refusing server14 deployment: DEPLOY_MODE must be deploy or prepare-shared-dagster-cutover." >&2
  exit 2
fi
CUTOVER_ENV_FILE="${REMOTE_APP_DIR}/.env.server14.shared-dagster-cutover"

compose() {
  docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml "$@"
}

shared_dagster_graphql_url="http://127.0.0.1:11002/graphql"
# 이 이미지의 dagster 버전 — 컨테이너를 네트워크 없이 잠깐 띄워 묻는다(서비스를 바꾸지 않는다).
image_dagster_version() {
  docker run --rm --network none --entrypoint python "${BACKEND_RUNTIME_IMAGE}" -I -c 'import importlib.metadata as m; print(m.version("dagster"))'
}
# 공용 Dagster 제어 평면(호스트 webserver)의 dagster 버전.
shared_dagster_version() {
  curl -fsS --max-time 20 -H 'Content-Type: application/json' -d '{"query":"{ version }"}' "${shared_dagster_graphql_url}" |
    python3 -c 'import json,sys; print(json.load(sys.stdin)["data"]["version"])'
}
# 이 release의 Alembic head가 운영 DB의 현재 revision인가 — 전환은 migrate를 돌리지 않는다.
database_at_release_head() {
  compose run --rm --no-deps -T migrate alembic current 2>/dev/null | grep -q '(head)'
}

compose config -q
# 이미지를 만드는 동안에는 기존 수집기를 계속 운영한다.
compose build

# code-server의 dagster는 공용 plane 호스트와 **같은 버전**이어야 한다. 높으면 공용 webserver가 unhealthy가 되어
# 다른 테넌트까지 내려가고(버전 상한), 낮아도 run worker가 다른 버전의 instance ref를 읽는다. 컨테이너를 바꾸기 전에 본다.
image_version="$(image_dagster_version)" || { echo "Refusing server14 deployment: cannot read the dagster version of ${BACKEND_RUNTIME_IMAGE}." >&2; exit 1; }
host_version="$(shared_dagster_version)" || { echo "Refusing server14 deployment: cannot ask the shared Dagster webserver for its version." >&2; exit 1; }
if [[ "${image_version}" != "${host_version}" ]]; then
  echo "Refusing server14 deployment: ${BACKEND_RUNTIME_IMAGE} has dagster ${image_version}, the shared Dagster plane runs ${host_version} — pin backend/pyproject.toml to the host version." >&2
  exit 2
fi

if [[ "${DEPLOY_MODE}" == "prepare-shared-dagster-cutover" ]]; then
  # Manager 전환은 code-server만 다시 만들고 Alembic migrate를 돌리지 않는다. 이 release에 운영 DB가 아직 받지 않은
  # migration이 있으면 새 code-server가 옛 schema 위에서 돈다 — 펜스 전, 여기서 멈춘다. 그런 migration은 먼저 일반
  # 배포(합류 전 release)로 반영한다.
  database_at_release_head || {
    echo "Refusing prepare: the production database is not at this release's Alembic head. Deploy the pending migrations first (normal deploy of a pre-join release), then prepare again." >&2
    exit 2
  }
  cutover_env_tmp="$(mktemp "${CUTOVER_ENV_FILE}.XXXXXX")"
  cat "${RUNTIME_ENV_FILE}" > "${cutover_env_tmp}"
  printf 'BACKEND_RUNTIME_IMAGE=%s\n' "${BACKEND_RUNTIME_IMAGE}" >> "${cutover_env_tmp}"
  chmod 600 "${cutover_env_tmp}"
  mv -f -- "${cutover_env_tmp}" "${CUTOVER_ENV_FILE}"
  echo "Built ${BACKEND_RUNTIME_IMAGE}; wrote ${CUTOVER_ENV_FILE} (0600). No containers were changed."
  echo "Next (root, right after installing the Manager release): systemd-run --unit=dagster-cutover-transport --collect -E EXTERNAL_ENV_FILE=${CUTOVER_ENV_FILE} /opt/kor-travel-docker-manager/scripts/dagster-shared-cutover.sh transport forward <manager-sha>"
  exit 0
fi

# ── 일반 배포(공용 plane 합류 뒤) ───────────────────────────────────────────────
dagster_code_server="${COMPOSE_PROJECT_NAME}-dagster-code-server-1"
dagster_location="kor-travel-transport"
# 공용 webserver의 loopback(인증 없음, host network). 이 프로젝트의 run만 본다 — 공용 instance에는 다른
# 테넌트의 run이 함께 있다. `dagster/code_location`은 Dagster가 launch된 모든 run에 다는 tag다.
dagster_graphql_url="http://127.0.0.1:11002/graphql"
dagster_runs_query="{\"query\":\"{runsOrError(filter:{statuses:[STARTED,STARTING,CANCELING],tags:[{key:\\\"dagster/code_location\\\",value:\\\"${dagster_location}\\\"}]}){__typename ... on Runs{results{runId jobName status}}}}\"}"
dagster_workspace_query='{"query":"{workspaceOrError{__typename ... on Workspace{locationEntries{name locationOrLoadError{__typename}}}}}"}'
in_flight_runs() {
  curl -fsS --max-time 20 -H 'Content-Type: application/json' -d "${dagster_runs_query}" "${dagster_graphql_url}" |
    python3 -c 'import json,sys; value=json.load(sys.stdin)["data"]["runsOrError"]; assert value["__typename"] == "Runs", value; [print(row["runId"], row["jobName"], row["status"]) for row in value["results"]]'
}
in_flight_workers() {
  docker top "${dagster_code_server}" -eo pid,ppid,args |
    python3 -c 'import sys; [print(line.strip()) for line in sys.stdin.readlines()[1:] if "multiprocessing.spawn" in line or "/storage/" in line]'
}
# 공용 webserver가 이 location을 무엇으로 싣고 있는가 — RepositoryLocation·PythonError 등, 없으면 absent.
location_state() {
  curl -fsS --max-time 20 -H 'Content-Type: application/json' -d "${dagster_workspace_query}" "${dagster_graphql_url}" |
    python3 -c 'import json,sys; w=json.load(sys.stdin)["data"]["workspaceOrError"]; assert w["__typename"] == "Workspace", w; got={e["name"]: (e["locationOrLoadError"] or {}).get("__typename") for e in w["locationEntries"]}; print(got.get(sys.argv[1]) or "absent")' "${dagster_location}"
}
wait_code_server_health() {
  local health="" attempt
  for attempt in $(seq 1 60); do
    health="$(docker inspect -f '{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "${dagster_code_server}" 2>/dev/null || true)"
    if [[ "${health}" == "true healthy" ]]; then
      return 0
    fi
    if [[ "${attempt}" == "60" ]]; then
      echo "Dagster code-server가 healthy가 되지 않았다: ${dagster_code_server} (${health:-missing})" >&2
      return 1
    fi
    sleep 5
  done
}
wait_location_loaded() {
  local state="" attempt
  for attempt in $(seq 1 36); do
    state="$(location_state 2>/dev/null || true)"
    if [[ "${state}" == "RepositoryLocation" ]]; then
      return 0
    fi
    if [[ "${attempt}" == "36" ]]; then
      echo "공용 Dagster webserver가 ${dagster_location}을 싣지 못했다: ${state:-조회 실패}" >&2
      return 1
    fi
    sleep 5
  done
}

# 공용 plane에 합류하기 전에는 이 배포가 code-server를 옮기면 안 된다 — 옛 daemon이 아직 schedule을 쏘는데
# code-server만 공용 instance로 가고, Manager 전환 스크립트의 펜스·검증을 건너뛴다. 합류 여부는 실제 상태로 본다.
plane_state="$(location_state)" || { echo "Refusing server14 deployment: cannot ask the shared Dagster webserver (${dagster_graphql_url}) for its workspace." >&2; exit 1; }
if [[ "${plane_state}" == "absent" ]]; then
  echo "Refusing server14 deployment: the shared Dagster plane does not list ${dagster_location} yet. Run DEPLOY_MODE=prepare-shared-dagster-cutover and the Manager cutover first." >&2
  exit 2
fi
for legacy in dagster-daemon dagster-webserver; do
  if [[ "$(docker inspect -f '{{.State.Running}}' "${COMPOSE_PROJECT_NAME}-${legacy}-1" 2>/dev/null || true)" == true ]]; then
    echo "Refusing server14 deployment: the old ${legacy} still runs next to the shared plane (double fire). Finish the Manager cutover first." >&2
    exit 2
  fi
done

# 공용 daemon은 다른 테넌트도 돌리므로 멈추지 않는다. 대신 이 location의 진행 중 run이 0이 될 때까지
# 기다린 직후 교체한다. 그 사이 schedule이 새 run을 띄우면(5분 주기 수집) 교체가 그 run을 끊는다 —
# 공용 instance의 run monitoring이 실패로 닫고 다음 tick이 다시 수집한다. 큐에만 있던 run은 code-server가
# 돌아오면 공용 run queue가 다시 꺼낸다(`run_queue.max_user_code_failure_retries`).
drain_deadline=$((SECONDS + 1800))
while :; do
  if runs="$(in_flight_runs)" && [[ -z "${runs}" ]]; then
    if workers="$(in_flight_workers)" && [[ -z "${workers}" ]]; then
      echo "Dagster(${dagster_location}) 실행 중인 작업 0건 — 서비스를 교체한다."
      break
    fi
  fi
  if ((SECONDS >= drain_deadline)); then
    printf 'Dagster 실행 종료 대기 30분 초과. 배포를 중단한다. 남은 실행:\n%s\n%s\n' "${runs:-조회 실패}" "${workers:-}" >&2
    exit 1
  fi
  sleep 15
done
compose up -d --no-build
compose ps
# Compose가 컨테이너를 만들었다는 것과 공용 plane이 이 location을 다시 싣는 것은 다르다.
wait_code_server_health
wait_location_loaded
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
