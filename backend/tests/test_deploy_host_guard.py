"""실제 배포 entry/원격 효과 helper를 합성 command로 실행한다. 운영 연결은 없다."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/validate-deploy-host.py"
spec = importlib.util.spec_from_file_location("deploy_host_effect", HELPER)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ADDR = "192.0.2.7"


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
def test_host_must_be_canonical_ipv4(value):
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
def test_registry_output_has_no_address_fallback(change):
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


def test_declared_address_matches_the_selected_key_only():
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
 raise SystemExit(97)
if name=='ssh':
 args=shlex.split(sys.argv[2])
 if args[:2]!=['python3','-']:raise SystemExit(97)
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


def test_permission_denied_environment_is_not_accepted(monkeypatch, tmp_path):
    envfile = tmp_path / ".env.prod"
    envfile.write_text("OWNED=fixture\n")

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 0, ADDR if argv[0] == "hostname" else json.dumps(document()), ""
        )

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.os, "access", lambda *args: False)
    assert module.main(["--host", ADDR, "--env-file", str(envfile)]) == 2


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
        env={"PATH": "/usr/bin:/bin", "REMOTE_ENV_FILE": ".env.prod", "REMOTE_STAGE": str(source), "REMOTE_APP_DIR": str(destination)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (destination / "candidate.txt").read_text() == "owned candidate"
    assert not (destination / "obsolete-owned.txt").exists()
    for name in protected:
        assert (destination / name).read_text() == "owned-preserve-" + name
