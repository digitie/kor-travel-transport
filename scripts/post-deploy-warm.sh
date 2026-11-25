#!/usr/bin/env bash
# 배포 직후 best-effort warm(감사 WLH-03·MC-07·RT-03·RT-11). 배포 성패를 바꾸지 않는다 — 인수 오류(exit 2)를 빼면
# 항상 exit 0이고, 문제는 stderr의 `WARN` 줄로만 남긴다.
#
# 언제 부르나: 배포 명령이 **끝난 뒤**(배포 lock이 풀리고 소유 일정·sensor가 복원된 뒤) 운영자가 Odroid에서 부른다.
#   배포 스크립트 안(lock·일정 STOPPED 동안)에서 부르지 않는다 — 준비·smoke가 길어지면 주차 수집 공백이 그만큼 늘어난다.
#   - Odroid 정본인 Manager v2(`ktdctl service-release apply-core-candidate transport ... --confirm`)가 성공하고 location이
#     다시 실린 뒤, 배포한 이미지와 같은 revision의 승인된 source clone에서 부른다(Manager 쪽 자동 호출은 후속).
#   - 확인 절차·결과 해석은 docs/runbooks/deployment.md "배포 직후 best-effort warm".
#
# 하는 일:
#   (a) 새 code-server 컨테이너 안에서 Map이 읽는 기준정보 본문(ADR-016 artifact, 철도역·여객선)을 준비한다. 입력
#       revision에는 본문 코드 지문이 들어가 본문 코드가 바뀐 배포는 본문이 모두 무효가 되므로(관계없는 배포는 그대로
#       재사용한다 — 그때 준비는 `reused`다), 다음 공항 수집을 기다리지 않고 미리 만든다. 서빙 중인 API /health의
#       reference_payload_fingerprint를 넘기고, 컨테이너 안 모듈이 자기 지문과 대조한다 — 다르면(한쪽만 롤백 등) API가
#       읽지 않을 revision을 만들고 head를 되돌리게 되므로 건너뛴다(exit 4). RELEASE_SHA는 보지 않는다. Dagster run
#       밖에서 돌므로 5분 공항 수집의 준비와 겹칠 수 있다. 겹친 종류는 `busy`로 끝나고 어느 쪽도 실패하지 않는다.
#   (b) 서빙 중인 backend 컨테이너 안에서 loopback으로 Map export(T1 limit=1, 철도역·여객선 첫 페이지)를 한 번씩
#       부른다. 토큰은 컨테이너 env에서만 읽고(argv·출력 없음) 경로·상태·problem code·지연만 출력한다.
#
# 사용: scripts/post-deploy-warm.sh [--project kor-travel-transport] [--api-port 12302]
#                                   [--prepare-timeout 180] [--request-timeout 20]
set -uo pipefail

usage() {
  echo "Usage: $0 [--project NAME] [--api-port PORT] [--prepare-timeout 30-1800] [--request-timeout 1-120]" >&2
  exit 2
}

project="kor-travel-transport"
api_port="12302"
prepare_timeout="180"
request_timeout="20"
while [[ "$#" -gt 0 ]]; do
  [[ "$#" -ge 2 ]] || usage
  case "$1" in
    --project) project="$2" ;;
    --api-port) api_port="$2" ;;
    --prepare-timeout) prepare_timeout="$2" ;;
    --request-timeout) request_timeout="$2" ;;
    *) usage ;;
  esac
  shift 2
done
# 컨테이너 안 모듈과 같은 범위로 검사한다(prepare_references 30~1800초, export_smoke 1~120초).
if [[ ! "${project}" =~ ^[a-z0-9][a-z0-9_-]*$ || ! "${api_port}" =~ ^[0-9]{1,5}$
      || ! "${prepare_timeout}" =~ ^[0-9]{1,4}$ || ! "${request_timeout}" =~ ^[0-9]{1,3}$ ]] \
   || (( 10#${api_port} < 1 || 10#${api_port} > 65535 || 10#${prepare_timeout} < 30 || 10#${prepare_timeout} > 1800
         || 10#${request_timeout} < 1 || 10#${request_timeout} > 120 )); then
  echo "post-deploy-warm: invalid arguments" >&2
  usage
fi

code_server="${project}-dagster-code-server-1"
backend="${project}-backend-1"
log() { printf 'post-deploy-warm: %s\n' "$*"; }
warn() { printf 'post-deploy-warm: WARN %s\n' "$*" >&2; }
running() { [[ "$(docker inspect -f '{{.State.Running}}' "$1" 2>/dev/null || true)" == "true" ]]; }
fingerprint_pattern='^[0-9a-f]{64}$'

# 서빙 중인 API가 실제로 쓰는 본문 코드 지문(ADR-016). 본문 준비는 이 값과 같은 code-server에서만 한다(모듈이 대조).
# 필드가 없으면(지문 이전 이미지) `absent`, null이면(API가 지문을 못 만들어 artifact 경로가 꺼짐) `null`로 구분한다.
api_fingerprint="$(curl -fsS --max-time 5 "http://127.0.0.1:${api_port}/health" 2>/dev/null \
  | python3 -c 'import json,sys; b=json.load(sys.stdin); print("absent" if "reference_payload_fingerprint" not in b else (b["reference_payload_fingerprint"] or "null"))' 2>/dev/null || true)"

# (a) 기준정보 본문 준비. 컨테이너 안 상한(--timeout-seconds)이 정본이다 — 바깥 timeout이 docker exec 클라이언트를
# 끊어도 컨테이너 안 프로세스는 남으므로 바깥 값은 안 상한보다 넉넉한 안전망일 뿐이다.
if ! running "${code_server}"; then
  warn "${code_server} is not running; reference prepare skipped"
elif [[ "${api_fingerprint}" == "absent" ]]; then
  warn "backend /health has no reference_payload_fingerprint (API image predates the payload fingerprint); reference prepare skipped"
elif [[ "${api_fingerprint}" == "null" ]]; then
  warn "backend reference artifacts are DISABLED: the API could not compute its payload fingerprint (/health reference_artifacts=disabled); every Map first page rebuilds in-request - check the image has app sources; reference prepare skipped"
elif [[ ! "${api_fingerprint}" =~ ${fingerprint_pattern} ]]; then
  warn "backend /health reference_payload_fingerprint is unavailable (${api_fingerprint:-none}); reference prepare skipped"
else
  started=${SECONDS}
  prepare_output="$(timeout --kill-after=10 "$((prepare_timeout + 60))" \
    docker exec "${code_server}" python -I -B -m app.deploy.prepare_references \
      --timeout-seconds "${prepare_timeout}" --expect-payload-fingerprint "${api_fingerprint}")"
  prepare_status=$?
  elapsed="$((SECONDS - started))s"
  case "${prepare_status}" in
    0) log "reference prepare (${elapsed}): ${prepare_output}" ;;
    2) warn "reference prepare skipped: code-server image predates the payload fingerprint (prepare_references rejected --expect-payload-fingerprint); deploy the same image to the code-server" ;;
    6) warn "reference prepare skipped: the code-server could not compute its payload fingerprint (its reference artifacts are disabled; check the image has app sources): ${prepare_output:-no output}" ;;
    4) warn "reference prepare skipped: code-server payload fingerprint differs from the API; artifacts would be keyed to a revision the API does not read (${prepare_output:-no output})" ;;
    5) warn "reference prepare incomplete (${elapsed}): not every Map reference body is ready yet (not_ready/busy/deferred); the next airport-job prepare or the first Map page builds it: ${prepare_output:-no output}" ;;
    *) warn "reference prepare did not fully succeed (exit ${prepare_status}, ${elapsed}): ${prepare_output:-no output}" ;;
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
    3) warn "export smoke: configuration mismatch (404 with a configured token, or a token shorter than 32 characters) — check TRANSPORT_SERVICE_EXPORT_TOKEN, SERVICE_EXPORT_ALLOWED_CLIENTS_CSV and router settings" ;;
    4) warn "export smoke skipped: no service export token in the backend container (exports are intentionally closed)" ;;
    5) warn "export smoke: some T1 exports are not available (see the problem code per route: source not current or disabled) — not a deploy failure" ;;
    1) warn "export smoke: a Map T3 first page was not 2xx, or a route timed out/was unreachable; the next Map call may rebuild in-request or get 503" ;;
    *) warn "export smoke did not complete (exit ${smoke_status})" ;;
  esac
else
  warn "${backend} is not running; export smoke skipped"
fi
exit 0
