#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-192.168.1.14}"
REMOTE_USER="${REMOTE_USER:-digitie}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-transport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.server14}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-transport}"
CUTOVER_RECEIPT_PATH="${CUTOVER_RECEIPT_PATH:-/var/tmp/kor-travel-transport-cutover/shared-db-cutover.receipt}"
DEPLOY_STAGE_ONLY="${DEPLOY_STAGE_ONLY:-false}"
CANDIDATE_SHA="$(git rev-parse HEAD)"

if [[ ! "${CANDIDATE_SHA}" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Refusing deployment: unable to resolve a full git candidate SHA." >&2
  exit 2
fi

if [[ "${REMOTE_HOST}" != "192.168.1.14" ]]; then
  echo "Refusing deployment: this script may run Docker only on 192.168.1.14 (got ${REMOTE_HOST})." >&2
  exit 2
fi
if [[ "${REMOTE_APP_DIR}" != "/home/digitie/apps/kor-travel-transport" ]]; then
  echo "Refusing deployment: only /home/digitie/apps/kor-travel-transport is an approved server14 app directory." >&2
  exit 2
fi
if [[ "${REMOTE_ENV_FILE}" != ".env.server14" ]]; then
  echo "Refusing deployment: only .env.server14 is an approved server14 environment file." >&2
  exit 2
fi
if [[ "${COMPOSE_PROJECT_NAME}" != "kor-travel-transport" ]]; then
  echo "Refusing deployment: this script may update only the kor-travel-transport Compose project." >&2
  exit 2
fi
if [[ "${CUTOVER_RECEIPT_PATH}" != "/var/tmp/kor-travel-transport-cutover/shared-db-cutover.receipt" ]]; then
  echo "Refusing deployment: CUTOVER_RECEIPT_PATH must be the approved n150 receipt path." >&2
  exit 2
fi
if [[ "${DEPLOY_STAGE_ONLY}" != "true" && "${DEPLOY_STAGE_ONLY}" != "false" ]]; then
  echo "Refusing deployment: DEPLOY_STAGE_ONLY must be true or false." >&2
  exit 2
fi

ARCHIVE_PATH="$(mktemp -p /tmp kor-travel-transport-server14.XXXXXX.tgz)"
REMOTE_ARCHIVE="/tmp/$(basename "${ARCHIVE_PATH}")"

cleanup() {
  rm -f "${ARCHIVE_PATH}"
}
trap cleanup EXIT

git archive --format=tar.gz --output="${ARCHIVE_PATH}" HEAD

ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p '${REMOTE_APP_DIR}'"
scp "${ARCHIVE_PATH}" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_ARCHIVE}"
ssh "${REMOTE_USER}@${REMOTE_HOST}" \
  "REMOTE_APP_DIR='${REMOTE_APP_DIR}' REMOTE_ARCHIVE='${REMOTE_ARCHIVE}' REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' COMPOSE_PROJECT_NAME='${COMPOSE_PROJECT_NAME}' CANDIDATE_SHA='${CANDIDATE_SHA}' CUTOVER_RECEIPT_PATH='${CUTOVER_RECEIPT_PATH}' DEPLOY_STAGE_ONLY='${DEPLOY_STAGE_ONLY}' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail
if ! command -v rsync >/dev/null 2>&1; then
  echo "Refusing deployment: rsync is required to remove stale candidate files safely." >&2
  exit 2
fi
if [[ ! -f "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" ]]; then
  echo "Missing ${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}; copy .env.server14.example and add the existing operations values." >&2
  exit 2
fi
# 관리자 배포·Dagster 긴급 교체와 같은 checkout의 동시 변경을 막는다.
# FD 9는 아래 remote 배포 자식에도 상속되어 빌드가 끝날 때까지 잠금을 유지한다.
RELEASE_LOCK_PATH="/home/digitie/apps/.kor-travel-transport-deploy.lock"
exec 9>"${RELEASE_LOCK_PATH}"
flock -n 9 || { echo "Refusing deployment: shared checkout is being changed." >&2; exit 2; }

REMOTE_STAGE="$(mktemp -d /tmp/kor-travel-transport-release.XXXXXX)"
cleanup_remote() {
  rm -rf -- "${REMOTE_STAGE}" "${REMOTE_ARCHIVE}"
}
trap cleanup_remote EXIT
tar -xzf "${REMOTE_ARCHIVE}" -C "${REMOTE_STAGE}"
# 이 receipt는 현재 배포된 SHA와 달리, 공유 checkout의 복사가 끝났다는 증거다.
# 복사 중 끊기면 이전 receipt로 혼합 소스를 배포하지 못하도록 먼저 무효화한다.
STAGE_MARKER="${REMOTE_APP_DIR}/.staged-release-sha"
rm -f -- "${STAGE_MARKER}"
rsync -a --delete \
  --exclude="${REMOTE_ENV_FILE}" \
  --exclude=".env.server14.legacy" \
  --exclude=".transport-admin-release-sha" \
  --exclude=".release-sha" \
  --exclude="backups/" \
  "${REMOTE_STAGE}/" "${REMOTE_APP_DIR}/"
cd "${REMOTE_APP_DIR}"
printf '%s\n' "${CANDIDATE_SHA}" > "${REMOTE_APP_DIR}/.release-sha"
chmod 600 "${REMOTE_APP_DIR}/.release-sha"
stage_marker_tmp="$(mktemp "${STAGE_MARKER}.XXXXXX")"
printf '%s\n' "${CANDIDATE_SHA}" > "${stage_marker_tmp}"
chmod 600 "${stage_marker_tmp}"
mv -f -- "${stage_marker_tmp}" "${STAGE_MARKER}"
if [[ "${DEPLOY_STAGE_ONLY}" == "true" ]]; then
  echo "Candidate ${CANDIDATE_SHA} staged on n150; no containers were changed."
  exit 0
fi
REMOTE_APP_DIR="${REMOTE_APP_DIR}" REMOTE_ENV_FILE="${REMOTE_ENV_FILE}" \
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" CANDIDATE_SHA="${CANDIDATE_SHA}" \
  CUTOVER_RECEIPT_PATH="${CUTOVER_RECEIPT_PATH}" \
  ./scripts/deploy-server14-remote.sh
REMOTE_SCRIPT

echo "192.168.1.14 deployment completed; existing compose projects were not stopped."
