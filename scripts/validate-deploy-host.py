#!/usr/bin/env python3
"""배포 주소를 원격 자기 IPv4와 검증된 Manager registry 효과로 확인한다."""
from __future__ import annotations

import argparse
from ipaddress import IPv4Address
import json
import os
from pathlib import Path
import subprocess
import sys


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


def validate_remote(address: str, env_file: Path) -> None:
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
        capture_output=True, text=True, timeout=60, check=True,
    )
    if len(manager.stdout) > 1048576 or not registry_matches(json.loads(manager.stdout), address):
        raise ValueError("Manager registry does not assign transport here")
    if not env_file.is_file() or not os.access(env_file, os.R_OK):
        raise ValueError("environment file is not readable")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--parse-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        address = parse_host(args.host)
        if not args.parse_only:
            if args.env_file is None:
                raise ValueError("environment file is required")
            validate_remote(address, args.env_file)
    except (OSError, ValueError, subprocess.SubprocessError):
        # 값/Manager stdout·stderr를 재노출하지 않는다.
        print("배포 거절: IPv4/Manager registry/환경 파일 효과 검증에 실패했습니다.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
