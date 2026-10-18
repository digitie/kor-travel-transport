"""운영 점검 주기·사전 컴파일·HTTP 정본 계약(외부 서비스/DB 접근 없음)."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml
from test_dagster_healthcheck_contract import ROOT, _ComposeLoader

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _services(filename: str) -> dict:
    return yaml.load((ROOT / filename).read_text(), Loader=_ComposeLoader)["services"]


@pytest.mark.parametrize(
    ("filename", "name", "expected"),
    [
        ("docker-compose.yml", "backend", ("30s", "5s", 10, "20s", None)),
        ("docker-compose.db.yml", "postgres", ("15s", "5s", 20, "10s", None)),
        ("docker-compose.yml", "frontend", ("30s", "5s", 10, "20s", None)),
        ("docker-compose.shared.yml", "dagster-code-server", ("90s", "10s", 5, "600s", "5s")),
        ("docker-compose.shared.yml", "dagster-webserver", ("45s", "5s", 8, "30s", None)),
        ("docker-compose.shared.yml", "dagster-daemon", ("360s", "60s", 2, "60s", "15s")),
        ("docker-compose.transport-admin.yml", "transport-api-gateway", ("45s", "5s", 5, None, None)),
        ("docker-compose.transport-admin.yml", "transport-admin-web", ("45s", "5s", 5, "20s", None)),
    ],
)
def test_production_and_legacy_health_intervals_only_triple(filename, name, expected):
    hc = _services(filename)[name]["healthcheck"]
    assert tuple(hc.get(k) for k in ("interval", "timeout", "retries", "start_period", "start_interval")) == expected


@pytest.mark.parametrize(
    ("filename", "port"),
    [("docker-compose.yml", "8000"), ("docker-compose.shared.yml", "${PUBLIC_API_PORT:-12302}")],
)
def test_api_health_uses_explicit_loopback_cli_and_port(filename, port):
    assert _services(filename)["backend"]["healthcheck"]["test"] == [
        "CMD", "python", "-I", "-m", "kortravelcommon.http_health",
        "--port", port, "--path", "/health", "--timeout-seconds", "4",
    ]


def test_stdlib_compile_uses_final_image_interpreter_after_installs():
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text()
    step = "RUN python -I -m kortravelcommon.build_bytecode --stdlib"
    assert dockerfile.count(step) == 1
    assert dockerfile.index('pip install --no-cache-dir -e ".[dev]"') < dockerfile.index(step)
    assert dockerfile.index("RUN playwright install --with-deps chromium") < dockerfile.index(step)
    assert dockerfile.index(step) < dockerfile.index('ENTRYPOINT ["/entrypoint.sh"]')


def test_installed_common_has_pinned_cli_modules():
    metadata = importlib.metadata.distribution("kor-travel-common")
    direct = json.loads(metadata.read_text("direct_url.json") or "{}")
    if "vcs_info" in direct:
        assert direct["vcs_info"]["commit_id"] == "89291f36d731ab906161b96757522e1cd833b4ef"
    else:
        # 실제 no-index wheel은 file URL이며 Git VCS 설치였다고 위조하지 않는다.
        assert direct.get("url", "").startswith("file:") and "archive_info" in direct
    package = Path(metadata.locate_file("kortravelcommon"))
    expected = {
        "http_health.py": "dafb57227662e1298675017be9de04ad602cbeb1a383dcb029e387792c9ec4f6",
        "build_bytecode.py": "b07c7f94565147f619bffba7f1f9871106c0ee07d3683974393d596ffda5d266",
    }
    for name, digest in expected.items():
        assert hashlib.sha256((package / name).read_bytes()).hexdigest() == digest
    for name in ("pyproject.toml", "uv.lock"):
        assert "89291f36d731ab906161b96757522e1cd833b4ef" in (BACKEND_ROOT / name).read_text()



@pytest.mark.parametrize(("status", "expected"), [(200, 0), (302, 1), (503, 1)])
def test_installed_http_cli_is_quiet_strict_and_does_not_follow_redirect(status, expected):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response(status)
            self.send_header("Location", "/redirect-target")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-m", "kortravelcommon.http_health",
             "--port", str(server.server_port), "--path", "/health", "--timeout-seconds", "1"],
            capture_output=True, timeout=4, check=False,
        )
        assert result.returncode == expected
        assert result.stdout == result.stderr == b""
        assert calls == ["/health"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_cs_guard_reaper_and_deadlines_are_byte_preserved():
    text = (ROOT / "docker-compose.shared.yml").read_text()
    anchor = text[text.index("x-dagster-code-server-probe:"):text.index("\n\nservices:")]
    assert hashlib.sha256(anchor.encode()).hexdigest() == "c615b49dd1b3eb6452a8d42f8a87927ab7db057cc7c16d27ecb9226514778b41"


def test_local_live_fixture_intervals_are_not_operational_policy():
    services = _services("docker-compose.live.yml")
    assert services["postgres"]["healthcheck"]["interval"] == "5s"
    assert services["backend"]["healthcheck"]["interval"] == "10s"
