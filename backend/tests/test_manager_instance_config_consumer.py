"""Manager 정본 metadata 소비와 원격 caller의 실패 경계를 운영 연결 없이 검증한다."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("instance_consumer", ROOT / "scripts/validate-deploy-host.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)
ADDR = "192.0.2.7"


def registry():
    return {"status": "ok", "targets": {"transport": {"host": "chosen"}}, "hosts": {"chosen": {"addr": ADDR}}}


def shown():
    return {"host": "chosen", "max_concurrent_runs": 5, "path": "/example/manager-owned/dagster.yaml", "sha256": "a" * 64}


@pytest.mark.parametrize("maximum", [5, 6])
def test_positive_policy_is_manager_owned(maximum):
    value = shown()
    value["max_concurrent_runs"] = maximum
    assert helper.instance_config_matches(value, registry())


@pytest.mark.parametrize("change", [
    {"max_concurrent_runs": True}, {"max_concurrent_runs": 0}, {"max_concurrent_runs": -1},
    {"max_concurrent_runs": 5.0}, {"max_concurrent_runs": "5"}, {"host": "elsewhere"},
    {"path": "relative.yaml"}, {"path": "//example/dagster.yaml"}, {"path": "/example/../dagster.yaml"}, {"path": "/example//dagster.yaml"},
    {"path": "/example/./dagster.yaml"}, {"path": "/example/dagster.yaml/"},
    {"path": "/example/a:rw"}, {"path": "/example/${override}.yaml"}, {"path": "/example/a\n"},
    {"path": "/example/a\\b"}, {"sha256": "a" * 16}, {"sha256": "A" * 64}, {"unknown": 1},
])
def test_unknown_or_unsafe_instance_metadata_fails(change):
    value = shown()
    value.update(change)
    assert not helper.instance_config_matches(value, registry())


@pytest.mark.parametrize("key", list(shown()))
def test_every_canonical_field_is_required(key):
    value = shown()
    value.pop(key)
    assert not helper.instance_config_matches(value, registry())


def test_show_uses_exact_cli_and_no_prepare_or_local_config_read(monkeypatch, tmp_path):
    envfile = tmp_path / ".env.prod"
    envfile.write_text("OWNED=fixture\n")
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["timeout"] in (15, 30) and kwargs["check"]
        stdout = ADDR if argv == ["hostname", "-I"] else json.dumps(
            shown() if "dagster-instance-config" in argv else registry()
        )
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    monkeypatch.setattr(helper.subprocess, "run", run)
    assert helper.validate_remote(ADDR, envfile, instance_config=True) == shown()
    assert calls == [["hostname", "-I"], ["sudo", "-n", "ktdctl", "targets", "validate", "--json"],
                     ["sudo", "-n", "ktdctl", "dagster-instance-config", "show", "--json"]]
    # 합성 정본 path는 실제 존재하지 않는다. 일반 계정의 별도 file read를 요구하지 않는다.
    assert not Path(shown()["path"]).exists()


@pytest.mark.parametrize("failure", ["exit", "timeout", "invalid", "duplicate", "oversize", "mismatch"])
def test_show_failure_has_fixed_error_without_raw_output(monkeypatch, tmp_path, capsys, failure):
    envfile = tmp_path / ".env.prod"
    envfile.write_text("OWNED=fixture\n")

    def run(argv, **kwargs):
        if argv == ["hostname", "-I"]:
            return subprocess.CompletedProcess(argv, 0, ADDR, "")
        if "targets" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps(registry()), "")
        if failure == "exit":
            raise subprocess.CalledProcessError(2, argv, output="sensitive-sentinel", stderr="sensitive-sentinel")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(argv, 30, output="sensitive-sentinel")
        value = shown()
        if failure == "mismatch":
            value["host"] = "sensitive-sentinel"
        raw = {"invalid": "sensitive-sentinel", "duplicate": '{"host":"x","host":"sensitive-sentinel"}',
               "oversize": " " * 16385}.get(failure, json.dumps(value))
        return subprocess.CompletedProcess(argv, 0, raw, "sensitive-sentinel")

    monkeypatch.setattr(helper.subprocess, "run", run)
    assert helper.main(["--host", ADDR, "--env-file", str(envfile), "--instance-config"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "sensitive-sentinel" not in output.err


def test_parse_only_cannot_bypass_manager_show(capsys):
    assert helper.main(["--host", ADDR, "--parse-only", "--instance-config"]) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("override,change,expected", [(None, False, 0), ("canonical", False, 0), ("/wrong.yaml", False, 2), (None, True, 2)])
def test_actual_binding_rejects_override_and_changed_show(tmp_path, override, change, expected):
    text = (ROOT / "scripts/deploy-prod-remote.sh").read_text()
    start = text.index("# 공식 배포는 호스트별 Manager 정본만 소비한다.")
    block = text[start:text.index('RUNTIME_ENV_FILE="$(mktemp', start)]
    bindir = tmp_path / "bin"
    bindir.mkdir()
    sudo = bindir / "sudo"
    sudo.write_text(f"#!{sys.executable}\n" +
        "import json,os,sys\nfrom pathlib import Path\n"
        "a=sys.argv[1:]\n"
        "assert a in (['-n','ktdctl','targets','validate','--json'],['-n','ktdctl','dagster-instance-config','show','--json'])\n"
        "if 'targets' in a: print(os.environ['REGISTRY']);raise SystemExit(0)\n"
        "p=Path(os.environ['COUNTER']);n=int(p.read_text()) if p.exists() else 0;p.write_text(str(n+1))\n"
        "d=json.loads(os.environ['SHOWN'])\n"
        "if n and os.environ['CHANGE']=='1':d['sha256']='b'*64\n"
        "print(json.dumps(d))\n")
    sudo.chmod(0o755)
    hostname = bindir / "hostname"
    hostname.write_text("#!/bin/sh\nprintf '%s\\n' 192.0.2.7\n")
    hostname.chmod(0o755)
    envfile = tmp_path / ".env.prod"
    envfile.write_text("OWNED=fixture\n")
    env = {"PATH": str(bindir) + ":/usr/bin:/bin", "SCRIPT_DIR": str(ROOT / "scripts"),
           "REMOTE_HOST": ADDR, "REMOTE_APP_DIR": str(tmp_path), "REMOTE_ENV_FILE": ".env.prod",
           "REGISTRY": json.dumps(registry()), "SHOWN": json.dumps(shown()),
           "COUNTER": str(tmp_path / "count"), "CHANGE": "1" if change else "0"}
    if override:
        env["KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG"] = shown()["path"] if override == "canonical" else override
    result = subprocess.run(["bash", "-c", "set -euo pipefail\n" + block +
                             "verify_manager_instance_config\nprintf '%s' \"$KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG\"\n"],
                            env=env, capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == expected
    assert result.stdout == (shown()["path"] if expected == 0 else "")
    assert "/wrong.yaml" not in result.stderr and "b" * 64 not in result.stderr


def test_revalidation_precedes_mutation_and_rollback_and_keeps_prepare_readonly():
    text = (ROOT / "scripts/deploy-prod-remote.sh").read_text()
    source = text.index('source "${REMOTE_ENV_FILE}"')
    bind = text.index('MANAGER_INSTANCE_CONFIG_JSON="$(manager_instance_config)"')
    assert source < bind < text.index("\ninstall_transport_override\n") < text.index("\ncompose build\n")
    assert "capture_previous_code_server_image\nverify_manager_instance_config || exit 2\nDEPLOYMENT_REPLACEMENT_STARTED=true" in text
    assert "rollback_dagster_code_server() {\n  verify_manager_instance_config || return 2" in text
    assert 'verify_manager_instance_config || exit 2\n  cutover_env_tmp=' in text
    assert "dagster-instance-config prepare" not in text
