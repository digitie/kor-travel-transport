"""Dagster 서비스 healthcheck 계약 (kor-travel-docker-manager #426, Map #1284와 같은 계약).

2026-09-27 n150에서 Dagster probe가 부하 되먹임을 만들었다. `CMD-SHELL` probe는 timeout 때
셸만 죽고 dagster를 import하던 Python을 고아로 남겼고, PID 1인 dagster는 고아를 거두지 않아
좀비가 565개, load가 137까지 올랐다. `dagster api grpc-health-check`는 호출마다 dagster를
import하고 deadline이 없어, 끼인 code-server 앞에서는 probe가 끝나지 않는다.

검사는 **이름 목록이 아니라 command에서 유도한다.** 저장소의 모든 compose 파일에서
`dagster api grpc`·`dagster-webserver`·`dagster-daemon run`을 실행하는 서비스를 찾으므로,
새 Dagster 서비스도 같은 요구를 받는다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
# Docker regression image에는 무비밀 compose 파일만 compose-contract/에 복사된다.
ROOT = (
    _BACKEND_ROOT / "compose-contract"
    if (_BACKEND_ROOT / "compose-contract" / "docker-compose.shared.yml").is_file()
    else _BACKEND_ROOT.parent
)

_CODE_SERVER = ("dagster", "api", "grpc")
_WEBSERVER = ("dagster-webserver",)
_DAEMON = ("dagster-daemon", "run")

#: `dagster api grpc-health-check`가 부르는 것과 같은 판정의 조각
#: (`HealthStub.Check(service="DagsterApi")`가 `SERVING`이어야 통과).
_GRPC_HEALTH_FRAGMENTS = ("grpc_health", "HealthStub", "'DagsterApi'", "SERVING", "timeout=")

#: dagster 자신이 "이만큼 낡으면 계속할 수 없다"로 쓰는 값(`DEFAULT_WORKSPACE_FRESHNESS_TOLERANCE`).
_MAX_HEARTBEAT_TOLERANCE_SECONDS = 300
#: `dagster-daemon liveness-check` 1회가 n150 부하 때 10초를 넘는다(2026-09-27 실측).
_DAEMON_PROBE_MIN_TIMEOUT_SECONDS = 30.0


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


_CODE_SERVERS = _services_running(_CODE_SERVER)
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
    """`CMD-SHELL`은 timeout 때 셸만 죽이고 그 아래 Python을 고아로 남긴다."""
    probe = _probe(_DAGSTER_SERVICES[key])
    assert probe[0] == "CMD", f"`{key}` healthcheck가 exec 형식(`CMD`)이 아니다: {probe[:2]}"
    if Path(probe[1]).name.startswith("python"):
        assert probe[2] == "-I", f"`{key}`의 Python probe가 `python -I`가 아니다: {probe[:4]}"


@pytest.mark.parametrize("key", sorted(_DAGSTER_SERVICES))
def test_every_dagster_service_reaps_its_orphans(key: str) -> None:
    """PID 1인 dagster는 healthcheck·exec의 고아를 거두지 않는다 — init이 거둔다."""
    service = _DAGSTER_SERVICES[key]
    assert service.get("init") is True, f"`{key}`에 `init: true`가 없다."
    assert service.get("restart") == "unless-stopped", (key, service.get("restart"))


@pytest.mark.parametrize("key", sorted(_CODE_SERVERS))
def test_code_server_probe_calls_grpc_health_with_a_deadline(key: str) -> None:
    """CLI가 아니라 grpc_health로 같은 판정을 부르고, deadline과 포트를 command에 맞춘다."""
    service = _CODE_SERVERS[key]
    probe = _probe(service)
    text = " ".join(probe)
    assert "grpc-health-check" not in text, f"`{key}`가 dagster CLI probe를 쓴다: {probe}"
    missing = [fragment for fragment in _GRPC_HEALTH_FRAGMENTS if fragment not in text]
    assert not missing, f"`{key}` probe에 gRPC health 판정 조각이 없다: {missing}"
    assert probe[-1] == _port(service), f"`{key}` probe 포트 {probe[-1]} != command 포트"
    healthcheck = service["healthcheck"]
    assert healthcheck.get("start_period"), (key, healthcheck)
    assert _seconds(healthcheck.get("timeout", "30s")) > 8, (key, "probe deadline보다 timeout이 짧다")


@pytest.mark.parametrize("key", sorted(_WEBSERVERS))
def test_webserver_probe_asks_whether_code_location_loaded(key: str) -> None:
    """정적 페이지가 아니라 GraphQL 본문으로 code location 로드 여부를 판정한다."""
    service = _WEBSERVERS[key]
    text = " ".join(_probe(service))
    assert "repositoriesOrError" in text and "RepositoryConnection" in text, (key, text)
    assert f"127.0.0.1:{_port(service)}/graphql" in text, f"`{key}` probe 포트가 command와 다르다"


@pytest.mark.parametrize("key", sorted(_DAEMONS))
def test_daemon_probe_survives_load_and_reports_within_tolerance(key: str) -> None:
    """liveness-check는 부하 때 10초를 넘는다. 끼인 스레드는 tolerance 안에 보여야 한다."""
    service = _DAEMONS[key]
    healthcheck = service.get("healthcheck") or {}
    assert "liveness-check" in " ".join(_probe(service)), (key, healthcheck)
    assert healthcheck.get("start_period"), (key, healthcheck)
    raw = str((service.get("environment") or {}).get("DAGSTER_DAEMON_HEARTBEAT_TOLERANCE"))
    tolerance = raw.split(":-", maxsplit=1)[1].rstrip("}") if ":-" in raw else raw
    assert tolerance.isdecimal(), f"`{key}`가 DAGSTER_DAEMON_HEARTBEAT_TOLERANCE를 선언하지 않는다"
    assert 1 <= int(tolerance) <= _MAX_HEARTBEAT_TOLERANCE_SECONDS, (key, tolerance)
    timeout = _seconds(healthcheck.get("timeout", "30s"))
    assert timeout >= _DAEMON_PROBE_MIN_TIMEOUT_SECONDS, f"`{key}` liveness timeout {timeout:g}초"
    interval = _seconds(healthcheck.get("interval", "30s"))
    retries = int(healthcheck.get("retries", 3))
    assert interval * retries <= int(tolerance), (
        f"`{key}` 주기 × retries({interval:g}초 × {retries})가 tolerance({tolerance}초)를 넘는다."
    )
