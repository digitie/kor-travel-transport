#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" != 2 || "$1" != "--host" || -z "$2" ]]; then
  echo "Usage: $0 --host <IPv4 address>" >&2
  exit 2
fi
REMOTE_HOST="$2"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "${SCRIPT_DIR}/validate-deploy-host.py" --host "${REMOTE_HOST}" --parse-only
REMOTE_USER="${REMOTE_USER:-digitie}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-transport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.prod}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-transport}"
DEPLOY_STAGE_ONLY="${DEPLOY_STAGE_ONLY:-false}"
DEPLOY_MODE="${DEPLOY_MODE:-deploy}"
CANDIDATE_SHA="$(git rev-parse HEAD)"

if [[ ! "${CANDIDATE_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Refusing deployment: unable to resolve a full git candidate SHA." >&2
  exit 2
fi

if [[ "${REMOTE_APP_DIR}" != "/home/digitie/apps/kor-travel-transport" ]]; then
  echo "Refusing deployment: only /home/digitie/apps/kor-travel-transport is an approved production app directory." >&2
  exit 2
fi
if [[ "${REMOTE_ENV_FILE}" != ".env.prod" ]]; then
  echo "Refusing deployment: only .env.prod is an approved production environment file." >&2
  exit 2
fi
if [[ "${COMPOSE_PROJECT_NAME}" != "kor-travel-transport" ]]; then
  echo "Refusing deployment: this script may update only the kor-travel-transport Compose project." >&2
  exit 2
fi
if [[ "${DEPLOY_MODE}" != "deploy" && "${DEPLOY_MODE}" != "prepare-shared-dagster-cutover" ]]; then
  echo "Refusing deployment: DEPLOY_MODE must be deploy or prepare-shared-dagster-cutover." >&2
  exit 2
fi
if [[ "${DEPLOY_STAGE_ONLY}" != "true" && "${DEPLOY_STAGE_ONLY}" != "false" ]]; then
  echo "Refusing deployment: DEPLOY_STAGE_ONLY must be true or false." >&2
  exit 2
fi

# 주소 정본은 Manager registry다. 복사/생성 전에 실제 효과를 확인한다.
ssh "${REMOTE_USER}@${REMOTE_HOST}" "python3 - --host '${REMOTE_HOST}' --env-file '${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}'" < "${SCRIPT_DIR}/validate-deploy-host.py"

ARCHIVE_PATH="$(mktemp -p /tmp kor-travel-transport-prod.XXXXXX.tgz)"
REMOTE_STAGE=""
cleanup() {
  rm -f -- "${ARCHIVE_PATH}"
  if [[ "${REMOTE_STAGE}" =~ ^/mnt/media/kor-travel/build/transport/transport-deploy\.[A-Za-z0-9_]+$ ]]; then
    # 원격 본문 전 scp/lock 실패는 archive와 빈 소유 디렉터리만 정리한다.
    ssh "${REMOTE_USER}@${REMOTE_HOST}" "rm -f -- '${REMOTE_STAGE}/archive.tgz'; rmdir -- '${REMOTE_STAGE}' 2>/dev/null || true" || true
  fi
}
trap cleanup EXIT

REMOTE_STAGE="$(ssh "${REMOTE_USER}@${REMOTE_HOST}" "python3 - --app-dir '${REMOTE_APP_DIR}'" < "${SCRIPT_DIR}/prepare-deploy-storage.py")"
[[ "${REMOTE_STAGE}" =~ ^/mnt/media/kor-travel/build/transport/transport-deploy\.[A-Za-z0-9_]+$ ]] || { echo "Refusing deployment: invalid owned NVMe stage." >&2; exit 2; }
REMOTE_ARCHIVE="${REMOTE_STAGE}/archive.tgz"


git archive --format=tar.gz --output="${ARCHIVE_PATH}" HEAD

ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_APP_DIR}'"
scp "${ARCHIVE_PATH}" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_ARCHIVE}"
ssh "${REMOTE_USER}@${REMOTE_HOST}" \
  "REMOTE_HOST='${REMOTE_HOST}' REMOTE_APP_DIR='${REMOTE_APP_DIR}' REMOTE_ARCHIVE='${REMOTE_ARCHIVE}' REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' COMPOSE_PROJECT_NAME='${COMPOSE_PROJECT_NAME}' CANDIDATE_SHA='${CANDIDATE_SHA}' REMOTE_STAGE='${REMOTE_STAGE}' DEPLOY_STAGE_ONLY='${DEPLOY_STAGE_ONLY}' DEPLOY_MODE='${DEPLOY_MODE}' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail
if ! command -v rsync >/dev/null 2>&1; then
  echo "Refusing deployment: rsync is required to remove stale candidate files safely." >&2
  exit 2
fi
if [[ ! -f "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" || ! -r "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" ]]; then
  echo "Missing ${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}; copy .env.prod.example and add the existing operations values." >&2
  exit 2
fi
# 관리자 배포·Dagster 긴급 교체와 같은 checkout의 동시 변경을 막는다.
# FD 9는 아래 remote 배포 자식에도 상속되어 빌드가 끝날 때까지 잠금을 유지한다.
RELEASE_LOCK_PATH="/mnt/media/kor-travel/build/transport/.kor-travel-transport-deploy.lock"
[[ ! -L "${RELEASE_LOCK_PATH}" ]] || { echo "Refusing deployment: symlink lock." >&2; exit 2; }
exec 9>"${RELEASE_LOCK_PATH}"
flock -n 9 || { echo "Refusing deployment: shared checkout is being changed." >&2; exit 2; }

[[ "${REMOTE_STAGE}" =~ ^/mnt/media/kor-travel/build/transport/transport-deploy\.[A-Za-z0-9_]+$ && ! -L "${REMOTE_STAGE}" ]] || { echo "Invalid owned NVMe stage." >&2; exit 2; }
[[ "${REMOTE_ARCHIVE}" == "${REMOTE_STAGE}/archive.tgz" ]] || { echo "Invalid stage archive." >&2; exit 2; }
REMOTE_SOURCE="${REMOTE_STAGE}/source"
mkdir -m 700 "${REMOTE_SOURCE}"
cleanup_remote() {
  rm -rf -- "${REMOTE_STAGE}" "${REMOTE_ARCHIVE}"
}
trap cleanup_remote EXIT
tar -xzf "${REMOTE_ARCHIVE}" -C "${REMOTE_SOURCE}"
# 이 receipt는 현재 배포된 SHA와 달리, 공유 checkout의 복사가 끝났다는 증거다.
# 복사 중 끊기면 이전 receipt로 혼합 소스를 배포하지 못하도록 먼저 무효화한다.
STAGE_MARKER="${REMOTE_APP_DIR}/.staged-release-sha"
rm -f -- "${STAGE_MARKER}"
rsync -a --delete \
  --exclude="${REMOTE_ENV_FILE}" \
  --exclude=".env.server14" \
  --exclude=".env.server14.legacy" \
  --exclude=".env.server14.shared-dagster-cutover" \
  --exclude=".env.prod.legacy" \
  --exclude=".transport-admin-release-sha" \
  --exclude=".release-sha" \
  --exclude=".env.prod.shared-dagster-cutover" \
  --exclude="backups/" \
  "${REMOTE_SOURCE}/" "${REMOTE_APP_DIR}/"
cd "${REMOTE_APP_DIR}"
printf '%s\n' "${CANDIDATE_SHA}" > "${REMOTE_APP_DIR}/.release-sha"
chmod 600 "${REMOTE_APP_DIR}/.release-sha"
stage_marker_tmp="$(mktemp "${STAGE_MARKER}.XXXXXX")"
printf '%s\n' "${CANDIDATE_SHA}" > "${stage_marker_tmp}"
chmod 600 "${stage_marker_tmp}"
mv -f -- "${stage_marker_tmp}" "${STAGE_MARKER}"
if [[ "${DEPLOY_STAGE_ONLY}" == "true" ]]; then
  echo "Candidate ${CANDIDATE_SHA} staged on ${REMOTE_HOST}; no containers were changed."
  exit 0
fi
REMOTE_APP_DIR="${REMOTE_APP_DIR}" REMOTE_ENV_FILE="${REMOTE_ENV_FILE}" \
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" CANDIDATE_SHA="${CANDIDATE_SHA}" \
  DEPLOY_MODE="${DEPLOY_MODE}" \
  ./scripts/deploy-prod-remote.sh --host "${REMOTE_HOST}"
REMOTE_SCRIPT

echo "Deployment completed; existing compose projects were not stopped."
