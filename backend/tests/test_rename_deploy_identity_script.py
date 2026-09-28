"""`scripts/rename-deploy-identity-server14.sh`가 가짜 n150 앞에서 fail-closed로 동작하는지 본다.

개명 cutover는 compose project·앱 디렉터리를 `kor-travel-airport`에서 `kor-travel-transport`로 옮긴다.
여기서 고정하는 것은 순서와 멈춤, 그리고 끝난 뒤의 상태다. 옛 daemon을 먼저 멈추고 run을 기다린다.
env는 fence 직전에 다시 복사한다. 새 스택을 검증한 뒤에만 옛 컨테이너를 은퇴시킨다(daemon 삭제,
나머지는 restart=no로 이름 변경). 관리 스택은 빌드 없이 재생성한다. rollback은 디렉터리를 겹치지
않게 되돌리고 고정 이미지로 재생성한다. 창이 끝나기 전에 멈추면 옛 스택을 되살린다.
docker·curl·ss·pgrep·crontab·sudo는 가짜다. compose 파일은 JSON으로 쓰고, 가짜 compose가 셸 env >
`--env-file` 순으로 치환해 렌더링한다. 새 디렉터리의 `deploy-server14-remote.sh`는 가짜 배포다(진짜는
`/home/digitie/apps/kor-travel-transport`에서만 돈다). 진짜 배포 스크립트의 guard는
`test_deploy_server14_remote_guard.py`가 본다.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
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
    if re.fullmatch(r"sha256:[0-9a-f]{64}", ref) and ref in tags.values():
        return ref
    return None

def label(container, key):
    return container["Labels"].get(key, "")

def running(service=None):
    return [c for c in state["containers"].values()
            if c["Running"] and (service is None or label(c, "com.docker.compose.service") == service)]

if program == "pgrep":
    if state.get("builds"):
        print(state["builds"])
        sys.exit(0)
    sys.exit(1)

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
    state["tags"][ref] = "sha256:" + hashlib.sha256(f"built {project}/{name}/{ref}".encode()).hexdigest()

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
    print(image)
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
        containers[name]["Running"] = command == "start"
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
runtime="$(mktemp ./.env.server14.runtime.XXXXXX)"
trap 'rm -f "$runtime"' EXIT
{ awk '!/^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE)=/' .env.server14; printf 'RELEASE_SHA=%s\\n' "$CANDIDATE_SHA"; } > "$runtime"
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
        "frontend": {"build": {"context": "."}, "restart": "unless-stopped", "healthcheck": _HEALTH},
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
        sudo.write_text('#!/bin/sh\n[ "$1" = -n ] && shift\nexec "$@"\n', encoding="utf-8")
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
            "schedules": [
                ["airport_collection_job_schedule", "RUNNING"],
                ["ferry_timetable_collection_job_schedule", "RUNNING"],
                ["fuel_collection_job_schedule", "STOPPED"],
            ],
            "migrations": {_BACKEND_IMG: _migration_listing(_MIGRATIONS)},
            "db_revision": "0015_fuel_statistics_priced",
            "dagster": {_CODE_IMG: "1.13.23"},
            "dagster_built": "1.13.23",
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
            "OLD_DIR": str(self.old),
            "NEW_DIR": str(self.new),
            "WORK_DIR": str(self.work),
            "MANAGER_LINK": str(self.manager_link),
            "FAKE_STATE": str(self.state_path),
            "FAKE_LOG": str(self.log_path),
            "FAKE_CRONTAB": str(self.crontab),
            "FAKE_DEPLOY_LOG": str(self.deploy_log),
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

    # prepare 뒤 다른 세션이 옛 env를 고친다(critique M1). 창의 fence 직전 재복사가 이 편집을 가져가야 한다.
    with (host.old / ".env.server14").open("a", encoding="utf-8") as env_file:
        env_file.write("FERRY_TIMETABLE_COLLECTION_INTERVAL_SECONDS=900\n")
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
    assert not [c for c in calls if c["argv"][:2] == ["docker", "compose"]]
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


def test_window_and_prebuild_wait_for_other_image_builds(host: Host) -> None:
    host.ready_for_window()
    host.update_state(builds="3438396 docker compose --env-file /dev/null -f - build pinvi-web")
    for args in (("prebuild", _R), ("window", _R)):
        result = host.run(*args)
        assert result.returncode != 0 and "빌드" in result.stderr, args
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


def test_prebuild_refuses_a_different_dagster_version(host: Host) -> None:
    host.ok("prepare", _R)
    host.stage()
    host.update_state(dagster_built="1.13.24")
    result = host.run("prebuild", _R)
    assert result.returncode != 0 and "dagster" in result.stderr


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
