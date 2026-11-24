"""Odroid 배포의 Dagster gRPC 포트 overlay 전달 계약."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
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
    preflight = remote.index('TRANSPORT_OVERRIDE_FILE="${TRANSPORT_OVERRIDE_SOURCE}" verify_legacy_compose compose')
    assert preflight < remote.index("\ninstall_transport_override\n") < remote.index("\ncompose build\n")
    assert preflight < remote.index('strict_prebuilt_gate --overlay >') < remote.index('\nif [[ "${DEPLOY_MODE}" == "prepare-shared-dagster-cutover" ]]; then')


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


def test_odroid_overlay_adds_one_external_nocopy_state_mount_only_to_code_server() -> None:
    overlay = _load(ROOT / "transport.override.yml")
    base = _load(ROOT / "docker-compose.shared.yml")
    volume = "kor-travel-transport-dagster-state"
    assert overlay["volumes"] == {volume: {"name": volume, "external": True}}
    assert {
        name: service["volumes"] for name, service in overlay["services"].items() if "volumes" in service
    } == {
        "dagster-code-server": [
            {"type": "volume", "source": volume, "target": "/opt/dagster/state", "volume": {"nocopy": True}}
        ]
    }
    mounts = base["services"]["dagster-code-server"]["volumes"]
    assert "opinet-checkpoints:/app/collector-state" in mounts
    assert any(mount.endswith(":/app/dagster_home/dagster.yaml:ro") for mount in mounts)
    for filename in ("docker-compose.yml", "docker-compose.shared.yml", "docker-compose.transport-admin.yml"):
        assert volume not in (ROOT / filename).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("candidate_mount", "current", "allowed"),
    [
        (True, "unreachable", False),
        (False, "mounted", False),
        (False, "inspect-error", False),
        (False, "list-error", False),
        (False, "mountless", True),
        (False, "absent", True),
    ],
)
def test_legacy_guard_refuses_managed_transitions(tmp_path, candidate_mount, current, allowed):
    service = _load(ROOT / "transport.override.yml")["services"]["dagster-code-server"]
    if not candidate_mount:
        service.pop("volumes")
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
case "$2" in
  ls)
    case "$CURRENT" in
      list-error|unreachable) exit 1 ;;
      absent) exit 0 ;;
      *) echo container-id ;;
    esac ;;
  inspect)
    case "$CURRENT" in
      mounted) echo '[{"Name":"kor-travel-transport-dagster-state","Destination":"/opt/dagster/state"}]' ;;
      mountless) echo '[{"Destination":"/app/collector-state"}]' ;;
      *) exit 1 ;;
    esac ;;
  *) exit 1 ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    calls = tmp_path / "calls"
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "verify-transport-override.py"), "--legacy-replacement"],
        input=json.dumps({"services": {"dagster-code-server": service}}),
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "CURRENT": current, "CALLS": str(calls)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == (0 if allowed else 2), result.stderr
    if not allowed:
        assert "ktdctl service-release apply-core-candidate transport" in result.stderr
        assert "state.seed on first attachment" in result.stderr
    if candidate_mount:
        assert not calls.exists()
    else:
        observed_calls = calls.read_text().splitlines()
        assert observed_calls[0].startswith("container ls -aq")
        assert "label=com.docker.compose.project=kor-travel-transport" in observed_calls[0]
        assert "label=com.docker.compose.service=dagster-code-server" in observed_calls[0]
