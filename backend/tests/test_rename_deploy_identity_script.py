"""`scripts/rename-deploy-identity-server14.sh`가 가짜 n150 앞에서 fail-closed로 동작하는지 본다.

개명 cutover는 compose project·앱 디렉터리를 `kor-travel-airport`에서 `kor-travel-transport`로 옮긴다.
여기서 고정하는 것은 순서와 멈춤, 그리고 끝난 뒤의 상태다. 창은 옛 스택을 멈추기 전에 다시 빌드하고
Dagster gate를 다시 보며, 새 컨테이너가 그 gate를 통과한 이미지 층으로 떴는지 확인한다. 옛 daemon을 먼저
멈추고 run을 기다린다. env는 fence 직전에 다시 복사한다. 새 스택을 검증한 뒤에만 옛 컨테이너를
은퇴시킨다(daemon 삭제, 나머지는 restart=no로 이름 변경). 관리 스택은 빌드 없이 재생성하고 중간에
실패해도 다시 실행할 수 있다. rollback은 run을 기다리고, 디렉터리를 겹치지 않게 되돌리고, 고정
이미지로 재생성한다. 창이 끝나기 전에 멈추면(신호 포함) 옛 스택을 되살리고, `docker start`로 뜨지 않는
서비스는 rollback 태그로 재생성한다.
docker·curl·ss·pgrep·crontab·sudo는 가짜다(pgrep은 가짜 프로세스 목록에 진짜처럼 ERE를 건다). 앱·Manager
경로는 `RENAME_TEST_ROOT` 아래로 옮긴다. compose 파일은 JSON으로 쓰고, 가짜 compose가 셸 env >
`--env-file` 순으로 치환해 렌더링한다. 새 디렉터리의 `deploy-server14-remote.sh`는 가짜 배포다(진짜는
`/home/digitie/apps/kor-travel-transport`에서만 돈다). 진짜 배포 스크립트의 guard는
`test_deploy_server14_remote_guard.py`가 본다.
"""

from __future__ import annotations

import hashlib
import json
import os
import pty
import select
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_NAME = "rename-deploy-identity-server14.sh"
# 로컬 체크아웃은 `<repo>/scripts`, Docker 이미지는 `/app/scripts`(Dockerfile `COPY scripts /app/scripts`)다.
_SCRIPT = next(
    (
        candidate
        for candidate in (_BACKEND_ROOT / "scripts" / _SCRIPT_NAME, _BACKEND_ROOT.parent / "scripts" / _SCRIPT_NAME)
        if candidate.is_file()
    ),
    _BACKEND_ROOT.parent / "scripts" / _SCRIPT_NAME,
)

_OLD = "kor-travel-airport"
_NEW = "kor-travel-transport"
_ADMIN = "kor-travel-transport-admin"
_SERVICES = ("backend", "frontend", "dagster-code-server", "dagster-webserver", "dagster-daemon", "dagster-gateway")
_R = "a" * 12 + "b" * 28
_REL = f"kor-travel-transport-backend:rel-{_R[:12]}"
_STAMP_SUFFIX = "-retired-"
_APP_SECRET = "S3cret-app-pw"
_DAGSTER_SECRET = "S3cret-dagster-pw"
_CRON_OTHER = "15 3 * * * /home/digitie/bin/run-standalone-backup.sh geo_dagster"


def _sha(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


_BACKEND_IMG = _sha("backend pr44 delta")
_CODE_IMG = _sha("code-server")
_GONE_DAGSTER_IMG = _sha("c8b47811 gone")
_FRONTEND_IMG = _sha("frontend")
_GONE_GATEWAY_IMG = _sha("f9f648a9 gone")
_GATEWAY_LATEST_IMG = _sha("gateway latest")
_ADMIN_WEB_IMG = _sha("admin web")
_ADMIN_GATEWAY_IMG = _sha("admin dagster gateway")
_NGINX_IMG = _sha("nginx")
_PG_IMG = _sha("postgis 16")

_FAKE = r'''
import hashlib, json, os, re, sys
from pathlib import Path

state_path = Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text())
program = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps({"argv": [program, *args], "cwd": os.getcwd(),
                          "image_env": os.environ.get("BACKEND_RUNTIME_IMAGE")}) + "\n")

def save():
    state_path.write_text(json.dumps(state))

def fail(message, code=1):
    print(message, file=sys.stderr)
    sys.exit(code)

PORTS = {"backend": 14001, "frontend": 14002, "dagster-gateway": 14003, "dagster-webserver": 14004,
         "dagster-code-server": 14005, "transport-api-gateway": 12301, "transport-dagster-gateway": 12302,
         "transport-admin-web": 12305}

def resolve(ref):
    tags = state["tags"]
    if ref in tags:
        return tags[ref]
    if not ref.startswith("sha256:") and ":" not in ref.split("/")[-1] and ref + ":latest" in tags:
        return tags[ref + ":latest"]
    if re.fullmatch(r"sha256:[0-9a-f]{64}", ref) and (ref in tags.values() or ref in state.get("layers", {})):
        return ref  # 태그가 옮겨 가도 컨테이너가 쓰는 이미지는 ID로 남는다.
    return None

def label(container, key):
    return container["Labels"].get(key, "")

def running(service=None):
    return [c for c in state["containers"].values()
            if c["Running"] and (service is None or label(c, "com.docker.compose.service") == service)]

if program == "pgrep":
    # 진짜 `pgrep -fa`처럼 명령줄 전체를 ERE로 본다. 패턴의 POSIX 문자 클래스 때문에 grep -E로 맞춘다.
    import subprocess
    if args[:-1] != ["-fa"]:
        fail(f"fake pgrep: unsupported flags {args[:-1]}", 2)
    processes = state["processes"]
    found = subprocess.run(["grep", "-nE", "--", args[-1]], input="".join(cmd + "\n" for _, cmd in processes),
                           capture_output=True, text=True)
    if found.returncode > 1:
        fail(f"pgrep: {found.stderr.strip()}", 2)
    hits = [processes[int(line.split(":", 1)[0]) - 1] for line in found.stdout.splitlines()]
    for pid, cmd in hits:
        print(pid, cmd)
    sys.exit(0 if hits else 1)

if program == "crontab":
    path = Path(os.environ["FAKE_CRONTAB"])
    if args == ["-l"]:
        if not path.exists():
            fail("no crontab for digitie")
        sys.stdout.write(path.read_text())
        sys.exit(0)
    path.write_text(sys.stdin.read() if args == ["-"] else Path(args[0]).read_text())
    sys.exit(0)

if program == "ss":
    port = int(args[-1].rsplit(":", 1)[1])
    for container in running():
        if PORTS.get(label(container, "com.docker.compose.service")) == port:
            print(f"LISTEN 0 4096 127.0.0.1:{port} 0.0.0.0:*")
    sys.exit(0)

if program == "curl":
    data = out = url = None
    i = 0
    while i < len(args):
        if args[i] in ("-d", "-o", "-H", "-m"):
            data = args[i + 1] if args[i] == "-d" else data
            out = args[i + 1] if args[i] == "-o" else out
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            url, i = args[i], i + 1
    port = int(re.match(r"https?://[^:/]+:(\d+)", url).group(1))
    by_port = {v: k for k, v in PORTS.items()}
    if not running(by_port[port]):
        fail(f"curl: (7) Failed to connect to 127.0.0.1 port {port}", 7)
    if url.endswith("/graphql"):
        if "runsOrError" in data:
            edit = state.get("env_edit_during_drain")
            if edit:  # 창이 run을 기다리는 동안 다른 세션이 옛 env를 고친다(critique M1).
                with open(edit["path"], "a") as handle:
                    handle.write(edit["line"])
                state["env_edit_during_drain"] = None
                save()
            body = {"runsOrError": {"__typename": "Runs", "results": state["runs"]}}
        else:
            nodes = []
            code = running("dagster-code-server")
            if code:
                schedules = state["schedules"]
                if state.get("new_schedules") and label(code[0], "com.docker.compose.project") == "kor-travel-transport":
                    schedules = state["new_schedules"]
                nodes = [{"name": "__repository__", "location": {"name": "kor-travel-transport"},
                          "schedules": [{"name": n, "scheduleState": {"status": s}} for n, s in schedules]}]
            body = {"repositoriesOrError": {"__typename": "RepositoryConnection", "nodes": nodes}}
        print(json.dumps({"data": body}))
        sys.exit(0)
    body = "ok"
    if port == 14001:
        env = running("backend")[0]["Env"]
        sha = next((e.split("=", 1)[1] for e in env if e.startswith("RELEASE_SHA=")), "unknown")
        body = json.dumps({"status": "ok", "release_sha": sha}, separators=(",", ":"))
    if out is None:
        print(body)
    sys.exit(0)

if program != "docker":
    fail(f"fake: unknown program {program}", 2)

TEMPLATES = {
    "{{.Id}}": lambda c: c["Id"],
    "{{.Image}}": lambda c: c["Image"],
    "{{.Config.Image}}": lambda c: c["ConfigImage"],
    "{{.State.Running}}": lambda c: str(c["Running"]).lower(),
    "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}": lambda c: c.get("Health") or "none",
    '{{index .Config.Labels "com.docker.compose.service"}}': lambda c: label(c, "com.docker.compose.service"),
    '{{index .Config.Labels "com.docker.compose.project.working_dir"}}':
        lambda c: label(c, "com.docker.compose.project.working_dir"),
    '{{index .Config.Labels "com.docker.compose.config-hash"}}': lambda c: label(c, "com.docker.compose.config-hash"),
    "{{.HostConfig.Init}}": lambda c: "<nil>" if c.get("Init") is None else str(c["Init"]).lower(),
    "{{.HostConfig.RestartPolicy.Name}}": lambda c: c.get("Restart", "no"),
    "{{range .Mounts}}{{.Source}}:{{.Destination}}{{println}}{{end}}": lambda c: "".join(m + "\n" for m in c["Mounts"]),
}

def load_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip("'\"")
    return values

def render(env_file, files, project):
    file_env = load_env(env_file)
    def substitute(match):
        name, op, default = match.group(1), match.group(2) or "", match.group(3) or ""
        value = os.environ.get(name, file_env.get(name, ""))
        if value:
            return value
        if op == ":?":
            fail(f"required variable {name} is missing a value: {default}")
        return default
    config = {"name": project, "services": {}}
    for path in files:
        doc = json.loads(re.sub(r"\$\{(\w+)(?:(:-|:\?)([^}]*))?\}", substitute, Path(path).read_text()))
        for name, spec in doc.get("services", {}).items():
            config["services"].setdefault(name, {}).update(spec)
        if doc.get("networks"):
            config["networks"] = doc["networks"]
    return config

def image_ref(project, name, spec):
    return spec.get("image") or f"{project}-{name}"

def build(project, name, spec):
    ref = image_ref(project, name, spec)
    ref = ref if ":" in ref.split("/")[-1] else ref + ":latest"
    # containerd image store처럼: 빌드마다 config 생성 시각이 바뀌어 이미지 ID는 늘 새로 나온다. 층은 입력
    # (렌더링한 build 절, 곧 env에서 온 build arg 포함)이 같으면 같다(cache hit). salt는 빌드 캐시가 비어
    # 다시 빌드된 경우(pip·apt 층이 새로 만들어진다)를 흉내 낸다.
    salt = state.get("build_salt", "") + os.environ.get("FAKE_BUILD_SALT", "")
    inputs = json.dumps(spec.get("build"), sort_keys=True)
    layer = "sha256:" + hashlib.sha256(f"layer {project}/{name}/{ref}{inputs}{salt}".encode()).hexdigest()
    image = "sha256:" + hashlib.sha256(f"{layer} created {os.urandom(8).hex()}".encode()).hexdigest()
    state.setdefault("layers", {})[image] = [layer]
    state["tags"][ref] = image

command = args[0]
if command == "compose":
    options, files, rest = {}, [], args[1:]
    while rest and rest[0].startswith("-"):
        flag, value, rest = rest[0], rest[1], rest[2:]
        if flag == "-f":
            files.append(value)
        else:
            options[flag] = value
    project = options["--project-name"]
    for path in files:
        if not Path(path).is_file():
            fail(f"open {path}: no such file or directory", 14)
    config = render(options["--env-file"], files, project)
    sub, rest = rest[0], rest[1:]
    if sub == "config":
        if rest == ["-q"]:
            sys.exit(0)
        if rest == ["--format", "json"]:
            print(json.dumps(config))
            sys.exit(0)
        fail(f"fake compose config {rest}", 2)
    if sub == "build":
        for name in rest:
            build(project, name, config["services"][name])
        save()
        sys.exit(0)
    if sub == "up":
        flags = [a for a in rest if a.startswith("-")]
        names = [a for a in rest if not a.startswith("-")] or list(config["services"])
        assert "-d" in flags, rest
        for name in names:
            spec = config["services"][name]
            if spec.get("restart") == "no":
                continue  # 한 번만 도는 migrate 계열
            if "--build" in flags and "build" in spec:
                build(project, name, spec)
            ref = image_ref(project, name, spec)
            image = resolve(ref)
            if image is None:
                fail(f"Error response from daemon: No such image: {ref}")
            for other in [n for n, c in state["containers"].items()
                          if label(c, "com.docker.compose.project") == project and label(c, "com.docker.compose.service") == name]:
                del state["containers"][other]
            if state.get("fail_up_at") == name:  # --force-recreate가 옛 컨테이너를 지운 뒤 실패한 경우
                state["fail_up_at"] = None
                save()
                fail(f"Error response from daemon: failed to create {project}-{name}-1")
            cwd = os.getcwd()
            state["containers"][f"{project}-{name}-1"] = {
                "Id": os.urandom(32).hex(), "Image": image, "ConfigImage": ref,
                "Labels": {"com.docker.compose.project": project, "com.docker.compose.service": name,
                           "com.docker.compose.project.working_dir": cwd,
                           "com.docker.compose.config-hash": hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()},
                "Env": [f"{k}={v}" for k, v in spec.get("environment", {}).items()],
                "Running": True, "Health": "healthy" if "healthcheck" in spec else None,
                "Init": spec.get("init"), "Restart": spec.get("restart", "no"),
                "Mounts": [os.path.normpath(os.path.join(cwd, v.split(":")[0])) + ":" + v.split(":")[1]
                           for v in spec.get("volumes", [])],
            }
        save()
        sys.exit(0)
    fail(f"fake compose: unsupported {sub}", 2)

containers = state["containers"]
if command == "ps":
    everything, quiet = "-a" in args, "-q" in args
    labels = [args[i + 1].split("=", 1)[1] for i, a in enumerate(args) if a == "--filter"]
    if not quiet and args[args.index("--format") + 1] != "{{.Names}}":
        fail("fake docker ps: unsupported format", 2)
    if state.get("fail_ps_filters") and all(f in labels for f in state["fail_ps_filters"]):
        fail("Cannot connect to the Docker daemon at unix:///var/run/docker.sock")
    for name, c in containers.items():
        if (everything or c["Running"]) and all(label(c, l.split("=", 1)[0]) == l.split("=", 1)[1] for l in labels):
            print(c["Id"][:12] if quiet else name)
elif command == "inspect":
    template, name = args[2], args[3]
    if name not in containers:
        fail(f"Error: No such object: {name}")
    if template not in TEMPLATES:
        fail(f"fake docker: unsupported inspect format {template}", 2)
    print(TEMPLATES[template](containers[name]))
elif command == "image":
    image = resolve(args[-1])
    if image is None:
        fail(f"Error: No such image: {args[-1]}")
    if args[3] == "{{json .RootFS.Layers}}":
        default = ["sha256:" + hashlib.sha256(f"layer of {image}".encode()).hexdigest()]
        print(json.dumps(state.get("layers", {}).get(image, default)))
    elif args[3] == "{{.Id}}":
        print(image)
    else:
        fail(f"fake docker: unsupported image inspect format {args[3]}", 2)
elif command == "tag":
    image = resolve(args[1])
    if image is None:
        fail(f"Error response from daemon: No such image: {args[1]}")
    state["tags"][args[2]] = image
    save()
elif command in ("stop", "start"):
    for name in args[1:]:
        if name not in containers:
            fail(f"Error response from daemon: No such container: {name}")
        # 돌던 이미지가 store에서 지워진 컨테이너를 start가 거부하는 경우(n150에서 확인하지 못한 동작).
        if command == "start" and state.get("start_needs_image") and containers[name]["Image"] not in state["tags"].values():
            fail(f"Error response from daemon: No such image: {containers[name]['Image']}")
        containers[name]["Running"] = command == "start"
        if command == "stop" and state.get("break_sudo_find_on_stop"):  # 중단이 시작된 뒤에야 find가 실패한다.
            Path(os.environ["FAKE_SUDO_FIND_BROKEN"]).touch()
    save()
elif command == "rm":
    if containers[args[1]]["Running"]:
        fail("cannot remove a running container")
    del containers[args[1]]
    save()
elif command == "rename":
    if args[2] in containers:
        fail("Conflict. The container name is already in use")
    containers[args[2]] = containers.pop(args[1])
    save()
elif command == "update":
    assert args[1] == "--restart=no", args
    containers[args[2]]["Restart"] = "no"
    save()
elif command == "run":
    rest, mounts, envs, entry = args[1:], {}, [], None
    while rest[0].startswith("-"):
        if rest[0] in ("--rm", "-i"):
            rest = rest[1:]
            continue
        flag, value, rest = rest[0], rest[1], rest[2:]
        if flag == "-v":
            parts = value.split(":")
            mounts[parts[1]] = parts[0]
        elif flag == "-e":
            envs.append(value)
        elif flag == "--entrypoint":
            entry = value
    image, argv = rest[0], rest[1:]
    if entry == "sh":
        sys.stdout.write(state["migrations"][resolve(image)])
        sys.exit(0)
    if entry == "python":
        print(state["dagster"].get(resolve(image), state["dagster_built"]))
        sys.exit(0)
    if image != state["pg_image"]:
        fail(f"fake: unexpected PostgreSQL client image {image}", 2)
    passfile = mounts.get("/run/secrets/pgpass")
    if "PGPASSFILE=/run/secrets/pgpass" not in envs or not passfile or not Path(passfile).is_file():
        fail("fake: PostgreSQL client without the passfile", 2)
    if os.stat(passfile).st_mode & 0o777 != 0o600:
        fail("fake: passfile is not 0600", 2)
    def host(path):
        for inner, outer in mounts.items():
            if path.startswith(inner + "/"):
                return outer + path[len(inner):]
        fail(f"fake: unmounted path {path}", 2)
    if argv[0] == "pg_dump":
        if state.get("fail_pg_dump"):
            fail("pg_dump: error: connection to server failed")
        Path(host(argv[argv.index("-f") + 1])).write_bytes(b"PGDMP" + argv[-1].encode())
    elif argv[0] == "pg_restore":
        data = Path(host(argv[-1])).read_bytes()
        if state.get("fail_pg_restore") or not data.startswith(b"PGDMP"):
            fail("pg_restore: error: input file does not appear to be a valid archive")
        print(";\n; Archive created at 2026-09-28\n3401; 0 16390 TABLE DATA public airports app\n3402; 0 16391 TABLE DATA public runs app")
    elif argv[0] == "psql":
        print(state["db_revision"])
    else:
        fail(f"fake docker run: unsupported {argv}", 2)
else:
    fail(f"fake docker: unsupported command {args}", 2)
'''

_DEPLOY_STUB = """#!/usr/bin/env bash
# 가짜 deploy-server14-remote.sh: 진짜처럼 개명 전 project가 돌면 거부하고, release 태그를 셸 env로 준다.
set -euo pipefail
printf '%s %s\\n' "$(pwd -P)" "${CANDIDATE_SHA}" >> "$FAKE_DEPLOY_LOG"
if [[ -n "$(docker ps -q --filter label=com.docker.compose.project=kor-travel-airport)" ]]; then
  echo "Refusing n150 deployment: the pre-rename project still runs containers" >&2
  exit 2
fi
export BACKEND_RUNTIME_IMAGE="kor-travel-transport-backend:rel-${CANDIDATE_SHA:0:12}"
export RELEASE_SHA="$CANDIDATE_SHA"
runtime="$(mktemp ./.env.server14.runtime.XXXXXX)"
trap 'rm -f "$runtime"' EXIT
{ awk '!/^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE)=/' .env.server14; printf 'RELEASE_SHA=%s\\n' "$CANDIDATE_SHA"; } > "$runtime"
# 창 전 재빌드와 이 `up --build` 사이에 빌드 캐시가 빈 경우: 다른 이미지가 빌드된다.
[[ "${FAKE_DEPLOY:-ok}" != rebuild-differs ]] || export FAKE_BUILD_SALT=evicted-during-window
docker compose --project-name kor-travel-transport --env-file "$runtime" -f docker-compose.yml -f docker-compose.shared.yml up -d --build
[[ "${FAKE_DEPLOY:-ok}" != fail-after-up ]] || { echo "fake deploy failed after up" >&2; exit 1; }
# 창 안에서 다른 세션이 옛 daemon을 이름으로 띄운 경우(critique H1).
[[ "${FAKE_DEPLOY:-ok}" != start-old-daemon ]] || docker start kor-travel-airport-dagster-daemon-1 >/dev/null
"""

_HEALTH = {"test": ["CMD", "probe"]}


def _shared_compose(project: str) -> str:
    image = "${BACKEND_RUNTIME_IMAGE:-" + project + "-backend:latest}"
    dagster_env = {"DAGSTER_POSTGRES_URL": "${DAGSTER_POSTGRES_URL:?set the Dagster DSN}"}
    services: dict[str, Any] = {
        "backend": {
            "image": image,
            "build": {"context": "."},
            "restart": "unless-stopped",
            "healthcheck": _HEALTH,
            "environment": {"DATABASE_URL": "${DATABASE_URL:?set the app DSN}", "RELEASE_SHA": "${RELEASE_SHA:-unknown}"},
            "volumes": ["./backups:/app/backups"],
        },
        "migrate": {"image": image, "restart": "no"},
        "dagster-migrate": {"image": image, "restart": "no"},
        "dagster-gateway": {"build": {"context": "."}, "restart": "unless-stopped"},
        # 진짜 compose처럼 frontend build arg는 env에서 온다.
        "frontend": {
            "build": {"context": ".", "args": {"NEXT_PUBLIC_API_PORT": "${NEXT_PUBLIC_API_PORT:-8000}"}},
            "restart": "unless-stopped",
            "healthcheck": _HEALTH,
        },
    }
    for name in ("dagster-code-server", "dagster-webserver", "dagster-daemon"):
        services[name] = {
            "image": image,
            "restart": "unless-stopped",
            "init": True,
            "healthcheck": _HEALTH,
            "environment": dict(dagster_env),
        }
    return json.dumps({"services": services}, indent=2) + "\n"


_ADMIN_COMPOSE = json.dumps(
    {
        "services": {
            "transport-api-gateway": {
                "image": "nginx:1.27-alpine",
                "restart": "unless-stopped",
                "healthcheck": _HEALTH,
                "volumes": [
                    "./deploy/transport-admin/api-gateway.conf.template:/etc/nginx/templates/default.conf.template:ro"
                ],
            },
            "transport-dagster-gateway": {"build": {"context": "."}, "restart": "unless-stopped", "healthcheck": _HEALTH},
            "transport-admin-web": {
                "build": {"context": "."},
                "restart": "unless-stopped",
                "healthcheck": _HEALTH,
                "environment": {"TRANSPORT_UI_PASSWORD": "${TRANSPORT_UI_PASSWORD:?set the admin password}"},
            },
        }
    },
    indent=2,
)

_MIGRATIONS = {
    "0014_kric_timetables.py": 'revision = "0014_kric_timetables"\ndown_revision = "0013_ferry_timetable_snapshots"\n',
    "0015_fuel_statistics_priced.py": (
        'revision = "0015_fuel_statistics_priced"\ndown_revision = "0014_kric_timetables"\n\n'
        "def upgrade():\n    pass\n"
    ),
}


def _migration_listing(files: dict[str, str]) -> str:
    """스크립트가 운영 이미지에서 읽는 형식: `파일 sha256(CRLF 제외)`, 파일 이름 C 순서."""
    return "".join(
        f"{name} {hashlib.sha256(text.replace(chr(13), '').encode()).hexdigest()}\n" for name, text in sorted(files.items())
    )


def _old_container(project: str, service: str, image: str, config_image: str, workdir: Path, **extra: Any) -> dict[str, Any]:
    return {
        "Id": hashlib.sha256(f"{project}/{service}".encode()).hexdigest(),
        "Image": image,
        "ConfigImage": config_image,
        "Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.service": service,
            "com.docker.compose.project.working_dir": str(workdir),
            "com.docker.compose.config-hash": "old",
        },
        "Env": extra.pop("Env", []),
        "Running": True,
        "Health": extra.pop("Health", "healthy"),
        "Init": None,
        "Restart": "unless-stopped",
        "Mounts": extra.pop("Mounts", []),
        **extra,
    }


class Host:
    """가짜 n150: 두 앱 디렉터리, 작업 디렉터리, docker 등 가짜 명령, 컨테이너·이미지 상태."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        apps = root / "apps"
        apps.mkdir()
        self.old = apps / _OLD
        self.new = apps / _NEW
        self.work = self.home / "transport-rename"
        self.bin = root / "bin"
        self.bin.mkdir()
        self.state_path = root / "state.json"
        self.log_path = root / "calls.jsonl"
        self.log_path.touch()
        self.deploy_log = root / "deploy.log"
        self.crontab = root / "crontab"
        fake = self.bin / "fake.py"
        # `-S`: 가짜 명령은 표준 라이브러리만 쓴다. site-packages를 읽지 않아 호출마다 시작이 빠르다.
        fake.write_text(f"#!{sys.executable} -S\n{_FAKE}", encoding="utf-8")
        fake.chmod(0o755)
        for name in ("docker", "curl", "ss", "pgrep", "crontab"):
            (self.bin / name).symlink_to(fake)
        sudo = self.bin / "sudo"
        # `self.sudo_find_broken`가 있으면 `sudo -n find`가 실패한다(권한·I/O 오류로 끝난 find).
        self.sudo_find_broken = root / "sudo-find-broken"
        sudo.write_text(
            '#!/bin/sh\n[ "$1" = -n ] && shift\n'
            'if [ "$1" = find ] && [ -e "$FAKE_SUDO_FIND_BROKEN" ]; then\n'
            '  echo "find: \'$2\': Input/output error" >&2\n  exit 1\nfi\n'
            'exec "$@"\n',
            encoding="utf-8",
        )
        sudo.chmod(0o755)
        manager = root / "ktdm-release-e25f105"
        manager.mkdir()
        self.manager_link = root / "kor-travel-docker-manager"
        self.manager_link.symlink_to(manager)
        self._write_old_dir()
        self.crontab.write_text(
            'MAILTO=""\n'
            f"0 18 */3 * * {self.old}/scripts/n150-backup-cron.sh >> {self.old}/backups/cron.log 2>&1\n"
            f"{_CRON_OTHER}\n",
            encoding="utf-8",
        )
        self.write_state(self._initial_state())

    # ------------------------------------------------------------------ fixtures
    def _write_old_dir(self) -> None:
        old = self.old
        (old / "backups").mkdir(parents=True)
        for name in ("parking-radar-20260905T230044Z.dump", "pre-kric-20260927T055443Z.dump"):
            (old / "backups" / name).write_bytes(b"PGDMP old backup")
        (old / "scripts").mkdir()
        (old / "scripts" / "n150-backup-cron.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (old / "docker-compose.yml").write_text('{"services": {}}\n', encoding="utf-8")
        (old / "docker-compose.shared.yml").write_text(_shared_compose(_OLD), encoding="utf-8")
        (old / "docker-compose.transport-admin.yml").write_text(_ADMIN_COMPOSE, encoding="utf-8")
        (old / "deploy" / "transport-admin").mkdir(parents=True)
        (old / "deploy" / "transport-admin" / "api-gateway.conf.template").write_text("# old\n", encoding="utf-8")
        (old / ".release-sha").write_text("0d7d2929" + "0" * 32 + "\n", encoding="utf-8")
        (old / ".transport-admin-release-sha").write_text("3b6d2201" + "0" * 32 + "\n", encoding="utf-8")
        env = old / ".env.server14"
        env.write_text(
            "RELEASE_SHA=0d7d292900000000000000000000000000000000\n"
            f"BACKEND_RUNTIME_IMAGE={_BACKEND_IMG}\n"
            f"DATABASE_URL=postgresql+asyncpg://kor_travel_transport_app:{_APP_SECRET}@127.0.0.1:11000/kor_travel_transport\n"
            f"DAGSTER_POSTGRES_URL=postgresql+psycopg2://kor_travel_transport_dagster:{_DAGSTER_SECRET}"
            "@127.0.0.1:11000/kor_travel_transport_dagster\n"
            "KRIC_SERVICE_KEY='quoted key value'\n"
            "TRANSPORT_UI_PASSWORD=admin-pw\n"
            "AIRPORT_CODES_CSV=GMP,PUS,CJU,ICN\n",
            encoding="utf-8",
        )
        env.chmod(0o600)

    def _initial_state(self) -> dict[str, Any]:
        old, containers = self.old, {}
        images = {
            "backend": (_BACKEND_IMG, _BACKEND_IMG),
            "dagster-code-server": (_CODE_IMG, _CODE_IMG),
            # n150 2026-09-28: webserver·daemon·gateway가 돌리는 이미지는 store에서 지워졌다.
            "dagster-webserver": (_GONE_DAGSTER_IMG, f"{_OLD}-backend:latest"),
            "dagster-daemon": (_GONE_DAGSTER_IMG, f"{_OLD}-backend:latest"),
            "dagster-gateway": (_GONE_GATEWAY_IMG, f"{_OLD}-dagster-gateway"),
            "frontend": (_FRONTEND_IMG, f"{_OLD}-frontend"),
        }
        for service, (image, config_image) in images.items():
            extra: dict[str, Any] = {}
            if service == "backend":
                extra = {"Mounts": [f"{old}/backups:/app/backups"], "Env": ["RELEASE_SHA=0d7d2929"]}
            containers[f"{_OLD}-{service}-1"] = _old_container(_OLD, service, image, config_image, old, **extra)
        admin_images = {
            "transport-admin-web": (_ADMIN_WEB_IMG, f"{_ADMIN}-transport-admin-web"),
            "transport-api-gateway": (_NGINX_IMG, "nginx:1.27-alpine"),
            "transport-dagster-gateway": (_ADMIN_GATEWAY_IMG, f"{_ADMIN}-transport-dagster-gateway"),
        }
        for service, (image, config_image) in admin_images.items():
            mounts = []
            if service == "transport-api-gateway":
                mounts = [f"{old}/deploy/transport-admin/api-gateway.conf.template:/etc/nginx/templates/default.conf.template"]
            containers[f"{_ADMIN}-{service}-1"] = _old_container(_ADMIN, service, image, config_image, old, Mounts=mounts)
        shared_pg = _old_container("kor-travel-docker-manager", "postgres", _PG_IMG, "postgis/postgis:16-3.5", self.root)
        containers["kor-travel-shared-postgres"] = shared_pg
        return {
            "containers": containers,
            "tags": {
                "local/transport-pr44:delta": _BACKEND_IMG,
                "local/transport-pr42:coordinates": _CODE_IMG,
                f"{_OLD}-backend:latest": _sha("airport backend latest"),
                f"{_OLD}-frontend:latest": _FRONTEND_IMG,
                f"{_OLD}-dagster-gateway:latest": _GATEWAY_LATEST_IMG,
                f"{_ADMIN}-transport-admin-web:latest": _ADMIN_WEB_IMG,
                f"{_ADMIN}-transport-dagster-gateway:latest": _ADMIN_GATEWAY_IMG,
                "nginx:1.27-alpine": _NGINX_IMG,
                "postgis/postgis:16-3.5": _PG_IMG,
            },
            "runs": [],
            # `pgrep -fa`가 보는 n150 프로세스. 빌드가 아닌 것만 있다. `--no-build` 재생성과 이 cutover
            # 자신은 빌드 확인에 걸리지 않아야 한다.
            "processes": [
                [812, "/usr/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock"],
                [2210, f"docker compose --project-name {_ADMIN} --env-file .env.server14 "
                       "-f docker-compose.transport-admin.yml up -d --no-build --force-recreate"],
                [3301, f"bash /home/digitie/rename-deploy-identity-server14.sh window {_R}"],
            ],
            "schedules": [
                ["airport_collection_job_schedule", "RUNNING"],
                ["ferry_timetable_collection_job_schedule", "RUNNING"],
                ["fuel_collection_job_schedule", "STOPPED"],
            ],
            "migrations": {_BACKEND_IMG: _migration_listing(_MIGRATIONS)},
            "db_revision": "0015_fuel_statistics_priced",
            # 2026-09-28 n150: code-server는 1.13.24다(uv.lock·CI는 1.13.23이지만 이미지 빌드는 PyPI 최신을 받는다).
            "dagster": {_CODE_IMG: "1.13.24"},
            "dagster_built": "1.13.24",
            "pg_image": "postgis/postgis:16-3.5",
        }

    def stage(self, migrations: dict[str, str] | None = None) -> None:
        """WSL의 `DEPLOY_STAGE_ONLY=true scripts/deploy-server14.sh`가 새 디렉터리에 R을 올린 상태."""
        new = self.new
        (new / "scripts").mkdir(parents=True, exist_ok=True)
        deploy = new / "scripts" / "deploy-server14-remote.sh"
        deploy.write_text(_DEPLOY_STUB, encoding="utf-8")
        deploy.chmod(0o755)
        (new / "docker-compose.yml").write_text('{"services": {}}\n', encoding="utf-8")
        (new / "docker-compose.shared.yml").write_text(_shared_compose(_NEW), encoding="utf-8")
        (new / "docker-compose.transport-admin.yml").write_text(_ADMIN_COMPOSE, encoding="utf-8")
        (new / "deploy" / "transport-admin").mkdir(parents=True, exist_ok=True)
        (new / "deploy" / "transport-admin" / "api-gateway.conf.template").write_text("# new\n", encoding="utf-8")
        versions = new / "backend" / "alembic" / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        # Windows autocrlf checkout의 git archive처럼 CRLF로 올라온다.
        for name, text in (migrations or _MIGRATIONS).items():
            (versions / name).write_bytes(text.replace("\n", "\r\n").encode())
        (new / ".release-sha").write_text(_R + "\n", encoding="utf-8")

    # ------------------------------------------------------------------ plumbing
    def env(self, **extra: str) -> dict[str, str]:
        return {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.home),
            "LC_ALL": "C.UTF-8",
            # 앱 디렉터리는 <root>/apps/{kor-travel-airport,kor-travel-transport}, Manager 링크는
            # <root>/kor-travel-docker-manager, 작업 디렉터리는 $HOME/transport-rename이다.
            "RENAME_TEST_ROOT": str(self.root),
            "FAKE_STATE": str(self.state_path),
            "FAKE_LOG": str(self.log_path),
            "FAKE_CRONTAB": str(self.crontab),
            "FAKE_DEPLOY_LOG": str(self.deploy_log),
            "FAKE_SUDO_FIND_BROKEN": str(self.sudo_find_broken),
            "DRAIN_TIMEOUT_SECONDS": "5",
            "DRAIN_POLL_SECONDS": "0",
            "HEALTH_TIMEOUT_SECONDS": "3",
            "HEALTH_POLL_SECONDS": "0",
            **extra,
        }

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(_SCRIPT), *args],
            cwd=self.home,
            env=self.env(**env),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def ok(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        result = self.run(*args, **env)
        assert result.returncode == 0, f"{args}\n{result.stdout}\n{result.stderr}"
        return result

    def state(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_state(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def update_state(self, **changes: Any) -> None:
        self.write_state({**self.state(), **changes})

    def calls(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def clear_log(self) -> None:
        self.log_path.write_text("", encoding="utf-8")

    def containers(self, project: str) -> dict[str, dict[str, Any]]:
        return {
            name: c
            for name, c in self.state()["containers"].items()
            if c["Labels"]["com.docker.compose.project"] == project
        }

    def running_daemons(self) -> list[str]:
        return [
            name
            for name, c in self.state()["containers"].items()
            if c["Running"] and c["Labels"]["com.docker.compose.service"] == "dagster-daemon"
        ]

    def stamp(self) -> str:
        return (self.work / "stamp").read_text(encoding="utf-8").strip()

    def ready_for_window(self) -> None:
        self.ok("prepare", _R)
        self.stage()
        self.ok("prebuild", _R)
        self.clear_log()


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def _filtered(env_text: str) -> str:
    return "".join(
        line + "\n"
        for line in env_text.splitlines()
        if not line.startswith(("RELEASE_SHA=", "BACKEND_RUNTIME_IMAGE="))
    )


def _index(calls: list[dict[str, Any]], prefix: list[str], *, after: int = -1) -> int:
    return next(i for i, call in enumerate(calls) if i > after and call["argv"][: len(prefix)] == prefix)


def _recorded(host: Host) -> dict[str, tuple[str, str]]:
    """`release-images`: 역할 → (층 지문, 기록할 때의 이미지 ID)."""
    rows = (host.work / "release-images").read_text(encoding="utf-8").splitlines()
    return {role: (layers, image) for role, layers, image in (row.split() for row in rows)}


def _layers(host: Host, image: str) -> list[str]:
    return host.state()["layers"][image]


def _assert_no_secret_leaked(host: Host, *results: subprocess.CompletedProcess[str]) -> None:
    logged = host.log_path.read_text(encoding="utf-8")
    for secret in (_APP_SECRET, _DAGSTER_SECRET, "admin-pw", "quoted key value"):
        assert secret not in logged
        for result in results:
            assert secret not in result.stdout + result.stderr


# ====================================================================== 전체 흐름


def test_cutover_runs_in_order_and_rolls_back_without_nesting(host: Host) -> None:
    prepared = host.ok("prepare", _R)
    new_env = host.new / ".env.server14"
    assert new_env.read_text(encoding="utf-8") == _filtered((host.old / ".env.server14").read_text(encoding="utf-8"))
    assert stat.S_IMODE(new_env.stat().st_mode) == 0o600
    assert stat.S_IMODE(host.new.stat().st_mode) == 0o700
    tags = host.state()["tags"]
    # 실행 중 이미지가 store에 없는 gateway는 compose 이미지 이름(:latest)으로 대신한다. daemon·webserver는 code로 되돌린다.
    assert {role: tags[f"kor-travel-airport-rollback:{role}"] for role in ("backend", "code", "frontend", "gateway")} == {
        "backend": _BACKEND_IMG,
        "code": _CODE_IMG,
        "frontend": _FRONTEND_IMG,
        "gateway": _GATEWAY_LATEST_IMG,
    }
    assert "compose 이미지 이름으로 대신한다" in prepared.stdout

    host.clear_log()
    restore_point = host.ok("restore-point")
    dumps = sorted(path.name for path in (host.work / "restore-point").glob("*.dump"))
    assert [name.rsplit("-", 1)[0] for name in dumps] == ["kor_travel_transport", "kor_travel_transport_dagster"]
    assert not list((host.work / "restore-point").glob("*.partial"))
    assert not list(host.work.glob(".pgpass.*"))  # 비밀번호 파일은 끝나면 지운다.
    dump_calls = [call["argv"] for call in host.calls() if call["argv"][:2] == ["docker", "run"] and "pg_dump" in call["argv"]]
    assert len(dump_calls) == 2
    assert all(argv[-1].startswith("postgresql://kor_travel_transport") and "@127.0.0.1:11000/" in argv[-1] for argv in dump_calls)
    _assert_no_secret_leaked(host, restore_point)

    host.stage()
    host.clear_log()
    host.ok("prebuild", _R)
    build = next(call for call in host.calls() if "build" in call["argv"] and call["argv"][1] == "compose")
    assert build["argv"][-3:] == ["backend", "frontend", "dagster-gateway"]
    assert build["image_env"] == _REL and build["cwd"] == str(host.new)

    # 창이 옛 daemon을 멈추고 run을 기다리는 동안 다른 세션이 옛 env를 고친다(critique M1). 창 전 재빌드의
    # env 사본 뒤의 편집이라 fence 직전 재복사만 이 편집을 가져간다.
    host.update_state(
        env_edit_during_drain={
            "path": str(host.old / ".env.server14"),
            "line": "FERRY_TIMETABLE_COLLECTION_INTERVAL_SECONDS=900\n",
        }
    )
    host.clear_log()
    window = host.ok("window", _R)
    calls = host.calls()
    stamp = host.stamp()

    stop_daemon = _index(calls, ["docker", "stop", f"{_OLD}-dagster-daemon-1"])
    drained = _index(calls, ["curl"], after=stop_daemon)
    stop_webserver = _index(calls, ["docker", "stop", f"{_OLD}-dagster-webserver-1"])
    up = next(i for i, call in enumerate(calls) if call["argv"][:2] == ["docker", "compose"] and "up" in call["argv"])
    retire = _index(calls, ["docker", "rm", f"{_OLD}-dagster-daemon-1"])
    assert stop_daemon < drained < stop_webserver < up < retire, [call["argv"] for call in calls]
    assert host.deploy_log.read_text(encoding="utf-8") == f"{host.new} {_R}\n"

    fenced = host.old / f".env.server14.fenced-{stamp}"
    assert not (host.old / ".env.server14").exists() and fenced.is_file()
    assert new_env.read_text(encoding="utf-8") == _filtered(fenced.read_text(encoding="utf-8"))
    assert "FERRY_TIMETABLE_COLLECTION_INTERVAL_SECONDS=900" in new_env.read_text(encoding="utf-8")
    assert sorted(p.name for p in (host.new / "backups").iterdir()) == sorted(p.name for p in (host.old / "backups").iterdir())

    rel_image = host.state()["tags"][_REL]
    # 재빌드마다 이미지 ID는 새로 나온다(containerd image store). 창 전 재빌드와 배포의 `up --build`는
    # 모두 cache hit이라 층이 같고, 검증은 층을 본다. 그래서 prebuild 뒤 바뀌었다는 주의도 없다.
    assert rel_image != _recorded(host)["release"][1]
    assert _layers(host, rel_image) == _layers(host, _recorded(host)["release"][1])
    assert "층이 바뀌었다" not in window.stdout
    new = host.containers(_NEW)
    assert sorted(c["Labels"]["com.docker.compose.service"] for c in new.values() if c["Running"]) == sorted(_SERVICES)
    for service in ("backend", "dagster-code-server", "dagster-webserver", "dagster-daemon"):
        assert new[f"{_NEW}-{service}-1"]["Image"] == rel_image, service
    for service in ("dagster-code-server", "dagster-webserver", "dagster-daemon"):
        assert new[f"{_NEW}-{service}-1"]["Init"] is True, service
    assert new[f"{_NEW}-backend-1"]["Mounts"] == [f"{host.new}/backups:/app/backups"]
    assert host.running_daemons() == [f"{_NEW}-dagster-daemon-1"]

    old = host.containers(_OLD)
    assert sorted(old) == sorted(f"{_OLD}-{s}-1-retired-{stamp}" for s in _SERVICES if s != "dagster-daemon")
    assert all(not c["Running"] and c["Restart"] == "no" for c in old.values())
    assert "창 완료" in window.stdout

    host.clear_log()
    host.ok("admin")
    admin_up = next(call for call in host.calls() if call["argv"][:2] == ["docker", "compose"] and "up" in call["argv"])
    assert admin_up["cwd"] == str(host.new)
    assert {"--no-build", "--force-recreate"} <= set(admin_up["argv"]) and "--build" not in admin_up["argv"]
    state = host.state()
    assert state["tags"][f"{_ADMIN}-transport-admin-web:pre-rename"] == _ADMIN_WEB_IMG
    assert state["tags"][f"{_ADMIN}-transport-dagster-gateway:pre-rename"] == _ADMIN_GATEWAY_IMG
    admin = host.containers(_ADMIN)
    assert {c["Labels"]["com.docker.compose.project.working_dir"] for c in admin.values()} == {str(host.new)}
    assert admin[f"{_ADMIN}-transport-admin-web-1"]["Image"] == _ADMIN_WEB_IMG
    assert admin[f"{_ADMIN}-transport-api-gateway-1"]["Mounts"][0].startswith(f"{host.new}/deploy/transport-admin/")
    assert (host.new / ".transport-admin-release-sha").read_text(encoding="utf-8").startswith("3b6d2201")

    host.ok("finish")
    retired = Path(f"{host.old}.retired-{stamp}")
    assert not host.old.exists() and (retired / ".env.server14.fenced-" f"{stamp}").is_file()
    crontab = host.crontab.read_text(encoding="utf-8")
    assert "n150-backup-cron.sh" not in crontab and _CRON_OTHER in crontab and 'MAILTO=""' in crontab

    # 옛 배포 스크립트의 `mkdir -p`와 옛 backend bind가 빈 OLD와 빈 backups를 다시 만든 상태(critique M4).
    (host.old / "backups").mkdir(parents=True)
    host.clear_log()
    rollback = host.ok("rollback")
    assert not retired.exists() and not (host.old / retired.name).exists()
    assert (host.old / ".env.server14").is_file() and (host.old / "backups" / "pre-kric-20260927T055443Z.dump").is_file()
    assert not (host.new / ".env.server14").exists() and list(host.new.glob(".env.server14.rolled-back-*"))
    assert not [c for c in host.containers(_NEW).values() if c["Running"]]
    old = host.containers(_OLD)
    assert sorted(old) == sorted(f"{_OLD}-{s}-1" for s in _SERVICES)
    expected_images = {
        "backend": _BACKEND_IMG,
        "dagster-code-server": _CODE_IMG,
        "dagster-webserver": _CODE_IMG,
        "dagster-daemon": _CODE_IMG,
        "frontend": _FRONTEND_IMG,
        "dagster-gateway": _GATEWAY_LATEST_IMG,
    }
    assert {s: old[f"{_OLD}-{s}-1"]["Image"] for s in _SERVICES} == expected_images
    assert all(c["Running"] and c["Restart"] == "unless-stopped" for c in old.values())
    calls = host.calls()
    # 새 daemon을 먼저 멈추고 run이 0인 것을 본 뒤에야 code-server 등 나머지를 멈춘다(critique 후속 LOW).
    new_daemon_stop = _index(calls, ["docker", "stop", f"{_NEW}-dagster-daemon-1"])
    drained = _index(calls, ["curl"], after=new_daemon_stop)
    new_code_stop = _index(calls, ["docker", "stop", f"{_NEW}-dagster-code-server-1"])
    assert new_daemon_stop < drained < new_code_stop, [call["argv"] for call in calls]
    old_ups = [
        call["argv"]
        for call in calls
        if call["argv"][:2] == ["docker", "compose"] and "up" in call["argv"] and _OLD in call["argv"]
    ]
    # daemon은 옛 스택의 마지막 up에서, 그 up에서만 띄운다(code-server가 healthy가 된 뒤).
    assert [argv for argv in old_ups if "dagster-daemon" in argv] == [old_ups[-1]]
    assert old_ups[-1][-2:] == ["--force-recreate", "dagster-daemon"]
    assert host.running_daemons() == [f"{_OLD}-dagster-daemon-1"]
    admin = host.containers(_ADMIN)
    assert {c["Labels"]["com.docker.compose.project.working_dir"] for c in admin.values()} == {str(host.old)}
    assert admin[f"{_ADMIN}-transport-admin-web-1"]["Image"] == _ADMIN_WEB_IMG
    assert host.crontab.read_text(encoding="utf-8").count("n150-backup-cron.sh") == 1
    _assert_no_secret_leaked(host, window, rollback)


# ====================================================================== 창 안의 멈춤


def test_window_restarts_the_old_daemon_when_runs_do_not_drain(host: Host) -> None:
    host.ready_for_window()
    host.update_state(runs=[{"runId": "f130efff", "jobName": "ferry_timetable_collection_job", "status": "STARTED"}])
    result = host.run("window", _R, DRAIN_TIMEOUT_SECONDS="0")

    assert result.returncode != 0
    assert "f130efff ferry_timetable_collection_job STARTED" in result.stderr
    calls = host.calls()
    assert _index(calls, ["docker", "stop", f"{_OLD}-dagster-daemon-1"]) < _index(
        calls, ["docker", "start", f"{_OLD}-dagster-daemon-1"]
    )
    assert not [c for c in calls if c["argv"][:2] == ["docker", "stop"] and "daemon" not in c["argv"][2]]
    assert not [c for c in calls if c["argv"][:2] == ["docker", "compose"] and "up" in c["argv"]]
    assert (host.old / ".env.server14").is_file()
    assert all(c["Running"] for c in host.containers(_OLD).values())
    assert not host.containers(_NEW)


def test_window_restores_the_old_stack_when_the_new_deploy_fails(host: Host) -> None:
    host.ready_for_window()
    result = host.run("window", _R, FAKE_DEPLOY="fail-after-up")

    assert result.returncode != 0
    assert "옛 스택으로 되돌렸다" in result.stderr
    calls = host.calls()
    # 새 daemon을 먼저 멈춘 뒤에야 옛 daemon을 띄운다. 두 daemon이 같은 metadata DB를 함께 쓰지 않는다.
    new_daemon_stop = _index(calls, ["docker", "stop", f"{_NEW}-dagster-daemon-1"])
    old_daemon_start = _index(calls, ["docker", "start", f"{_OLD}-dagster-daemon-1"])
    old_backend_start = _index(calls, ["docker", "start", f"{_OLD}-backend-1"])
    assert new_daemon_stop < old_backend_start < old_daemon_start
    assert not [c for c in host.containers(_NEW).values() if c["Running"]]
    assert all(c["Running"] for c in host.containers(_OLD).values())
    assert sorted(host.containers(_OLD)) == sorted(f"{_OLD}-{s}-1" for s in _SERVICES)  # 은퇴하지 않았다.
    assert (host.old / ".env.server14").is_file() and not list(host.old.glob(".env.server14.fenced-*"))
    assert host.running_daemons() == [f"{_OLD}-dagster-daemon-1"]


def _assert_restored(host: Host, result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode != 0
    assert "옛 스택으로 되돌렸다" in result.stderr
    assert not [c for c in host.containers(_NEW).values() if c["Running"]]
    assert sorted(host.containers(_OLD)) == sorted(f"{_OLD}-{s}-1" for s in _SERVICES)
    assert all(c["Running"] for c in host.containers(_OLD).values())
    assert (host.old / ".env.server14").is_file()
    assert host.running_daemons() == [f"{_OLD}-dagster-daemon-1"]


def test_window_restores_the_old_stack_when_schedule_states_changed(host: Host) -> None:
    # 새 webserver가 읽은 schedule 상태가 창 전과 다르면(다른 location·꺼진 schedule) 새 스택을 받지 않는다.
    host.ready_for_window()
    host.update_state(
        new_schedules=[
            ["airport_collection_job_schedule", "RUNNING"],
            ["ferry_timetable_collection_job_schedule", "RUNNING"],
            ["fuel_collection_job_schedule", "RUNNING"],
        ]
    )
    result = host.run("window", _R)
    _assert_restored(host, result)
    assert "schedule" in result.stderr


def test_window_restores_the_old_stack_when_a_second_daemon_appears(host: Host) -> None:
    host.ready_for_window()
    result = host.run("window", _R, FAKE_DEPLOY="start-old-daemon")
    _assert_restored(host, result)
    assert "dagster-daemon이 2개" in result.stderr


def test_window_stops_before_touching_anything_when_an_old_image_changed(host: Host) -> None:
    host.ready_for_window()
    state = host.state()
    state["containers"][f"{_OLD}-backend-1"]["Image"] = _sha("redeployed by another session")
    host.write_state(state)
    result = host.run("window", _R)

    assert result.returncode != 0 and "prepare부터 다시" in result.stderr
    assert not [c for c in host.calls() if c["argv"][:2] in (["docker", "stop"], ["docker", "compose"])]
    assert (host.old / ".env.server14").is_file()


@pytest.mark.parametrize(
    "command",
    [
        "docker compose --env-file /dev/null -f - build pinvi-web",
        # n150에 배포하는 저장소들의 표준 명령. 빌드 중에만 보이는 docker-buildx 프로세스가 없어도 잡는다.
        "docker compose --project-name kor-travel-weather --env-file .env.n150 -f compose.yaml up -d --build",
        "docker image build -t kor-travel-geo-api:rel-0123456789ab .",
        "/usr/libexec/docker/cli-plugins/docker-buildx buildx bake --file docker-bake.hcl",
    ],
)
def test_window_and_prebuild_wait_for_other_image_builds(host: Host, command: str) -> None:
    host.ready_for_window()
    host.update_state(processes=[*host.state()["processes"], [3438396, command]])
    for args in (("prebuild", _R), ("window", _R)):
        result = host.run(*args)
        assert result.returncode != 0 and "빌드" in result.stderr and command in result.stderr, args
    assert not [c for c in host.calls() if c["argv"][:2] in (["docker", "stop"], ["docker", "compose"])]


def test_window_refuses_a_second_run_after_the_cutover(host: Host) -> None:
    host.ready_for_window()
    host.ok("window", _R)
    host.clear_log()
    result = host.run("window", _R)
    assert result.returncode != 0 and "status" in result.stderr
    assert not [c for c in host.calls() if c["argv"][:2] in (["docker", "stop"], ["docker", "compose"], ["docker", "rm"])]


# ====================================================================== gate


def test_prebuild_refuses_a_release_whose_migrations_differ_from_production(host: Host) -> None:
    host.ok("prepare", _R)
    edited = {**_MIGRATIONS, "0015_fuel_statistics_priced.py": _MIGRATIONS["0015_fuel_statistics_priced.py"] + "# edited\n"}
    host.stage(edited)
    result = host.run("prebuild", _R)
    assert result.returncode != 0 and "migration" in result.stderr
    assert not [c for c in host.calls() if "build" in c["argv"]]

    host.stage()  # 같은 파일이지만 운영 DB는 아직 0014다.
    host.update_state(db_revision="0014_kric_timetables")
    result = host.run("prebuild", _R)
    assert result.returncode != 0 and "revision" in result.stderr


def test_prebuild_refuses_a_render_that_still_has_a_network(host: Host) -> None:
    host.ok("prepare", _R)
    host.stage()
    (host.new / "docker-compose.yml").write_text(
        '{"services": {}, "networks": {"kor-travel-transport-net": {}}}\n', encoding="utf-8"
    )
    host.clear_log()
    result = host.run("prebuild", _R)
    assert result.returncode != 0 and "network가 남았다" in result.stderr
    assert not [c for c in host.calls() if "build" in c["argv"]]


def test_prebuild_refuses_a_different_dagster_version(host: Host) -> None:
    host.ok("prepare", _R)
    host.stage()
    host.update_state(dagster_built="1.13.25")
    result = host.run("prebuild", _R)
    assert result.returncode != 0 and "dagster 버전이 다르다" in result.stderr
    assert not (host.work / "release-images").exists()  # gate를 통과하지 못한 빌드는 기록하지 않는다.
    window = host.run("window", _R)
    assert window.returncode != 0 and "prebuild" in window.stderr


def test_prepare_refuses_while_the_new_project_runs(host: Host) -> None:
    state = host.state()
    state["containers"][f"{_NEW}-backend-1"] = _old_container(_NEW, "backend", _BACKEND_IMG, _BACKEND_IMG, host.new)
    host.write_state(state)
    result = host.run("prepare", _R)
    assert result.returncode != 0 and "이미 실행 중" in result.stderr
    assert not host.new.exists()


def test_restore_point_keeps_no_dump_that_pg_restore_cannot_read(host: Host) -> None:
    host.ok("prepare", _R)
    host.update_state(fail_pg_restore=True)
    result = host.run("restore-point")
    assert result.returncode != 0 and "pg_restore" in result.stderr
    assert not list((host.work / "restore-point").glob("*.dump"))
    assert not list(host.work.glob(".pgpass.*"))


def test_rollback_refuses_to_move_the_retired_tree_into_a_non_empty_directory(host: Host) -> None:
    host.ready_for_window()
    host.ok("window", _R)
    host.ok("admin")
    host.ok("finish")
    retired = Path(f"{host.old}.retired-{host.stamp()}")
    host.old.mkdir()
    (host.old / ".env.server14").write_text("recreated by an old-branch deploy\n", encoding="utf-8")
    host.clear_log()
    result = host.run("rollback")

    assert result.returncode != 0 and "비어 있지 않다" in result.stderr
    assert (retired / ".env.server14.fenced-" f"{host.stamp()}").is_file()
    assert not (host.old / retired.name).exists()
    assert not [c for c in host.calls() if c["argv"][:2] in (["docker", "stop"], ["docker", "compose"])]


def test_rollback_refuses_when_no_cutover_is_in_progress(host: Host) -> None:
    # prepare만 한 상태에서 잘못 부르면 멀쩡히 도는 옛 스택을 재생성할 뿐이다.
    host.ok("prepare", _R)
    host.clear_log()
    result = host.run("rollback")

    assert result.returncode != 0 and "되돌릴 cutover가 없다" in result.stderr
    assert not [c for c in host.calls() if c["argv"][:2] in (["docker", "stop"], ["docker", "compose"], ["docker", "tag"])]
    assert all(c["Running"] for c in host.containers(_OLD).values())


def test_rollback_waits_for_runs_and_keeps_the_new_stack_when_they_do_not_drain(host: Host) -> None:
    host.ready_for_window()
    host.ok("window", _R)
    host.ok("admin")
    host.ok("finish")
    retired = Path(f"{host.old}.retired-{host.stamp()}")
    host.update_state(runs=[{"runId": "0f1e2d3c", "jobName": "fuel_collection_job", "status": "STARTED"}])
    host.clear_log()
    result = host.run("rollback", DRAIN_TIMEOUT_SECONDS="0")

    assert result.returncode != 0 and "0f1e2d3c fuel_collection_job STARTED" in result.stderr
    assert "--no-drain" in result.stderr
    calls = host.calls()
    new_daemon = f"{_NEW}-dagster-daemon-1"
    assert _index(calls, ["docker", "stop", new_daemon]) < _index(calls, ["docker", "start", new_daemon])
    assert not [c for c in calls if c["argv"][:2] == ["docker", "stop"] and c["argv"][2] != new_daemon]
    assert not [c for c in calls if c["argv"][:2] == ["docker", "compose"]]
    assert all(c["Running"] for c in host.containers(_NEW).values())
    assert retired.is_dir() and not host.old.exists()  # 아무것도 옮기지 않았다.
    assert (host.new / ".env.server14").is_file()

    host.clear_log()
    host.ok("rollback", "--no-drain")
    assert not [c for c in host.containers(_NEW).values() if c["Running"]]
    assert host.running_daemons() == [f"{_OLD}-dagster-daemon-1"]
    assert not [c for c in host.calls() if c["argv"][0] == "curl" and "-d" in c["argv"]]  # run을 묻지 않았다.


# ====================================================================== 창 전 재빌드와 이미지 동일성


def test_window_regates_a_rebuilt_image_before_stopping_anything(host: Host) -> None:
    # prebuild 뒤 빌드 캐시가 비어 창 전 재빌드가 PyPI의 새 Dagster를 받았다. 옛 스택을 멈추기 전에 멈춘다.
    host.ready_for_window()
    host.update_state(build_salt="cache-evicted", dagster_built="1.13.25")
    result = host.run("window", _R)

    assert result.returncode != 0 and "dagster 버전이 다르다(운영 1.13.24, 빌드 1.13.25)" in result.stderr
    calls = host.calls()
    assert [c for c in calls if c["argv"][:2] == ["docker", "compose"] and "build" in c["argv"]]
    assert not [c for c in calls if c["argv"][:2] in (["docker", "stop"], ["docker", "rm"])]
    assert not [c for c in calls if c["argv"][:2] == ["docker", "compose"] and "up" in c["argv"]]
    assert all(c["Running"] for c in host.containers(_OLD).values())
    assert (host.old / ".env.server14").is_file()


def test_window_deploys_the_image_it_gated_after_a_cache_miss(host: Host) -> None:
    host.ready_for_window()
    prebuilt = _recorded(host)
    host.update_state(build_salt="cache-evicted")
    result = host.ok("window", _R)

    assert "prebuild 뒤 이미지 층이 바뀌었다" in result.stdout
    rebuilt = _recorded(host)
    assert rebuilt["release"][0] != prebuilt["release"][0]
    new = host.containers(_NEW)
    expected = {"frontend": "frontend", "dagster-gateway": "gateway"}
    for service in _SERVICES:
        role = expected.get(service, "release")
        assert _layers(host, new[f"{_NEW}-{service}-1"]["Image"]) == _layers(host, rebuilt[role][1]), service


def test_window_rebuilds_with_the_env_the_deploy_will_use(host: Host) -> None:
    # frontend build arg는 env에서 온다. prebuild 뒤 옛 env가 바뀌었으면 창 전 재빌드도 그 env로 빌드해야
    # 배포의 `up --build`가 같은 이미지(cache hit)가 되고 이미지 확인을 통과한다.
    host.ready_for_window()
    with (host.old / ".env.server14").open("a", encoding="utf-8") as env_file:
        env_file.write("NEXT_PUBLIC_API_PORT=14001\n")
    result = host.ok("window", _R)

    assert "prebuild 뒤 이미지 층이 바뀌었다" in result.stdout
    frontend = host.containers(_NEW)[f"{_NEW}-frontend-1"]["Image"]
    assert _layers(host, frontend) == _layers(host, _recorded(host)["frontend"][1])


def test_window_restores_the_old_stack_when_the_deploy_runs_an_ungated_image(host: Host) -> None:
    # 창 전 재빌드와 배포의 `up --build` 사이에 캐시가 비어 gate가 보지 않은 이미지가 떴다.
    host.ready_for_window()
    result = host.run("window", _R, FAKE_DEPLOY="rebuild-differs")
    _assert_restored(host, result)
    assert "gate를 통과한 이미지" in result.stderr


# ====================================================================== 되살리기·재실행


def test_window_recreates_old_services_that_docker_start_cannot_bring_back(host: Host) -> None:
    # webserver·daemon(c8b47811)·gateway(f9f648a9)가 돌던 이미지는 store에 없다. start가 그런 컨테이너를
    # 거부하면 되살리기는 rollback 태그로 재생성한다(daemon은 맨 나중).
    host.ready_for_window()
    host.update_state(start_needs_image=True)
    result = host.run("window", _R, FAKE_DEPLOY="fail-after-up")

    _assert_restored(host, result)
    assert "실패:" not in result.stderr
    old = host.containers(_OLD)
    assert {s: old[f"{_OLD}-{s}-1"]["Image"] for s in _SERVICES} == {
        "backend": _BACKEND_IMG,
        "dagster-code-server": _CODE_IMG,
        "frontend": _FRONTEND_IMG,
        "dagster-webserver": _CODE_IMG,
        "dagster-daemon": _CODE_IMG,
        "dagster-gateway": _GATEWAY_LATEST_IMG,
    }
    old_ups = [
        call["argv"]
        for call in host.calls()
        if call["argv"][:2] == ["docker", "compose"] and "up" in call["argv"] and _OLD in call["argv"]
    ]
    assert old_ups and old_ups[-1][-2:] == ["--force-recreate", "dagster-daemon"]
    assert [argv for argv in old_ups if "dagster-daemon" in argv] == [old_ups[-1]]


def test_window_stops_before_the_outage_when_new_backups_differ(host: Host) -> None:
    # 지난 시도의 새 backend가 NEW/backups에 dump를 남겼다. 창 4단계에서 멈추면 중단만 생기고, 흔한 손
    # 정리(`sudo rm -rf NEW/backups`)는 NEW에만 있는 dump를 지운다.
    host.ready_for_window()
    (host.new / "backups").mkdir()
    for path in (host.old / "backups").iterdir():
        os.link(path, host.new / "backups" / path.name)
    only_new = host.new / "backups" / "kor_travel_transport-20260929T010000Z.dump"
    only_new.write_bytes(b"PGDMP new stack")
    result = host.run("window", _R)

    assert result.returncode != 0
    assert f"> {only_new.name}" in result.stderr and "--update=none" in result.stderr
    calls = host.calls()
    assert not [c for c in calls if c["argv"][:2] in (["docker", "stop"], ["docker", "rm"], ["docker", "compose"])]
    assert only_new.is_file()
    assert all(c["Running"] for c in host.containers(_OLD).values())


@pytest.mark.parametrize("new_backups", ["absent", "differs"])
def test_window_stops_before_the_outage_when_it_cannot_list_backups(host: Host, new_backups: str) -> None:
    # `sudo -n find`가 실패하면 목록 비교는 빈 목록 둘을 "같다"고 봤다. NEW/backups가 다르면 그대로 통과했고,
    # NEW가 없으면 창 4단계의 hardlink 사본을 확인하지 않은 채 성공으로 적었다.
    host.ready_for_window()
    if new_backups == "differs":
        (host.new / "backups").mkdir()
        (host.new / "backups" / "kor_travel_transport-20260929T010000Z.dump").write_bytes(b"PGDMP new stack")
    host.sudo_find_broken.touch()
    result = host.run("window", _R)

    assert result.returncode != 0 and "목록을 읽지 못했다" in result.stderr
    assert not [c for c in host.calls() if c["argv"][:2] in (["docker", "stop"], ["docker", "rm"], ["docker", "compose"])]
    assert all(c["Running"] for c in host.containers(_OLD).values())
    assert (host.old / ".env.server14").is_file()


def test_window_restores_the_old_stack_when_it_cannot_list_the_backups_copy(host: Host) -> None:
    # 창 전 확인은 통과했고 중단 안(4단계)에서 find가 실패한다. 빈 목록 둘을 같다고 보면 확인하지 않은
    # hardlink 사본으로 새 스택을 올렸다.
    host.ready_for_window()
    host.update_state(break_sudo_find_on_stop=True)
    result = host.run("window", _R)

    _assert_restored(host, result)
    assert "목록을 읽지 못했다" in result.stderr
    assert not host.deploy_log.exists()  # 새 project 배포까지 가지 않았다.


def test_stray_exports_of_generic_names_do_not_retarget_the_stages(host: Host) -> None:
    # 운영자의 tmux 셸에 남은 흔한 이름의 export. 예전에는 모든 단계가 이 값을 따라갔다.
    stray = host.root / "stray"
    stray.mkdir()
    exports = {
        "OLD_DIR": str(stray / "old"),
        "NEW_DIR": str(stray / "new"),
        "WORK_DIR": str(stray / "work"),
        "MANAGER_LINK": str(stray / "manager"),
        "DAGSTER_GRAPHQL_URL": "http://127.0.0.1:1/graphql",
        "API_URL": "http://127.0.0.1:1",
        "WEB_URL": "http://127.0.0.1:1",
        "ADMIN_API_URL": "http://127.0.0.1:1/health",
    }
    host.ok("prepare", _R, **exports)
    host.stage()
    host.ok("prebuild", _R, **exports)
    host.ok("window", _R, **exports)
    host.ok("admin", **exports)

    assert not list(stray.iterdir())
    assert (host.work / "release").read_text(encoding="utf-8").strip() == _R
    assert (host.new / ".env.server14").is_file() and not (host.old / ".env.server14").exists()
    assert {c["Labels"]["com.docker.compose.project.working_dir"] for c in host.containers(_NEW).values()} == {str(host.new)}
    assert {c["Labels"]["com.docker.compose.project.working_dir"] for c in host.containers(_ADMIN).values()} == {str(host.new)}
    assert not [c for c in host.calls() if c["argv"][0] == "curl" and any(":1/" in a or a.endswith(":1") for a in c["argv"])]


def test_admin_can_be_rerun_after_a_recreate_failed_half_way(host: Host) -> None:
    host.ready_for_window()
    host.ok("window", _R)
    host.update_state(fail_up_at="transport-admin-web")
    failed = host.run("admin")
    assert failed.returncode != 0
    assert f"{_ADMIN}-transport-admin-web-1" not in host.state()["containers"]

    rerun = host.ok("admin")
    assert "pre-rename으로 다시 만든다" in rerun.stdout
    admin = host.containers(_ADMIN)
    assert admin[f"{_ADMIN}-transport-admin-web-1"]["Image"] == _ADMIN_WEB_IMG
    assert admin[f"{_ADMIN}-transport-dagster-gateway-1"]["Image"] == _ADMIN_GATEWAY_IMG
    assert {c["Labels"]["com.docker.compose.project.working_dir"] for c in admin.values()} == {str(host.new)}
    assert (host.work / "admin-images").read_text(encoding="utf-8").count("\n") == 2


def test_window_restores_the_old_stack_when_it_cannot_count_the_old_daemon(host: Host) -> None:
    # 옛 project의 daemon 조회만 실패하고 옛 daemon은 실제로 떠 있다. 실패를 0으로 세면 daemon 둘을 통과시킨다.
    host.ready_for_window()
    host.update_state(fail_ps_filters=[f"com.docker.compose.project={_OLD}", "com.docker.compose.service=dagster-daemon"])
    result = host.run("window", _R, FAKE_DEPLOY="start-old-daemon")
    _assert_restored(host, result)
    assert "dagster-daemon을 세지 못했다" in result.stderr


# ====================================================================== 창 안의 신호


def _drain_forever(host: Host) -> tuple[list[str], dict[str, str]]:
    """끝나지 않는 run 앞에서 대기 루프에 머무는 창."""
    host.ready_for_window()
    host.update_state(runs=[{"runId": "f130efff", "jobName": "ferry_timetable_collection_job", "status": "STARTED"}])
    return ["bash", str(_SCRIPT), "window", _R], host.env(DRAIN_TIMEOUT_SECONDS="600", DRAIN_POLL_SECONDS="0.2")


def _read_until_draining(host: Host, output: int, deadline: float) -> None:
    """옛 daemon을 멈추고 대기 루프에서 run을 물을 때까지 스크립트 출력을 읽어 버린다."""
    old_daemon = f"{_OLD}-dagster-daemon-1"
    while time.monotonic() < deadline:
        try:
            calls = host.calls()
        except json.JSONDecodeError:  # 가짜 명령이 쓰는 중인 줄
            calls = []
        stops = [i for i, call in enumerate(calls) if call["argv"] == ["docker", "stop", old_daemon]]
        if stops and any(call["argv"][0] == "curl" for call in calls[stops[0] :]):
            return
        if select.select([output], [], [], 0.1)[0]:
            try:
                data = os.read(output, 65536)
            except OSError:  # pty: 자식이 끝나면 EIO
                data = b""
            if not data:
                raise AssertionError(f"대기 루프 전에 끝났다: {calls}")
    raise AssertionError(f"대기 루프에 들어가지 않았다: {host.calls()}")


def _assert_old_daemon_restarted(host: Host, exit_code: int, signal_number: int) -> None:
    """출력이 끊긴 뒤: 새 스택은 없고, 멈췄던 옛 daemon을 다시 띄웠고, 끊긴 이유를 exit code로 남겼다."""
    calls = host.calls()
    assert exit_code == 128 + signal_number, (exit_code, [call["argv"] for call in calls])
    old_daemon = f"{_OLD}-dagster-daemon-1"
    stop = _index(calls, ["docker", "stop", old_daemon])
    assert any(call["argv"] == ["docker", "start", old_daemon] for call in calls[stop:])
    assert not [call for call in calls if call["argv"][:2] == ["docker", "compose"] and "up" in call["argv"]]
    assert all(c["Running"] for c in host.containers(_OLD).values())
    assert not host.containers(_NEW)
    assert (host.old / ".env.server14").is_file()


def test_window_restarts_the_old_daemon_when_the_ssh_terminal_hangs_up(host: Host) -> None:
    # tmux 없이 SSH가 끊긴 경우: 터미널이 사라져 SIGHUP이 오고, 그 뒤 모든 출력이 EIO로 실패한다.
    command, env = _drain_forever(host)
    pid, terminal = pty.fork()
    if pid == 0:  # 자식은 곧바로 스크립트가 된다.
        try:
            os.chdir(host.home)
            os.execvpe(command[0], command, env)
        finally:
            os._exit(127)
    try:
        _read_until_draining(host, terminal, time.monotonic() + 90)
    except BaseException:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        raise
    finally:
        os.close(terminal)
    deadline = time.monotonic() + 60
    while (status := os.waitpid(pid, os.WNOHANG))[0] == 0:
        if time.monotonic() > deadline:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            raise AssertionError("터미널이 사라진 뒤에도 스크립트가 끝나지 않았다")
        time.sleep(0.1)
    _assert_old_daemon_restarted(host, os.waitstatus_to_exitcode(status[1]), signal.SIGHUP)


def test_window_restarts_the_old_daemon_when_the_output_pipe_closes(host: Host) -> None:
    # pty 없는 `ssh n150 bash …`의 클라이언트가 끊기거나 `| tee`가 죽은 경우: 다음 출력이 SIGPIPE를 받는다.
    command, env = _drain_forever(host)
    process = subprocess.Popen(
        command,
        cwd=host.home,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    assert process.stdout is not None
    try:
        _read_until_draining(host, process.stdout.fileno(), time.monotonic() + 90)
        process.stdout.close()
        exit_code = process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    _assert_old_daemon_restarted(host, exit_code, signal.SIGPIPE)
