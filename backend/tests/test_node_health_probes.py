"""Compose에 실제 선언한 Node probe를 로컬 HTTP 프로세스로 검증한다(DB 없음)."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from test_dagster_healthcheck_contract import ROOT, _ComposeLoader

NODE = shutil.which("node")
FIXTURE = Path(__file__).parent / "fixtures" / "node-health-server.mjs"
CASES = [
    ("base", "docker-compose.yml", "frontend", "http://127.0.0.1:3000/"),
    ("shared", "docker-compose.shared.yml", "frontend", "http://127.0.0.1:${PUBLIC_WEB_PORT:-12303}/"),
    ("admin", "docker-compose.transport-admin.yml", "transport-admin-web",
     "http://127.0.0.1:${TRANSPORT_PUBLIC_WEB_PORT:-12305}/login"),
]


def declared_probe(filename: str, service: str) -> tuple[list[str], str]:
    services = yaml.load((ROOT / filename).read_text(), Loader=_ComposeLoader)["services"]
    argv = services[service]["healthcheck"]["test"]
    # 원본 CMD-SHELL도 동일 fixture에서 RED를 재현할 수 있게 실제 argv로 해석한다.
    argv = argv[1:] if argv[0] == "CMD" else shlex.split(argv[1])
    assert argv[:2] == ["node", "-e"]
    match = re.findall(r"http://127\.0\.0\.1:[^'\"]+", argv[2])
    assert len(match) == 1
    return argv, match[0]


@contextmanager
def server(mode: str):
    assert NODE is not None, "Node fixture 검증에 WSL Node가 필요하다."
    proc = subprocess.Popen(
        [NODE, str(FIXTURE), mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, env={"PATH": os.defpath, "LANG": "C.UTF-8"},
    )
    assert proc.stdout is not None
    info = json.loads(proc.stdout.readline())
    state = {"port": info["port"]}
    try:
        yield state
    finally:
        try:
            stdout, stderr = proc.communicate("stop\n", timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise
        assert proc.returncode == 0 and stderr == ""
        state["calls"] = json.loads(stdout.strip())["calls"]


def run_probe(filename: str, service: str, state: dict):
    argv, old_url = declared_probe(filename, service)
    path = "/login" if old_url.endswith("/login") else "/"
    url = f"http://127.0.0.1:{state['port']}{path}"
    code = argv[2].replace(old_url, url)
    started = time.monotonic()
    result = subprocess.run(
        [NODE, "-e", code], capture_output=True, timeout=7, check=False,
        env={"PATH": os.defpath, "LANG": "C.UTF-8"},
    )
    assert result.stdout == result.stderr == b""
    return result, time.monotonic() - started, path


@pytest.mark.parametrize(("role", "filename", "service", "url"), CASES)
@pytest.mark.parametrize("mode", ["ok", "no_content", "upper_2xx", "max_body"])
def test_node_health_consumes_complete_strict_2xx(role, filename, service, url, mode):
    with server(mode) as state:
        result, _elapsed, path = run_probe(filename, service, state)
        assert result.returncode == 0
    assert state["calls"] == [{"method": "GET", "path": path, "connection": "close"}]


@pytest.mark.parametrize(("role", "filename", "service", "url"), CASES)
@pytest.mark.parametrize("mode", [
    "redirect", "unavailable", "aborted", "oversized_length",
    "oversized_chunked", "headers_stall", "slow_drip", "closed",
])
def test_node_health_rejects_incomplete_or_unbounded(role, filename, service, url, mode):
    with server(mode) as state:
        result, elapsed, path = run_probe(filename, service, state)
        assert result.returncode == 1
        if mode in {"headers_stall", "slow_drip"}:
            assert 3.5 <= elapsed < 5.5
    expected = [] if mode == "closed" else [{"method": "GET", "path": path, "connection": "close"}]
    assert state["calls"] == expected


def test_three_declarations_keep_original_urls_and_same_probe_body():
    scripts = []
    for _role, filename, service, expected_url in CASES:
        argv, url = declared_probe(filename, service)
        assert url == expected_url
        scripts.append(argv[2].replace(url, "<SAME_LOOPBACK_URL>"))
    assert len(set(scripts)) == 1
