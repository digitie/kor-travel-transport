#!/usr/bin/env bash
set -euo pipefail

# transport backend와 Dagster 실행부만 갱신한다. 기존 parking-radar frontend는 이
# 스크립트의 Compose 대상이 아니며, transport-admin UI는 별도 배포 스크립트를 쓴다.
REMOTE_HOST="${REMOTE_HOST:-192.168.1.14}"
REMOTE_USER="${REMOTE_USER:-digitie}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-airport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.server14}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-airport}"
CANDIDATE_SHA="$(git rev-parse HEAD)"

[[ "${REMOTE_HOST}" == "192.168.1.14" ]] || { echo "n150만 배포할 수 있습니다." >&2; exit 2; }
[[ "${REMOTE_APP_DIR}" == "/home/digitie/apps/kor-travel-airport" ]] || { echo "승인된 transport checkout만 허용합니다." >&2; exit 2; }
[[ "${REMOTE_ENV_FILE}" == ".env.server14" ]] || { echo "승인된 운영 환경 파일만 허용합니다." >&2; exit 2; }
[[ "${COMPOSE_PROJECT_NAME}" == "kor-travel-airport" ]] || { echo "승인된 Compose project만 허용합니다." >&2; exit 2; }
[[ "${CANDIDATE_SHA}" =~ ^[0-9a-f]{40}$ ]] || { echo "전체 candidate SHA가 필요합니다." >&2; exit 2; }

# 기존 stage-only 검증·archive 경로를 재사용하며, 이 단계에서는 컨테이너를 건드리지 않는다.
DEPLOY_STAGE_ONLY=true REMOTE_HOST="${REMOTE_HOST}" REMOTE_USER="${REMOTE_USER}" \
  REMOTE_APP_DIR="${REMOTE_APP_DIR}" REMOTE_ENV_FILE="${REMOTE_ENV_FILE}" \
  COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME}" ./scripts/deploy-server14.sh

ssh "${REMOTE_USER}@${REMOTE_HOST}" \
  "REMOTE_APP_DIR='${REMOTE_APP_DIR}' REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' COMPOSE_PROJECT_NAME='${COMPOSE_PROJECT_NAME}' CANDIDATE_SHA='${CANDIDATE_SHA}' bash -s" <<'REMOTE'
set -euo pipefail
cd "${REMOTE_APP_DIR}"
[[ -f "${REMOTE_ENV_FILE}" ]] || { echo "운영 환경 파일이 없습니다." >&2; exit 2; }
[[ -f .release-sha ]] && [[ "$(tr -d '\r\n' < .release-sha)" == "${CANDIDATE_SHA}" ]] \
  || { echo "stage candidate SHA가 일치하지 않습니다." >&2; exit 2; }

runtime_env="$(mktemp "${REMOTE_APP_DIR}/.env.server14.runtime.XXXXXX")"
cleanup() { rm -f -- "${runtime_env}"; }
trap cleanup EXIT
awk '!/^RELEASE_SHA=/' "${REMOTE_ENV_FILE}" > "${runtime_env}"
printf 'RELEASE_SHA=%s\n' "${CANDIDATE_SHA}" >> "${runtime_env}"
chmod 600 "${runtime_env}"

compose=(docker compose --project-name "${COMPOSE_PROJECT_NAME}" --env-file "${runtime_env}" -f docker-compose.yml -f docker-compose.shared.yml)
"${compose[@]}" config -q
# application schema는 runtime보다 먼저 같은 candidate image로 one-shot migration을
# 실행한다. revision이 head가 아니면 runtime 재생성 전에 fail-close한다.
"${compose[@]}" run --rm --no-deps --build migrate
current_revision="$("${compose[@]}" run --rm --no-deps migrate alembic current)"
grep -Fq "(head)" <<<"${current_revision}" \
  || { echo "application Alembic revision이 head가 아닙니다: ${current_revision}" >&2; exit 1; }
services=(backend dagster-code-server dagster-webserver dagster-daemon)
"${compose[@]}" up -d --build --force-recreate --no-deps "${services[@]}"

for service in "${services[@]}"; do
  "${compose[@]}" ps --status running --services | grep -qx "${service}" \
    || { echo "실행 중이지 않은 transport 서비스: ${service}" >&2; exit 1; }
done
for attempt in $(seq 1 30); do
  health="$(curl -fsS http://127.0.0.1:14001/health 2>/dev/null || true)"
  if grep -Fq "\"release_sha\":\"${CANDIDATE_SHA}\"" <<<"${health}"; then
    exit 0
  fi
  sleep 2
done
echo "transport backend health/release SHA 확인 시간이 초과됐습니다." >&2
exit 1
REMOTE

echo "transport backend와 Dagster runtime만 배포했습니다: ${CANDIDATE_SHA}"
