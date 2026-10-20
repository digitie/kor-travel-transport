#!/usr/bin/env python3
"""렌더링된 Transport Compose에서 Dagster code-server/healthcheck 포트를 검증한다."""
from __future__ import annotations

import json
import sys

EXPECTED_PORT = "12306"
EXPECTED_LOCATION = "kor-travel-transport"


def _option_is_unique(command: list[str], names: tuple[str, ...], expected: str) -> bool:
    values = [command[index + 1] for index, value in enumerate(command[:-1]) if value in names]
    return values == [expected]


def verify(document: object) -> bool:
    if not isinstance(document, dict):
        return False
    services = document.get("services")
    service = services.get("dagster-code-server") if isinstance(services, dict) else None
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


def main() -> int:
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
