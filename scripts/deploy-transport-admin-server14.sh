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
for key in TRANSPORT_UI_PASSWORD TRANSPORT_UI_SESSION_SECRET TRANSPORT_UI_PUBLIC_ORIGIN TRANSPORT_DAGSTER_PUBLIC_ORIGIN TRANSPORT_DAGSTER_PASSWORD; do
  grep -Eq "^${key}=.+" "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" || { echo "${key}가 설정되지 않았습니다." >&2; exit 2; }
done

stage="$(mktemp -d /tmp/kor-travel-transport-admin-release.XXXXXX)"
cleanup() { rm -rf -- "${stage}" "${REMOTE_ARCHIVE}"; }
trap cleanup EXIT
tar -xzf "${REMOTE_ARCHIVE}" -C "${stage}"
rsync -a --delete --exclude="${REMOTE_ENV_FILE}" --exclude=".env.server14.legacy" --exclude="backups/" "${stage}/" "${REMOTE_APP_DIR}/"
cd "${REMOTE_APP_DIR}"

# 현재 전용 project가 이미 실행 중이면 compose가 안전하게 recreate한다. 실행 중이
# 아닌 서비스의 port가 점유돼 있으면 기존 서비스(cAdvisor 등)를 절대 중단하지 않는다.
running="$(docker compose --project-name kor-travel-transport-admin --env-file "${REMOTE_ENV_FILE}" -f docker-compose.transport-admin.yml ps --services --status running || true)"
for pair in 'transport-api-gateway:12301' 'transport-dagster-gateway:12302' 'transport-admin-web:12305'; do
  service="${pair%%:*}"; port="${pair##*:}"
  if ! grep -qx "${service}" <<<"${running}" && ss -lnt "( sport = :${port} )" | grep -q ":${port}"; then
    echo "${port}가 이미 사용 중입니다. 기존 listener를 중단하지 않았습니다." >&2
    exit 2
  fi
done
docker compose --project-name kor-travel-transport-admin --env-file "${REMOTE_ENV_FILE}" -f docker-compose.transport-admin.yml up -d --build
for url in http://127.0.0.1:12301/health http://127.0.0.1:12302/health http://127.0.0.1:12305/login; do
  curl --fail --silent --show-error --max-time 15 "${url}" >/dev/null
done
printf '%s\n' "${CANDIDATE_SHA}" > .transport-admin-release-sha
chmod 600 .transport-admin-release-sha
REMOTE

echo "transport admin 배포 완료: ${CANDIDATE_SHA}"
