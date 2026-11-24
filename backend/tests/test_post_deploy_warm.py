"""배포 직후 best-effort warm(감사 WLH-03·MC-07·RT-03·RT-11).

- code-server 안 기준정보 본문 준비 모듈: 종류별 결과 JSON 한 줄, 실패는 종료 코드로만.
- backend 안 loopback export 확인 모듈: 토큰은 env에서만 읽고 출력은 경로·상태·지연뿐, 토큰이 있는데 404면 3.
- 호스트 wrapper: 어떤 결과에도 exit 0, 경고만 남긴다. legacy 배포 스크립트는 current 발행 뒤에 부른다.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from app import service_exports
from app.deploy import export_smoke, prepare_references

TOKEN = "t" * 40
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = next(
    (candidate for candidate in (_BACKEND_ROOT / "scripts", _BACKEND_ROOT.parent / "scripts")
     if (candidate / "post-deploy-warm.sh").is_file()),
    _BACKEND_ROOT.parent / "scripts",
)


def test_smoke_constants_match_the_export_router():
    # smoke 모듈은 표준 라이브러리만 쓰므로 값을 복제한다. 원본과 어긋나면 운영 smoke가 404를 설정 오류로 오판한다.
    assert export_smoke.TOKEN_HEADER == service_exports.SERVICE_TOKEN_HEADER
    assert export_smoke.MIN_TOKEN_LENGTH == service_exports.MIN_SERVICE_TOKEN_LENGTH


def test_smoke_routes_exist_in_the_application(test_settings):
    from app.main import create_app
    registered = set(create_app(test_settings).openapi()["paths"])
    for path in export_smoke.T1_ROUTES + export_smoke.T3_ROUTES:
        assert export_smoke.PREFIX + path.split("?", 1)[0] in registered


class _Handler(BaseHTTPRequestHandler):
    statuses: ClassVar[dict[str, int]] = {}
    bodies: ClassVar[dict[str, bytes]] = {}
    seen: ClassVar[list[tuple[str, str | None]]] = []

    def do_GET(self):
        type(self).seen.append((self.path, self.headers.get(export_smoke.TOKEN_HEADER)))
        path = self.path.split("?", 1)[0]
        status = type(self).statuses.get(path, 200)
        body = type(self).bodies.get(path, b'{"items":[]}')
        self.send_response(status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return None


@pytest.fixture
def server():
    _Handler.statuses, _Handler.bodies, _Handler.seen = {}, {}, []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        httpd.server_close()


def _smoke(server, monkeypatch, capsys, *, token=TOKEN, map_current="true"):
    if token is None:
        monkeypatch.delenv(export_smoke.TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(export_smoke.TOKEN_ENV, token)
    monkeypatch.setenv("TRANSPORT_MAP_CURRENT_ENABLED", map_current)
    code = export_smoke.main(["--port", str(server.server_address[1]), "--timeout-seconds", "5"])
    return code, capsys.readouterr()


def test_smoke_calls_map_routes_with_the_env_token_and_prints_no_secret(server, monkeypatch, capsys):
    code, out = _smoke(server, monkeypatch, capsys)
    assert code == 0
    assert [path for path, _ in _Handler.seen] == [
        export_smoke.PREFIX + path for path in export_smoke.T1_ROUTES + export_smoke.T3_ROUTES
    ]
    assert all(token == TOKEN for _, token in _Handler.seen)
    lines = out.out.strip().splitlines()
    assert len(lines) == 8
    assert lines[0].startswith("GET /v1/service/exports/fuel-stations 200 ") and lines[0].endswith("ms")
    assert lines[-1] == "export smoke summary: ok=7 not_found=0 unreachable=0 t3_failed=0 t1_unavailable=0"
    assert TOKEN not in out.out + out.err


def test_smoke_reports_config_mismatch_and_other_failures(server, monkeypatch, capsys):
    _Handler.statuses = {"/v1/service/exports/rail-stations": 503}
    assert _smoke(server, monkeypatch, capsys)[0] == export_smoke.EXIT_T3_FAILED
    _Handler.statuses = {"/v1/service/exports/rail-stations": 503, "/v1/service/exports/airports": 404}
    assert _smoke(server, monkeypatch, capsys)[0] == export_smoke.EXIT_CONFIG


def test_smoke_separates_unavailable_t1_sources_by_problem_code(server, monkeypatch, capsys):
    """T1 원천이 최신이 아니거나 비활성이라 503인 것은 배포 문제가 아니다 — problem code를 붙여 따로 센다."""
    _Handler.statuses = {"/v1/service/exports/highway-incidents/active": 503, "/v1/service/exports/fuel-stations": 503}
    _Handler.bodies = {
        "/v1/service/exports/highway-incidents/active": b'{"type":"about:blank","status":503,"code":"EXPORT_EMPTY_SET",'
                                                        b'"detail":"private-canary"}',
        "/v1/service/exports/fuel-stations": b"<html>not json private-canary</html>",
    }
    code, out = _smoke(server, monkeypatch, capsys)
    assert code == export_smoke.EXIT_T1_UNAVAILABLE == 5
    lines = out.out.strip().splitlines()
    assert any(line.startswith("GET /v1/service/exports/highway-incidents/active 503 EXPORT_EMPTY_SET ") for line in lines)
    assert any(line.startswith("GET /v1/service/exports/fuel-stations 503 ") and "EXPORT" not in line for line in lines)
    assert lines[-1].endswith("t3_failed=0 t1_unavailable=2")
    assert "private-canary" not in out.out  # problem detail·본문은 출력하지 않는다


def test_smoke_skips_without_token_and_skips_t3_when_map_current_is_off(server, monkeypatch, capsys):
    code, out = _smoke(server, monkeypatch, capsys, token=None)
    # 건너뜀은 통과가 아니다(자기 종료 코드, wrapper가 경고한다).
    assert code == export_smoke.EXIT_SKIPPED == 4 and _Handler.seen == [] and "skipped" in out.out
    short = "s" * (export_smoke.MIN_TOKEN_LENGTH - 1)
    code, out = _smoke(server, monkeypatch, capsys, token=short)
    # 설정은 됐지만 짧아서 export가 닫혀 있다 — "설정 안 됨"과 구분해 설정 불일치로 본다.
    assert code == export_smoke.EXIT_CONFIG and _Handler.seen == [] and "shorter than 32" in out.out
    assert short not in out.out
    code, out = _smoke(server, monkeypatch, capsys, map_current="false")
    assert code == 0
    assert [path for path, _ in _Handler.seen] == [export_smoke.PREFIX + path for path in export_smoke.T1_ROUTES]


def test_smoke_connection_failure_is_a_warning(monkeypatch, capsys):
    import socket
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    monkeypatch.setenv(export_smoke.TOKEN_ENV, TOKEN)
    monkeypatch.setenv("TRANSPORT_MAP_CURRENT_ENABLED", "false")
    assert export_smoke.main(["--port", str(port), "--timeout-seconds", "2"]) == export_smoke.EXIT_T3_FAILED
    # Linux는 즉시 거절, Windows는 SYN 재시도로 시간 초과가 된다. 어느 쪽이든 도달 불가(1)다(T1 원천 문제와 다르다).
    out = capsys.readouterr().out
    assert "ConnectionRefusedError" in out or " timeout " in out
    assert "unreachable=5" in out


RELEASE = "0123456789abcdef0123456789abcdef01234567"
_SETTINGS = SimpleNamespace(release_sha=RELEASE)


@pytest.mark.parametrize(("result", "exit_code"), [
    ({"status": "success", "prepared": 1, "reused": 3, "busy": 0, "failed": 0, "kinds": [
        {"kind": "rail-stations-v1", "status": "prepared", "duration_ms": 4000, "artifact_id": "secret-ish-id"},
    ], "gc": {"expired_handles": 1, "unused_artifacts": 1, "duration_ms": 9}}, 0),
    # 5분 공항 수집의 준비와 겹친 종류(busy)는 실패가 아니지만 다 준비된 것도 아니다(5 = 미완료 경고).
    ({"status": "success", "prepared": 0, "reused": 3, "busy": 1, "failed": 0, "kinds": [
        {"kind": "rail-stations-v1", "status": "busy", "duration_ms": 5012, "error_type": "DBAPIError",
         "sqlstate": "55P03"},
    ], "gc": {"expired_handles": 0, "unused_artifacts": 0, "duration_ms": 3, "busy": True}}, 5),
    # 원천 미완결·예산 소진도 성공처럼 보이지 않게 미완료(5)다.
    ({"status": "not_ready", "prepared": 0, "reused": 0, "busy": 0, "deferred": 0, "failed": 0, "kinds": [
        {"kind": "rail-stations-v1", "status": "source_unavailable", "duration_ms": 9},
    ]}, 5),
    ({"status": "deferred", "prepared": 0, "reused": 0, "busy": 0, "deferred": 1, "failed": 0, "kinds": [
        {"kind": "ferry-ports-v1", "status": "deferred", "duration_ms": 0},
    ]}, 5),
    ({"status": "partial_success", "prepared": 0, "reused": 3, "busy": 0, "failed": 1, "kinds": [
        {"kind": "ferry-ports-v1", "status": "failed", "duration_ms": 9, "error_type": "HTTPException"},
    ]}, 1),
    ({"status": "disabled", "prepared": 0, "reused": 0, "busy": 0, "failed": 0, "kinds": []}, 0),
])
def test_prepare_module_prints_one_summary_line(monkeypatch, capsys, result, exit_code):
    from app.core import config
    from app.services import reference_export_preparation as prep

    async def fake_prepare(settings, *, kinds, total_budget_seconds):
        assert settings is _SETTINGS
        assert kinds == ("rail-stations-v1", "ferry-ports-v1")  # Map이 읽는 종류만
        assert total_budget_seconds == 20  # 바깥 상한(30초)보다 10초 먼저 끝낸다
        return result

    monkeypatch.setattr(config, "get_settings", lambda: _SETTINGS)
    monkeypatch.setattr(prep, "prepare_reference_exports_for_settings", fake_prepare)
    assert prepare_references.main(["--timeout-seconds", "30", "--expect-release-sha", RELEASE]) == exit_code
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1
    summary = json.loads(lines[0])
    assert summary["event"] == "reference_prepare_after_deploy" and summary["status"] == result["status"]
    assert "artifact_id" not in lines[0]
    assert all({"kind", "status", "duration_ms"} <= set(row) for row in summary["kinds"])
    assert summary["busy"] == result["busy"]


@pytest.mark.parametrize("local_release", ["fedcba9876543210fedcba9876543210fedcba98", "unknown", ""])
def test_prepare_module_skips_when_its_release_differs_from_the_api(monkeypatch, capsys, local_release):
    """code-server만 롤백됐거나 RELEASE_SHA 없이 떴으면 API가 읽지 않을 revision을 만들지 않는다(head 되돌림 방지)."""
    from app.core import config
    from app.services import reference_export_preparation as prep

    async def must_not_run(_settings, **_kwargs):
        raise AssertionError("release가 다르면 준비하지 않는다")

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(release_sha=local_release))
    monkeypatch.setattr(prep, "prepare_reference_exports_for_settings", must_not_run)
    code = prepare_references.main(["--timeout-seconds", "30", "--expect-release-sha", RELEASE])
    assert code == prepare_references.EXIT_RELEASE_MISMATCH == 4
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "release_mismatch" and summary["api_release_sha"] == RELEASE


def test_prepare_module_requires_a_plain_release_argument():
    with pytest.raises(SystemExit):
        prepare_references.main(["--timeout-seconds", "30"])
    with pytest.raises(SystemExit):
        prepare_references.main(["--expect-release-sha", "abc; rm -rf /"])
    with pytest.raises(SystemExit):
        prepare_references.main(["--timeout-seconds", "29", "--expect-release-sha", RELEASE])


def test_prepare_module_timeout_and_error_are_warnings_without_messages(monkeypatch, capsys):
    from app.core import config
    from app.services import reference_export_preparation as prep

    async def timed_out(_settings, **_kwargs):
        raise TimeoutError  # asyncio.wait_for 상한 초과와 같은 예외

    async def leaky(_settings, **_kwargs):
        raise RuntimeError("postgresql://user:password@127.0.0.1/db")

    monkeypatch.setattr(config, "get_settings", lambda: _SETTINGS)
    monkeypatch.setattr(prep, "prepare_reference_exports_for_settings", timed_out)
    args = ["--timeout-seconds", "30", "--expect-release-sha", RELEASE]
    assert prepare_references.main(args) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "timeout"
    monkeypatch.setattr(prep, "prepare_reference_exports_for_settings", leaky)
    assert prepare_references.main(args) == 1
    out = capsys.readouterr().out
    assert json.loads(out)["error_type"] == "RuntimeError" and "password" not in out


_FAKE_DOCKER = r'''
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "inspect" and "Config.Env" in sys.argv[3]:
    print("PATH=/opt/venv/bin:/usr/bin")
    print("RELEASE_SHA=" + os.environ.get("FAKE_CS_RELEASE", "0123456789abcdef0123456789abcdef01234567"))
    sys.exit(0)
if sys.argv[1] == "inspect":
    print("false" if os.environ.get("FAKE_STOPPED") == sys.argv[-1] else "true")
    sys.exit(0)
if sys.argv[1] == "exec" and "app.deploy.prepare_references" in sys.argv:
    print('{"event":"reference_prepare_after_deploy","status":"success"}')
    sys.exit(int(os.environ.get("FAKE_PREPARE_EXIT", "0")))
if sys.argv[1] == "exec" and "app.deploy.export_smoke" in sys.argv:
    print("GET /v1/service/exports/airports 200 3ms")
    sys.exit(int(os.environ.get("FAKE_SMOKE_EXIT", "0")))
sys.exit(9)
'''


_FAKE_CURL = r'''
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(["curl", *sys.argv[1:]]) + "\n")
if os.environ.get("FAKE_API_DOWN"):
    sys.exit(7)
assert sys.argv[-1] == "http://127.0.0.1:12302/health", sys.argv
print(json.dumps({"status": "ok", "database": "ready", "seeded": True,
                  "release_sha": os.environ.get("FAKE_API_RELEASE", "0123456789abcdef0123456789abcdef01234567")}))
'''


def _wrapper(tmp_path: Path, **env: str):
    if sys.platform == "win32":
        pytest.skip("POSIX bash wrapper 실행 검증(운영 Odroid·CI Linux)")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, body in (("docker", _FAKE_DOCKER), ("curl", _FAKE_CURL)):
        fake = bin_dir / name
        fake.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        fake.chmod(0o755)
    log = tmp_path / "docker.jsonl"
    log.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(_SCRIPTS / "post-deploy-warm.sh"), "--project", "kor-travel-transport", "--api-port", "12302"],
        capture_output=True, text=True, timeout=60, check=False,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_LOG": str(log), TOKEN_ENV_NAME: TOKEN, **env},
    )
    return result, [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


TOKEN_ENV_NAME = "TRANSPORT_SERVICE_EXPORT_TOKEN"


def test_wrapper_runs_prepare_in_code_server_then_smoke_in_backend(tmp_path: Path):
    result, calls = _wrapper(tmp_path)
    assert result.returncode == 0, result.stderr
    execs = [call for call in calls if call[0] == "exec"]
    assert execs[0][:2] == ["exec", "kor-travel-transport-dagster-code-server-1"]
    assert execs[0][2:] == ["python", "-I", "-B", "-m", "app.deploy.prepare_references", "--timeout-seconds", "180",
                            "--expect-release-sha", RELEASE]
    # 준비 전에 API health와 code-server의 RELEASE_SHA를 먼저 본다.
    first_exec = calls.index(execs[0])
    assert any(call[0] == "curl" for call in calls[:first_exec])
    assert any(call[0] == "inspect" and "Config.Env" in call[2] for call in calls[:first_exec])
    assert execs[1][:2] == ["exec", "kor-travel-transport-backend-1"]
    assert execs[1][2:7] == ["python", "-I", "-B", "-m", "app.deploy.export_smoke"]
    # 토큰은 argv로 넘기지 않는다(컨테이너 env에서 읽는다).
    assert all(TOKEN not in " ".join(call) for call in calls)
    assert "WARN" not in result.stderr


@pytest.mark.parametrize(("env", "warning"), [
    ({"FAKE_SMOKE_EXIT": "3"}, "configuration mismatch"),
    ({"FAKE_SMOKE_EXIT": "1"}, "a Map T3 first page was not 2xx"),
    ({"FAKE_SMOKE_EXIT": "4"}, "export smoke skipped"),
    ({"FAKE_SMOKE_EXIT": "5"}, "some T1 exports are not available"),
    ({"FAKE_PREPARE_EXIT": "1"}, "reference prepare did not fully succeed"),
    ({"FAKE_PREPARE_EXIT": "5"}, "reference prepare incomplete"),
    ({"FAKE_PREPARE_EXIT": "4"}, "settings release_sha differs from the API"),
    ({"FAKE_STOPPED": "kor-travel-transport-dagster-code-server-1"}, "reference prepare skipped"),
])
def test_wrapper_never_fails_the_deploy(tmp_path: Path, env: dict[str, str], warning: str):
    result, _calls = _wrapper(tmp_path, **env)
    assert result.returncode == 0
    assert warning in result.stderr


@pytest.mark.parametrize(("env", "warning"), [
    ({"FAKE_CS_RELEASE": "fedcba9876543210fedcba9876543210fedcba98"}, "release_sha mismatch: code-server fedcba98"),
    ({"FAKE_CS_RELEASE": "unknown"}, "release_sha mismatch: code-server unknown"),
    ({"FAKE_API_RELEASE": "unknown"}, "release_sha is unavailable"),
    ({"FAKE_API_DOWN": "1"}, "release_sha is unavailable"),
])
def test_wrapper_skips_prepare_unless_code_server_and_api_releases_match(tmp_path: Path, env, warning):
    result, calls = _wrapper(tmp_path, **env)
    assert result.returncode == 0
    assert warning in result.stderr and "reference prepare skipped" in result.stderr
    execs = [call for call in calls if call[0] == "exec"]
    assert all("app.deploy.prepare_references" not in call for call in execs)
    # 준비를 건너뛰어도 backend loopback smoke는 한다.
    assert any("app.deploy.export_smoke" in call for call in execs)


def test_deploy_scripts_do_not_warm_inside_the_deploy_lock():
    """warm은 배포 lock이 풀리고 소유 일정이 복원된 뒤 운영자가 부른다(lock 안에서 돌면 주차 수집 공백이 는다)."""
    for name in ("deploy-prod-remote.sh", "deploy-prod.sh"):
        path = _SCRIPTS / name
        if path.is_file():
            assert "post-deploy-warm" not in path.read_text(encoding="utf-8"), name


@pytest.mark.parametrize("args", [
    ["--project"], ["--api-port", "12302", "--request-timeout"],  # 값이 없는 flag(예전에는 무한 반복)
    ["--request-timeout", "0"], ["--request-timeout", "121"], ["--prepare-timeout", "29"],
    ["--prepare-timeout", "1801"], ["--api-port", "0"], ["--api-port", "65536"], ["--project", "Bad Name"],
    ["--unknown", "x"],
])
def test_wrapper_rejects_bad_arguments_quickly(tmp_path: Path, args):
    if sys.platform == "win32":
        pytest.skip("POSIX bash wrapper 실행 검증(운영 Odroid·CI Linux)")
    result = subprocess.run(["bash", str(_SCRIPTS / "post-deploy-warm.sh"), *args], capture_output=True, text=True,
                            timeout=10, check=False, env={"PATH": "/usr/bin:/bin"})
    assert result.returncode == 2 and "Usage" in result.stderr
