"""Dagster 서비스 healthcheck 계약 (kor-travel-docker-manager #426, Map #1284와 같은 계약).

2026-09-27 n150에서 Dagster probe가 부하 되먹임을 만들었다. `CMD-SHELL` probe는 timeout 때
셸만 죽고 dagster를 import하던 Python을 고아로 남겼고, PID 1인 dagster는 고아를 거두지 않아
좀비가 565개, load가 137까지 올랐다. `dagster api grpc-health-check`는 호출마다 dagster를
import하고 deadline이 없어, 끼인 code-server 앞에서는 probe가 끝나지 않는다.

검사는 **이름 목록이 아니라 command에서 유도한다.** 저장소의 모든 compose 파일에서
`dagster code-server start`(또는 옛 `dagster api grpc`)·`dagster-webserver`·`dagster-daemon run`을 실행하는 서비스를 찾으므로,
새 Dagster 서비스도 같은 요구를 받는다. code-server probe의 판정은 문자열이 아니라 실제
gRPC health 서버 앞에서 probe를 실행해 확인한다.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from concurrent import futures
from pathlib import Path
from typing import Any

import grpc
import pytest
import yaml
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
# Docker regression image에는 무비밀 compose 파일만 compose-contract/에 복사된다.
ROOT = (
    _BACKEND_ROOT / "compose-contract"
    if (_BACKEND_ROOT / "compose-contract" / "docker-compose.shared.yml").is_file()
    else _BACKEND_ROOT.parent
)

#: code-server는 `dagster code-server start`(공용 plane, reload 가능) 또는 옛 `dagster api grpc`다.
_CODE_SERVER_PROGRAMS = (("dagster", "code-server", "start"), ("dagster", "api", "grpc"))
_WEBSERVER = ("dagster-webserver",)
_DAEMON = ("dagster-daemon", "run")

#: probe를 셸로 감싸면 timeout 때 셸만 죽고 그 아래 프로세스가 고아가 된다.
_SHELLS = frozenset({"sh", "bash", "dash", "ash", "zsh", "ksh", "busybox"})

#: dagster 자신이 "이만큼 낡으면 계속할 수 없다"로 쓰는 값(`DEFAULT_WORKSPACE_FRESHNESS_TOLERANCE`).
_MAX_HEARTBEAT_TOLERANCE_SECONDS = 300
#: `dagster-daemon liveness-check` 1회가 n150 부하 때 10초를 넘는다(2026-09-27 실측).
_DAEMON_PROBE_MIN_TIMEOUT_SECONDS = 30.0
#: compose가 `timeout`을 생략했을 때 쓰는 기본값.
_COMPOSE_DEFAULT_TIMEOUT = "30s"


class _ComposeLoader(yaml.SafeLoader):
    """Compose 전용 `!reset`·`!override` 태그를 태그 없는 값처럼 읽는다."""


def _construct_tagged(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


for _tag in ("!reset", "!override"):
    _ComposeLoader.add_constructor(_tag, _construct_tagged)


def _tokens(value: object) -> list[str]:
    parts = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return " ".join(str(part) for part in parts).split()


def _argv(service: dict[str, Any]) -> list[str]:
    return _tokens(service.get("entrypoint")) + _tokens(service.get("command"))


def _runs(service: dict[str, Any], program: tuple[str, ...]) -> bool:
    argv = _argv(service)
    width = len(program)
    return any(tuple(argv[index : index + width]) == program for index in range(len(argv)))


def _all_services() -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = {}
    for path in sorted(ROOT.glob("docker-compose*.yml")):
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader) or {}
        for name, service in (document.get("services") or {}).items():
            services[f"{path.name}:{name}"] = service or {}
    return services


def _services_running(program: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    return {key: service for key, service in _all_services().items() if _runs(service, program)}


def _port(service: dict[str, Any]) -> str:
    argv = _argv(service)
    for flag in ("-p", "--port"):
        if flag in argv:
            return argv[argv.index(flag) + 1]
    raise AssertionError(f"command에 포트가 없다: {argv}")


def _probe(service: dict[str, Any]) -> list[str]:
    test = (service.get("healthcheck") or {}).get("test")
    return [str(part) for part in test] if isinstance(test, list) else [str(test)]


def _program(probe: list[str]) -> list[str]:
    """`CMD` 뒤에서 실제로 실행되는 argv. `env [-옵션|NAME=값]...` 접두는 건너뛴다."""
    argv = probe[1:]
    if argv and Path(argv[0]).name == "env":
        argv = argv[1:]
        while argv and (argv[0].startswith("-") or "=" in argv[0]):
            argv = argv[1:]
    return argv


def _seconds(value: object) -> float:
    """compose duration(`90s`, `2m`, `1m30s`)을 초로 읽는다."""
    total, number = 0.0, ""
    for char in str(value):
        if char.isdigit() or char == ".":
            number += char
            continue
        assert char in {"h", "m", "s"} and number, (value, "unsupported duration")
        total += float(number) * {"h": 3600.0, "m": 60.0, "s": 1.0}[char]
        number = ""
    assert not number, (value, "duration without a unit")
    return total


def _docker_timeout(service: dict[str, Any]) -> float:
    return _seconds((service.get("healthcheck") or {}).get("timeout", _COMPOSE_DEFAULT_TIMEOUT))


def _python_probe(key: str, service: dict[str, Any]) -> tuple[str, str]:
    """`python -I -c <source> <port>` probe의 (source, port)."""
    program = _program(_probe(service))
    assert len(program) == 5 and Path(program[0]).name.startswith("python"), (key, program)
    assert program[1:3] == ["-I", "-c"], f"`{key}` probe가 `python -I -c <source> <port>`가 아니다"
    return program[3], program[4]


_CODE_SERVERS = {
    key: service
    for program in _CODE_SERVER_PROGRAMS
    for key, service in _services_running(program).items()
}
_WEBSERVERS = _services_running(_WEBSERVER)
_DAEMONS = _services_running(_DAEMON)
_DAGSTER_SERVICES = {**_CODE_SERVERS, **_WEBSERVERS, **_DAEMONS}


@pytest.mark.parametrize(
    ("kind", "found"),
    [("code-server", _CODE_SERVERS), ("webserver", _WEBSERVERS), ("daemon", _DAEMONS)],
)
def test_compose_declares_each_dagster_role(kind: str, found: dict[str, Any]) -> None:
    """유도의 전제. 하나도 못 찾으면 아래 검사가 아무것도 재지 않는다."""
    assert found, f"Dagster {kind}를 실행하는 서비스를 command에서 찾지 못했다 — 파서가 낡았다."


@pytest.mark.parametrize("key", sorted(_DAGSTER_SERVICES))
def test_every_dagster_probe_is_exec_form(key: str) -> None:
    """`CMD-SHELL`이나 `CMD sh -c`는 timeout 때 셸만 죽이고 그 아래 Python을 고아로 남긴다."""
    healthcheck = _DAGSTER_SERVICES[key].get("healthcheck") or {}
    assert healthcheck.get("disable") is not True, f"`{key}` healthcheck가 꺼져 있다."
    probe = _probe(_DAGSTER_SERVICES[key])
    assert probe[0] == "CMD", f"`{key}` healthcheck가 exec 형식(`CMD`)이 아니다: {probe[:2]}"
    program = _program(probe)
    assert program, f"`{key}` probe에 실행할 프로그램이 없다: {probe}"
    name = Path(program[0]).name
    assert name not in _SHELLS, f"`{key}` probe가 셸(`{name}`)로 감싸여 있다: {probe[:3]}"
    if name.startswith("python"):
        assert program[1:2] == ["-I"], f"`{key}`의 Python probe가 `python -I`가 아니다: {program[:3]}"


@pytest.mark.parametrize("key", sorted(_DAGSTER_SERVICES))
def test_every_dagster_service_reaps_its_orphans(key: str) -> None:
    """PID 1인 dagster는 healthcheck·exec의 고아를 거두지 않는다 — init이 거둔다."""
    service = _DAGSTER_SERVICES[key]
    assert service.get("init") is True, f"`{key}`에 `init: true`가 없다."
    assert service.get("restart") == "unless-stopped", (key, service.get("restart"))


@pytest.mark.parametrize("key", sorted(_CODE_SERVERS))
def test_code_server_probe_calls_grpc_health_with_a_deadline(key: str) -> None:
    """CLI가 아니라 gRPC health `Check`를 부르고, 모든 호출의 deadline이 docker timeout 안이다."""
    service = _CODE_SERVERS[key]
    probe = _probe(service)
    assert "grpc-health-check" not in " ".join(probe), f"`{key}`가 dagster CLI probe를 쓴다: {probe}"
    source, port = _python_probe(key, service)
    assert port == _port(service), f"`{key}` probe 포트 {port} != command 포트 {_port(service)}"
    assert (service.get("healthcheck") or {}).get("start_period"), (key, "start_period가 없다")
    docker_timeout = _docker_timeout(service)
    checks = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Check"
    ]
    assert checks, f"`{key}` probe가 gRPC health `Check`를 부르지 않는다."
    for call in checks:
        deadlines = [kw.value for kw in call.keywords if kw.arg == "timeout"]
        assert len(deadlines) == 1, f"`{key}` `Check`에 `timeout=` deadline이 없다."
        deadline = deadlines[0]
        is_number = (
            isinstance(deadline, ast.Constant)
            and isinstance(deadline.value, int | float)
            and not isinstance(deadline.value, bool)
        )
        assert is_number, f"`{key}` deadline이 숫자 상수가 아니다: {ast.unparse(deadline)}"
        assert 0 < deadline.value < docker_timeout, (
            f"`{key}` deadline {deadline.value}초가 docker timeout {docker_timeout:g}초 안에 들지 않는다."
        )


#: 공용 plane의 probe(Manager `x-dagster-code-server-probe`)가 자식까지 닿는 조각 — proxy가 자식에 전달하는 RPC, 그
#: 답의 load error 표지, 확정된 죽음에서 PID 1(init)을 끝내는 동작. 그 probe의 판정은 Manager의 실행 테스트가 잰다
#: (healthy 표지·orphan reaper가 `/tmp`와 PID 1을 건드리므로 여기서 실제로 돌리지 않는다).
_PROXY_PROBE_FRAGMENTS = ("/api.DagsterApi/ListRepositories", "SerializableErrorInfo", "os.kill(1,")
_PROXY_CODE_SERVERS = {key: s for key, s in _CODE_SERVERS.items() if _runs(s, ("dagster", "code-server", "start"))}
_SIMPLE_PROBE_CODE_SERVERS = {key: s for key, s in _CODE_SERVERS.items() if key not in _PROXY_CODE_SERVERS}


@pytest.mark.parametrize("key", sorted(_PROXY_CODE_SERVERS))
def test_proxy_code_server_probe_reaches_the_child(key: str) -> None:
    """`code-server start`의 proxy는 자식이 죽어도 SERVING이다 — probe는 자식에 전달되는 RPC를 보고 PID 1을 끝낸다."""
    source, _ = _python_probe(key, _PROXY_CODE_SERVERS[key])
    missing = [fragment for fragment in _PROXY_PROBE_FRAGMENTS if fragment not in source]
    assert not missing, (key, missing)
    heartbeat = str((_PROXY_CODE_SERVERS[key].get("environment") or {}).get("DAGSTER_GRPC_PROXY_HEARTBEAT_TTL_SECONDS"))
    assert heartbeat.isdecimal() and 300 <= int(heartbeat) <= 1800, (key, heartbeat)


#: Manager #460과 같은 냉기동 창. 2026-10-04 n150 재구축에서 180초 창이 디스크 대기 중 냉기동(자식 import가 4분 55초에야
#: 시작)을 못 덮었다. 짧은 `start_interval`이 빨리 뜬 기동을 바로 healthy로 만든다.
_CODE_SERVER_MIN_START_PERIOD_SECONDS = 600.0
_CODE_SERVER_MAX_START_INTERVAL_SECONDS = 5.0


@pytest.mark.parametrize("key", sorted(_PROXY_CODE_SERVERS))
def test_proxy_code_server_start_window_covers_a_loaded_cold_start(key: str) -> None:
    healthcheck = _PROXY_CODE_SERVERS[key].get("healthcheck") or {}
    start_period = _seconds(healthcheck.get("start_period", "0s"))
    assert start_period >= _CODE_SERVER_MIN_START_PERIOD_SECONDS, (key, healthcheck.get("start_period"))
    assert "start_interval" in healthcheck, (key, "start_interval이 없다")
    assert _seconds(healthcheck["start_interval"]) <= _CODE_SERVER_MAX_START_INTERVAL_SECONDS, (key, healthcheck)


def test_the_proxy_probe_derivation_sees_the_code_server() -> None:
    assert _PROXY_CODE_SERVERS, "`dagster code-server start` code-server를 찾지 못했다"


@pytest.mark.parametrize("key", sorted(_SIMPLE_PROBE_CODE_SERVERS))
def test_code_server_probe_passes_only_while_dagster_api_is_serving(key: str) -> None:
    """실제 gRPC health 서버 앞에서 probe를 실행한다. `DagsterApi`가 SERVING일 때만 exit 0이다.

    grpcio·grpcio-health-checking은 dagster 의존성이라 backend 환경과 runtime image에 항상 있다.
    """
    service = _CODE_SERVERS[key]
    source, _ = _python_probe(key, service)
    docker_timeout = _docker_timeout(service)

    def run_probe(port: int) -> int:
        # probe와 같은 `-I`로, 테스트 인터프리터(같은 grpc 설치)에서 실행한다.
        completed = subprocess.run(
            [sys.executable, "-I", "-c", source, str(port)],
            capture_output=True,
            timeout=docker_timeout,
            check=False,
        )
        return completed.returncode

    status = health_pb2.HealthCheckResponse
    servicer = health.HealthServicer()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    health_pb2_grpc.add_HealthServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    verdicts: dict[str, int] = {}
    server.start()
    try:
        # 전체 서버("")는 SERVING인 채로 둔다 — probe는 `DagsterApi`만 물어야 한다.
        for name in ("SERVING", "NOT_SERVING", "UNKNOWN", "SERVICE_UNKNOWN"):
            servicer.set("DagsterApi", getattr(status, name))
            verdicts[name] = run_probe(port)
    finally:
        server.stop(None)
    verdicts["closed port"] = run_probe(port)

    assert verdicts["SERVING"] == 0, (key, verdicts)
    failing = {name: code for name, code in verdicts.items() if name != "SERVING" and code == 0}
    assert not failing, f"`{key}` probe가 SERVING이 아닌데 통과한다: {verdicts}"


@pytest.mark.parametrize("key", sorted(_WEBSERVERS))
def test_webserver_probe_asks_whether_code_location_loaded(key: str) -> None:
    """정적 페이지가 아니라 GraphQL 본문으로 code location 로드 여부를 판정한다."""
    service = _WEBSERVERS[key]
    text = " ".join(_probe(service))
    assert "repositoriesOrError" in text and "RepositoryConnection" in text, (key, text)
    assert f"127.0.0.1:{_port(service)}/graphql" in text, f"`{key}` probe 포트가 command와 다르다"


@pytest.mark.parametrize("key", sorted(_DAEMONS))
def test_daemon_probe_survives_load_with_a_bounded_tolerance(key: str) -> None:
    """liveness-check는 부하 때 10초를 넘는다. heartbeat tolerance는 dagster 자신의 상한 안이다.

    끼인 daemon이 unhealthy로 보이기까지는 heartbeat 주기 + tolerance + timeout(진행 중이던
    probe) + retries × (interval + timeout)까지 걸린다. docker는 이전 probe가 끝난 뒤에야
    interval을 다시 센다. 이 시간을 기다리는 소비자는 없으므로(docker는 unhealthy를 재시작하지
    않는다) 상한으로 걸지 않는다.
    """
    service = _DAEMONS[key]
    healthcheck = service.get("healthcheck") or {}
    assert "liveness-check" in " ".join(_probe(service)), (key, healthcheck)
    assert healthcheck.get("start_period"), (key, healthcheck)
    raw = str((service.get("environment") or {}).get("DAGSTER_DAEMON_HEARTBEAT_TOLERANCE"))
    tolerance = raw.split(":-", maxsplit=1)[1].rstrip("}") if ":-" in raw else raw
    assert tolerance.isdecimal(), f"`{key}`가 DAGSTER_DAEMON_HEARTBEAT_TOLERANCE를 선언하지 않는다"
    assert 1 <= int(tolerance) <= _MAX_HEARTBEAT_TOLERANCE_SECONDS, (key, tolerance)
    timeout = _docker_timeout(service)
    assert timeout >= _DAEMON_PROBE_MIN_TIMEOUT_SECONDS, f"`{key}` liveness timeout {timeout:g}초"
