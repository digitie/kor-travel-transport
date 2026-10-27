"""Odroid 배포의 Dagster gRPC 포트 overlay 전달 계약."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

BACKEND = Path(__file__).resolve().parents[1]
# 저장소 checkout은 `<repo>/backend/tests`다. Docker 회귀 이미지는 `/app/tests`이고 무비밀 compose 계약 파일은
# `/app/compose-contract/`, scripts는 `/app/scripts`에 있다.
ROOT = BACKEND.parent if (BACKEND.parent / "transport.override.yml").is_file() else BACKEND / "compose-contract"
SCRIPTS = BACKEND / "scripts" if (BACKEND / "scripts" / "deploy-prod.sh").is_file() else BACKEND.parent / "scripts"


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_tagged(loader: yaml.SafeLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    return loader.construct_scalar(node)


for _tag in ("!reset", "!override"):
    _ComposeLoader.add_constructor(_tag, _construct_tagged)


def _load(path: Path) -> dict[str, Any]:
    result = yaml.load(path.read_text(encoding="utf-8"), Loader=_ComposeLoader)
    assert isinstance(result, dict)
    return result


def _flag(command: list[str], *names: str) -> str | None:
    for index, value in enumerate(command[:-1]):
        if value in names:
            return command[index + 1]
    return None


def test_tracked_odroid_override_matches_base_probe_and_uses_port_12306() -> None:
    base = _load(ROOT / "docker-compose.shared.yml")
    override = _load(ROOT / "transport.override.yml")
    base_service = base["services"]["dagster-code-server"]
    override_service = override["services"]["dagster-code-server"]
    command = override_service["command"]
    health_test = override_service["healthcheck"]["test"]

    assert override["x-dagster-code-server-probe"] == base["x-dagster-code-server-probe"]
    assert command[:3] == ["dagster", "code-server", "start"]
    assert _flag(command, "-h", "--host") == "127.0.0.1"
    assert _flag(command, "-p", "--port") == "12306"
    assert _flag(command, "--location-name", "-l") == "kor-travel-transport"
    assert health_test == ["CMD", "python", "-I", "-c", base["x-dagster-code-server-probe"], "12306"]
    assert base_service["healthcheck"]["test"][-1] == "14005"  # n150 기본값은 유지한다.


def test_production_deployment_stages_installs_and_renders_the_override_before_build() -> None:
    stage = (SCRIPTS / "deploy-prod.sh").read_text(encoding="utf-8")
    remote = (SCRIPTS / "deploy-prod-remote.sh").read_text(encoding="utf-8")
    release_guard = (SCRIPTS / "verify-release-stage.sh").read_text(encoding="utf-8")

    assert "git ls-files --error-unmatch -- transport.override.yml" in stage
    assert "tar -tzf \"${ARCHIVE_PATH}\" | grep -x 'transport.override.yml' >/dev/null" in stage
    assert "${REMOTE_SOURCE}/transport.override.yml" in stage
    assert "transport.override.yml" in release_guard
    compose = remote[remote.index("compose() {"):remote.index("\n}\n", remote.index("compose() {"))]
    assert '-f "${TRANSPORT_OVERRIDE_FILE}"' in compose
    assert 'TRANSPORT_OVERRIDE_FILE="${TRANSPORT_OVERRIDE_DIR}/transport.override.yml"' in remote
    assert "sudo -n install -o root -g root -m 0644" in remote
    assert "sudo -n mv -fT" in remote
    assert remote.index("install_transport_override\n") < remote.index("compose config --format json")
    assert remote.index("compose config --format json") < remote.index("\ncompose build\n")


def test_rendered_compose_guard_accepts_only_port_12306_for_command_and_healthcheck() -> None:
    verifier = SCRIPTS / "verify-transport-override.py"
    probe = "grpc HealthStub ListRepositories"
    valid = {
        "services": {
            "dagster-code-server": {
                "command": [
                    "dagster", "code-server", "start", "-h", "127.0.0.1", "-p", "12306",
                    "-m", "app.dagster.definitions", "--location-name", "kor-travel-transport",
                    "--inject-env-vars-from-instance",
                ],
                "healthcheck": {"test": ["CMD", "python", "-I", "-c", probe, "12306"]},
            }
        }
    }
    accepted = subprocess.run(
        [sys.executable, str(verifier)], input=json.dumps(valid), capture_output=True, text=True, check=False
    )
    assert accepted.returncode == 0, accepted.stderr

    invalid = json.loads(json.dumps(valid))
    invalid["services"]["dagster-code-server"]["healthcheck"]["test"][-1] = "14005"
    rejected = subprocess.run(
        [sys.executable, str(verifier)], input=json.dumps(invalid), capture_output=True, text=True, check=False
    )
    assert rejected.returncode == 2
    assert "12306" in rejected.stderr

    duplicate_port = json.loads(json.dumps(valid))
    duplicate_port["services"]["dagster-code-server"]["command"][6:6] = ["--port", "14005"]
    rejected_duplicate = subprocess.run(
        [sys.executable, str(verifier)], input=json.dumps(duplicate_port), capture_output=True, text=True, check=False
    )
    assert rejected_duplicate.returncode == 2
