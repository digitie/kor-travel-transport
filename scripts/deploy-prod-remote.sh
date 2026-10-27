#!/usr/bin/env bash
set -euo pipefail

# Manager registry가 transport 소유 호스트임을 확인한 뒤 실행하는 deploy 단계다. 공용 DB 대상은 아래 DSN 검사가 고정한다(한 번짜리 cutover
# receipt 게이트는 cutover가 끝나 ADR-011에서 걷어냈다). 로컬 Git checkout은 필요하지 않으며,
# deploy-prod.sh가 staging한 candidate artifact 또는 cutover 직후의 staged artifact를 쓴다.
if [[ "$#" != 2 || "$1" != "--host" || -z "$2" ]]; then
  echo "Usage: $0 --host <IPv4 address>" >&2
  exit 2
fi
REMOTE_HOST="$2"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/validate-deploy-host.py" --host "${REMOTE_HOST}" --parse-only
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-transport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.prod}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-transport}"
CANDIDATE_SHA="${CANDIDATE_SHA:?set the staged candidate SHA}"
RELEASE_MANIFEST_FILE="${REMOTE_APP_DIR}/.release-sha"

if [[ "${REMOTE_APP_DIR}" != "/home/digitie/apps/kor-travel-transport" ]]; then
  echo "Refusing production deployment: only the approved app directory may be used." >&2
  exit 2
fi
if [[ "${REMOTE_ENV_FILE}" != ".env.prod" || "${COMPOSE_PROJECT_NAME}" != "kor-travel-transport" ]]; then
  echo "Refusing production deployment: unexpected environment file or Compose project." >&2
  exit 2
fi
if [[ ! "${CANDIDATE_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Refusing production deployment: candidate SHA must be a full Git SHA." >&2
  exit 2
fi
if [[ "$(pwd -P)" != "$(realpath -e -- "${REMOTE_APP_DIR}")" || ! -f "${REMOTE_ENV_FILE}" || ! -r "${REMOTE_ENV_FILE}" ]]; then
  echo "Refusing production deployment: run from the staged approved app directory with its environment file." >&2
  exit 2
fi
python3 "${SCRIPT_DIR}/validate-deploy-host.py" --host "${REMOTE_HOST}" --env-file "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}"
python3 "${SCRIPT_DIR}/prepare-deploy-storage.py" --app-dir "${REMOTE_APP_DIR}" --check-only

# deploy-prod.sh의 자식이면 FD 9의 열린 파일 설명과 lock을 상속한다.
# 수동 실행이면 여기서 동일 lock을 새로 잡는다. 경로가 다른 FD는 재사용하지 않는다.
release_lock_path="/mnt/media/kor-travel/build/transport/.kor-travel-transport-deploy.lock"
[[ ! -L "${release_lock_path}" ]] || { echo "Refusing deployment: symlink lock." >&2; exit 2; }
if [[ "$(readlink -f "/proc/$$/fd/9" 2>/dev/null || true)" != "$(realpath -m -- "${release_lock_path}")" ]]; then
  exec 9>"${release_lock_path}"
fi
flock -n 9 || { echo "Refusing production deployment: shared checkout is being changed." >&2; exit 2; }
if [[ ! -f "${RELEASE_MANIFEST_FILE}" || -L "${RELEASE_MANIFEST_FILE}" ]] \
  || [[ "$(tr -d '\r\n' < "${RELEASE_MANIFEST_FILE}")" != "${CANDIDATE_SHA}" ]]; then
  echo "Refusing production deployment: staged release manifest does not match candidate." >&2
  exit 2
fi
bash ./scripts/verify-release-stage.sh "${REMOTE_APP_DIR}" "${CANDIDATE_SHA}"

# 외부 controller의 strict 선택과 고정 receipt는 운영 env가 덮어쓰지 못한다.
requested_deploy_mode="${DEPLOY_MODE:-deploy}"
prebuilt_handoff_file="${PREBUILT_HANDOFF_FILE:-}"
prebuilt_handoff_sha256="${PREBUILT_HANDOFF_SHA256:-}"
readonly requested_deploy_mode prebuilt_handoff_file prebuilt_handoff_sha256
set -a
source "${REMOTE_ENV_FILE}"
set +a
if [[ "${requested_deploy_mode}" == "deploy-prebuilt" ]]; then
  DEPLOY_MODE=deploy-prebuilt
fi

require_exact() {
  local name="$1"
  local expected="$2"
  local actual="${!name-}"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "Refusing production deployment: ${name}=${actual@Q}, expected ${expected@Q}." >&2
    exit 2
  fi
}

require_exact PUBLIC_API_PORT 12302
require_exact PUBLIC_WEB_PORT 12303
require_exact ENABLE_SCHEDULER true
require_exact SCHEDULER_MODE dagster
require_exact ENABLE_MANUAL_COLLECT false
require_exact RUN_DB_MIGRATIONS true
require_exact SEED_SAMPLE_DATA false
require_exact USE_SAMPLE_CLIENT_WHEN_NO_KEY false
require_exact COLLECT_INTERVAL_SECONDS 300
if [[ "${SCHEDULER_SAFETY_BUFFER_SECONDS:-}" != "120" ]]; then
  echo "Refusing production deployment: SCHEDULER_SAFETY_BUFFER_SECONDS must be explicitly set to 120." >&2
  exit 2
fi
require_exact MANUAL_COLLECT_MIN_INTERVAL_SECONDS 300
require_exact BACKEND_INTERNAL_URL http://127.0.0.1:12302
require_exact BACKUP_DIR /app/backups
if [[ -n "${NEXT_PUBLIC_API_BASE_URL:-}" ]]; then
  echo "Refusing production deployment: NEXT_PUBLIC_API_BASE_URL must be empty for same-origin proxying." >&2
  exit 2
fi
if [[ ! "${DATABASE_URL:-}" =~ ^postgresql\+asyncpg://[^@]+@127\.0\.0\.1:11000/kor_travel_transport$ ]]; then
  echo "Refusing production deployment: DATABASE_URL must target the Manager shared application DB." >&2
  exit 2
fi
if [[ ! "${DAGSTER_POSTGRES_URL:-}" =~ ^postgresql(\+psycopg2)?://[^@]+@127\.0\.0\.1:11000/kor_travel_transport_dagster$ ]]; then
  echo "Refusing production deployment: DAGSTER_POSTGRES_URL must target the dedicated Manager metadata DB." >&2
  exit 2
fi

# 공식 배포는 호스트별 Manager 정본만 소비한다. show는 준비/설치/서비스 변경을 하지 않는다.
manager_instance_config() {
  python3 "${SCRIPT_DIR}/validate-deploy-host.py" --host "${REMOTE_HOST}" \
    --env-file "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" --instance-config
}
verify_manager_instance_config() {
  local current
  current="$(manager_instance_config)" || return 2
  if [[ "${current}" != "${MANAGER_INSTANCE_CONFIG_JSON}" ]]; then
    echo "Refusing production deployment: Manager instance configuration changed." >&2
    return 2
  fi
}
MANAGER_INSTANCE_CONFIG_JSON="$(manager_instance_config)" || exit 2
manager_instance_path="$(printf '%s' "${MANAGER_INSTANCE_CONFIG_JSON}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])')" || exit 2
if [[ -n "${KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG:-}" && "${KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG}" != "${manager_instance_path}" ]]; then
  echo "Refusing production deployment: independent instance configuration override." >&2
  exit 2
fi
export KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG="${manager_instance_path}"

RUNTIME_ENV_FILE="$(mktemp "${REMOTE_APP_DIR}/.env.prod.runtime.XXXXXX")"
ROLLBACK_RUNTIME_ENV_FILE=""
PREVIOUS_CODE_SERVER_IMAGE=""
PREVIOUS_CODE_SERVER_TAG=""
DEPLOYMENT_REPLACEMENT_STARTED=false
DEPLOYMENT_VERIFIED=false
PREBUILT_COMPOSE_FILE=""
cleanup_remote() {
  local exit_status=$?
  set +e
  # strict controller만 child의 실제 종료·새 probe·drain0 뒤 복구를 결정한다.
  if [[ "${DEPLOY_MODE:-deploy}" != "deploy-prebuilt" ]]; then
  if [[ "${DEPLOYMENT_REPLACEMENT_STARTED}" == true && "${DEPLOYMENT_VERIFIED}" != true ]]; then
    if rollback_dagster_code_server; then
      echo "배포 검증 실패: 이전 Dagster code-server release로 복구했다." >&2
    else
      echo "배포 검증과 Dagster code-server 복구가 모두 실패했다. Manager에서 ${dagster_location:-kor-travel-transport} location을 확인해야 한다." >&2
    fi
  fi
  fi
  if [[ -n "${PREBUILT_COMPOSE_FILE:-}" ]]; then
    rm -f -- "${PREBUILT_COMPOSE_FILE}"
  fi
  rm -f -- "${RUNTIME_ENV_FILE}"
  if [[ -n "${ROLLBACK_RUNTIME_ENV_FILE}" ]]; then
    rm -f -- "${ROLLBACK_RUNTIME_ENV_FILE}"
  fi
  if [[ -n "${TRANSPORT_OVERRIDE_TMP:-}" ]]; then
    sudo -n rm -f -- "${TRANSPORT_OVERRIDE_TMP}" || true
  fi
  exit "${exit_status}"
}
trap cleanup_remote EXIT
awk '!/^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE|KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG)=/' "${REMOTE_ENV_FILE}" > "${RUNTIME_ENV_FILE}"
printf 'RELEASE_SHA=%s\n' "${CANDIDATE_SHA}" >> "${RUNTIME_ENV_FILE}"
printf 'KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG=%s\n' \
  "${KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG}" >> "${RUNTIME_ENV_FILE}"
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
  echo "Refusing production deployment: KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD must be the Manager shared Dagster password (URI-unreserved characters)." >&2
  exit 2
fi
# DEPLOY_MODE=prepare-shared-dagster-cutover: 이미지만 빌드하고, Manager의 전환 스크립트
# (`dagster-shared-cutover.sh transport forward`)가 `EXTERNAL_ENV_FILE`로 쓸 env 파일을 남긴 뒤 끝난다.
# 컨테이너는 바꾸지 않는다 — code-server를 공용 instance로 옮기는 일은 옛 daemon을 먼저 멈추는 전환
# 스크립트만 한다(이중 발화 방지).
DEPLOY_MODE="${DEPLOY_MODE:-deploy}"
if [[ "${DEPLOY_MODE}" != "deploy" && "${DEPLOY_MODE}" != "prepare-shared-dagster-cutover" && "${DEPLOY_MODE}" != "deploy-prebuilt" ]]; then
  echo "Refusing production deployment: DEPLOY_MODE must be deploy, prepare-shared-dagster-cutover or deploy-prebuilt." >&2
  exit 2
fi
CUTOVER_ENV_FILE="${REMOTE_APP_DIR}/.env.prod.shared-dagster-cutover"
TRANSPORT_OVERRIDE_SOURCE="${REMOTE_APP_DIR}/transport.override.yml"
TRANSPORT_OVERRIDE_DIR="/opt/kor-travel-odroid/transport"
TRANSPORT_OVERRIDE_FILE="${TRANSPORT_OVERRIDE_DIR}/transport.override.yml"
TRANSPORT_OVERRIDE_TMP=""

compose() {
  local extra=()
  if [[ -n "${PREBUILT_COMPOSE_FILE}" ]]; then
    extra=(-f "${PREBUILT_COMPOSE_FILE}")
  fi
  docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${RUNTIME_ENV_FILE}" -f docker-compose.yml -f docker-compose.shared.yml -f "${TRANSPORT_OVERRIDE_FILE}" "${extra[@]}" "$@"
}

strict_prebuilt_gate() {
  python3 "${SCRIPT_DIR}/verify-prebuilt-handoff.py" \
    --receipt "${prebuilt_handoff_file}" --sha256 "${prebuilt_handoff_sha256}" \
    --revision "${CANDIDATE_SHA}" "$@"
}

install_transport_override() {
  if [[ ! -f "${TRANSPORT_OVERRIDE_SOURCE}" || -L "${TRANSPORT_OVERRIDE_SOURCE}" ]]; then
    echo "Refusing production deployment: staged release is missing a regular transport.override.yml." >&2
    return 2
  fi
  if [[ ! -d "${TRANSPORT_OVERRIDE_DIR}" || -L "${TRANSPORT_OVERRIDE_DIR}" ]] \
    || ! sudo -n test -d "${TRANSPORT_OVERRIDE_DIR}" \
    || sudo -n test -L "${TRANSPORT_OVERRIDE_FILE}"; then
    echo "Refusing production deployment: the approved Odroid transport override directory/file is unavailable or unsafe." >&2
    return 2
  fi
  local mount_source
  mount_source="$(findmnt -T "${TRANSPORT_OVERRIDE_DIR}" -n -o SOURCE)" || {
    echo "Refusing production deployment: cannot verify the transport override storage device." >&2
    return 2
  }
  if [[ "${mount_source}" != /dev/nvme* ]]; then
    echo "Refusing production deployment: transport.override.yml must be stored on NVMe." >&2
    return 2
  fi
  TRANSPORT_OVERRIDE_TMP="${TRANSPORT_OVERRIDE_DIR}/.transport.override.yml.${CANDIDATE_SHA:0:12}.$$"
  if sudo -n test -e "${TRANSPORT_OVERRIDE_TMP}" || sudo -n test -L "${TRANSPORT_OVERRIDE_TMP}"; then
    echo "Refusing production deployment: a transport override staging file already exists." >&2
    return 2
  fi
  sudo -n install -o root -g root -m 0644 -- "${TRANSPORT_OVERRIDE_SOURCE}" "${TRANSPORT_OVERRIDE_TMP}" \
    && sudo -n mv -fT -- "${TRANSPORT_OVERRIDE_TMP}" "${TRANSPORT_OVERRIDE_FILE}" || {
      echo "Refusing production deployment: could not atomically install transport.override.yml." >&2
      return 2
    }
  TRANSPORT_OVERRIDE_TMP=""
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

# The manager workspace and registry pin this location to 12306. Validate the tracked overlay and its
# rendered effect before any image build or container replacement; a missing overlay cannot fall back to 14005.
install_transport_override
compose config -q
compose config --format json | python3 ./scripts/verify-transport-override.py
# 이미지를 만드는 동안에는 기존 수집기를 계속 운영한다.
if [[ "${DEPLOY_MODE}" == "deploy-prebuilt" ]]; then
  PREBUILT_COMPOSE_FILE="$(mktemp "${REMOTE_APP_DIR}/.prebuilt-compose.XXXXXX.json")"
  strict_prebuilt_gate --overlay > "${PREBUILT_COMPOSE_FILE}"
  compose config -q
else
compose build
fi

# code-server의 dagster는 공용 plane 호스트와 **같은 버전**이어야 한다. 높으면 공용 webserver가 unhealthy가 되어
# 다른 테넌트까지 내려가고(버전 상한), 낮아도 run worker가 다른 버전의 instance ref를 읽는다. 컨테이너를 바꾸기 전에 본다.
image_version="$(image_dagster_version)" || { echo "Refusing production deployment: cannot read the dagster version of ${BACKEND_RUNTIME_IMAGE}." >&2; exit 1; }
host_version="$(shared_dagster_version)" || { echo "Refusing production deployment: cannot ask the shared Dagster webserver for its version." >&2; exit 1; }
if [[ "${image_version}" != "${host_version}" ]]; then
  echo "Refusing production deployment: ${BACKEND_RUNTIME_IMAGE} has dagster ${image_version}, the shared Dagster plane runs ${host_version} — pin backend/pyproject.toml to the host version." >&2
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
  verify_manager_instance_config || exit 2
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
capture_previous_code_server_image() {
  PREVIOUS_CODE_SERVER_IMAGE="$(docker inspect -f '{{.Config.Image}}' "${dagster_code_server}" 2>/dev/null)" || {
    echo "Refusing production deployment: cannot capture the current Dagster code-server image for rollback." >&2
    return 2
  }
  if [[ "${PREVIOUS_CODE_SERVER_IMAGE}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    # strict가 실제 ID로 띄운 컨테이너도 다음 일반 배포에서 복구할 수 있어야 한다.
    # label만 믿지 않고 실제 image ID·전체 release env·그 release의 로컬 tag를 모두 대조한다.
    local release previous_id="${PREVIOUS_CODE_SERVER_IMAGE}"
    release="$(docker inspect "${dagster_code_server}" | python3 -c '
import json,re,sys
v=json.load(sys.stdin)[0]; c=v["Config"]; labels=c["Labels"]
r=labels.get("io.kor-travel-transport.prebuilt-release", "")
values=[s.split("=",1)[1] for s in c["Env"] if s.startswith("RELEASE_SHA=")]
assert re.fullmatch("[0-9a-f]{40}",r) and values == [r]
assert v["Image"] == c["Image"] == sys.argv[1]
assert labels.get("com.docker.compose.project") == "kor-travel-transport"
assert labels.get("com.docker.compose.service") == "dagster-code-server"
print(r)' "${previous_id}")" || return 2
    PREVIOUS_CODE_SERVER_IMAGE="kor-travel-transport-backend:rel-${release:0:12}"
    if [[ "$(docker image inspect -f '{{.Id}}' "${PREVIOUS_CODE_SERVER_IMAGE}")" != "${previous_id}" ]]; then
      echo "Refusing production deployment: strict release tag no longer matches the actual previous image." >&2
      return 2
    fi
  fi
  if [[ "${PREVIOUS_CODE_SERVER_IMAGE}" =~ ^kor-travel-transport-backend:rel-([0-9a-f]{12})$ ]]; then
    PREVIOUS_CODE_SERVER_TAG="${BASH_REMATCH[1]}"
  else
    echo "Refusing production deployment: current Dagster code-server does not use a rollback-safe immutable release image tag." >&2
    return 2
  fi
  docker image inspect "${PREVIOUS_CODE_SERVER_IMAGE}" >/dev/null || {
    echo "Refusing production deployment: previous Dagster code-server image is no longer available for rollback." >&2
    return 2
  }
}
rollback_dagster_code_server() {
  verify_manager_instance_config || return 2
  if [[ ! "${PREVIOUS_CODE_SERVER_TAG}" =~ ^[0-9a-f]{12}$ ]] \
    || [[ "${PREVIOUS_CODE_SERVER_IMAGE}" != "kor-travel-transport-backend:rel-${PREVIOUS_CODE_SERVER_TAG}" ]]; then
    echo "Cannot roll back Dagster code-server: previous immutable image tag was not captured." >&2
    return 2
  fi
  if [[ -z "${ROLLBACK_RUNTIME_ENV_FILE}" ]]; then
    ROLLBACK_RUNTIME_ENV_FILE="$(mktemp "${REMOTE_APP_DIR}/.env.prod.runtime.rollback.XXXXXX")" || return 1
    awk '!/^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE|KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG)=/' "${REMOTE_ENV_FILE}" > "${ROLLBACK_RUNTIME_ENV_FILE}" || return 1
    printf 'BACKEND_RUNTIME_IMAGE=%s\n' \
      "${PREVIOUS_CODE_SERVER_IMAGE}" >> "${ROLLBACK_RUNTIME_ENV_FILE}" || return 1
    printf 'KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG=%s\n' \
      "${KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG}" >> "${ROLLBACK_RUNTIME_ENV_FILE}" || return 1
    chmod 600 "${ROLLBACK_RUNTIME_ENV_FILE}" || return 1
  fi
  echo "Dagster code-server 배포 실패 — ${PREVIOUS_CODE_SERVER_IMAGE}로 복구를 시도한다." >&2
  if ! env -u RELEASE_SHA -u BACKEND_RUNTIME_IMAGE docker compose \
    --project-name "${COMPOSE_PROJECT_NAME}" \
    --env-file "${ROLLBACK_RUNTIME_ENV_FILE}" \
    -f docker-compose.yml -f docker-compose.shared.yml -f "${TRANSPORT_OVERRIDE_FILE}" \
    up -d --no-deps --no-build dagster-code-server; then
    echo "이전 Dagster code-server 컨테이너 복구 명령이 실패했다." >&2
    return 1
  fi
  wait_code_server_health && wait_location_loaded
}

# 공용 plane에 합류하기 전에는 이 배포가 code-server를 옮기면 안 된다 — 옛 daemon이 아직 schedule을 쏘는데
# code-server만 공용 instance로 가고, Manager 전환 스크립트의 펜스·검증을 건너뛴다. 합류 여부는 실제 상태로 본다.
plane_state="$(location_state)" || { echo "Refusing production deployment: cannot ask the shared Dagster webserver (${dagster_graphql_url}) for its workspace." >&2; exit 1; }
if [[ "${plane_state}" == "absent" ]]; then
  echo "Refusing production deployment: the shared Dagster plane does not list ${dagster_location} yet. Run DEPLOY_MODE=prepare-shared-dagster-cutover and the Manager cutover first." >&2
  exit 2
fi
for legacy in dagster-daemon dagster-webserver; do
  if [[ "$(docker inspect -f '{{.State.Running}}' "${COMPOSE_PROJECT_NAME}-${legacy}-1" 2>/dev/null || true)" == true ]]; then
    echo "Refusing production deployment: the old ${legacy} still runs next to the shared plane (double fire). Finish the Manager cutover first." >&2
    exit 2
  fi
done

# 공용 daemon은 다른 테넌트도 돌리므로 멈추지 않는다. 대신 이 location의 진행 중 run이 0이 될 때까지
# 기다린 직후 교체한다. 그 사이 schedule이 새 run을 띄우면(5분 주기 수집) 교체가 그 run을 끊는다 —
# 공용 instance의 run monitoring이 실패로 닫고 다음 tick이 다시 수집한다. 큐에만 있던 run은 code-server가
# 돌아오면 공용 run queue가 다시 꺼낸다(`run_queue.max_user_code_failure_retries`).
# BEGIN replacement gate
if [[ "${DEPLOY_MODE}" == "deploy-prebuilt" ]]; then
  verify_manager_instance_config || exit 2
  # 모든 준비 뒤 최신 state·run5·worker·STOPPED를 재검산한다. busy는 대기 없이 실패한다.
  # 이 probe와 Compose launch 사이에는 원자적 fence가 없다.
  strict_prebuilt_gate
  DEPLOYMENT_REPLACEMENT_STARTED=true
  compose up -d --no-build --pull never --no-deps backend frontend dagster-code-server
else
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
capture_previous_code_server_image
verify_manager_instance_config || exit 2
DEPLOYMENT_REPLACEMENT_STARTED=true
compose up -d --no-build
fi
# END replacement gate
compose ps
# Compose가 컨테이너를 만들었다는 것과 공용 plane이 이 location을 다시 싣는 것은 다르다.
wait_code_server_health
wait_location_loaded
health_payload=""
for attempt in $(seq 1 30); do
  if health_payload="$(curl -fsS "http://127.0.0.1:${PUBLIC_API_PORT:-12302}/health" 2>/dev/null)"; then
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
  if curl -fsS "http://127.0.0.1:${PUBLIC_WEB_PORT:-12303}/" >/dev/null; then
    break
  fi
  if [[ "${attempt}" == "30" ]]; then
    echo "frontend did not become ready within 60 seconds" >&2
    exit 1
  fi
  sleep 2
done
DEPLOYMENT_VERIFIED=true
