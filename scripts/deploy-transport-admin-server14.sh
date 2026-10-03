#!/usr/bin/env bash
set -euo pipefail

# 별도 Compose project만 갱신한다. 기본 kor-travel-transport backend/frontend/Dagster는 이
# 스크립트의 Docker 명령 대상이 아니다.
REMOTE_HOST="${REMOTE_HOST:-192.168.1.14}"
REMOTE_USER="${REMOTE_USER:-digitie}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/digitie/apps/kor-travel-transport}"
REMOTE_ENV_FILE="${REMOTE_ENV_FILE:-.env.server14}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kor-travel-transport-admin}"
CANDIDATE_SHA="$(git rev-parse HEAD)"

[[ "${REMOTE_HOST}" == "192.168.1.14" ]] || { echo "n150만 배포할 수 있습니다." >&2; exit 2; }
[[ "${REMOTE_APP_DIR}" == "/home/digitie/apps/kor-travel-transport" ]] || { echo "승인된 transport checkout만 허용합니다." >&2; exit 2; }
[[ "${REMOTE_ENV_FILE}" == ".env.server14" ]] || { echo "승인된 운영 환경 파일만 허용합니다." >&2; exit 2; }
[[ "${COMPOSE_PROJECT_NAME}" == "kor-travel-transport-admin" ]] || { echo "전용 Compose project만 허용합니다." >&2; exit 2; }

# 새 release를 복사하기 전에 환경과 port를 먼저 확인한다. listener 충돌 때문에
# 실패한 배포가 공유 checkout의 비추적 파일을 삭제·교체하지 않도록 한다.
ssh "${REMOTE_USER}@${REMOTE_HOST}" \
  "REMOTE_APP_DIR='${REMOTE_APP_DIR}' REMOTE_ENV_FILE='${REMOTE_ENV_FILE}' bash -s" <<'PREFLIGHT'
set -euo pipefail
[[ -f "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" ]] || { echo "운영 환경 파일이 없습니다." >&2; exit 2; }
for key in TRANSPORT_UI_PASSWORD TRANSPORT_UI_SESSION_SECRET TRANSPORT_ADMIN_WRITE_TOKEN TRANSPORT_UI_PUBLIC_ORIGIN NEXT_PUBLIC_VWORLD_API_KEY; do
  grep -Eq "^${key}=.+" "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" || { echo "${key}가 설정되지 않았습니다." >&2; exit 2; }
done
# Dagster는 공용 제어 평면이다 — 운영 UI는 공용 webserver(loopback 11002)만 부른다. 옛 값(전용 webserver 14004)이
# 남아 있으면 지워진 webserver를 부르게 되므로 배포하지 않는다. 비우면 compose 기본값(11002)이다.
dagster_url="$({ grep -E '^TRANSPORT_DAGSTER_INTERNAL_URL=' "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" || true; } | tail -n 1 | cut -d= -f2- | tr -d "\"'")"
if [[ -n "${dagster_url}" && "${dagster_url}" != "http://127.0.0.1:11002" ]]; then
  echo "TRANSPORT_DAGSTER_INTERNAL_URL은 비우거나 http://127.0.0.1:11002(공용 Dagster webserver)여야 합니다: ${dagster_url}" >&2
  exit 2
fi
unset dagster_url
write_token="$(grep -E '^TRANSPORT_ADMIN_WRITE_TOKEN=' "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" | tail -n 1 | cut -d= -f2-)"
[[ ${#write_token} -ge 32 ]] || { echo "TRANSPORT_ADMIN_WRITE_TOKEN은 32자 이상이어야 합니다." >&2; exit 2; }
capability="$(curl --fail --silent --show-error --max-time 5 -H @- http://127.0.0.1:14001/v1/transport/admin/place-locations/capability <<<"X-Transport-Admin-Token: ${write_token}")" || {
  echo "좌표 보정 기능이 있는 backend를 먼저 배포해야 합니다." >&2; exit 2;
}
unset write_token
grep -Fq '"contract":"coordinate-write-v1"' <<<"${capability}" || {
  echo "backend 좌표 보정 계약이 일치하지 않습니다." >&2; exit 2;
}
unset capability
port_from_env() {
  local key="$1" fallback="$2" line value
  line="$(grep -E "^${key}=" "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" || true)"
  value="$(printf '%s\n' "${line}" | tail -n 1 | cut -d= -f2-)"
  printf '%s' "${value:-${fallback}}"
}
running="$(docker compose --project-name kor-travel-transport-admin --env-file "${REMOTE_APP_DIR}/${REMOTE_ENV_FILE}" -f "${REMOTE_APP_DIR}/docker-compose.transport-admin.yml" ps --services --status running || true)"
for pair in "transport-api-gateway:$(port_from_env TRANSPORT_PUBLIC_API_PORT 12301)" "transport-admin-web:$(port_from_env TRANSPORT_PUBLIC_WEB_PORT 12305)"; do
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
# backend 동기화·빌드와 Dagster Compose 교체가 끝날 때까지 같은 checkout을 건드리지 않는다.
exec 9>"/home/digitie/apps/.kor-travel-transport-deploy.lock"
flock -n 9 || { echo "공유 checkout을 다른 배포가 변경 중입니다." >&2; exit 2; }
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
# 두 배포가 같은 checkout을 쓴다. 관리자 동기화도 backend staging 증거를
# 무효화해야 수동 remote 재시도에서 혼합 파일을 release로 오인하지 않는다.
rm -f -- "${REMOTE_APP_DIR}/.staged-release-sha"
rsync -a --exclude="${REMOTE_ENV_FILE}" --exclude=".env.server14.legacy" --exclude="backups/" "${stage}/" "${REMOTE_APP_DIR}/"
# Next.js 16은 `proxy.ts`와 이전 `middleware.ts`가 함께 있으면 build를 중단한다.
# archive에 없는, 과거 release에서만 남은 정확한 파일만 제거한다. `--delete`로 checkout의
# 알려지지 않은 운영 파일을 넓게 지우지 않는다.
legacy_middleware="packages/kor-travel-transport-admin/frontend/middleware.ts"
if [[ ! -e "${stage}/${legacy_middleware}" && -e "${REMOTE_APP_DIR}/${legacy_middleware}" ]]; then
  rm -f -- "${REMOTE_APP_DIR}/${legacy_middleware}"
fi
cd "${REMOTE_APP_DIR}"

# api-gateway는 설정 파일을 bind mount한다. image digest만으로는 파일 내용 변경을
# 감지하지 못하므로, 이 전용 두 서비스를 명시적으로 재생성해 공개 allowlist가
# 이전 설정에 머무르지 않게 한다. `--remove-orphans`는 이 project에서 정의가 사라진
# 서비스(공용 Dagster plane 합류로 없어진 옛 `transport-dagster-gateway`, 12302)의 컨테이너를 지운다.
TRANSPORT_ADMIN_RELEASE_SHA="${CANDIDATE_SHA}" docker compose --project-name kor-travel-transport-admin --env-file "${REMOTE_ENV_FILE}" -f docker-compose.transport-admin.yml up -d --build --force-recreate --remove-orphans transport-api-gateway transport-admin-web
api_port="$(port_from_env TRANSPORT_PUBLIC_API_PORT 12301)"
web_port="$(port_from_env TRANSPORT_PUBLIC_WEB_PORT 12305)"
for url in "http://127.0.0.1:${api_port}/health" "http://127.0.0.1:${web_port}/login"; do
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
