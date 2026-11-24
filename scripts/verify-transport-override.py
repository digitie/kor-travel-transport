#!/usr/bin/env python3
"""렌더링된 Transport Compose와 legacy 교체의 state 경계를 검증한다."""
from __future__ import annotations

import argparse
import json
import posixpath
import subprocess
import sys

EXPECTED_PORT = "12306"
EXPECTED_LOCATION = "kor-travel-transport"
CODE_SERVER = "dagster-code-server"
STATE = "/opt/dagster/state"
STATE_VOLUME = "kor-travel-transport-dagster-state"
MANAGER_ROUTE = (
    "Use Manager v2: ktdctl service-release apply-core-candidate transport "
    "(state.seed on first attachment, volume proof only for routine deployments)."
)


def _option_is_unique(command: list[str], names: tuple[str, ...], expected: str) -> bool:
    values = [command[index + 1] for index, value in enumerate(command[:-1]) if value in names]
    return values == [expected]


def verify(document: object) -> bool:
    if not isinstance(document, dict):
        return False
    services = document.get("services")
    service = services.get(CODE_SERVER) if isinstance(services, dict) else None
    if not isinstance(service, dict):
        return False
    command = service.get("command")
    healthcheck = service.get("healthcheck")
    test = healthcheck.get("test") if isinstance(healthcheck, dict) else None
    if not isinstance(command, list) or not isinstance(test, list):
        return False
    command = [str(value) for value in command]
    test = [str(value) for value in test]
    return (
        command[:3] == ["dagster", "code-server", "start"]
        and _option_is_unique(command, ("-h", "--host"), "127.0.0.1")
        and _option_is_unique(command, ("-p", "--port"), EXPECTED_PORT)
        and _option_is_unique(command, ("--location-name", "-l"), EXPECTED_LOCATION)
        and "--inject-env-vars-from-instance" in command
        and len(test) == 6
        and test[:4] == ["CMD", "python", "-I", "-c"]
        and "HealthStub" in test[4]
        and "ListRepositories" in test[4]
        and test[5] == EXPECTED_PORT
    )


def _overlaps_state(path: str) -> bool:
    path = posixpath.normpath(path).rstrip("/")
    return path == STATE or path.startswith(STATE + "/") or STATE.startswith(path + "/")


def _allows_legacy_replacement(document: dict) -> bool:
    service = document["services"][CODE_SERVER]
    if any(
        _overlaps_state(mount["target"]) or mount.get("source") == STATE_VOLUME
        for mount in service.get("volumes", [])
    ) or any(_overlaps_state(path.split(":", 1)[0]) for path in service.get("tmpfs", [])):
        return False

    # Include stopped containers. An empty successful listing allows mountless rollback when
    # Compose already removed the old code server. Inspection errors must refuse replacement.
    ids = subprocess.check_output(
        [
            "docker", "container", "ls", "-aq", "--no-trunc",
            "--filter", f"label=com.docker.compose.project={EXPECTED_LOCATION}",
            "--filter", f"label=com.docker.compose.service={CODE_SERVER}",
        ],
        text=True, timeout=15, stderr=subprocess.DEVNULL,
    ).splitlines()
    if not ids:
        return True
    if len(ids) != 1:
        raise ValueError("ambiguous code server")
    mounts = json.loads(subprocess.check_output(
        ["docker", "container", "inspect", "--format", "{{json .Mounts}}", ids[0]],
        text=True, timeout=15, stderr=subprocess.DEVNULL,
    ))
    if not isinstance(mounts, list):
        raise ValueError("missing code-server mounts")
    return not any(
        _overlaps_state(mount["Destination"]) or mount.get("Name") == STATE_VOLUME
        for mount in mounts
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-replacement", action="store_true")
    args = parser.parse_args()
    try:
        document = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("Refusing deployment: rendered Compose is not valid JSON.", file=sys.stderr)
        return 2
    if not verify(document):
        print(
            "Refusing deployment: Dagster code-server, healthcheck, location, or gRPC port does not match Odroid (12306).",
            file=sys.stderr,
        )
        return 2
    if args.legacy_replacement:
        try:
            if _allows_legacy_replacement(document):
                return 0
        except (AttributeError, KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
            print("Refusing legacy deployment: could not verify code-server state mounts.", file=sys.stderr)
        else:
            print("Refusing legacy deployment: the candidate or current code server mounts Dagster state.", file=sys.stderr)
        print(MANAGER_ROUTE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
