"""`scripts/redeploy-dagster-services-server14.sh`가 fail-closed로 동작하는지 가짜 docker·curl 앞에서 본다.

스크립트는 n150에서 Dagster 세 서비스만 다시 만든다. 여기서 고정하는 것은 순서와 멈춤이다.
drift·허용 밖 변경·닿지 않는 GraphQL은 daemon을 멈추기 전에 STOP이다. daemon을 멈춘 뒤의
STOP·실패·SSH 끊김·출력 pipe 닫힘은 daemon 컨테이너를 `docker start`로 되살린다. 기다리는 동안
바뀐 env, 다른 작업이 다시 만든 Dagster 컨테이너, 다른 작업이 띄운 daemon은 교체 직전에 다시 잡는다.
compose의 실제 렌더링·hash는 흉내만 낸다. 가짜 compose는 shared 파일(JSON)을 셸 env >
`--env-file` 순으로 치환해 렌더링하고, 서비스 정의의 hash를 config-hash label로 쓴다.
"""

from __future__ import annotations

import json
import os
import pty
import select
import signal
import subprocess
import sys
import time
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

_PROJECT = "kor-travel-transport"
_SERVICES = ("dagster-code-server", "dagster-webserver", "dagster-daemon")
_DAEMON = f"{_PROJECT}-dagster-daemon-1"
_PIN = "sha256:" + "1" * 64
_LATEST = "sha256:" + "2" * 64
_DRAFT = "sha256:" + "3" * 64
_ENV_DSN = "postgresql+psycopg2://dagster:pw@127.0.0.1:11000/kor_travel_transport_dagster"
_OLD_SCHEME_DSN = "postgresql://dagster:pw@127.0.0.1:11000/kor_travel_transport_dagster"

_FAKE = r'''
import hashlib, json, os, re, subprocess, sys
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
    if state.get("curl_fails"):
        fail("curl: (7) Failed to connect to 127.0.0.1 port 14004", 7)
    # 기다리는 동안(daemon이 멈춘 동안) 다른 작업이 한 번 끼어든다.
    waiting = not state["containers"]["kor-travel-transport-dagster-daemon-1"]["Running"]
    edit = state.pop("append_on_curl", None) if waiting else None  # [경로, 덧붙일 내용]
    other_job = state.pop("run_on_curl", None) if waiting else None  # 다른 세션의 명령
    if edit or other_job:
        save()
    if edit:
        with open(edit[0], "a") as edited:
            edited.write(edit[1])
    if other_job:
        # 다른 세션은 이 스크립트가 export한 고정 이미지를 모른다.
        env = {key: value for key, value in os.environ.items() if key != "BACKEND_RUNTIME_IMAGE"}
        subprocess.run(other_job, env=env, check=True, stdout=subprocess.DEVNULL)
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
    if options.get("--project-name") != "kor-travel-transport" or len(files) != 2 or not Path(files[0]).is_file():
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
            state["containers"][f"kor-travel-transport-{name}-1"] = {
                "Id": os.urandom(32).hex(),
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
        "{{.Id}}": lambda: container["Id"],
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
            "image": "${BACKEND_RUNTIME_IMAGE:-kor-travel-transport-backend:latest}",
            "environment": {"DAGSTER_POSTGRES_URL": "${DAGSTER_POSTGRES_URL:?set the Dagster DSN}"},
            "healthcheck": {"test": ["CMD", probe, name]},
        }
        if init is not None:
            service["init"] = init
        services[name] = service
    services["dagster-code-server"]["environment"]["DATABASE_URL"] = "${DATABASE_URL:?set the app DSN}"
    services["dagster-webserver"]["command"] = [webserver_command]
    services["backend"] = {
        "image": "${BACKEND_RUNTIME_IMAGE:-kor-travel-transport-backend:latest}",
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
                    "kor-travel-transport-backend:latest": _LATEST,
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
            BACKEND_RUNTIME_IMAGE="kor-travel-transport-backend:latest",
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

    def compose_up_command(self, services: list[str]) -> list[str]:
        compose = [str(self.bin / "docker"), "compose", "--project-name", _PROJECT, "--env-file", ".env.server14"]
        files = ["-f", "docker-compose.yml", "-f", "docker-compose.shared.yml"]
        return [*compose, *files, "up", "-d", "--no-deps", "--no-build", *services]

    def compose_up(self, services: list[str], **env: str) -> None:
        subprocess.run(
            self.compose_up_command(services),
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

    def script_env(self, *, drain_timeout: int = 0, drain_poll: str = "0") -> dict[str, str]:
        return self.env(
            APP_DIR=str(self.app),
            DRAIN_TIMEOUT_SECONDS=str(drain_timeout),
            DRAIN_POLL_SECONDS=drain_poll,
            HEALTH_TIMEOUT_SECONDS="0",
            HEALTH_POLL_SECONDS="0",
        )

    def run(self, candidate: Path, *, drain_timeout: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(_SCRIPT), str(candidate)],
            env=self.script_env(drain_timeout=drain_timeout),
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


def _index(calls: list[list[str]], wanted: list[str], *, after: int = -1) -> int:
    return next(i for i, call in enumerate(calls) if i > after and call[: len(wanted)] == wanted)


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
    reachable = _index(calls, ["curl"])  # GraphQL에 닿는지 daemon을 멈추기 전에 본다.
    tag = _index(calls, ["docker", "tag", _PIN])
    stop = _index(calls, ["docker", "stop", _DAEMON])
    drained = _index(calls, ["curl"], after=stop)
    up = next(i for i, call in enumerate(calls) if call[0] == "docker" and "up" in call)
    assert reachable < tag < stop < drained < up, calls
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
    assert state["tags"][f"kor-travel-transport-backend:dagster-pin-{_PIN[7:19]}"] == _PIN
    assert host.installed() == _NEW
    backups = sorted(host.app.glob("docker-compose.shared.yml.before-*"))
    assert [backup.read_text(encoding="utf-8") for backup in backups] == [_OLD]

    # 되돌리기는 새 셸에서 같은 스크립트에 백업을 준다. 이미지는 고정 이미지에 남는다.
    host.log_path.write_text("", encoding="utf-8")
    rollback = host.run(backups[0])
    assert rollback.returncode == 0, rollback.stdout + rollback.stderr
    rollback_calls = host.calls()
    stopped = _index(rollback_calls, ["docker", "stop", _DAEMON])
    assert any(call[0] == "curl" for call in rollback_calls[stopped:]), rollback_calls  # 멈춘 뒤 run을 기다렸다.
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
        BACKEND_RUNTIME_IMAGE="kor-travel-transport-backend:latest",
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


def test_redeploy_stops_before_the_daemon_when_graphql_is_unreachable(host: Host, tmp_path: Path) -> None:
    # run을 물을 수 없으면 대기가 상한(기본 1800초)까지 daemon을 멈춘 채 헛돈다.
    host.update_state(curl_fails=True)
    _assert_untouched(host, host.run(_candidate(tmp_path)))


# 기다리는 동안 다른 세션이 하는 일. 다시 만드는 서비스는 그 세션의 이미지(.env.server14의 draft)로
# 뜨고, gate는 각 컨테이너의 자기 이미지로 계산하므로 통과한다.
_OTHER_JOBS: dict[str, list[str]] = {
    # 세 서비스를 다시 만든다. compose up이 daemon도 다시 띄운다.
    "recreates-the-services": list(_SERVICES),
    # code-server만 다시 만든다. daemon은 멈춘 그대로라 컨테이너 ID로만 잡힌다.
    "recreates-the-code-server": ["dagster-code-server"],
    # daemon만 다시 띄운다. 새 run이 시작될 수 있다.
    "starts-the-daemon": [],
}


@pytest.mark.parametrize("other_job", list(_OTHER_JOBS))
def test_redeploy_stops_when_another_job_took_the_services_during_the_wait(
    host: Host, tmp_path: Path, other_job: str
) -> None:
    recreated = _OTHER_JOBS[other_job]
    job = host.compose_up_command(recreated) if recreated else ["docker", "start", _DAEMON]
    host.update_state(run_on_curl=job)
    before = {name: container["Id"] for name, container in host.state()["containers"].items()}
    result = host.run(_candidate(tmp_path))

    assert result.returncode != 0
    assert "STOP" in result.stderr
    ups = [call for call in host.calls() if call[0] == "docker" and "up" in call]
    assert len(ups) == (1 if recreated else 0), ups  # 다른 세션의 up뿐이다.
    assert host.installed() == _OLD
    state = host.state()
    assert state["containers"][_DAEMON]["Running"] is True
    for service in _SERVICES:
        name = f"{_PROJECT}-{service}-1"
        container = state["containers"][name]
        if service in recreated:
            # 다른 세션이 만든 그대로다. 고정 이미지로 되돌려 놓지 않았다.
            assert (container["ConfigImage"], container["HealthTest"][1]) == (_DRAFT, "old-probe"), service
        else:
            assert container["Id"] == before[name], service


def _drain_forever(host: Host, tmp_path: Path) -> tuple[list[str], dict[str, str]]:
    """끝나지 않는 run 앞에서 대기 루프에 머무는 실행."""
    host.update_state(runs=[{"runId": "f130efff", "jobName": "ferry_job", "status": "STARTED"}])
    return ["bash", str(_SCRIPT), str(_candidate(tmp_path))], host.script_env(drain_timeout=600, drain_poll="0.2")


def _read_until_draining(host: Host, output: int, deadline: float) -> None:
    """daemon을 멈추고 대기 루프에서 run을 물을 때까지 스크립트 출력을 읽어 버린다."""
    while time.monotonic() < deadline:
        try:
            calls = host.calls()
        except json.JSONDecodeError:  # 가짜 docker가 쓰는 중인 줄
            calls = []
        stops = [i for i, call in enumerate(calls) if call[:2] == ["docker", "stop"]]
        if stops and any(call[0] == "curl" for call in calls[stops[0] :]):
            return
        if select.select([output], [], [], 0.1)[0]:
            try:
                data = os.read(output, 65536)
            except OSError:  # pty: 자식이 끝나면 EIO
                data = b""
            if not data:
                raise AssertionError(f"대기 루프 전에 끝났다: {calls}")
    raise AssertionError(f"대기 루프에 들어가지 않았다: {host.calls()}")


def _assert_daemon_restored(host: Host, exit_code: int, signal_number: int) -> None:
    """출력이 끊긴 뒤: 아무것도 바꾸지 않았고, 멈췄던 daemon을 다시 띄웠고, 끊긴 이유를 exit code로 남겼다.

    bash는 신호로 끝나도 EXIT trap을 돌리지만 trap 안의 $?가 0이라, 신호를 exit로 바꾸지 않으면
    끊긴 실행이 exit 0으로 끝난다.
    """
    calls = host.calls()
    assert exit_code == 128 + signal_number, (exit_code, calls)
    assert any(call == ["docker", "start", _DAEMON] for call in calls[_index(calls, ["docker", "stop", _DAEMON]) :]), (
        exit_code,
        calls,
    )
    assert not [call for call in calls if call[0] == "docker" and "up" in call]
    assert host.installed() == _OLD
    assert host.state()["containers"][_DAEMON]["Running"] is True


def test_redeploy_restarts_the_daemon_when_the_ssh_terminal_hangs_up(host: Host, tmp_path: Path) -> None:
    # tmux 없이 SSH가 끊긴 경우: 터미널이 사라져 SIGHUP이 오고, 그 뒤 모든 출력이 EIO로 실패한다.
    command, env = _drain_forever(host, tmp_path)
    pid, terminal = pty.fork()
    if pid == 0:  # 자식은 곧바로 스크립트가 된다.
        try:
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
    _assert_daemon_restored(host, os.waitstatus_to_exitcode(status[1]), signal.SIGHUP)


def test_redeploy_restarts_the_daemon_when_the_output_pipe_closes(host: Host, tmp_path: Path) -> None:
    # pty 없는 `ssh n150 bash …`의 클라이언트가 끊기거나 `| tee`가 죽은 경우: 다음 출력이 SIGPIPE를 받는다.
    command, env = _drain_forever(host, tmp_path)
    process = subprocess.Popen(
        command,
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
    _assert_daemon_restored(host, exit_code, signal.SIGPIPE)
