"""`scripts/redeploy-dagster-services-server14.sh`가 fail-closed로 동작하는지 가짜 docker·curl 앞에서 본다.

스크립트는 n150에서 Dagster 세 서비스만 다시 만든다. 여기서 고정하는 것은 순서와 멈춤이다.
drift·허용 밖 변경은 daemon을 멈추기 전에 STOP이고, daemon을 멈춘 뒤의 STOP·실패는 daemon
컨테이너를 `docker start`로 되살리며, 기다리는 동안 바뀐 env는 교체 직전에 다시 잡는다.
compose의 실제 렌더링·hash는 흉내만 낸다. 가짜 compose는 shared 파일(JSON)을 셸 env >
`--env-file` 순으로 치환해 렌더링하고, 서비스 정의의 hash를 config-hash label로 쓴다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_NAME = "redeploy-dagster-services-server14.sh"
# 로컬 체크아웃은 `<repo>/scripts`, Docker 이미지는 `/app/scripts`(Dockerfile `COPY scripts /app/scripts`)다.
_SCRIPT = next(
    (
        candidate
        for candidate in (_BACKEND_ROOT / "scripts" / _SCRIPT_NAME, _BACKEND_ROOT.parent / "scripts" / _SCRIPT_NAME)
        if candidate.is_file()
    ),
    _BACKEND_ROOT.parent / "scripts" / _SCRIPT_NAME,
)

_PROJECT = "kor-travel-airport"
_SERVICES = ("dagster-code-server", "dagster-webserver", "dagster-daemon")
_DAEMON = f"{_PROJECT}-dagster-daemon-1"
_PIN = "sha256:" + "1" * 64
_LATEST = "sha256:" + "2" * 64
_DRAFT = "sha256:" + "3" * 64
_ENV_DSN = "postgresql+psycopg2://dagster:pw@127.0.0.1:11000/kor_travel_transport_dagster"
_OLD_SCHEME_DSN = "postgresql://dagster:pw@127.0.0.1:11000/kor_travel_transport_dagster"

_FAKE = r'''
import hashlib, json, os, re, sys
from pathlib import Path

state_path = Path(os.environ["FAKE_STATE"])
state = json.loads(state_path.read_text())
program = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps([program, *args]) + "\n")

def save():
    state_path.write_text(json.dumps(state))

def fail(message, code=1):
    print(message, file=sys.stderr)
    sys.exit(code)

def resolve(image):
    if image in state["tags"]:
        return state["tags"][image]
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image) and image in state["tags"].values():
        return image
    fail(f"No such image: {image}")

if program == "curl":
    # 기다리는 동안 다른 작업이 파일을 고치는 경우: [경로, 덧붙일 내용]
    edit = state.pop("append_on_curl", None)
    if edit:
        with open(edit[0], "a") as edited:
            edited.write(edit[1])
        save()
    print(json.dumps({"data": {"runsOrError": {"__typename": "Runs", "results": state["runs"]}}}))
    sys.exit(0)

def load_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values

def render(env_file, shared):
    file_env = load_env(env_file)
    def substitute(match):
        name, op, default = match.group(1), match.group(2) or "", match.group(3) or ""
        value = os.environ.get(name, file_env.get(name, ""))
        if value:
            return value
        if op == ":?":
            fail(f"required variable {name} is missing a value: {default}")
        return default
    text = re.sub(r"\$\{(\w+)(?:(:-|:\?)([^}]*))?\}", substitute, Path(shared).read_text())
    return json.loads(text)

def service_hash(service):
    return hashlib.sha256(json.dumps(service, sort_keys=True).encode()).hexdigest()

if args[0] == "compose":
    options, rest = {}, args[1:]
    files = []
    while rest and rest[0].startswith("-"):
        flag, value, rest = rest[0], rest[1], rest[2:]
        if flag == "-f":
            files.append(value)
        else:
            options[flag] = value
    if options.get("--project-name") != "kor-travel-airport" or len(files) != 2 or not Path(files[0]).is_file():
        fail(f"fake compose: unexpected invocation {args}", 2)
    config = render(options["--env-file"], files[1])
    command, rest = rest[0], rest[1:]
    if command == "config":
        if rest == ["--format", "json"]:
            print(json.dumps(config))
        elif rest[:1] == ["--hash"]:
            print(rest[1], service_hash(config["services"][rest[1]]))
        elif rest != ["-q"]:
            fail(f"fake compose config: {rest}", 2)
        sys.exit(0)
    if command == "up":
        assert rest[:3] == ["-d", "--no-deps", "--no-build"], rest
        for name in rest[3:]:
            service = config["services"][name]
            state["containers"][f"kor-travel-airport-{name}-1"] = {
                "Image": resolve(service["image"]),
                "ConfigImage": service["image"],
                "Labels": {"com.docker.compose.config-hash": service_hash(service)},
                "Env": [f"{key}={value}" for key, value in service["environment"].items()],
                "Running": True,
                "Health": "healthy",
                "Init": service.get("init"),
                "HealthTest": service["healthcheck"]["test"],
            }
        save()
        sys.exit(0)
    # 실제 n150: `compose start`는 한 번만 도는 migrate 컨테이너가 없어 거부된다.
    fail(f"service {command} is missing dependency migrate")

command = args[0]
if command == "inspect":
    assert args[1] == "-f", args
    template, name = args[2], args[3]
    container = state["containers"].get(name)
    if container is None:
        fail(f"Error: No such object: {name}")
    formats = {
        "{{.Image}}": lambda: container["Image"],
        "{{.Config.Image}}": lambda: container["ConfigImage"],
        '{{index .Config.Labels "com.docker.compose.config-hash"}}':
            lambda: container["Labels"]["com.docker.compose.config-hash"],
        "{{range .Config.Env}}{{println .}}{{end}}": lambda: "\n".join(container["Env"]) + "\n",
        "{{.State.Running}}": lambda: str(container["Running"]).lower(),
        "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}": lambda: container["Health"],
        "{{.Name}} init={{.HostConfig.Init}} {{json .Config.Healthcheck.Test}}":
            lambda: f"/{name} init={container['Init']} {json.dumps(container['HealthTest'])}",
    }
    if template not in formats:
        fail(f"fake docker: unsupported inspect format {template}", 2)
    print(formats[template]())
elif command == "tag":
    state["tags"][args[2]] = resolve(args[1])
    save()
elif command in ("stop", "start"):
    state["containers"][args[1]]["Running"] = command == "start"
    save()
else:
    fail(f"fake docker: unsupported command {args}", 2)
'''


def _shared(*, probe: str, init: bool | None, webserver_command: str = "dagster-webserver") -> str:
    services: dict[str, Any] = {}
    for name in _SERVICES:
        service: dict[str, Any] = {
            "image": "${BACKEND_RUNTIME_IMAGE:-kor-travel-airport-backend:latest}",
            "environment": {"DAGSTER_POSTGRES_URL": "${DAGSTER_POSTGRES_URL:?set the Dagster DSN}"},
            "healthcheck": {"test": ["CMD", probe, name]},
        }
        if init is not None:
            service["init"] = init
        services[name] = service
    services["dagster-code-server"]["environment"]["DATABASE_URL"] = "${DATABASE_URL:?set the app DSN}"
    services["dagster-webserver"]["command"] = [webserver_command]
    services["backend"] = {
        "image": "${BACKEND_RUNTIME_IMAGE:-kor-travel-airport-backend:latest}",
        "environment": {"DATABASE_URL": "${DATABASE_URL:?set the app DSN}"},
    }
    return json.dumps({"name": _PROJECT, "services": services}, indent=2) + "\n"


_OLD = _shared(probe="old-probe", init=None)
_NEW = _shared(probe="new-probe", init=True)


class Host:
    """가짜 n150: 배포 디렉터리, docker·curl, 컨테이너 상태."""

    def __init__(self, root: Path) -> None:
        self.app = root / "app"
        self.app.mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        self.state_path = root / "state.json"
        self.log_path = root / "calls.jsonl"
        self.log_path.touch()
        fake = self.bin / "fake.py"
        fake.write_text(f"#!{sys.executable}\n{_FAKE}", encoding="utf-8")
        fake.chmod(0o755)
        for name in ("docker", "curl"):
            (self.bin / name).symlink_to(fake)
        (self.bin / "python3").symlink_to(sys.executable)
        (self.app / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        (self.app / "docker-compose.shared.yml").write_text(_OLD, encoding="utf-8")
        self.env_file = self.app / ".env.server14"
        self.env_file.write_text(
            # 다른 배포(draft PR)가 바꿔 둔 이미지. 고정 없이 재생성하면 이 이미지로 옮겨 간다.
            f"BACKEND_RUNTIME_IMAGE={_DRAFT}\n"
            "DATABASE_URL=postgresql+asyncpg://app:pw@127.0.0.1:11000/kor_travel_transport\n"
            f"DAGSTER_POSTGRES_URL={_ENV_DSN}\n",
            encoding="utf-8",
        )
        self.write_state(
            {
                "containers": {},
                "tags": {
                    "kor-travel-airport-backend:latest": _LATEST,
                    "local/transport-pr42:coordinates": _PIN,
                    "local/transport-pr43:backend": _DRAFT,
                },
                "runs": [],
            }
        )
        # n150 2026-09-28과 같은 출발점: code-server는 고정할 이미지, webserver·daemon은
        # `:latest` 문자열과 scheme만 다른 DSN으로 옛 파일에서 만들어졌다.
        self.compose_up(["dagster-code-server"], BACKEND_RUNTIME_IMAGE=_PIN)
        self.compose_up(
            ["dagster-webserver", "dagster-daemon"],
            BACKEND_RUNTIME_IMAGE="kor-travel-airport-backend:latest",
            DAGSTER_POSTGRES_URL=_OLD_SCHEME_DSN,
        )
        self.log_path.write_text("", encoding="utf-8")

    def env(self, **extra: str) -> dict[str, str]:
        return {
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.app.parent),
            "LC_ALL": "C.UTF-8",
            "FAKE_STATE": str(self.state_path),
            "FAKE_LOG": str(self.log_path),
            **extra,
        }

    def compose_up(self, services: list[str], **env: str) -> None:
        compose = [str(self.bin / "docker"), "compose", "--project-name", _PROJECT, "--env-file", ".env.server14"]
        files = ["-f", "docker-compose.yml", "-f", "docker-compose.shared.yml"]
        subprocess.run(
            [*compose, *files, "up", "-d", "--no-deps", "--no-build", *services],
            cwd=self.app,
            env=self.env(**env),
            check=True,
            capture_output=True,
            text=True,
        )

    def state(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_state(self, state: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def update_state(self, **changes: Any) -> None:
        self.write_state({**self.state(), **changes})

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]

    def installed(self) -> str:
        return (self.app / "docker-compose.shared.yml").read_text(encoding="utf-8")

    def run(self, candidate: Path, *, drain_timeout: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(_SCRIPT), str(candidate)],
            env=self.env(
                APP_DIR=str(self.app),
                DRAIN_TIMEOUT_SECONDS=str(drain_timeout),
                DRAIN_POLL_SECONDS="0",
                HEALTH_TIMEOUT_SECONDS="0",
                HEALTH_POLL_SECONDS="0",
            ),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def _candidate(tmp_path: Path, text: str = _NEW) -> Path:
    path = tmp_path / "docker-compose.shared.yml.new"
    path.write_text(text, encoding="utf-8")
    return path


def _index(calls: list[list[str]], wanted: list[str]) -> int:
    return next(i for i, call in enumerate(calls) if call[: len(wanted)] == wanted)


def _assert_untouched(host: Host, result: subprocess.CompletedProcess[str]) -> None:
    """daemon을 멈추기 전의 STOP: 아무것도 멈추거나 바꾸지 않았다."""
    assert result.returncode != 0, result.stdout
    assert "STOP" in result.stderr, result.stderr
    assert not [call for call in host.calls() if call[:2] in (["docker", "stop"], ["docker", "tag"])]
    assert not [call for call in host.calls() if call[0] == "docker" and "up" in call]
    assert host.installed() == _OLD
    assert all(container["Running"] for container in host.state()["containers"].values())


def test_redeploy_recreates_the_three_services_on_the_pinned_image_and_rolls_back(
    host: Host, tmp_path: Path
) -> None:
    result = host.run(_candidate(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr

    calls = host.calls()
    tag = _index(calls, ["docker", "tag", _PIN])
    stop = _index(calls, ["docker", "stop", _DAEMON])
    drained = _index(calls, ["curl"])
    up = next(i for i, call in enumerate(calls) if call[0] == "docker" and "up" in call)
    assert tag < stop < drained < up, calls
    assert calls[up][-3:] == list(_SERVICES)
    assert ["docker", "start", _DAEMON] not in calls  # 성공하면 up이 새 daemon을 띄운다.

    state = host.state()
    for service in _SERVICES:
        container = state["containers"][f"{_PROJECT}-{service}-1"]
        # .env.server14의 draft 이미지가 아니라 실행 중이던 code-server 이미지로 고정됐다.
        assert (container["Image"], container["ConfigImage"]) == (_PIN, _PIN), service
        assert container["Init"] is True and container["HealthTest"][1] == "new-probe", service
        # webserver·daemon도 .env.server14의 DSN(scheme `postgresql+psycopg2`)으로 다시 떴다.
        assert f"DAGSTER_POSTGRES_URL={_ENV_DSN}" in container["Env"], service
    assert state["tags"][f"kor-travel-airport-backend:dagster-pin-{_PIN[7:19]}"] == _PIN
    assert host.installed() == _NEW
    backups = sorted(host.app.glob("docker-compose.shared.yml.before-*"))
    assert [backup.read_text(encoding="utf-8") for backup in backups] == [_OLD]

    # 되돌리기는 새 셸에서 같은 스크립트에 백업을 준다. 이미지는 고정 이미지에 남는다.
    host.log_path.write_text("", encoding="utf-8")
    rollback = host.run(backups[0])
    assert rollback.returncode == 0, rollback.stdout + rollback.stderr
    assert _index(host.calls(), ["docker", "stop", _DAEMON]) < _index(host.calls(), ["curl"])
    assert host.installed() == _OLD
    for service in _SERVICES:
        container = host.state()["containers"][f"{_PROJECT}-{service}-1"]
        assert (container["Image"], container["Init"], container["HealthTest"][1]) == (_PIN, None, "old-probe")
    # 같은 초에 돌아도 되돌리기가 넘겨받은 백업을 덮어쓰지 않는다.
    assert backups[0].read_text(encoding="utf-8") == _OLD
    after = sorted(host.app.glob("docker-compose.shared.yml.before-*"))
    assert sorted(backup.read_text(encoding="utf-8") for backup in after) == sorted([_OLD, _NEW])


def test_redeploy_stops_before_the_daemon_when_containers_drifted_from_the_file(
    host: Host, tmp_path: Path
) -> None:
    with host.env_file.open("a", encoding="utf-8") as env_file:
        env_file.write("DATABASE_URL=postgresql+asyncpg://app:pw@127.0.0.1:11000/other\n")
    _assert_untouched(host, host.run(_candidate(tmp_path)))


def test_redeploy_refuses_a_file_that_changes_more_than_probes(host: Host, tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, _shared(probe="new-probe", init=True, webserver_command="changed"))
    result = host.run(candidate)
    _assert_untouched(host, result)
    assert "NOT ALLOWED services.dagster-webserver.command" in result.stdout


def test_redeploy_accepts_only_a_scheme_difference_in_the_running_dsn(host: Host, tmp_path: Path) -> None:
    host.compose_up(
        ["dagster-daemon"],
        BACKEND_RUNTIME_IMAGE="kor-travel-airport-backend:latest",
        DAGSTER_POSTGRES_URL="postgresql://dagster:pw@127.0.0.2:11000/kor_travel_transport_dagster",
    )
    host.log_path.write_text("", encoding="utf-8")
    _assert_untouched(host, host.run(_candidate(tmp_path)))


def test_redeploy_restarts_the_old_daemon_when_runs_do_not_drain(host: Host, tmp_path: Path) -> None:
    host.update_state(runs=[{"runId": "f130efff", "jobName": "ferry_job", "status": "STARTED"}])
    before = host.state()["containers"][_DAEMON]
    result = host.run(_candidate(tmp_path), drain_timeout=0)

    assert result.returncode != 0
    assert "f130efff ferry_job STARTED" in result.stderr
    calls = host.calls()
    assert _index(calls, ["docker", "stop", _DAEMON]) < _index(calls, ["docker", "start", _DAEMON])
    assert not [call for call in calls if call[0] == "docker" and "up" in call]
    assert host.installed() == _OLD
    assert host.state()["containers"][_DAEMON] == {**before, "Running": True}


def test_redeploy_rechecks_drift_after_the_wait(host: Host, tmp_path: Path) -> None:
    # 기다리는 동안 다른 배포가 .env.server14를 고친다.
    edit = "DATABASE_URL=postgresql+asyncpg://app:pw@127.0.0.1:11000/edited\n"
    host.update_state(append_on_curl=[str(host.env_file), edit])
    result = host.run(_candidate(tmp_path))

    assert result.returncode != 0
    assert "STOP" in result.stderr
    calls = host.calls()
    assert _index(calls, ["curl"]) < _index(calls, ["docker", "start", _DAEMON])
    assert not [call for call in calls if call[0] == "docker" and "up" in call]
    assert host.installed() == _OLD
    assert host.state()["containers"][_DAEMON]["Running"] is True


def test_redeploy_installs_the_content_it_checked(host: Host, tmp_path: Path) -> None:
    # 기다리는 동안 넘겨준 파일이 바뀌어도, 검사한 시작 시점의 내용을 넣는다.
    candidate = _candidate(tmp_path)
    host.update_state(append_on_curl=[str(candidate), "# edited during the wait\n"])
    result = host.run(candidate)

    assert result.returncode == 0, result.stdout + result.stderr
    assert candidate.read_text(encoding="utf-8") != _NEW
    assert host.installed() == _NEW
