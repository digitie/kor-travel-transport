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
    if str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts:
        return False
    # Manager의 trusted 설치 alias는 허용한다. 여기서 resolve/read/copy하지 않는다.
    digest = document["sha256"]
    return type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest) is not None


def validate_remote(
    address: str, env_file: Path, *, instance_config: bool = False,
) -> dict[str, object] | None:
    interfaces = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=15, check=True)
    local = set()
    for value in interfaces.stdout.split():
        try:
            local.add(str(IPv4Address(value)))
        except ValueError:
            continue
    if address not in local:
        raise ValueError("address not assigned here")
    manager = subprocess.run(
        ["sudo", "-n", "ktdctl", "targets", "validate", "--json"],
        capture_output=True, text=True, timeout=30, check=True,
    )
    registry = json.loads(manager.stdout)
    if len(manager.stdout) > 1048576 or not registry_matches(registry, address):
        raise ValueError("Manager registry does not assign transport here")
    if not env_file.is_file() or not os.access(env_file, os.R_OK):
        raise ValueError("environment file is not readable")
    if instance_config:
        shown = subprocess.run(
            ["sudo", "-n", "ktdctl", "dagster-instance-config", "show", "--json"],
            capture_output=True, text=True, timeout=30, check=True,
        )
        if len(shown.stdout) > 16384:
            raise ValueError("Manager instance output exceeds bound")
        document = json.loads(shown.stdout, object_pairs_hook=_unique_object)
        if not instance_config_matches(document, registry):
            raise ValueError("Manager instance does not match the deployment host")
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
        address = parse_host(args.host)
        if args.instance_config and args.parse_only:
            raise ValueError("instance output requires remote validation")
        if not args.parse_only:
            if args.env_file is None:
                raise ValueError("environment file is required")
            document = validate_remote(address, args.env_file, instance_config=args.instance_config)
            if args.instance_config:
                print(json.dumps(document, sort_keys=True, separators=(",", ":")))
    except (OSError, ValueError, subprocess.SubprocessError):
        # 값/Manager stdout·stderr를 재노출하지 않는다.
        print("배포 거절: IPv4/Manager registry/환경 파일 효과 검증에 실패했습니다.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
