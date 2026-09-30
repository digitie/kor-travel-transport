#!/usr/bin/env bash
# n150 kor-travel-transport project에서 Dagster 세 서비스(code-server·webserver·daemon)만 다시
# 만든다. 설치할 docker-compose.shared.yml은 지금 파일과 세 서비스의 healthcheck·init만 달라야
# 한다. 전체 배포(`up --build`, `rsync --delete`)를 쓰지 않고 이미지도 빌드하지 않는다.
#
#   bash redeploy-dagster-services-server14.sh <설치할 docker-compose.shared.yml>
#
# 되돌리기도 같은 스크립트에 옛 파일을 준다. 매 실행이 이미지 고정·gate·daemon 정지·run 대기를
# 처음부터 다시 하므로 새 셸에서 그대로 쓴다. daemon을 멈춘 뒤 어디서 끝나든(STOP·실패·Ctrl-C·
# SSH 끊김·출력 pipe 닫힘) daemon 컨테이너를 `docker start`로 다시 띄운다. `compose start|up`은 쓰지
# 않는다: 전자는 한 번만 도는 migrate 컨테이너가 없어 실패하고, 후자는 daemon을 재생성한다.
set -euo pipefail

APP_DIR="${APP_DIR:-/home/digitie/apps/kor-travel-transport}"
PROJECT=kor-travel-transport
DAGSTER_GRAPHQL_URL="${DAGSTER_GRAPHQL_URL:-http://127.0.0.1:14004/graphql}"
# 고속도로 run이 17분(1002초)까지 걸린 적이 있다. 이보다 오래 남은 run은 끼인 것으로 보고 멈춘다.
DRAIN_TIMEOUT_SECONDS="${DRAIN_TIMEOUT_SECONDS:-1800}"
DRAIN_POLL_SECONDS="${DRAIN_POLL_SECONDS:-30}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-600}"
HEALTH_POLL_SECONDS="${HEALTH_POLL_SECONDS:-15}"

SERVICES=(dagster-code-server dagster-webserver dagster-daemon)
CODE_SERVER="${PROJECT}-dagster-code-server-1"
DAEMON="${PROJECT}-dagster-daemon-1"
SHARED=docker-compose.shared.yml

die() { echo "STOP: $*" >&2; exit 1; }

[[ $# -eq 1 && -f "${1:-}" ]] || die "사용법: $0 <설치할 docker-compose.shared.yml>"
source_file="$(realpath -e -- "$1")"
APP_DIR="$(realpath -e -- "$APP_DIR")" || die "앱 디렉터리의 실제 경로를 확인할 수 없다."
cd "$APP_DIR"
# 전체 release와 관리자 배포는 같은 checkout을 사용한다. 검증·drain·교체가
# 진행되는 동안 그 두 배포가 파일을 바꾸지 못하도록 동일 잠금을 잡는다.
exec 9>"$(dirname "$APP_DIR")/.kor-travel-transport-deploy.lock"
flock -n 9 || die "공유 checkout을 다른 배포가 변경 중이다."
[[ -f .env.server14 && -f docker-compose.yml && -f "$SHARED" ]] || die "$APP_DIR에 배포 파일이 없다."

compose() {
  local shared="$1"
  shift
  docker compose --project-name "$PROJECT" --env-file .env.server14 \
    -f docker-compose.yml -f "$shared" "$@"
}

container_of() { printf '%s-%s-1' "$PROJECT" "$1"; }

# 세 컨테이너의 ID. 컨테이너의 이미지는 바뀌지 않으므로 ID가 같으면 이미지도 같다.
container_ids() {
  local service
  for service in "${SERVICES[@]}"; do
    docker inspect -f '{{.Id}}' "$(container_of "$service")" || return 1
  done
}

container_dsn() {
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" | sed -n 's/^DAGSTER_POSTGRES_URL=//p'
}

# 비교용: scheme만 다른 DSN(`postgresql://`와 `postgresql+psycopg2://`)을 같게 본다.
dsn_without_scheme() {
  local value="$1"
  value="${value#postgresql+psycopg2://}"
  printf '%s' "${value#postgresql://}"
}

FILE_DSN_PY='
import json, sys
print(json.load(sys.stdin)["services"]["dagster-webserver"]["environment"]["DAGSTER_POSTGRES_URL"])
'

# 실행 중인 세 컨테이너가 $1(과 지금 .env.server14)에서 만들어진 그대로인지 본다. 각 컨테이너의
# config-hash label을, 그 컨테이너가 만들어질 때의 이미지 문자열과 DAGSTER_POSTGRES_URL을 넣고 다시
# 계산한 hash와 비교한다. 이 둘만 알려진 차이로 허용한다. 이미지는 이번에 고정 이미지로 바뀌고,
# DSN은 scheme만 달라도 된다(webserver·daemon은 `postgresql://`로 떠 있었다). 값은 출력하지 않는다.
gate() {
  local shared="$1" file_dsn service container want image dsn got
  file_dsn="$(compose "$shared" config --format json | python3 -c "$FILE_DSN_PY")" || {
    echo "STOP: $shared를 렌더링하지 못했다." >&2
    return 1
  }
  for service in "${SERVICES[@]}"; do
    container="$(container_of "$service")"
    want="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.config-hash"}}' "$container")" || return 1
    image="$(docker inspect -f '{{.Config.Image}}' "$container")" || return 1
    dsn="$(container_dsn "$container")" || return 1
    if [[ -z "$dsn" || "$(dsn_without_scheme "$dsn")" != "$(dsn_without_scheme "$file_dsn")" ]]; then
      echo "STOP: $container의 DAGSTER_POSTGRES_URL이 .env.server14와 scheme 밖에서 다르다." >&2
      return 1
    fi
    got="$(BACKEND_RUNTIME_IMAGE="$image" DAGSTER_POSTGRES_URL="$dsn" compose "$shared" config --hash "$service" \
      | awk -v service="$service" '$1 == service { print $2 }')" || return 1
    if [[ -z "$want" || "$got" != "$want" ]]; then
      echo "STOP: $container가 $shared·.env.server14와 다르다(label ${want:-없음}, 파일 ${got:-없음})." >&2
      return 1
    fi
  done
  echo "gate OK: 세 Dagster 컨테이너가 $shared 그대로다."
}

# 두 파일의 렌더링 결과(지금 .env.server14, 고정 이미지)를 비교한다. 세 Dagster 서비스의
# healthcheck·init 밖에서 다르면 STOP이다. 차이는 경로만 출력한다(값에는 비밀이 있다).
DIFF_PY='
import json, sys
SERVICES = ("dagster-code-server", "dagster-webserver", "dagster-daemon")
ALLOWED = ("healthcheck", "init")
ABSENT = object()

def walk(old, new, path, out):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            walk(old.get(key, ABSENT), new.get(key, ABSENT), path + (str(key),), out)
    elif old != new:
        out.append(path)

with open(sys.argv[1], encoding="utf-8") as old_file, open(sys.argv[2], encoding="utf-8") as new_file:
    old, new = json.load(old_file), json.load(new_file)
changed = []
walk(old, new, (), changed)
other = [p for p in changed if not (len(p) >= 3 and p[0] == "services" and p[1] in SERVICES and p[2] in ALLOWED)]
for path in changed:
    print(("  NOT ALLOWED " if path in other else "  changes ") + ".".join(path))
if not changed:
    print("  (렌더링 결과가 같다)")
sys.exit(1 if other else 0)
'

only_probe_changes() {
  echo "$SHARED → $source_file:"
  python3 -c "$DIFF_PY" <(compose "$SHARED" config --format json) <(compose "$candidate" config --format json) || {
    echo "STOP: 설치할 파일이 Dagster healthcheck·init 밖도 바꾼다. 전체 릴리스로 반영한다." >&2
    return 1
  }
}

RUNS_QUERY='{"query":"{runsOrError(filter:{statuses:[STARTED,STARTING,CANCELING]}){__typename ... on Runs{results{runId jobName status}}}}"}'
RUNS_PY='
import json, sys
runs = json.load(sys.stdin)["data"]["runsOrError"]
if runs.get("__typename") != "Runs":
    sys.exit(f"runsOrError: {runs}")
for run in runs["results"]:
    print(run["runId"], run["jobName"], run["status"])
'

in_flight_runs() {
  curl -fsS -m 20 -H 'Content-Type: application/json' -d "$RUNS_QUERY" "$DAGSTER_GRAPHQL_URL" | python3 -c "$RUNS_PY"
}

# code-server 재생성은 실행 중 run을 끊는다. daemon이 멈춰 있으면 run_monitoring도 돌지 않으므로
# 끼인 run(STARTED·CANCELING)이나 멈춘 daemon이 남긴 STARTING은 스스로 끝나지 않는다. 기다림에
# 상한을 두고, 넘으면 남은 run을 출력하고 멈춘다(trap이 daemon을 다시 띄운다).
drain() {
  local deadline=$((SECONDS + DRAIN_TIMEOUT_SECONDS)) runs
  while :; do
    if runs="$(in_flight_runs)"; then
      if [[ -z "$runs" ]]; then
        echo "in-flight run 0"
        return 0
      fi
      printf 'in-flight run:\n%s\n' "$runs"
    else
      runs="(조회 실패)"
      echo "in-flight run 조회에 실패했다. 다시 묻는다." >&2
    fi
    if ((SECONDS >= deadline)); then
      printf 'STOP: %s초가 지나도 run이 남았다:\n%s\n' "$DRAIN_TIMEOUT_SECONDS" "$runs" >&2
      return 1
    fi
    sleep "$DRAIN_POLL_SECONDS"
  done
}

wait_healthy() {
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS)) service state pending
  while :; do
    pending=""
    for service in "${SERVICES[@]}"; do
      state="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$(container_of "$service")")"
      [[ "$state" == healthy ]] || pending+=" $service=$state"
    done
    if [[ -z "$pending" ]]; then
      echo "세 서비스 모두 healthy"
      return 0
    fi
    if ((SECONDS >= deadline)); then
      echo "아직 healthy가 아니다:$pending — docker ps로 계속 본다." >&2
      return 1
    fi
    sleep "$HEALTH_POLL_SECONDS"
  done
}

# EXIT trap에서만 쓴다. 터미널이 사라졌거나(EIO) 출력 pipe가 닫혔으면(EPIPE) 출력은 버린다.
note() { echo "$*" >&2 2>/dev/null || :; }

daemon_down=0
stopping=0
rollback_file=""
work=""
# SSH가 끊겨 터미널이 사라지거나 출력 pipe가 닫힌 뒤에도 daemon을 되살려야 한다. 그때는 모든 출력이
# 실패하고, errexit가 켜져 있으면 trap이 첫 echo에서 끝난다. 그래서 errexit를 풀고 신호(두 번째
# Ctrl-C 포함)를 무시한 채, 출력보다 `docker start`를 먼저 한다.
restore_daemon() {
  local status=$?
  set +e
  trap '' INT TERM HUP PIPE
  if ((daemon_down)); then
    # `docker stop` 도중에 끊겼으면 daemon은 이미 SIGTERM을 받아 곧 멈춘다. 그 전에 start하면 아무 일도
    # 하지 않은 채 뒤이어 멈추므로, stop을 마저 끝낸 뒤 start한다.
    ((stopping)) && docker stop "$DAEMON" >/dev/null 2>&1
    docker start "$DAEMON" >/dev/null 2>&1
    if [[ "$(docker inspect -f '{{.State.Running}}' "$DAEMON" 2>/dev/null)" == true ]]; then
      note "daemon 실행 중: $DAEMON"
    else
      note "실패: $DAEMON이 떠 있지 않다. 'docker start $DAEMON'을 직접 실행한다."
    fi
  fi
  if ((status != 0)) && [[ -n "$rollback_file" ]]; then
    note "파일은 이미 교체됐다. 'docker ps -a'로 세 서비스를 보고, 되돌리려면 이 스크립트에 $rollback_file을 준다."
  fi
  [[ -z "$work" ]] || rm -rf -- "$work"
  exit "$status"
}
# 신호는 exit code(128+번호)로 바꾼다. 비대화형 bash는 EXIT trap이 있으면 종료 신호에도 그 trap을
# 돌리지만, 그때 trap 안의 $?는 신호를 담지 않는다(2026-09-28 bash 5.2·5.3 실측: SIGPIPE에서 0). 그러면
# `exit "$status"`가 끊긴 실행을 exit 0으로 끝낸다. PIPE는 출력 pipe가 닫힌 경우다(pty 없는
# `ssh n150 bash …`의 클라이언트가 끊기거나 `| tee`가 죽으면 다음 출력이 SIGPIPE를 받는다).
# 각 신호 trap은 exit 전에 네 신호를 먼저 무시한다. 두 번째 신호가 restore_daemon의 `trap ''`보다
# 먼저 닿으면(마이크로초 창, 적대 리뷰가 합성 테스트로 650회 중 16회 재현) 대기 중이던 exit가
# `docker start`를 건너뛴다.
trap restore_daemon EXIT
trap 'trap "" INT TERM HUP PIPE; exit 130' INT
trap 'trap "" INT TERM HUP PIPE; exit 143' TERM
trap 'trap "" INT TERM HUP PIPE; exit 129' HUP
trap 'trap "" INT TERM HUP PIPE; exit 141' PIPE

# 검사한 내용과 설치하는 내용이 같도록 처음에 사본을 떠 두고 끝까지 그 사본만 쓴다.
work="$(mktemp -d)"
candidate="$work/docker-compose.shared.yml"
cp -- "$source_file" "$candidate"

for service in "${SERVICES[@]}"; do
  [[ "$(docker inspect -f '{{.State.Running}}' "$(container_of "$service")")" == true ]] \
    || die "$(container_of "$service")가 실행 중이 아니다."
done
# 교체 직전(5)에 이 컨테이너들이 그대로인지 본다.
ids="$(container_ids)"

# 1) 이미지를 지금 code-server 이미지로 고정한다. .env.server14의 BACKEND_RUNTIME_IMAGE는 다른 배포가
#    바꿀 수 있고, 셸 env가 --env-file보다 우선한다. 고정 이미지는 태그로 붙잡아 둔다. 다른 작업의
#    태그만 붙은 이미지는 그 태그가 지워지면 사라지고, 그러면 되돌리기의 재생성이 실패한다.
pin="$(docker inspect -f '{{.Image}}' "$CODE_SERVER")"
[[ "$pin" =~ ^sha256:[0-9a-f]{64}$ ]] || die "code-server 이미지 ID를 읽지 못했다: $pin"
export BACKEND_RUNTIME_IMAGE="$pin"
pin_tag="kor-travel-transport-backend:dagster-pin-${pin:7:12}"
echo "이미지 고정: $pin ($pin_tag)"

# 2) 설치할 파일은 healthcheck·init만 바꿔야 하고, 실행 중 컨테이너는 지금 파일 그대로여야 한다.
only_probe_changes || exit 1
gate "$SHARED" || exit 1
# run을 물을 수 없으면 4의 대기는 상한까지 daemon을 멈춘 채 헛돈다. 멈추기 전에 한 번 묻는다.
in_flight_runs >/dev/null || die "Dagster GraphQL($DAGSTER_GRAPHQL_URL)에서 run을 읽지 못했다. daemon은 그대로다."
docker tag "$pin" "$pin_tag"

# 3) 새 run이 시작되지 않게 daemon을 먼저 멈춘다(schedule·queue dequeue는 daemon이 한다).
daemon_down=1
stopping=1
docker stop "$DAEMON" >/dev/null
stopping=0

# 4) 실행 중 run이 끝나기를 기다린다.
drain || exit 1

# 5) 기다리는 동안 다른 배포가 env·compose를 바꿨거나, Dagster 서비스를 다시 만들었거나, daemon을
#    띄웠을 수 있다. 교체 직전에 모두 다시 본다. gate는 각 컨테이너의 자기 이미지로 계산하므로 다른
#    이미지로 다시 만든 컨테이너도 통과한다. 그것은 ID로 잡는다. 떠 있는 daemon은 새 run을 시작했을 수
#    있고 재생성이 그 run을 끊는다.
only_probe_changes || exit 1
gate "$SHARED" || exit 1
[[ "$(container_ids)" == "$ids" ]] \
  || die "기다리는 동안 다른 작업이 Dagster 컨테이너를 다시 만들었다. 'docker ps -a'로 이미지를 확인한다."
[[ "$(docker inspect -f '{{.State.Running}}' "$DAEMON")" == false ]] \
  || die "기다리는 동안 다른 작업이 daemon을 띄웠다. run을 다시 확인하고 처음부터 실행한다."
# 백업 이름은 겹치지 않아야 한다. 같은 초에 되돌리기가 돌면 넘겨받은 백업을 덮어쓸 수 있다.
backup="$(mktemp "$SHARED.before-$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"
cp -p "$SHARED" "$backup"
# 이 긴급 재배포는 공유 checkout의 추적 파일을 교체한다. 이전 전체 release의
# stage 완료 표식으로 이후 원격 재배포를 허용하면 후보 SHA와 Compose가 어긋난다.
rm -f -- "$APP_DIR/.staged-release-sha"
install -m 664 "$candidate" "$SHARED"
rollback_file="$APP_DIR/$backup"
echo "교체: $SHARED (이전 파일 $rollback_file)"
compose "$SHARED" config -q
compose "$SHARED" up -d --no-deps --no-build "${SERVICES[@]}"
daemon_down=0

# 6) 효과 확인: 세 컨테이너가 설치한 파일 그대로이고 고정 이미지로 떠 있다.
for service in "${SERVICES[@]}"; do
  container="$(container_of "$service")"
  [[ "$(docker inspect -f '{{.Image}}' "$container")" == "$pin" ]] || die "$container 이미지가 $pin이 아니다."
  docker inspect -f '{{.Name}} init={{.HostConfig.Init}} {{json .Config.Healthcheck.Test}}' "$container"
done
gate "$SHARED" || die "재생성한 컨테이너가 $SHARED와 다르다."
wait_healthy
echo "완료. 되돌리려면 같은 스크립트에 $rollback_file을 준다. $pin_tag는 다음 전체 릴리스까지 둔다."
