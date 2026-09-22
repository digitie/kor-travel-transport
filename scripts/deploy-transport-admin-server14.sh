#!/usr/bin/env bash
set -euo pipefail

# 별도 Compose project만 갱신한다. parking-radar backend/frontend/Dagster는 이
# 스크립트의 Docker 명령 대상이 아니다.
REMOTE_HOST="${REMOTE_HOST:-192.168.1.14}"
REMOTE_USER="${REMOTE_USER:-digitie}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-airport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.server14}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-transport-admin}"
CANDIDATE_SHA="$(git rev-parse HEAD)"

[[ "${REMOTE_HOST}" == "192.168.1.14" ]] || { echo "n150만 배포할 수 있습니다." >&2; exit 2; }
[[ "${REMOTE_APP_DIR}" == "/home/digitie/apps/kor-travel-airport" ]] || { echo "승인된 transport checkout만 허용합니다." >&2; exit 2; }
[[ "${REMOTE_ENV_FILE}" == ".env.server14" ]] || { echo "승인된 운영 환경 파일만 허용합니다." >&2; exit 2; }
[[ "${COMPOSE_PROJECT_NAME}" == "kor-travel-transport-admin" ]] || { echo "전용 Compose project만 허용합니다." >&2; exit 2; }

# 새 release를 복사하기 전에 환경과 port를 먼저 확인한다. listener 충돌 때문에
# 실패한 배포가 공유 checkout의 비추적 파일을 삭제·교체하지 않도록 한다.
ssh "${REMOTE_USER}@${REMOTE_HOST}" \
  "REMOTE_APP_DIR='${REMOTE_APP_DIR}' REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' bash -s" <<'PREFLIGHT'
set -euo pipefail
[[ -f "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" ]] || { echo "운영 환경 파일이 없습니다." >&2; exit 2; }
for key in TRANSPORT_UI_PASSWORD TRANSPORT_UI_SESSION_SECRET TRANSPORT_UI_PUBLIC_ORIGIN TRANSPORT_DAGSTER_PUBLIC_ORIGIN TRANSPORT_DAGSTER_PASSWORD; do
  grep -Eq "^${key}=.+" "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" || { echo "${key}가 설정되지 않았습니다." >&2; exit 2; }
done
port_from_env() {
  local key="$1" fallback="$2" line value
  line="$(grep -E "^${key}=" "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" || true)"
  value="$(printf '%s\n' "${line}" | tail -n 1 | cut -d= -f2-)"
  printf '%s' "${value:-${fallback}}"
}
running="$(docker compose --project-name kor-travel-transport-admin --env-file "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" -f "${REMOTE_APP_DIR}/docker-compose.transport-admin.yml" ps --services --status running || true)"
for pair in "transport-api-gateway:$(port_from_env TRANSPORT_PUBLIC_API_PORT 12301)" "transport-dagster-gateway:$(port_from_env TRANSPORT_DAGSTER_PORT 12302)" "transport-admin-web:$(port_from_env TRANSPORT_PUBLIC_WEB_PORT 12305)"; do
  service="${pair%%:*}"; port="${pair##*:}"
  if ! grep -qx "${service}" <<<"${running}" && ss -lnt "( sport = :${port} )" | grep -q ":${port}"; then
    echo "${port}가 이미 사용 중입니다. 기존 listener를 중단하지 않았습니다." >&2
    exit 2
  fi
done
PREFLIGHT

archive="$(mktemp -p /tmp kor-travel-transport-admin.XXXXXX.tgz)"
remote_archive="/tmp/$(basename "${archive}")"
trap 'rm -f "${archive}"' EXIT
git archive --format=tar.gz --output="${archive}" HEAD
ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_APP_DIR}'"
scp "${archive}" "${REMOTE_USER}@${REMOTE_HOST}:${remote_archive}"

ssh "${REMOTE_USER}@${REMOTE_HOST}" \
  "REMOTE_APP_DIR='${REMOTE_APP_DIR}' REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' REMOTE_ARCHIVE='${remote_archive}' CANDIDATE_SHA='${CANDIDATE_SHA}' bash -s" <<'REMOTE'
set -euo pipefail
[[ -f "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" ]] || { echo "운영 환경 파일이 없습니다." >&2; exit 2; }
port_from_env() {
  local key="$1" fallback="$2" line value
  line="$(grep -E "^${key}=" "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" || true)"
  value="$(printf '%s\n' "${line}" | tail -n 1 | cut -d= -f2-)"
  printf '%s' "${value:-${fallback}}"
}
stage="$(mktemp -d /tmp/kor-travel-transport-admin-release.XXXXXX)"
cleanup() { rm -rf -- "${stage}" "${REMOTE_ARCHIVE}"; }
trap cleanup EXIT
tar -xzf "${REMOTE_ARCHIVE}" -C "${stage}"
rsync -a --exclude="${REMOTE_ENV_FILE}" --exclude=".env.server14.legacy" --exclude="backups/" "${stage}/" "${REMOTE_APP_DIR}/"
cd "${REMOTE_APP_DIR}"

# api-gateway는 설정 파일을 bind mount한다. image digest만으로는 파일 내용 변경을
# 감지하지 못하므로, 이 전용 세 서비스를 명시적으로 재생성해 공개 allowlist가
# 이전 설정에 머무르지 않게 한다.
TRANSPORT_ADMIN_RELEASE_SHA="${CANDIDATE_SHA}" docker compose --project-name kor-travel-transport-admin --env-file "${REMOTE_ENV_FILE}" -f docker-compose.transport-admin.yml up -d --build --force-recreate transport-api-gateway transport-dagster-gateway transport-admin-web
api_port="$(port_from_env TRANSPORT_PUBLIC_API_PORT 12301)"
dagster_port="$(port_from_env TRANSPORT_DAGSTER_PORT 12302)"
web_port="$(port_from_env TRANSPORT_PUBLIC_WEB_PORT 12305)"
for url in "http://127.0.0.1:${api_port}/health" "http://127.0.0.1:${dagster_port}/health" "http://127.0.0.1:${web_port}/login"; do
  ready=false
  for attempt in $(seq 1 20); do
    if curl --fail --silent --show-error --max-time 5 "${url}" >/dev/null; then
      ready=true
      break
    fi
    sleep 3
  done
  "${ready}" || { echo "health check 시간 초과: ${url}" >&2; exit 1; }
done
printf '%s\n' "${CANDIDATE_SHA}" > .transport-admin-release-sha
chmod 600 .transport-admin-release-sha
REMOTE

echo "transport admin 배포 완료: ${CANDIDATE_SHA}"
