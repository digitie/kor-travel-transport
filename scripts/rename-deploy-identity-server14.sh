#!/usr/bin/env bash
# n150 운영 식별자 개명 cutover(ADR-010). compose project와 앱 디렉터리를 `kor-travel-airport`에서
# `kor-travel-transport`로 옮긴다. 공항 주차 도메인(airports 테이블, /v1/airports, airport_collection_job,
# AIRPORT_CODES_CSV …)은 바꾸지 않는다. DB·RustFS bucket·Dagster location은 이미 transport 이름이라
# 옮기지 않는다. 절차와 타이밍은 docs/runbooks/deployment.md "운영 식별자 개명 cutover"가 정본이다.
#
#   bash rename-deploy-identity-server14.sh prepare <R>   # 창 전: 새 디렉터리·env 사본·스냅숏·rollback 태그
#   bash rename-deploy-identity-server14.sh restore-point # 창 전: 두 DB의 직접 pg_dump + pg_restore --list
#   (WSL, R 체크아웃) DEPLOY_STAGE_ONLY=true scripts/deploy-server14.sh
#   bash rename-deploy-identity-server14.sh prebuild <R>  # 창 전: migration·Dagster gate, 이미지 미리 빌드
#   bash rename-deploy-identity-server14.sh window <R>    # 창: 옛 스택 정지 → 새 스택 → 검증 → 옛 컨테이너 은퇴
#   bash rename-deploy-identity-server14.sh admin         # 창: 관리 스택을 빌드 없이 새 디렉터리에서 재생성
#   bash rename-deploy-identity-server14.sh finish        # 창 끝: crontab 백업 줄 제거, 옛 디렉터리 은퇴
#   bash rename-deploy-identity-server14.sh rollback      # 되돌리기(정리 단계 전까지)
#   bash rename-deploy-identity-server14.sh status        # 읽기 전용 상태
#
# 모든 단계는 조건이 어긋나면 `STOP:`을 출력하고 exit 1로 끝난다. 비밀값(env 값·DSN 비밀번호)은
# 출력하지 않는다. `window`는 옛 daemon을 멈춘 뒤 새 스택 검증이 끝나기 전에 어디서 끝나든(STOP·실패·
# Ctrl-C·SSH 끊김·출력 pipe 닫힘) 새 스택을 멈추고 옛 env를 되돌리고 옛 컨테이너를 다시 띄운다.
set -euo pipefail

OLD_PROJECT=kor-travel-airport
NEW_PROJECT=kor-travel-transport
ADMIN_PROJECT=kor-travel-transport-admin
OLD_DIR="${OLD_DIR:-/home/digitie/apps/kor-travel-airport}"
NEW_DIR="${NEW_DIR:-/home/digitie/apps/kor-travel-transport}"
WORK_DIR="${WORK_DIR:-${HOME}/transport-rename}"
ENV_NAME=.env.server14
ROLLBACK_REPO=kor-travel-airport-rollback
NEW_BACKEND_REPO=kor-travel-transport-backend
DAGSTER_GRAPHQL_URL="${DAGSTER_GRAPHQL_URL:-http://127.0.0.1:14004/graphql}"
API_URL="${API_URL:-http://127.0.0.1:14001}"
WEB_URL="${WEB_URL:-http://127.0.0.1:14002}"
ADMIN_API_URL="${ADMIN_API_URL:-http://127.0.0.1:12301/health}"
ADMIN_DAGSTER_URL="${ADMIN_DAGSTER_URL:-http://127.0.0.1:12302/health}"
ADMIN_WEB_URL="${ADMIN_WEB_URL:-http://127.0.0.1:12305/login}"
# 고속도로 run이 17분까지 걸린 적이 있다. 유가 run은 보통 2시간이라 유가 시작 뒤 2시간 안에서는 창을 열지 않는다.
DRAIN_TIMEOUT_SECONDS="${DRAIN_TIMEOUT_SECONDS:-1800}"
DRAIN_POLL_SECONDS="${DRAIN_POLL_SECONDS:-30}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-600}"
HEALTH_POLL_SECONDS="${HEALTH_POLL_SECONDS:-10}"
SHARED_PG_CONTAINER="${SHARED_PG_CONTAINER:-kor-travel-shared-postgres}"
PG_CLIENT_IMAGE="${PG_CLIENT_IMAGE:-}"
MANAGER_LINK="${MANAGER_LINK:-/opt/kor-travel-docker-manager}"

SERVICES=(backend frontend dagster-code-server dagster-webserver dagster-daemon dagster-gateway)
DAGSTER_SERVICES=(dagster-code-server dagster-webserver dagster-daemon)
# daemon을 먼저 멈추고 맨 나중에 띄운다(schedule·queue dequeue는 daemon이 한다).
OLD_STOP_ORDER=(dagster-webserver dagster-gateway dagster-code-server backend frontend)
OLD_START_ORDER=(dagster-code-server dagster-webserver dagster-gateway backend frontend)
ADMIN_SERVICES=(transport-admin-web transport-api-gateway transport-dagster-gateway)
ADMIN_BUILT=(transport-admin-web transport-dagster-gateway)
# rollback 역할 → 옛 서비스. webserver·daemon은 code 이미지로 되돌린다(그들이 돌던 c8b47811은 store에 없다).
ROLLBACK_ROLES=(backend:backend code:dagster-code-server frontend:frontend gateway:dagster-gateway)
CRON_SCRIPT="${OLD_DIR}/scripts/n150-backup-cron.sh"
BUILD_PATTERN='docker-buildx|docker build|compose .*[[:space:]]build([[:space:]]|$)'

T_ID='{{.Id}}'
T_IMAGE='{{.Image}}'
T_CFG_IMAGE='{{.Config.Image}}'
T_RUNNING='{{.State.Running}}'
T_HEALTH='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}'
T_SERVICE='{{index .Config.Labels "com.docker.compose.service"}}'
T_WORKDIR='{{index .Config.Labels "com.docker.compose.project.working_dir"}}'
T_HASH='{{index .Config.Labels "com.docker.compose.config-hash"}}'
T_INIT='{{.HostConfig.Init}}'
T_RESTART='{{.HostConfig.RestartPolicy.Name}}'
T_MOUNTS='{{range .Mounts}}{{.Source}}:{{.Destination}}{{println}}{{end}}'

die() { echo "STOP: $*" >&2; exit 1; }
private_dir() { mkdir -p -- "$1" && chmod 700 -- "$1"; }
say() { echo "== $*"; }
# EXIT trap에서만 쓴다. 터미널이 사라졌거나(EIO) 출력 pipe가 닫혔으면(EPIPE) 출력은 버린다.
note() { echo "$*" >&2 2>/dev/null || :; }

old_c() { printf '%s-%s-1' "$OLD_PROJECT" "$1"; }
new_c() { printf '%s-%s-1' "$NEW_PROJECT" "$1"; }
admin_c() { printf '%s-%s-1' "$ADMIN_PROJECT" "$1"; }
insp() { docker inspect -f "$1" "$2"; }
image_id() { docker image inspect -f "$T_ID" "$1" 2>/dev/null; }
# project label의 정확한 값으로 찾는다. 이름 접두어는 kor-travel-transport-admin-*과 겹친다.
containers() {  # <project> [-a]
  docker ps ${2:-} --filter "label=com.docker.compose.project=$1" --format '{{.Names}}' | sort
}
# `[[ -z "$(containers …)" ]]`는 docker ps가 실패해도 참이다. 목록을 먼저 받아 실패를 STOP으로 만든다.
none_running() {
  local names
  names="$(containers "$1")" || die "docker ps로 $1 project를 읽지 못했다."
  [[ -z "$names" ]]
}
running_services() {
  local name
  for name in $(containers "$1"); do insp "$T_SERVICE" "$name"; done | sort
}
expected_services() { printf '%s\n' "${SERVICES[@]}" | sort; }
require_sha() { [[ "${1:-}" =~ ^[0-9a-f]{40}$ ]] || die "R은 40자리 Git SHA여야 한다: '${1:-}'"; }
stamp() { [[ -f "$WORK_DIR/stamp" ]] || die "$WORK_DIR/stamp가 없다. 먼저 prepare를 실행한다."; cat "$WORK_DIR/stamp"; }
release_tag() { printf '%s:rel-%s' "$NEW_BACKEND_REPO" "${1:0:12}"; }
retired_dir() { printf '%s.retired-%s' "$OLD_DIR" "$(stamp)"; }
fenced_env() { printf '%s/%s.fenced-%s' "$OLD_DIR" "$ENV_NAME" "$(stamp)"; }

require_release() {  # prepare에서 적은 R과 같아야 한다.
  require_sha "$1"
  [[ -f "$WORK_DIR/release" && "$(cat "$WORK_DIR/release")" == "$1" ]] \
    || die "prepare가 기록한 R과 다르다. 같은 R로 prepare부터 다시 실행한다."
}

no_builds() {
  local builds
  builds="$(pgrep -fa "$BUILD_PATTERN" || true)"
  [[ -z "$builds" ]] || die "n150에서 이미지 빌드가 돌고 있다(디스크 대기로 창이 길어진다). 끝난 뒤 다시 실행한다:
$builds"
}

# RELEASE_SHA·BACKEND_RUNTIME_IMAGE는 새 env에 두지 않는다. release SHA는 배포 스크립트가 runtime env에
# 붙이고, 이미지는 배포 스크립트가 release마다 셸 env로 준다.
filter_env() { awk '!/^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE)=/' "$1"; }

copy_env() {
  local src="$OLD_DIR/$ENV_NAME" dst="$NEW_DIR/$ENV_NAME" tmp
  [[ -f "$src" && ! -L "$src" ]] || die "$src가 일반 파일이 아니다."
  tmp="$(mktemp "$NEW_DIR/.env.server14.copy.XXXXXX")"
  filter_env "$src" > "$tmp"
  chmod 600 "$tmp"
  mv -f -- "$tmp" "$dst"
  # 값은 출력하지 않는다. 내용 비교와 키 이름만 본다.
  cmp -s <(filter_env "$src") "$dst" || die "$dst가 $src(두 키 제외)와 다르다."
  if grep -qE '^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE)=' "$dst"; then
    die "$dst에 RELEASE_SHA·BACKEND_RUNTIME_IMAGE가 남았다."
  fi
  echo "env 사본 확인: $(grep -c '=' "$dst")개 줄, RELEASE_SHA·BACKEND_RUNTIME_IMAGE 제외"
}

# ---------------------------------------------------------------- Dagster GraphQL
RUNS_QUERY='{"query":"{runsOrError(filter:{statuses:[STARTED,STARTING,CANCELING]}){__typename ... on Runs{results{runId jobName status}}}}"}'
RUNS_PY='
import json, sys
runs = json.load(sys.stdin)["data"]["runsOrError"]
if runs.get("__typename") != "Runs":
    sys.exit(f"runsOrError: {runs}")
for run in runs["results"]:
    print(run["runId"], run["jobName"], run["status"])
'
SCHEDULES_QUERY='{"query":"{repositoriesOrError{__typename ... on RepositoryConnection{nodes{name location{name} schedules{name scheduleState{status}}}}}}"}'
SCHEDULES_PY='
import json, sys
repos = json.load(sys.stdin)["data"]["repositoriesOrError"]
if repos.get("__typename") != "RepositoryConnection":
    sys.exit("repositoriesOrError: " + str(repos))
rows = []
for node in repos["nodes"]:
    location = node["location"]["name"]
    if location != sys.argv[1]:
        continue
    for schedule in node["schedules"]:
        rows.append(location + "/" + node["name"] + "/" + schedule["name"] + " " + schedule["scheduleState"]["status"])
if not rows:
    sys.exit("location " + sys.argv[1] + "의 schedule이 없다")
for row in sorted(rows):
    print(row)
'
graphql() { curl -fsS -m 20 -H 'Content-Type: application/json' -d "$1" "$DAGSTER_GRAPHQL_URL"; }
in_flight_runs() { graphql "$RUNS_QUERY" | python3 -c "$RUNS_PY"; }
schedule_states() { graphql "$SCHEDULES_QUERY" | python3 -c "$SCHEDULES_PY" "$NEW_PROJECT"; }

# daemon이 멈춘 동안에는 run_monitoring도 돌지 않아 끼인 STARTED·STARTING은 스스로 끝나지 않는다. 상한을 둔다.
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

wait_healthy() {  # <container...>
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS)) name state pending
  while :; do
    pending=""
    for name in "$@"; do
      state="$(insp "$T_HEALTH" "$name" 2>/dev/null || echo missing)"
      [[ "$state" == healthy ]] || pending+=" $name=$state"
    done
    if [[ -z "$pending" ]]; then
      echo "healthy:$(printf ' %s' "$@")"
      return 0
    fi
    if ((SECONDS >= deadline)); then
      echo "STOP: 아직 healthy가 아니다:$pending" >&2
      return 1
    fi
    sleep "$HEALTH_POLL_SECONDS"
  done
}

http_ok() { curl -fsS -m 10 -o /dev/null "$1"; }
wait_http() {  # <url>
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  until http_ok "$1"; do
    ((SECONDS < deadline)) || { echo "STOP: $1이 응답하지 않는다." >&2; return 1; }
    sleep "$HEALTH_POLL_SECONDS"
  done
}
port_busy() { [[ -n "$(ss -Hltn "sport = :$1" 2>/dev/null)" ]]; }

daemon_count() {  # 두 project에서 실행 중인 dagster-daemon 수. 다른 저장소의 daemon은 세지 않는다.
  local project total=0 names
  for project in "$OLD_PROJECT" "$NEW_PROJECT"; do
    names="$(docker ps --filter "label=com.docker.compose.project=$project" \
      --filter "label=com.docker.compose.service=dagster-daemon" --format '{{.Names}}')"
    [[ -z "$names" ]] || total=$((total + $(printf '%s\n' "$names" | wc -l)))
  done
  echo "$total"
}

# ---------------------------------------------------------------- PostgreSQL client
pg_image() {
  if [[ -n "$PG_CLIENT_IMAGE" ]]; then
    printf '%s' "$PG_CLIENT_IMAGE"
  else
    # 서버와 같은 major의 client(pg_dump는 서버보다 옛 major면 거부한다). 공용 PostgreSQL 이미지를 쓴다.
    insp "$T_CFG_IMAGE" "$SHARED_PG_CONTAINER"
  fi
}

env_value() {  # <env file> <key>. 배포 스크립트처럼 source로 읽고 값은 출력하지 않는 호출부에만 넘긴다.
  ( set +u; set -a; source "$1" >/dev/null 2>&1; printf '%s' "${!2:-}" )
}

PGPASS_FILE=""
# DSN의 비밀번호는 PGPASS_FILE(0600)에만 쓴다. docker 명령줄에는 비밀번호 없는 URI만 넘긴다.
client_dsn() {  # <dsn>
  printf '%s' "$1" | python3 -c '
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

value = sys.stdin.read()
parts = urlsplit(value)
database = parts.path.removeprefix("/")
if (
    parts.scheme not in {"postgresql", "postgresql+psycopg2", "postgresql+asyncpg"}
    or not parts.hostname or not parts.port or not database
    or parts.username is None or parts.password is None
):
    raise SystemExit("STOP: DSN이 완전한 PostgreSQL URI가 아니다.")
username, password = unquote(parts.username), unquote(parts.password)
if any("\n" in item or "\r" in item for item in (parts.hostname, database, username, password)):
    raise SystemExit("STOP: DSN에 줄바꿈이 있다.")
escape = lambda item: item.replace("\\", "\\\\").replace(":", "\\:")
with Path(sys.argv[1]).open("a", encoding="utf-8") as handle:
    handle.write(":".join(escape(item) for item in (parts.hostname, str(parts.port), database, username, password)) + "\n")
print(f"postgresql://{quote(username, safe=chr(39))}@{parts.hostname}:{parts.port}/{quote(database, safe=chr(39))}")
' "$PGPASS_FILE"
}

APP_DSN=""
DAGSTER_DSN=""
open_databases() {  # 운영 env에서 두 DSN을 읽어 비밀번호 없는 client DSN으로 바꾼다.
  local env_file="$OLD_DIR/$ENV_NAME" app dagster
  [[ -f "$env_file" ]] || env_file="$NEW_DIR/$ENV_NAME"
  [[ -f "$env_file" ]] || die "DSN을 읽을 $ENV_NAME이 없다."
  app="$(env_value "$env_file" DATABASE_URL)"
  dagster="$(env_value "$env_file" DAGSTER_POSTGRES_URL)"
  [[ "$app" =~ ^postgresql\+asyncpg://[^@]+@127\.0\.0\.1:11000/kor_travel_transport$ ]] \
    || die "DATABASE_URL이 공용 application DB(127.0.0.1:11000/kor_travel_transport)가 아니다."
  [[ "$dagster" =~ ^postgresql(\+psycopg2)?://[^@]+@127\.0\.0\.1:11000/kor_travel_transport_dagster$ ]] \
    || die "DAGSTER_POSTGRES_URL이 공용 Dagster metadata DB가 아니다."
  private_dir "$WORK_DIR"
  PGPASS_FILE="$(mktemp "$WORK_DIR/.pgpass.XXXXXX")"
  chmod 600 "$PGPASS_FILE"
  APP_DSN="$(client_dsn "$app")"
  DAGSTER_DSN="$(client_dsn "$dagster")"
}

pg_run() {  # <extra docker args...> -- <command...>
  local args=()
  while [[ "$1" != -- ]]; do args+=("$1"); shift; done
  shift
  docker run --rm --network host -u "$(id -u):$(id -g)" \
    -v "$PGPASS_FILE:/run/secrets/pgpass:ro" -e PGPASSFILE=/run/secrets/pgpass \
    "${args[@]}" "$(pg_image)" "$@"
}

db_revision() { pg_run -- psql -X "$APP_DSN" -qAt -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version'; }

# ---------------------------------------------------------------- migration·Dagster gate
# 파일 이름과 CRLF를 뺀 내용의 sha256. 운영 트리는 Windows autocrlf checkout의 git archive라 CRLF일 수 있다.
MIGRATION_LIST='cd /app/alembic/versions && for f in *.py; do printf "%s %s\n" "$f" "$(tr -d "\r" < "$f" | sha256sum | cut -d" " -f1)"; done'
new_migrations() {
  (cd "$NEW_DIR/backend/alembic/versions" && sh -c "${MIGRATION_LIST#cd /app/alembic/versions && }") | LC_ALL=C sort
}
HEAD_PY='
import re, sys
from pathlib import Path
revisions, parents = set(), set()
for path in Path(sys.argv[1]).glob("*.py"):
    text = path.read_text(encoding="utf-8")
    revision = re.search(r"^revision(?:\s*:\s*str)?\s*=\s*[\x27\"]([^\x27\"]+)[\x27\"]", text, re.M)
    down = re.search(r"^down_revision(?:\s*:[^=]+)?\s*=\s*(.+)$", text, re.M)
    if revision:
        revisions.add(revision.group(1))
    if down:
        parents.update(re.findall(r"[\x27\"]([^\x27\"]+)[\x27\"]", down.group(1)))
heads = sorted(revisions - parents)
if len(heads) != 1:
    sys.exit(f"STOP: alembic head가 하나가 아니다: {heads}")
print(heads[0])
'

# 배포되는 R의 migration이 운영 DB에 이미 적용된 그대로여야 migrate one-shot이 no-op이고 rollback이
# 같은 스키마로 돌아간다. revision ID만이 아니라 파일 내용(CRLF 무시)까지 지금 backend 이미지와 비교한다.
migration_gate() {
  local running new head revision
  running="$(docker run --rm --network none --entrypoint sh "$ROLLBACK_REPO:backend" -c "$MIGRATION_LIST" | LC_ALL=C sort)" \
    || die "rollback backend 이미지에서 migration 목록을 읽지 못했다."
  [[ -n "$running" ]] || die "rollback backend 이미지에 migration 파일이 없다."
  new="$(new_migrations)" || die "$NEW_DIR의 migration 목록을 읽지 못했다."
  if [[ "$running" != "$new" ]]; then
    diff <(printf '%s\n' "$running") <(printf '%s\n' "$new") >&2 || :
    die "R의 alembic migration이 지금 운영 backend 이미지와 다르다(< 운영, > R). 스키마가 바뀌는 release는 이 cutover로 내지 않는다."
  fi
  head="$(python3 -c "$HEAD_PY" "$NEW_DIR/backend/alembic/versions")" || die "R의 alembic head를 정하지 못했다."
  revision="$(db_revision)" || die "운영 DB의 alembic_version을 읽지 못했다."
  [[ "$revision" == "$head" ]] || die "운영 DB revision($revision)이 R의 head($head)와 다르다."
  echo "migration gate OK: 파일 $(printf '%s\n' "$new" | wc -l)개 동일, DB revision $revision = head"
}

dagster_version() { docker run --rm --network none --entrypoint python "$1" -c 'import dagster; print(dagster.__version__)'; }

# ---------------------------------------------------------------- 상태 기록
snapshot() {
  local file project name
  file="$WORK_DIR/snapshot-$(date -u +%Y%m%dT%H%M%SZ).txt"
  {
    echo "# $(date -u +%FT%TZ) 운영 식별자 개명 스냅숏(값 없음)"
    for project in "$OLD_PROJECT" "$NEW_PROJECT" "$ADMIN_PROJECT"; do
      echo "## project $project"
      for name in $(containers "$project" -a); do
        echo "$name id=$(insp "$T_ID" "$name") image=$(insp "$T_IMAGE" "$name") config_image=$(insp "$T_CFG_IMAGE" "$name") hash=$(insp "$T_HASH" "$name") running=$(insp "$T_RUNNING" "$name") restart=$(insp "$T_RESTART" "$name")"
      done
    done
    echo "## manager release"
    readlink "$MANAGER_LINK" 2>/dev/null || echo "(없음)"
    echo "## release files"
    for name in .release-sha .transport-admin-release-sha; do
      echo "$name=$(cat "$OLD_DIR/$name" 2>/dev/null || echo '(없음)')"
    done
    echo "## $ENV_NAME key names"
    grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$OLD_DIR/$ENV_NAME" | sort
    echo "## backups"
    sudo -n ls -li "$OLD_DIR/backups" 2>&1 || :
    echo "## in-flight runs"
    in_flight_runs 2>&1 || echo "(조회 실패)"
  } > "$file"
  chmod 600 "$file"
  echo "스냅숏: $file"
}

check_old_images() {  # prepare 뒤 다른 배포가 옛 컨테이너를 바꿨으면 rollback 태그가 낡았다.
  local service want got
  while read -r service want; do
    got="$(insp "$T_IMAGE" "$(old_c "$service")")" || die "$(old_c "$service")를 읽지 못했다."
    [[ "$got" == "$want" ]] || die "$(old_c "$service") 이미지가 prepare 뒤 바뀌었다. prepare부터 다시 실행한다."
  done < "$WORK_DIR/old-images"
}

# ================================================================ prepare
cmd_prepare() {
  local R="${1:-}" role service ref id source name
  require_sha "$R"
  [[ -d "$OLD_DIR" && -f "$OLD_DIR/$ENV_NAME" && ! -L "$OLD_DIR/$ENV_NAME" ]] \
    || die "$OLD_DIR/$ENV_NAME가 없다(이미 cutover했거나 경로가 다르다)."
  [[ "$(running_services "$OLD_PROJECT")" == "$(expected_services)" ]] \
    || die "$OLD_PROJECT project의 실행 중 서비스가 여섯 개(${SERVICES[*]})가 아니다."
  none_running "$NEW_PROJECT" || die "$NEW_PROJECT project 컨테이너가 이미 실행 중이다."

  private_dir "$WORK_DIR"
  [[ -f "$WORK_DIR/stamp" ]] || date -u +%Y%m%d > "$WORK_DIR/stamp"
  printf '%s\n' "$R" > "$WORK_DIR/release"

  if [[ -e "$NEW_DIR" ]]; then
    [[ -d "$NEW_DIR" && ! -L "$NEW_DIR" && -O "$NEW_DIR" ]] || die "$NEW_DIR가 내 소유 디렉터리가 아니다."
    chmod 700 "$NEW_DIR"
  else
    mkdir -m 700 "$NEW_DIR"
  fi
  say "env 사본(창에서 fence 직전에 다시 복사한다)"
  copy_env

  say "스냅숏"
  snapshot
  if [[ ! -f "$WORK_DIR/crontab.before" ]]; then
    crontab -l > "$WORK_DIR/crontab.before" 2>/dev/null || : > "$WORK_DIR/crontab.before"
    chmod 600 "$WORK_DIR/crontab.before"
  fi
  for service in "${SERVICES[@]}"; do
    printf '%s %s\n' "$service" "$(insp "$T_IMAGE" "$(old_c "$service")")"
  done > "$WORK_DIR/old-images"

  say "rollback 이미지 태그(다른 세션의 태그가 지워져도 되돌리기 재생성이 이미지를 찾게 한다)"
  : > "$WORK_DIR/rollback-images"
  for role in "${ROLLBACK_ROLES[@]}"; do
    service="${role#*:}"
    role="${role%%:*}"
    name="$(old_c "$service")"
    id=""
    for source in "$T_IMAGE" "$T_CFG_IMAGE"; do
      ref="$(insp "$source" "$name")"
      if id="$(image_id "$ref")" && [[ -n "$id" ]]; then
        break
      fi
      id=""
    done
    [[ -n "$id" ]] || die "$name의 이미지가 store에 없어 rollback 태그를 만들 수 없다."
    docker tag "$id" "$ROLLBACK_REPO:$role"
    printf '%s %s %s\n' "$role" "$id" "$ref" >> "$WORK_DIR/rollback-images"
    if [[ "$id" != "$(insp "$T_IMAGE" "$name")" ]]; then
      echo "$ROLLBACK_REPO:$role = $ref ($id). 실행 중 이미지는 store에 없어 compose 이미지 이름으로 대신한다."
    else
      echo "$ROLLBACK_REPO:$role = $id"
    fi
  done
  echo "다음: restore-point, 그다음 WSL에서 R 체크아웃의 DEPLOY_STAGE_ONLY=true scripts/deploy-server14.sh"
}

# ================================================================ restore-point
cleanup_pgpass() { [[ -z "$PGPASS_FILE" ]] || rm -f -- "$PGPASS_FILE"; }

cmd_restore_point() {
  local out="$WORK_DIR/restore-point" ts name dsn file toc entries
  [[ -f "$WORK_DIR/stamp" ]] || die "먼저 prepare를 실행한다."
  trap cleanup_pgpass EXIT
  open_databases
  private_dir "$out"
  df -h "$out" | tail -n 1
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  for name in kor_travel_transport kor_travel_transport_dagster; do
    if [[ "$name" == kor_travel_transport ]]; then dsn="$APP_DSN"; else dsn="$DAGSTER_DSN"; fi
    file="$name-$ts.dump"
    say "pg_dump -Fc $name"
    pg_run -v "$out:/out" -- pg_dump -Fc --no-password -f "/out/$file.partial" "$dsn" \
      || die "$name pg_dump가 실패했다."
    [[ "$(head -c 5 "$out/$file.partial")" == PGDMP ]] || die "$file이 custom format dump가 아니다."
    toc="$out/$name-$ts.toc"
    pg_run -v "$out:/out:ro" -- pg_restore --list "/out/$file.partial" > "$toc" \
      || die "$file을 pg_restore --list가 읽지 못했다."
    entries="$(grep -c ' TABLE DATA ' "$toc" || true)"
    ((entries > 0)) || die "$file 목차에 TABLE DATA가 없다."
    mv -f -- "$out/$file.partial" "$out/$file"
    echo "$out/$file $(du -h "$out/$file" | cut -f1) TABLE DATA $entries개"
  done
}

# ================================================================ prebuild
cmd_prebuild() {
  local R="${1:-}" tag
  require_release "$R"
  no_builds
  [[ "$(tr -d '\r\n' < "$NEW_DIR/.release-sha" 2>/dev/null)" == "$R" ]] \
    || die "$NEW_DIR/.release-sha가 R이 아니다. WSL에서 DEPLOY_STAGE_ONLY=true scripts/deploy-server14.sh로 R을 올린다."
  [[ -x "$NEW_DIR/scripts/deploy-server14-remote.sh" && -f "$NEW_DIR/$ENV_NAME" ]] || die "$NEW_DIR 배포 파일이 없다."
  trap cleanup_pgpass EXIT
  open_databases
  migration_gate
  tag="$(release_tag "$R")"
  cd "$NEW_DIR"
  export BACKEND_RUNTIME_IMAGE="$tag"
  compose_new() { docker compose --project-name "$NEW_PROJECT" --env-file "$ENV_NAME" -f docker-compose.yml -f docker-compose.shared.yml "$@"; }
  compose_new config -q
  # 운영 overlay는 모든 서비스를 host network로 돌린다. 렌더링에 network가 남으면 손으로 만든 network가
  # 필요해지고 db stack의 label과 어긋난다. 렌더링에는 비밀값이 있으므로 stdin으로만 넘기고 출력하지 않는다.
  compose_new config --format json | python3 -c '
import json, sys
config = json.load(sys.stdin)
if config.get("name") != "kor-travel-transport":
    sys.exit("STOP: 렌더링 project 이름이 " + repr(config.get("name")) + "다.")
if config.get("networks"):
    sys.exit("STOP: 운영 렌더링에 network가 남았다: " + ", ".join(sorted(config["networks"])))
backend = sorted(name for name, service in config["services"].items() if service.get("image") == sys.argv[1])
if backend != ["backend", "dagster-code-server", "dagster-daemon", "dagster-migrate", "dagster-webserver", "migrate"]:
    sys.exit("STOP: release 이미지를 쓰는 서비스가 다르다: " + ", ".join(backend))
' "$tag"
  say "이미지 미리 빌드(창 안의 up --build는 cache hit)"
  compose_new build backend frontend dagster-gateway
  for ref in "$tag" "$NEW_PROJECT-frontend:latest" "$NEW_PROJECT-dagster-gateway:latest"; do
    [[ -n "$(image_id "$ref")" ]] || die "$ref 이미지가 없다."
  done
  # Dagster 버전이 같아야 dagster instance migrate가 no-op이고 rollback의 옛 daemon이 metadata DB를 읽는다.
  local new_version old_version
  new_version="$(dagster_version "$tag")" || die "$tag의 dagster 버전을 읽지 못했다."
  old_version="$(dagster_version "$ROLLBACK_REPO:code")" || die "$ROLLBACK_REPO:code의 dagster 버전을 읽지 못했다."
  [[ "$new_version" == "$old_version" ]] || die "dagster 버전이 다르다(운영 $old_version, R $new_version)."
  echo "prebuild OK: $tag, dagster $new_version"
}

# ================================================================ window
armed=0
daemon_down=0
stopping=0
others_down=0
fenced=0
new_started=0

restore_old_stack() {
  local status=$? name service
  set +e
  trap '' INT TERM HUP PIPE
  cleanup_pgpass
  if ((armed)) && ((status != 0)); then
    if ((new_started)); then
      # 새 daemon을 먼저 멈춘다. 옛 daemon과 같은 metadata DB를 두 daemon이 함께 쓰지 않게 한다.
      docker stop "$(new_c dagster-daemon)" >/dev/null 2>&1
      for name in $(containers "$NEW_PROJECT"); do docker stop "$name" >/dev/null 2>&1; done
    fi
    if ((fenced)) && [[ ! -e "$OLD_DIR/$ENV_NAME" ]]; then
      mv -- "$(fenced_env)" "$OLD_DIR/$ENV_NAME"
    fi
    if ((others_down)); then
      for service in "${OLD_START_ORDER[@]}"; do docker start "$(old_c "$service")" >/dev/null 2>&1; done
    fi
    if ((daemon_down)); then
      ((stopping)) && docker stop "$(old_c dagster-daemon)" >/dev/null 2>&1
      docker start "$(old_c dagster-daemon)" >/dev/null 2>&1
    fi
    for service in "${SERVICES[@]}"; do
      if [[ "$(insp "$T_RUNNING" "$(old_c "$service")" 2>/dev/null)" != true ]]; then
        note "실패: $(old_c "$service")가 떠 있지 않다. 'bash $0 rollback'으로 고정 이미지 재생성을 한다."
      fi
    done
    note "창이 끝나지 않아 옛 스택으로 되돌렸다. 원인을 고친 뒤 window를 다시 실행한다."
  elif ((status != 0)) && ((new_started)); then
    note "새 스택 검증은 끝났고 옛 컨테이너 은퇴 중 멈췄다. 'bash $0 status'로 보고 남은 은퇴를 마치거나 rollback한다."
  fi
  exit "$status"
}

backups_listing() { sudo -n find "$1" -mindepth 1 -printf '%P %s %y\n' | sort; }

link_backups() {
  local old="$OLD_DIR/backups" new="$NEW_DIR/backups"
  sudo -n test -d "$old" || die "$old가 없다."
  if sudo -n test -e "$new"; then
    [[ "$(backups_listing "$old")" == "$(backups_listing "$new")" ]] \
      || die "$new가 이미 있고 $old와 다르다. 내용을 확인한 뒤 옮긴다."
    echo "backups 이미 같다: $new"
    return 0
  fi
  # 같은 파일시스템의 hardlink 사본: 즉시, 추가 공간 없음, root 소유·mode 유지. OLD는 그대로 남아 rollback이 쓴다.
  sudo -n cp -a -l -T -- "$old" "$new"
  [[ "$(backups_listing "$old")" == "$(backups_listing "$new")" ]] || die "$new 사본이 $old와 다르다."
  echo "backups hardlink 사본: $(backups_listing "$new" | wc -l)개 항목"
}

verify_new_stack() {
  local R="$1" name service mounts health project
  [[ "$(running_services "$NEW_PROJECT")" == "$(expected_services)" ]] \
    || die "$NEW_PROJECT의 실행 중 서비스가 여섯 개가 아니다: $(running_services "$NEW_PROJECT" | tr '\n' ' ')"
  wait_healthy "$(new_c dagster-code-server)" "$(new_c dagster-webserver)" "$(new_c dagster-daemon)" || exit 1
  for service in "${SERVICES[@]}"; do
    name="$(new_c "$service")"
    [[ "$(insp "$T_WORKDIR" "$name")" == "$NEW_DIR" ]] || die "$name의 working_dir가 $NEW_DIR가 아니다."
  done
  for service in "${DAGSTER_SERVICES[@]}"; do
    [[ "$(insp "$T_INIT" "$(new_c "$service")")" == true ]] || die "$(new_c "$service")에 init이 없다."
  done
  [[ "$(daemon_count)" == 1 ]] || die "두 project에서 dagster-daemon이 $(daemon_count)개 돈다."
  mounts="$(insp "$T_MOUNTS" "$(new_c backend)")"
  [[ "$mounts" == *"$NEW_DIR/backups:/app/backups"* && "$mounts" != *"$OLD_DIR"* ]] \
    || die "$(new_c backend)의 backups bind가 $NEW_DIR/backups가 아니다."
  health="$(curl -fsS -m 10 "$API_URL/health")" || die "$API_URL/health가 응답하지 않는다."
  [[ "$health" == *"\"release_sha\":\"$R\""* ]] || die "/health release_sha가 R이 아니다."
  http_ok "$WEB_URL/" || die "$WEB_URL이 응답하지 않는다."
  # webserver가 healthy여도 code location을 막 다시 읽는 중일 수 있다. 상한 안에서 다시 묻는다.
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS)) after="$WORK_DIR/schedules.after"
  until schedule_states > "$after" 2>/dev/null && cmp -s "$WORK_DIR/schedules.before" "$after"; do
    ((SECONDS < deadline)) \
      || die "새 webserver의 location $NEW_PROJECT schedule 상태가 창 전과 다르다(diff $WORK_DIR/schedules.before $after)."
    sleep "$HEALTH_POLL_SECONDS"
  done
  echo "새 스택 확인: 여섯 서비스, Dagster healthy·init, daemon 1개, backups bind, release_sha, schedule $(wc -l < "$after")개 상태 동일"
}

retire_old_containers() {
  local service name stamp_value
  stamp_value="$(stamp)"
  # 옛 daemon은 지운다. 이미지(c8b47811)가 store에 없어 rollback 재료가 아니다. 이름으로 다시 띄울 수 없게 한다.
  docker rm "$(old_c dagster-daemon)" >/dev/null
  for service in "${OLD_STOP_ORDER[@]}"; do
    name="$(old_c "$service")"
    # restart=no: reboot·Manager Start·`docker start <옛 이름>`이 옛 스택을 되살리지 못하게 한다.
    docker update --restart=no "$name" >/dev/null
    docker rename "$name" "$name-retired-$stamp_value"
  done
  local left
  left="$(containers "$OLD_PROJECT" -a)"
  [[ "$(printf '%s\n' "$left" | grep -c -- "-retired-$stamp_value\$")" == 5 ]] && none_running "$OLD_PROJECT" \
    || die "옛 컨테이너 은퇴 결과가 다르다: $left"
  for name in $left; do
    [[ "$(insp "$T_RESTART" "$name")" == no ]] || die "$name의 restart가 no가 아니다."
  done
  echo "옛 컨테이너 은퇴: daemon 삭제, 다섯 개 *-retired-$stamp_value(restart=no)"
}

cmd_window() {
  local R="${1:-}" service port
  require_release "$R"
  no_builds
  [[ "$(tr -d '\r\n' < "$NEW_DIR/.release-sha" 2>/dev/null)" == "$R" ]] || die "$NEW_DIR/.release-sha가 R이 아니다."
  [[ -x "$NEW_DIR/scripts/deploy-server14-remote.sh" ]] || die "$NEW_DIR/scripts/deploy-server14-remote.sh가 없다."
  for ref in "$(release_tag "$R")" "$NEW_PROJECT-frontend:latest" "$NEW_PROJECT-dagster-gateway:latest"; do
    [[ -n "$(image_id "$ref")" ]] || die "$ref가 없다. prebuild를 먼저 실행한다."
  done
  for role in "${ROLLBACK_ROLES[@]}"; do
    [[ -n "$(image_id "$ROLLBACK_REPO:${role%%:*}")" ]] || die "$ROLLBACK_REPO:${role%%:*}가 없다. prepare를 다시 실행한다."
  done
  [[ "$(running_services "$OLD_PROJECT")" == "$(expected_services)" ]] \
    || die "$OLD_PROJECT의 실행 중 서비스가 여섯 개가 아니다(이미 cutover했으면 status로 확인한다)."
  none_running "$NEW_PROJECT" || die "$NEW_PROJECT 컨테이너가 이미 실행 중이다."
  check_old_images
  [[ -f "$OLD_DIR/$ENV_NAME" && ! -e "$(fenced_env)" ]] || die "$OLD_DIR/$ENV_NAME 상태가 창 전과 다르다."
  trap cleanup_pgpass EXIT
  open_databases
  migration_gate
  cleanup_pgpass
  schedule_states > "$WORK_DIR/schedules.before" || die "창 전 schedule 상태를 읽지 못했다."
  echo "창 전 schedule $(wc -l < "$WORK_DIR/schedules.before")개 기록"

  armed=1
  trap restore_old_stack EXIT
  trap 'trap "" INT TERM HUP PIPE; exit 130' INT
  trap 'trap "" INT TERM HUP PIPE; exit 143' TERM
  trap 'trap "" INT TERM HUP PIPE; exit 129' HUP
  trap 'trap "" INT TERM HUP PIPE; exit 141' PIPE

  say "1. 옛 daemon 정지와 in-flight run 대기(상한 ${DRAIN_TIMEOUT_SECONDS}초)"
  daemon_down=1
  stopping=1
  docker stop "$(old_c dagster-daemon)" >/dev/null
  stopping=0
  drain || exit 1

  say "2. 나머지 옛 서비스 정지(rm·down 아님)"
  others_down=1
  for service in "${OLD_STOP_ORDER[@]}"; do docker stop "$(old_c "$service")" >/dev/null; done
  none_running "$OLD_PROJECT" || die "$OLD_PROJECT 컨테이너가 아직 돈다."
  for port in 14001 14002 14003 14004 14005; do
    ! port_busy "$port" || die "포트 $port가 아직 LISTEN이다."
  done

  say "3. env 재복사(창 전 편집 반영)와 옛 env fence"
  copy_env
  fenced=1
  mv -- "$OLD_DIR/$ENV_NAME" "$(fenced_env)"
  [[ ! -e "$OLD_DIR/$ENV_NAME" ]] || die "$OLD_DIR/$ENV_NAME fence에 실패했다."

  say "4. backups hardlink 사본"
  link_backups

  say "5. 새 project 배포(deploy-server14-remote.sh: config·up --build·health)"
  new_started=1
  (cd "$NEW_DIR" && env -u REMOTE_APP_DIR -u COMPOSE_PROJECT_NAME -u REMOTE_ENV_FILE \
    CANDIDATE_SHA="$R" ./scripts/deploy-server14-remote.sh) || die "새 project 배포가 실패했다."

  say "6. 새 스택 검증"
  verify_new_stack "$R"
  armed=0

  say "7. 옛 컨테이너 은퇴"
  retire_old_containers
  echo "창 완료. 다음: bash $0 admin"
}

# ================================================================ admin
cmd_admin() {
  local service name repo running latest pre gateway_mount
  [[ "$(running_services "$NEW_PROJECT")" == "$(expected_services)" ]] || die "$NEW_PROJECT가 여섯 서비스로 떠 있지 않다. window부터 마친다."
  [[ -f "$NEW_DIR/$ENV_NAME" && -f "$NEW_DIR/docker-compose.transport-admin.yml" ]] || die "$NEW_DIR 관리 스택 파일이 없다."
  for service in "${ADMIN_BUILT[@]}"; do
    name="$(admin_c "$service")"
    repo="$ADMIN_PROJECT-$service"
    running="$(insp "$T_IMAGE" "$name")" || die "$name을 읽지 못했다."
    latest="$(image_id "$repo:latest" || true)"
    [[ "$latest" == "$running" ]] || die "$repo:latest가 실행 중 이미지와 다르다. 빌드 없는 재생성이 이미지를 바꾼다."
    pre="$(image_id "$repo:pre-rename" || true)"
    if [[ -z "$pre" ]]; then
      docker tag "$running" "$repo:pre-rename"
    elif [[ "$pre" != "$running" ]]; then
      die "$repo:pre-rename이 실행 중 이미지와 다르다."
    fi
    printf '%s %s\n' "$service" "$running" >> "$WORK_DIR/admin-images"
  done
  say "관리 스택 재생성(빌드 없음, bind 경로만 $NEW_DIR로)"
  (cd "$NEW_DIR" && docker compose --project-name "$ADMIN_PROJECT" --env-file "$ENV_NAME" \
    -f docker-compose.transport-admin.yml up -d --no-build --force-recreate) || die "관리 스택 재생성이 실패했다."
  for service in "${ADMIN_SERVICES[@]}"; do
    name="$(admin_c "$service")"
    [[ "$(insp "$T_RUNNING" "$name")" == true ]] || die "$name이 떠 있지 않다."
    [[ "$(insp "$T_WORKDIR" "$name")" == "$NEW_DIR" ]] || die "$name의 working_dir가 $NEW_DIR가 아니다."
  done
  for service in "${ADMIN_BUILT[@]}"; do
    [[ "$(insp "$T_IMAGE" "$(admin_c "$service")")" == "$(image_id "$ADMIN_PROJECT-$service:pre-rename")" ]] \
      || die "$(admin_c "$service") 이미지가 바뀌었다."
  done
  gateway_mount="$(insp "$T_MOUNTS" "$(admin_c transport-api-gateway)")"
  [[ "$gateway_mount" == *"$NEW_DIR/deploy/transport-admin/api-gateway.conf.template:"* ]] \
    || die "transport-api-gateway bind가 $NEW_DIR를 가리키지 않는다."
  for url in "$ADMIN_API_URL" "$ADMIN_DAGSTER_URL" "$ADMIN_WEB_URL"; do wait_http "$url" || exit 1; done
  if [[ -f "$OLD_DIR/.transport-admin-release-sha" && ! -f "$NEW_DIR/.transport-admin-release-sha" ]]; then
    # 이미지를 다시 빌드하지 않았으므로 관리 UI release는 그대로다.
    cp -p -- "$OLD_DIR/.transport-admin-release-sha" "$NEW_DIR/.transport-admin-release-sha"
  fi
  echo "관리 스택 확인: 세 서비스 $NEW_DIR, 이미지 동일, 12301·12302·12305 응답. 다음: bash $0 finish"
}

# ================================================================ finish
cmd_finish() {
  local retired before after removed service name project
  retired="$(retired_dir)"
  [[ "$(running_services "$NEW_PROJECT")" == "$(expected_services)" ]] || die "$NEW_PROJECT가 여섯 서비스로 떠 있지 않다."
  for service in "${ADMIN_SERVICES[@]}"; do
    [[ "$(insp "$T_WORKDIR" "$(admin_c "$service")")" == "$NEW_DIR" ]] || die "관리 스택이 아직 $OLD_DIR에서 돈다. admin을 먼저 실행한다."
  done
  for project in "$NEW_PROJECT" "$ADMIN_PROJECT"; do
    for name in $(containers "$project"); do
      [[ "$(insp "$T_MOUNTS" "$name")$(insp "$T_WORKDIR" "$name")" != *"$OLD_DIR"* ]] || die "$name이 아직 $OLD_DIR를 쓴다."
    done
  done

  say "crontab: 옛 백업 줄 제거(transport 백업은 Manager로 옮긴다)"
  before="$WORK_DIR/crontab.before-finish"
  if crontab -l > "$before" 2>/dev/null; then
    removed="$(grep -F -- "$CRON_SCRIPT" "$before" || true)"
    if [[ -n "$removed" ]]; then
      after="$(mktemp "$WORK_DIR/crontab.after.XXXXXX")"
      grep -v -F -- "$CRON_SCRIPT" "$before" > "$after" || :
      printf '%s\n' "$removed" >> "$WORK_DIR/crontab.removed"
      crontab "$after"
      cmp -s "$after" <(crontab -l) || die "crontab 설치 결과가 다르다."
      rm -f -- "$after"
      echo "crontab 줄 $(printf '%s\n' "$removed" | wc -l)개 제거(원본 $before)"
    else
      echo "crontab에 $CRON_SCRIPT 줄이 없다."
    fi
    [[ "$(crontab -l)" != *"$OLD_DIR"* ]] || die "crontab에 아직 $OLD_DIR를 쓰는 줄이 있다."
  else
    echo "crontab이 없다."
  fi

  say "옛 디렉터리 은퇴"
  if [[ -e "$OLD_DIR" ]]; then
    [[ ! -e "$retired" ]] || die "$retired가 이미 있다. 옮기면 겹친다."
    mv -T -- "$OLD_DIR" "$retired"
    echo "$OLD_DIR → $retired"
  else
    [[ -d "$retired" ]] || die "$OLD_DIR도 $retired도 없다."
    echo "이미 은퇴: $retired"
  fi
  echo "완료. Manager 설치·검증과 72시간 관찰 뒤 정리는 runbook을 따른다."
}

# ================================================================ rollback
compose_old() { docker compose --project-name "$OLD_PROJECT" --env-file "$ENV_NAME" -f docker-compose.yml -f docker-compose.shared.yml "$@"; }

cmd_rollback() {
  local retired entry name line repo service
  retired="$(retired_dir)"
  say "1. 옛 디렉터리"
  if [[ -e "$retired" ]]; then
    if [[ -e "$OLD_DIR" ]]; then
      # 옛 배포 스크립트의 `mkdir -p`나 옛 backend의 bind가 빈 OLD(와 빈 backups)를 만들 수 있다.
      # 그대로 mv하면 은퇴한 트리가 그 안으로 들어간다(critique M4).
      for entry in "$OLD_DIR"/* "$OLD_DIR"/.[!.]* "$OLD_DIR"/..?*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        [[ "$entry" == "$OLD_DIR/backups" ]] && sudo -n test -d "$entry" \
          && [[ -z "$(sudo -n find "$entry" -mindepth 1 -print -quit)" ]] \
          || die "$OLD_DIR가 비어 있지 않다($entry). 겹치지 않게 직접 정리한 뒤 다시 실행한다."
      done
      [[ ! -e "$OLD_DIR/backups" ]] || sudo -n rmdir -- "$OLD_DIR/backups"
      rmdir -- "$OLD_DIR"
    fi
    mv -T -- "$retired" "$OLD_DIR"
    echo "$retired → $OLD_DIR"
  fi
  [[ -d "$OLD_DIR" ]] || die "$OLD_DIR가 없다."
  for entry in "${ROLLBACK_ROLES[@]}"; do
    [[ -n "$(image_id "$ROLLBACK_REPO:${entry%%:*}")" ]] || die "$ROLLBACK_REPO:${entry%%:*}가 없다."
  done

  say "2. 새 project 정지(daemon 먼저)"
  docker stop "$(new_c dagster-daemon)" >/dev/null 2>&1 || :
  for name in $(containers "$NEW_PROJECT"); do docker stop "$name" >/dev/null; done
  none_running "$NEW_PROJECT" || die "$NEW_PROJECT 컨테이너가 아직 돈다."

  say "3. 옛 env 되돌림"
  if [[ ! -f "$OLD_DIR/$ENV_NAME" ]]; then
    [[ -f "$(fenced_env)" ]] || die "$OLD_DIR/$ENV_NAME도 fence 파일도 없다."
    mv -- "$(fenced_env)" "$OLD_DIR/$ENV_NAME"
  fi

  say "4. 옛 스택을 고정 이미지로 재생성(daemon 마지막)"
  docker tag "$ROLLBACK_REPO:frontend" "$OLD_PROJECT-frontend:latest"
  docker tag "$ROLLBACK_REPO:gateway" "$OLD_PROJECT-dagster-gateway:latest"
  cd "$OLD_DIR"
  BACKEND_RUNTIME_IMAGE="$ROLLBACK_REPO:code" compose_old up -d --no-deps --no-build --force-recreate dagster-code-server dagster-webserver
  wait_healthy "$(old_c dagster-code-server)" || exit 1
  BACKEND_RUNTIME_IMAGE="$ROLLBACK_REPO:backend" compose_old up -d --no-deps --no-build --force-recreate backend dagster-gateway frontend
  BACKEND_RUNTIME_IMAGE="$ROLLBACK_REPO:code" compose_old up -d --no-deps --no-build --force-recreate dagster-daemon
  [[ "$(running_services "$OLD_PROJECT")" == "$(expected_services)" ]] || die "옛 스택 여섯 서비스가 떠 있지 않다."
  [[ "$(daemon_count)" == 1 ]] || die "dagster-daemon이 $(daemon_count)개 돈다."
  wait_http "$API_URL/health" || exit 1

  say "5. 관리 스택을 옛 디렉터리에서 옛 이미지로"
  local tagged=1
  for service in "${ADMIN_BUILT[@]}"; do
    repo="$ADMIN_PROJECT-$service"
    if [[ -n "$(image_id "$repo:pre-rename")" ]]; then docker tag "$repo:pre-rename" "$repo:latest"; else tagged=0; fi
  done
  if ((tagged)); then
    docker compose --project-name "$ADMIN_PROJECT" --env-file "$ENV_NAME" -f docker-compose.transport-admin.yml \
      up -d --no-build --force-recreate
  else
    echo "pre-rename 태그가 없다(admin 단계 전). 관리 스택은 $OLD_DIR에서 돌던 그대로다."
  fi

  say "6. crontab 줄 되돌림"
  if [[ -s "$WORK_DIR/crontab.removed" ]]; then
    local current
    current="$(mktemp "$WORK_DIR/crontab.rollback.XXXXXX")"
    crontab -l > "$current" 2>/dev/null || :
    while IFS= read -r line; do
      grep -qxF -- "$line" "$current" || printf '%s\n' "$line" >> "$current"
    done < "$WORK_DIR/crontab.removed"
    crontab "$current"
    rm -f -- "$current"
  fi

  say "7. 새 env fence(되돌린 동안 새 배포가 돌지 않게)"
  if [[ -f "$NEW_DIR/$ENV_NAME" ]]; then
    mv -- "$NEW_DIR/$ENV_NAME" "$NEW_DIR/$ENV_NAME.rolled-back-$(date -u +%Y%m%dT%H%M%SZ)"
  fi
  echo "rollback 완료. Manager는 이전 sha로 다시 설치한다(runbook)."
}

# ================================================================ status
cmd_status() {
  local project name
  for project in "$OLD_PROJECT" "$NEW_PROJECT" "$ADMIN_PROJECT"; do
    echo "## $project"
    for name in $(containers "$project" -a); do
      echo "$name running=$(insp "$T_RUNNING" "$name") health=$(insp "$T_HEALTH" "$name") restart=$(insp "$T_RESTART" "$name") workdir=$(insp "$T_WORKDIR" "$name")"
    done
  done
  echo "## dirs"
  ls -ld "$OLD_DIR" "$NEW_DIR" "$OLD_DIR".retired-* 2>&1 || :
  ls -l "$OLD_DIR/$ENV_NAME" "$OLD_DIR/$ENV_NAME".fenced-* "$NEW_DIR/$ENV_NAME" 2>&1 | awk '{print $1, $NF}' || :
  echo "## rollback tags"
  for name in backend code frontend gateway; do
    echo "$ROLLBACK_REPO:$name $(image_id "$ROLLBACK_REPO:$name" || echo '(없음)')"
  done
  echo "dagster-daemon(두 project): $(daemon_count)"
}

main() {
  local command="${1:-}"
  shift || :
  case "$command" in
    prepare) cmd_prepare "$@" ;;
    restore-point) cmd_restore_point ;;
    prebuild) cmd_prebuild "$@" ;;
    window) cmd_window "$@" ;;
    admin) cmd_admin ;;
    finish) cmd_finish ;;
    rollback) cmd_rollback ;;
    status) cmd_status ;;
    *) die "사용법: $0 {prepare <R>|restore-point|prebuild <R>|window <R>|admin|finish|rollback|status}" ;;
  esac
}

main "$@"
