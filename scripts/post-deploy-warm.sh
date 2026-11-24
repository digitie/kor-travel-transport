#!/usr/bin/env bash
# 배포 직후 best-effort warm(감사 WLH-03·MC-07·RT-03·RT-11). 배포 성패를 바꾸지 않는다 — 항상 exit 0이고,
# 문제는 stderr의 `WARN` 줄로만 남긴다.
#
# 언제 부르나: backend /health의 release_sha가 후보와 같고 공용 Dagster가 location을 다시 실은 뒤.
#   - Odroid 정본인 Manager v2(`ktdctl service-release apply-core-candidate transport ... --confirm`)로 배포했다면
#     그 명령이 성공한 뒤 운영자가 Odroid에서 승인된 source clone의 이 스크립트를 부른다(Manager 쪽 자동 호출은 후속).
#   - legacy `deploy-prod-remote.sh`는 current 발행 뒤 스스로 부른다.
#
# 하는 일:
#   (a) 새 code-server 컨테이너 안에서 기준정보 본문(ADR-016 artifact)을 준비한다. 입력 revision에 release_sha가
#       들어가 배포마다 본문이 모두 무효가 되므로, 다음 공항 수집을 기다리지 않고 미리 만든다. 먼저 code-server의
#       RELEASE_SHA가 서빙 중인 API /health의 release_sha와 같은지 본다 — 다르면(code-server만 롤백, RELEASE_SHA 없이
#       기동 등) API가 읽지 않을 revision을 만들고 head를 되돌리게 되므로 건너뛴다. Dagster run 밖에서 돌므로 5분 공항
#       수집의 준비와 겹칠 수 있다. 겹친 종류는 `busy`로 끝나고 어느 쪽도 실패하지 않는다.
#   (b) 서빙 중인 backend 컨테이너 안에서 loopback으로 Map export(T1 limit=1, 철도역·여객선 첫 페이지)를 한 번씩
#       부른다. 토큰은 컨테이너 env에서만 읽고(argv·출력 없음) 경로·상태·지연만 출력한다. 토큰이 설정됐는데
#       404면 설정 불일치(토큰·허용 peer·라우터)로 경고한다.
#
# 사용: scripts/post-deploy-warm.sh [--project kor-travel-transport] [--api-port 12302]
#                                   [--prepare-timeout 300] [--request-timeout 20]
set -uo pipefail

project="kor-travel-transport"
api_port="12302"
prepare_timeout="300"
request_timeout="20"
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --project) project="${2:-}"; shift 2 ;;
    --api-port) api_port="${2:-}"; shift 2 ;;
    --prepare-timeout) prepare_timeout="${2:-}"; shift 2 ;;
    --request-timeout) request_timeout="${2:-}"; shift 2 ;;
    *) echo "Usage: $0 [--project NAME] [--api-port PORT] [--prepare-timeout SECONDS] [--request-timeout SECONDS]" >&2; exit 2 ;;
  esac
done
if [[ ! "${project}" =~ ^[a-z0-9][a-z0-9_-]*$ || ! "${api_port}" =~ ^[0-9]{1,5}$
      || ! "${prepare_timeout}" =~ ^[0-9]{2,4}$ || ! "${request_timeout}" =~ ^[0-9]{1,3}$ ]]; then
  echo "post-deploy-warm: invalid arguments" >&2
  exit 2
fi

code_server="${project}-dagster-code-server-1"
backend="${project}-backend-1"
log() { printf 'post-deploy-warm: %s\n' "$*"; }
warn() { printf 'post-deploy-warm: WARN %s\n' "$*" >&2; }
running() { [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" == "true" ]]; }
release_pattern='^[0-9A-Za-z._-]{1,80}$'

# 서빙 중인 API가 실제로 쓰는 release_sha. 본문 준비는 이 값과 같은 code-server에서만 한다.
api_release="$(curl -fsS --max-time 5 "http://127.0.0.1:${api_port}/health" 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("release_sha") or "")' 2>/dev/null || true)"
code_server_release=""
if running "${code_server}"; then
  code_server_release="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "${code_server}" 2>/dev/null \
    | sed -n 's/^RELEASE_SHA=//p' | head -n 1 || true)"
fi

# (a) 기준정보 본문 준비. 컨테이너 안 상한(--timeout-seconds)이 정본이다 — 바깥 timeout이 docker exec 클라이언트를
# 끊어도 컨테이너 안 프로세스는 남으므로 바깥 값은 안 상한보다 넉넉한 안전망일 뿐이다.
if ! running "${code_server}"; then
  warn "${code_server} is not running; reference prepare skipped"
elif [[ ! "${api_release}" =~ ${release_pattern} || "${api_release}" == "unknown" ]]; then
  warn "backend /health release_sha is unavailable (${api_release:-none}); reference prepare skipped"
elif [[ "${code_server_release}" != "${api_release}" ]]; then
  warn "release_sha mismatch: code-server ${code_server_release:-none} vs API ${api_release}; reference prepare skipped (artifacts would be keyed to a revision the API does not read)"
else
  started=${SECONDS}
  prepare_output="$(timeout --kill-after=10 "$((prepare_timeout + 60))" \
    docker exec "${code_server}" python -I -B -m app.deploy.prepare_references \
      --timeout-seconds "${prepare_timeout}" --expect-release-sha "${api_release}")"
  prepare_status=$?
  case "${prepare_status}" in
    0) log "reference prepare ($((SECONDS - started))s): ${prepare_output}" ;;
    4) warn "reference prepare skipped: code-server settings release_sha differs from the API (${prepare_output:-no output})" ;;
    *) warn "reference prepare did not fully succeed (exit ${prepare_status}, $((SECONDS - started))s): ${prepare_output:-no output}" ;;
  esac
fi

# (b) loopback smoke + warm. 서빙 프로세스의 지문 memo·커넥션을 데우는 유일한 경로다.
if running "${backend}"; then
  timeout --kill-after=10 "$((request_timeout * 8 + 60))" \
    docker exec "${backend}" python -I -B -m app.deploy.export_smoke \
      --port "${api_port}" --timeout-seconds "${request_timeout}"
  smoke_status=$?
  case "${smoke_status}" in
    0) log "export smoke passed" ;;
    3) warn "export smoke: 404 while a service export token is configured — check the token, SERVICE_EXPORT_ALLOWED_CLIENTS_CSV and router settings" ;;
    *) warn "export smoke: some routes did not return 2xx (exit ${smoke_status}); the next Map call may rebuild in-request" ;;
  esac
else
  warn "${backend} is not running; export smoke skipped"
fi
exit 0
