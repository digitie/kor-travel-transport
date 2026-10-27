"""실제 배포 entry/원격 효과 helper를 합성 command로 실행한다. 운영 연결은 없다."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
# 저장소 checkout은 `<repo>/backend/tests`·`<repo>/scripts`, Docker 회귀 이미지는 `/app/tests`·`/app/scripts`다.
ROOT = _BACKEND_ROOT if (_BACKEND_ROOT / "scripts" / "validate-deploy-host.py").is_file() else _BACKEND_ROOT.parent
HELPER = ROOT / "scripts/validate-deploy-host.py"
ADDR = "192.0.2.7"


@pytest.fixture(scope="module")
def module():
    """helper는 수집 시점이 아니라 쓰는 시험에서 읽는다 — layout 차이가 전체 수집 오류로 번지지 않는다."""
    spec = importlib.util.spec_from_file_location("deploy_host_effect", HELPER)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def document():
    return {
        "status": "ok",
        "targets": {"transport": {"host": "chosen"}},
        "hosts": {"chosen": {"addr": ADDR}},
    }


@pytest.mark.parametrize(
    "value",
    [
        "",
        "server.invalid",
        "::1",
        "192.0.2.999",
        "192.0.2.007",
        "-oProxyCommand=x",
        "192.0.2.7;touch /tmp/no",
    ],
)
def test_host_must_be_canonical_ipv4(module, value):
    with pytest.raises(ValueError):
        module.parse_host(value)


@pytest.mark.parametrize(
    "change",
    [
        "missing_hosts",
        "blank_key",
        "unknown_key",
        "wrong_address",
        "list_key",
        "not_ok",
    ],
)
def test_registry_output_has_no_address_fallback(module, change):
    value = document()
    if change == "missing_hosts":
        value.pop("hosts")
    elif change == "blank_key":
        value["targets"]["transport"]["host"] = ""
    elif change == "unknown_key":
        value["targets"]["transport"]["host"] = "unknown"
    elif change == "wrong_address":
        value["hosts"]["chosen"]["addr"] = "198.51.100.1"
    elif change == "list_key":
        value["targets"]["transport"]["host"] = ["chosen"]
    else:
        value["status"] = "error"
    assert not module.registry_matches(value, ADDR)


def test_declared_address_matches_the_selected_key_only(module):
    value = document()
    value["hosts"]["unrelated"] = {"addr": "203.0.113.1"}
    assert module.registry_matches(value, ADDR)
    assert not module.registry_matches(value, "203.0.113.1")


_COMMAND = r"""
import json,os,shlex,subprocess,sys
from pathlib import Path
name=Path(sys.argv[0]).name
with open(os.environ['CALLS'],'a')as f:f.write(json.dumps([name,*sys.argv[1:]])+'\n')
if name=='git':
 if sys.argv[1:]==['rev-parse','HEAD']:print('a'*40);raise SystemExit(0)
 if sys.argv[1:]==['ls-files','--error-unmatch','--','transport.override.yml']:print('transport.override.yml');raise SystemExit(0)
 raise SystemExit(97)
if name=='ssh':
 args=shlex.split(sys.argv[2])
 if args[:2]!=['python3','-']:raise SystemExit(97)
 if '--app-dir' in args:raise SystemExit(97)
 args[args.index('--env-file')+1]=os.environ['OWN_ENV']
 result=subprocess.run(args,input=sys.stdin.buffer.read())
 raise SystemExit(result.returncode)
if name=='hostname':print(os.environ.get('LOCAL_ADDRESSES','192.0.2.7 ::1'));raise SystemExit(0)
if name=='sudo':
 assert sys.argv[1:]==['-n','ktdctl','targets','validate','--json']
 if os.environ.get('SUDO_FAIL'):print('owned-sensitive-error',file=sys.stderr);raise SystemExit(int(os.environ['SUDO_FAIL']))
 print(os.environ['DOCUMENT']);raise SystemExit(0)
raise SystemExit(98)
"""


def run_entry(tmp_path, script, args, **changes):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for command in ("git", "ssh", "scp", "hostname", "sudo"):
        path = bindir / command
        path.write_text(f"#!{sys.executable}\n" + _COMMAND)
        path.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    envfile = tmp_path / ".env.prod"
    envfile.write_text("OWNED=fixture\n")
    env = {
        "PATH": str(bindir) + ":/usr/bin:/bin",
        "CALLS": str(calls),
        "OWN_ENV": str(envfile),
        "DOCUMENT": json.dumps(document()),
        **changes,
    }
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / script), *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result, [
        json.loads(line) for line in calls.read_text().splitlines()
    ] if calls.exists() else []


@pytest.mark.parametrize("script", ["deploy-prod.sh", "deploy-transport-admin-prod.sh"])
@pytest.mark.parametrize("args", [[], ["--host"], ["--host", "server.invalid"], ["--host", "-oProxyCommand=x"], ["--host", ADDR, "extra"]])
def test_missing_host_refuses_before_any_command(tmp_path, script, args):
    result, calls = run_entry(tmp_path, script, args)
    assert result.returncode == 2 and calls == []


@pytest.mark.parametrize("script", ["deploy-prod.sh", "deploy-transport-admin-prod.sh"])
@pytest.mark.parametrize(
    "failure",
    [
        "not_assigned",
        "manager_missing",
        "sudo_denied",
        "missing_hosts",
        "blank_key",
        "wrong_address",
        "unreadable_env",
    ],
)
def test_effect_failure_refuses_before_archive_or_copy(tmp_path, script, failure):
    value = document()
    changes = {}
    if failure == "not_assigned":
        changes["LOCAL_ADDRESSES"] = "198.51.100.90"
    elif failure == "manager_missing":
        changes["SUDO_FAIL"] = "127"
    elif failure == "sudo_denied":
        changes["SUDO_FAIL"] = "1"
    elif failure == "missing_hosts":
        value.pop("hosts")
    elif failure == "blank_key":
        value["targets"]["transport"]["host"] = ""
    elif failure == "wrong_address":
        value["hosts"]["chosen"]["addr"] = "198.51.100.90"
    else:
        changes["OWN_ENV"] = str(tmp_path / "absent")
    changes["DOCUMENT"] = json.dumps(value)
    result, calls = run_entry(tmp_path, script, ["--host", ADDR], **changes)
    assert result.returncode == 2
    assert [c[0] for c in calls].count("ssh") == 1
    assert not any(c[0] == "scp" or c[:2] == ["git", "archive"] for c in calls)
    assert "owned-sensitive-error" not in result.stdout + result.stderr


_REFUSAL = "배포 거절: IPv4/Manager registry/환경 파일 효과 검증에 실패했습니다."


def test_permission_denied_environment_is_not_accepted(module, monkeypatch, tmp_path, capsys):
    envfile = tmp_path / ".env.prod"
    envfile.write_text("OWNED=fixture\n")

    def run(argv, *, timeout):
        return ADDR if argv[0] == "hostname" else json.dumps(document())

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(module.os, "access", lambda *args: False)
    assert module.main(["--host", ADDR, "--env-file", str(envfile)]) == 2
    assert capsys.readouterr().err == f"{_REFUSAL} reason=env\n"


def test_manager_validation_allows_a_bounded_response_after_thirty_seconds(module, monkeypatch, tmp_path):
    envfile = tmp_path / ".env.prod"
    envfile.write_text("OWNED=fixture\n")
    calls = []

    def run(argv, *, timeout):
        calls.append((argv, timeout))
        if argv[0] == "hostname":
            return ADDR
        # 실제로 기다리지 않고 45초에 완료되는 Manager 응답을 재현한다.
        if timeout < 45:
            raise module.DeployHostError("timeout")
        return json.dumps(document())

    monkeypatch.setattr(module, "_run", run)
    assert module.main(["--host", ADDR, "--env-file", str(envfile)]) == 0
    assert calls == [
        (["hostname", "-I"], 15),
        (["sudo", "-n", "ktdctl", "targets", "validate", "--json"], 60),
    ]


class _HangingPopen:
    """`communicate`가 정해진 횟수만큼 시간 초과하는 가짜 프로세스. 신호 순서를 기록한다."""

    def __init__(self, events, timed_out_command, stops_after_terminate):
        self.events, self.timed_out_command, self.stops_after_terminate = events, timed_out_command, stops_after_terminate

    def __call__(self, argv, **kwargs):
        process = _HangingProcess(self, argv)
        self.events.append(("start", argv[0], kwargs.get("stdin")))
        return process


class _HangingProcess:
    def __init__(self, owner, argv):
        self.owner, self.argv, self.returncode, self.signals = owner, argv, None, []

    def communicate(self, timeout=None):
        self.owner.events.append(("communicate", self.argv[0], timeout))
        if self.argv[0] != self.owner.timed_out_command:
            self.returncode = 0
            return ADDR, ""
        hung = not self.signals or (self.signals == ["terminate"] and not self.owner.stops_after_terminate)
        if hung:
            raise subprocess.TimeoutExpired(self.argv, timeout, output="owned-sensitive-output", stderr="owned-sensitive-error")
        self.returncode = -15 if self.signals == ["terminate"] else -9
        return "owned-sensitive-output", "owned-sensitive-error"

    def terminate(self):
        self.signals.append("terminate")
        self.owner.events.append(("terminate", self.argv[0]))

    def kill(self):
        self.signals.append("kill")
        self.owner.events.append(("kill", self.argv[0]))


@pytest.mark.parametrize("stops_after_terminate", [True, False])
@pytest.mark.parametrize(("timed_out_command", "deadline"), [("hostname", 15), ("sudo", 60)])
def test_command_timeout_terminates_before_kill_and_reports_only_the_reason(
    module, monkeypatch, tmp_path, capsys, timed_out_command, deadline, stops_after_terminate,
):
    """시간 초과면 sudo가 root ktdctl에 전달하는 SIGTERM을 먼저 보내고, 그래도 안 끝나면 kill한다."""
    envfile = tmp_path / ".env.prod"
    envfile.write_text("OWNED=fixture\n")
    events = []

    def unread_environment(*args):
        pytest.fail("시간 초과 후 환경 파일 검사를 진행하면 안 된다")

    monkeypatch.setattr(module.subprocess, "Popen", _HangingPopen(events, timed_out_command, stops_after_terminate))
    monkeypatch.setattr(module.os, "access", unread_environment)
    assert module.main(["--host", ADDR, "--env-file", str(envfile)]) == 2
    timed_out = [event for event in events if event[1] == timed_out_command]
    expected = [("start", timed_out_command, subprocess.DEVNULL), ("communicate", timed_out_command, deadline),
                ("terminate", timed_out_command), ("communicate", timed_out_command, module.TERMINATE_GRACE_SECONDS)]
    if not stops_after_terminate:
        expected += [("kill", timed_out_command), ("communicate", timed_out_command, None)]
    assert timed_out == expected
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{_REFUSAL} reason=timeout\n"


@pytest.mark.parametrize(("failure", "reason"), [
    ("not_assigned", "address"), ("sudo_exit", "command"), ("invalid_json", "output"),
    ("other_host", "registry"), ("bad_host_argument", "address"),
])
def test_refusal_names_a_fixed_reason_without_values(module, monkeypatch, tmp_path, capsys, failure, reason):
    envfile = tmp_path / ".env.prod"
    envfile.write_text("OWNED=fixture\n")

    def run(argv, *, timeout):
        if argv[0] == "hostname":
            return "198.51.100.90" if failure == "not_assigned" else ADDR
        if failure == "sudo_exit":
            raise module.DeployHostError("command")
        if failure == "invalid_json":
            return "owned-sensitive-output"
        value = document()
        if failure == "other_host":
            value["hosts"]["chosen"]["addr"] = "198.51.100.90"
        return json.dumps(value)

    monkeypatch.setattr(module, "_run", run)
    host = "owned-sensitive-host" if failure == "bad_host_argument" else ADDR
    assert module.main(["--host", host, "--env-file", str(envfile)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"{_REFUSAL} reason={reason}\n"


@pytest.mark.parametrize("script", ["deploy-prod.sh", "deploy-transport-admin-prod.sh"])
def test_matching_effect_reaches_existing_next_step_only(tmp_path, script):
    result, calls = run_entry(tmp_path, script, ["--host", ADDR])
    assert (
        result.returncode == 97
    )  # 대역이 기존 archive 또는 admin preflight에서 중단한다.
    assert any(c[0] == "sudo" for c in calls)
    assert not any(c[0] == "scp" for c in calls)


def test_both_entries_and_direct_remote_use_the_same_effect_contract():
    for name in (
        "deploy-prod.sh",
        "deploy-prod-remote.sh",
        "deploy-transport-admin-prod.sh",
    ):
        text = (ROOT / "scripts" / name).read_text()
        assert "validate-deploy-host.py" in text and "--host" in text
        assert "REMOTE_HOST:-" not in text and "192.168.1.14" not in text
    assert {p.name for p in (ROOT / "scripts").glob("deploy-*.sh")} == {
        "deploy-prod.sh", "deploy-prod-remote.sh", "deploy-transport-admin-prod.sh"
    }


def test_backend_sync_preserves_old_and_new_environment_artifacts(tmp_path):
    import shutil

    if shutil.which("rsync") is None:
        pytest.skip("소유 임시 디렉터리의 rsync 계약에는 rsync 실행 파일이 필요하다")
    text = (ROOT / "scripts/deploy-prod.sh").read_text()
    start = text.index("rsync -a --delete")
    block = text[start:text.index('\ncd "${REMOTE_APP_DIR}"', start)]
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    protected = (
        ".env.prod", ".env.prod.legacy", ".env.prod.shared-dagster-cutover",
        ".env.server14", ".env.server14.legacy", ".env.server14.shared-dagster-cutover",
    )
    for name in protected:
        (destination / name).write_text("owned-preserve-" + name)
    (destination / "obsolete-owned.txt").write_text("owned stale")
    (source / "candidate.txt").write_text("owned candidate")
    result = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + block],
        env={"PATH": "/usr/bin:/bin", "REMOTE_ENV_FILE": ".env.prod", "REMOTE_SOURCE": str(source), "REMOTE_APP_DIR": str(destination)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (destination / "candidate.txt").read_text() == "owned candidate"
    assert not (destination / "obsolete-owned.txt").exists()
    for name in protected:
        assert (destination / name).read_text() == "owned-preserve-" + name
