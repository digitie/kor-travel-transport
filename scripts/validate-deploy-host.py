#!/usr/bin/env python3
"""배포 주소를 원격 자기 IPv4와 검증된 Manager registry 효과로 확인한다."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from ipaddress import IPv4Address
from pathlib import Path, PurePosixPath

#: 시간 초과 때 SIGTERM(sudo가 자식 ktdctl에 전달한다) 뒤 kill 전까지 기다리는 시간.
TERMINATE_GRACE_SECONDS = 5


class DeployHostError(ValueError):
    """고정·비민감 원인 토큰을 가진 거절. 값·명령 출력은 담지 않는다."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _run(argv: list[str], *, timeout: float) -> str:
    """명령의 stdout을 돌려준다. 시간 초과면 sudo 아래 root ktdctl까지 정리한다.

    `subprocess.run(timeout=)`은 직계 자식(sudo)에만 SIGKILL을 보내고, sudo는 그것을 전달하지 못해 root
    ktdctl이 고아로 남는다. 먼저 SIGTERM(sudo가 자식에 전달)을 보내고 짧게 기다린 뒤 kill한다.
    """
    process = subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.communicate(timeout=TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        raise DeployHostError("timeout") from None
    if process.returncode != 0:
        raise DeployHostError("command")
    return stdout


def _json(text: str, **kwargs: object) -> object:
    try:
        return json.loads(text, **kwargs)
    except ValueError:
        raise DeployHostError("output") from None


def parse_host(value: str) -> str:
    address = str(IPv4Address(value))
    if address != value:
        raise ValueError("canonical IPv4 required")
    return address


def registry_matches(document: object, address: str) -> bool:
    if not isinstance(document, dict) or document.get("status") != "ok":
        return False
    targets, hosts = document.get("targets"), document.get("hosts")
    if not isinstance(targets, dict) or not isinstance(hosts, dict):
        return False
    target = targets.get("transport")
    if not isinstance(target, dict):
        return False
    key = target.get("host")
    if not isinstance(key, str) or not key or key == "all":
        return False
    host = hosts.get(key)
    return isinstance(host, dict) and host.get("addr") == address


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Manager field")
        result[key] = value
    return result


def instance_config_matches(document: object, registry: dict[str, object]) -> bool:
    if not isinstance(document, dict) or set(document) != {"host", "max_concurrent_runs", "path", "sha256"}:
        return False
    targets = registry.get("targets")
    if not isinstance(targets, dict) or not isinstance(targets.get("transport"), dict):
        return False
    target = targets["transport"]
    if type(document["host"]) is not str or document["host"] != target["host"]:
        return False
    maximum = document["max_concurrent_runs"]
    if type(maximum) is not int or maximum <= 0:
        return False
    path = document["path"]
    if type(path) is not str or not re.fullmatch(r"/[A-Za-z0-9_./-]+", path):
        return False
    if path.startswith("//") or str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts:
        return False
    # Manager의 trusted 설치 alias는 허용한다. 여기서 resolve/read/copy하지 않는다.
    digest = document["sha256"]
    return type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None


def validate_remote(
    address: str, env_file: Path, *, instance_config: bool = False,
) -> dict[str, object] | None:
    interfaces = _run(["hostname", "-I"], timeout=15)
    local = set()
    for value in interfaces.split():
        try:
            local.add(str(IPv4Address(value)))
        except ValueError:
            continue
    if address not in local:
        raise DeployHostError("address")
    manager = _run(["sudo", "-n", "ktdctl", "targets", "validate", "--json"], timeout=60)
    if len(manager) > 1048576:
        raise DeployHostError("output")
    registry = _json(manager)
    if not registry_matches(registry, address):
        raise DeployHostError("registry")
    if not env_file.is_file() or not os.access(env_file, os.R_OK):
        raise DeployHostError("env")
    if instance_config:
        shown = _run(["sudo", "-n", "ktdctl", "dagster-instance-config", "show", "--json"], timeout=30)
        if len(shown) > 16384:
            raise DeployHostError("output")
        document = _json(shown, object_pairs_hook=_unique_object)
        if not instance_config_matches(document, registry):
            raise DeployHostError("instance")
        return document
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--parse-only", action="store_true")
    parser.add_argument("--instance-config", action="store_true")
    args = parser.parse_args(argv)
    try:
        try:
            address = parse_host(args.host)
        except ValueError:
            raise DeployHostError("address") from None
        if args.instance_config and args.parse_only:
            raise DeployHostError("instance")
        if not args.parse_only:
            if args.env_file is None:
                raise DeployHostError("env")
            document = validate_remote(address, args.env_file, instance_config=args.instance_config)
            if args.instance_config:
                print(json.dumps(document, sort_keys=True, separators=(",", ":")))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # 값/Manager stdout·stderr를 재노출하지 않는다. 고정 원인 토큰(address|timeout|command|output|registry|
        # env|instance)만 stderr에 덧붙인다 — stdout은 --instance-config JSON 계약이라 건드리지 않는다.
        if isinstance(exc, DeployHostError):
            reason = exc.reason
        elif isinstance(exc, (OSError, subprocess.SubprocessError)):
            reason = "command"
        else:
            reason = "output"
        print(f"배포 거절: IPv4/Manager registry/환경 파일 효과 검증에 실패했습니다. reason={reason}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
