"""공용 Dagster 제어 평면 합류 계약(kor-travel-docker-manager ADR-54).

운영 compose(`docker-compose.shared.yml`)에서 이 프로젝트의 Dagster는 code-server 하나다. 공용 daemon·webserver
(`127.0.0.1:11002`)가 그것을 workspace location `kor-travel-transport`로 싣는다. Manager의 전환 스크립트
(`scripts/dagster-shared-cutover.sh transport …`)는 이 compose를 렌더해 같은 모양을 **파생**하고 Manager
`config/docker-targets.yml`의 transport 선언과 대조한다. 여기서는 이 저장소가 지킬 쪽을 본다.

- code-server: `dagster code-server start`(공용 webserver의 reload가 정의를 다시 읽는다), Manager의 공용 probe
  (`x-dagster-code-server-probe` 원문)·proxy heartbeat 600초·`init: true`, gRPC는 loopback,
  `-p`는 literal이고 healthcheck가 같은 포트를 부른다, `--location-name`은 운영 UI(`lib/dagster-scope.ts`)와 같다,
  공용 instance URL을 받고 옛 metadata DSN은 받지 않는다, `$DAGSTER_HOME/dagster.yaml`을 공용 instance 정의로
  덮는다.
- 옛 webserver·daemon(과 그것에 기대는 gateway), 옛 metadata DB의 migrate는 `profiles: [legacy-dagster]`다.
  활성 서비스는 그것에 기대지 않고, 그 포트(14003·14004)를 부르지 않는다.

모양은 **이름이 아니라 command에서** 찾는다(Manager 파생과 같은 규칙). 마지막 테스트들은 한 단계씩 되돌린
compose가 그 단계를 이름으로 말하는지 본다(빨간 대조군).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT = (
    _BACKEND_ROOT / "compose-contract"
    if (_BACKEND_ROOT / "compose-contract" / "docker-compose.shared.yml").is_file()
    else _BACKEND_ROOT.parent
)
_SHARED = ROOT / "docker-compose.shared.yml"
_ADMIN_SCOPE = ROOT / "packages/kor-travel-transport-admin/frontend/lib/dagster-scope.ts"

_LEGACY_PROFILE = "legacy-dagster"
_LOCATION = "kor-travel-transport"
_SHARED_URL = re.compile(
    r"^postgresql\+psycopg2://kor_travel_dagster_shared_app:\$\{KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD:\?[^}]*\}"
    r"@127\.0\.0\.1:11000/dagster_shared$"
)
_INSTANCE_SOURCE = "/opt/kor-travel-docker-manager/config/dagster-shared/dagster.yaml"


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


def _compose() -> dict[str, Any]:
    document = yaml.load(_SHARED.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    assert isinstance(document, dict)
    return document


def _argv(service: dict[str, Any]) -> list[str]:
    words: list[str] = []
    for key in ("entrypoint", "command"):
        value = service.get(key)
        words += [str(part) for part in value] if isinstance(value, list) else str(value or "").split()
    return words


def _runs(service: dict[str, Any], *program: str) -> bool:
    argv, width = _argv(service), len(program)
    return any(tuple(argv[i : i + width]) == program for i in range(len(argv)))


def _flag(argv: list[str], *names: str) -> str | None:
    for index, word in enumerate(argv[:-1]):
        if word in names:
            return argv[index + 1]
    return None


def _depends(service: dict[str, Any]) -> set[str]:
    depends = service.get("depends_on") or {}
    return set(depends) if isinstance(depends, dict | list) else set()


def _split_top(text: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for index, char in enumerate(text):
        depth += char == "{"
        depth -= char == "}"
        if char == ":" and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    return [*parts, text[start:]]


def _location_in_admin_scope() -> str:
    match = re.search(r'export const DAGSTER_LOCATION_NAME = "([^"]+)";', _ADMIN_SCOPE.read_text(encoding="utf-8"))
    assert match, "lib/dagster-scope.ts에 DAGSTER_LOCATION_NAME이 없다"
    return match.group(1)


def _violations(compose: dict[str, Any]) -> list[str]:
    """합류 계약과 compose의 차이. 빈 목록이면 일치."""

    services: dict[str, dict[str, Any]] = compose["services"]
    violations: list[str] = []
    code_servers = [
        name for name, s in services.items() if _runs(s, "dagster", "code-server") or _runs(s, "dagster", "api", "grpc")
    ]
    if len(code_servers) != 1:
        return [f"code-server를 하나로 찾지 못했다: {code_servers}"]
    code_name = code_servers[0]
    code = services[code_name]
    argv = _argv(code)

    # (a) code-server
    if not _runs(code, "dagster", "code-server", "start"):
        violations.append("(a) code-server가 `dagster code-server start`가 아니다 — `api grpc`는 공용 webserver의 reload를 무시한다")
    if _flag(argv, "-h", "--host") != "127.0.0.1":
        violations.append(f"(a) gRPC가 `{_flag(argv, '-h', '--host')}`에서 듣는다 — loopback만")
    port = _flag(argv, "-p", "--port") or ""
    if not port.isdigit():
        violations.append(f"(a) `-p {port}`는 literal 포트여야 한다 — 공용 workspace가 그 값을 싣는다")
    probe = [str(word) for word in ((code.get("healthcheck") or {}).get("test") or [])]
    if not probe or probe[-1] != port:
        violations.append(f"(a) healthcheck가 `-p {port}`와 다른 포트를 부른다: {probe[-1:]}")
    # 공용 probe — Manager `x-dagster-code-server-probe` 원문(이 파일의 같은 이름 anchor)을 exec 형식으로. 원문이 Manager와
    # 같은지는 Manager 전환 스크립트가 렌더끼리 대조한다(저장소 사이에 SHA를 박지 않는다).
    anchor = str(compose.get("x-dagster-code-server-probe") or "")
    if not anchor or probe[:4] != ["CMD", "python", "-I", "-c"] or len(probe) != 6 or probe[4] != anchor:
        violations.append("(a) healthcheck가 공용 probe(`x-dagster-code-server-probe`, exec 형식)가 아니다")
    if code.get("init") is not True:
        violations.append("(a) code-server에 `init: true`가 없다")
    location = _flag(argv, "--location-name", "-l")
    if location != _LOCATION:
        violations.append(f"(a) `--location-name`이 `{location}`다 — `{_LOCATION}`여야 한다(옛 location 이름·selector id)")
    environment = code.get("environment") or {}
    if not _SHARED_URL.match(str(environment.get("KOR_TRAVEL_DAGSTER_SHARED_PG_URL", ""))):
        violations.append("(a) code-server에 공용 instance URL(`KOR_TRAVEL_DAGSTER_SHARED_PG_URL`, psycopg2·dagster_shared)이 없다")
    if str(environment.get("DAGSTER_GRPC_PROXY_HEARTBEAT_TTL_SECONDS")) != "600":
        violations.append("(a) `DAGSTER_GRPC_PROXY_HEARTBEAT_TTL_SECONDS`가 공용 code-server의 600이 아니다")
    if "DAGSTER_POSTGRES_URL" in environment:
        violations.append("(a) code-server가 옛 metadata DSN(`DAGSTER_POSTGRES_URL`)을 받는다")
    home = environment.get("DAGSTER_HOME")
    mounts = [_split_top(str(volume)) for volume in code.get("volumes") or []]
    instance = [m for m in mounts if len(m) >= 2 and m[1] == f"{home}/dagster.yaml"]
    if len(instance) != 1 or _INSTANCE_SOURCE not in instance[0][0] or instance[0][2:] != ["ro"]:
        violations.append(f"(a) `{home}/dagster.yaml`을 공용 instance 정의(`{_INSTANCE_SOURCE}`)로 읽기 전용으로 덮지 않는다")

    # (c) 옛 전용 Dagster
    runners = {
        name
        for name, s in services.items()
        if (_runs(s, "dagster-webserver") or _runs(s, "dagster-daemon")) and code_name in _depends(s)
    }
    legacy = runners | {name for name, s in services.items() if _depends(s) & runners}
    legacy |= {name for name, s in services.items() if _runs(s, "dagster", "instance", "migrate")}
    if not runners:
        violations.append("(c) 옛 webserver·daemon을 모양으로 찾지 못했다(되돌리기와 Manager 파생이 찾는다)")
    for name in sorted(legacy):
        if services[name].get("profiles") != [_LEGACY_PROFILE]:
            violations.append(f"(c) `{name}`: `profiles: [{_LEGACY_PROFILE}]`가 아니다({services[name].get('profiles')})")
    legacy_ports = {_flag(_argv(services[name]), "-p", "--port") for name in runners} | {"14003"}
    for name, service in services.items():
        if service.get("profiles"):
            continue
        for dependency in sorted(_depends(service) & legacy):
            violations.append(f"(c) 활성 `{name}`이 옛 `{dependency}`에 기댄다")
        for variable, value in (service.get("environment") or {}).items():
            if re.search(rf"(?:127\.0\.0\.1|localhost):({'|'.join(sorted(p for p in legacy_ports if p))})(?!\d)", str(value)):
                violations.append(f"(b) 활성 `{name}`의 `{variable}`가 옛 Dagster 포트를 부른다")
    return violations


def test_the_committed_compose_is_on_the_shared_plane() -> None:
    assert _violations(_compose()) == []


def test_the_admin_ui_scopes_to_the_code_servers_location() -> None:
    code = next(s for s in _compose()["services"].values() if _runs(s, "dagster", "code-server", "start"))
    assert _flag(_argv(code), "--location-name") == _location_in_admin_scope() == _LOCATION


def _mutate(compose: dict[str, Any], step: str) -> None:
    services = compose["services"]
    code = services["dagster-code-server"]
    command = code["command"]
    if step == "command":
        code["command"] = ["dagster", "api", "grpc", *command[3:]]
    elif step == "host":
        command[command.index("-h") + 1] = "0.0.0.0"
    elif step == "port":
        command[command.index("-p") + 1] = "${DAGSTER_PORT:-14005}"
    elif step == "location":
        index = command.index("--location-name")
        del command[index : index + 2]
    elif step == "url":
        code["environment"].pop("KOR_TRAVEL_DAGSTER_SHARED_PG_URL")
    elif step == "old-dsn":
        code["environment"]["DAGSTER_POSTGRES_URL"] = "${DAGSTER_POSTGRES_URL:?x}"
    elif step == "mount":
        code["volumes"] = []
    elif step == "profile":
        services["dagster-daemon"].pop("profiles")
    elif step == "migrate-profile":
        services["dagster-migrate"].pop("profiles")
    elif step == "depends":
        code["depends_on"]["dagster-migrate"] = {"condition": "service_completed_successfully"}
    elif step == "probe":
        code["healthcheck"]["test"][4] = "import sys; sys.exit(0)"
    elif step == "shell-probe":
        code["healthcheck"]["test"] = ["CMD-SHELL", "python -I -c x 14005"]
    elif step == "heartbeat":
        code["environment"].pop("DAGSTER_GRPC_PROXY_HEARTBEAT_TTL_SECONDS")
    elif step == "init":
        code.pop("init")
    elif step == "old-port":
        services["backend"]["environment"]["DAGSTER_URL"] = "http://127.0.0.1:14004"
    else:  # pragma: no cover - 표가 틀렸다
        raise AssertionError(step)


@pytest.mark.parametrize(
    ("step", "named"),
    [
        ("command", "`dagster code-server start`가 아니다"),
        ("host", "loopback만"),
        ("port", "literal 포트"),
        ("location", "`--location-name`"),
        ("url", "공용 instance URL"),
        ("old-dsn", "옛 metadata DSN"),
        ("mount", "읽기 전용으로 덮지 않는다"),
        ("profile", "`dagster-daemon`: `profiles: [legacy-dagster]`가 아니다"),
        ("migrate-profile", "`dagster-migrate`: `profiles: [legacy-dagster]`가 아니다"),
        ("depends", "활성 `dagster-code-server`이 옛 `dagster-migrate`에 기댄다"),
        ("old-port", "옛 Dagster 포트를 부른다"),
        ("probe", "공용 probe"),
        ("shell-probe", "공용 probe"),
        ("heartbeat", "HEARTBEAT_TTL_SECONDS"),
        ("init", "`init: true`가 없다"),
    ],
)
def test_undoing_one_step_of_the_join_is_named(step: str, named: str) -> None:
    compose = copy.deepcopy(_compose())
    _mutate(compose, step)
    violations = _violations(compose)
    assert any(named in violation for violation in violations), violations
