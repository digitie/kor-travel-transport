"""Manager current release 표식(Manager ADR-60)을 두 배포 스크립트가 쓰는 방식.

- 교체 전 verify가 exit 0이 아니면(drift·표식 없음·CLI 없음) 멈춘다.
- health 뒤에만 adopt --replace-current로 실제 실행 이미지를 발행한다.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = next(
    (candidate for candidate in (_BACKEND_ROOT / "scripts", _BACKEND_ROOT.parent / "scripts")
     if (candidate / "manager-release-pointer.sh").is_file()),
    _BACKEND_ROOT.parent / "scripts",
)
_HELPER = _SCRIPTS / "manager-release-pointer.sh"
_ID = "sha256:" + "b" * 64

_FAKE_SUDO = r'''
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
action = sys.argv[4] if len(sys.argv) > 4 else ""
if action == "show":
    print(json.dumps({"groups": {"core": {"oneshot_images": {"migrate": os.environ["FAKE_MIGRATE"]}}}}))
    sys.exit(0)
print(json.dumps({"result": "fake"}))
sys.exit(int(os.environ.get("FAKE_EXIT_" + action.upper(), "0")))
'''


def _call(tmp_path: Path, script: str, **env: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    sudo = bin_dir / "sudo"
    sudo.write_text(f"#!{sys.executable}\n{_FAKE_SUDO}", encoding="utf-8")
    sudo.chmod(0o755)
    log = tmp_path / "sudo.jsonl"
    log.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", f'set -euo pipefail; source "$1"; {script}', "_", str(_HELPER)],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "FAKE_LOG": str(log), "FAKE_MIGRATE": _ID, **env},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return result, [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_in_sync_pointer_lets_the_deploy_continue(tmp_path: Path) -> None:
    result, calls = _call(tmp_path, "require_release_pointer_in_sync")
    assert result.returncode == 0, result.stderr
    assert calls == [["-n", "ktdctl", "service-release", "verify", "transport", "--json"]]


@pytest.mark.parametrize(("code", "message"), [("1", "drift"), ("2", "cannot verify"), ("127", "cannot verify")])
def test_drift_or_unverifiable_pointer_stops_the_deploy(tmp_path: Path, code: str, message: str) -> None:
    result, _ = _call(tmp_path, "require_release_pointer_in_sync", FAKE_EXIT_VERIFY=code)
    assert result.returncode == 2
    assert message in result.stderr


def test_publish_records_the_runtime_with_the_explicit_migrate_id(tmp_path: Path) -> None:
    result, calls = _call(tmp_path, f'publish_release_pointer "{_ID}"')
    assert result.returncode == 0, result.stderr
    assert calls == [["-n", "ktdctl", "service-release", "adopt", "transport", "--confirm",
                      "--replace-current", "--oneshot-image", f"migrate={_ID}"]]


@pytest.mark.parametrize("bad", ["", "kor-travel-transport-backend:rel-abc", "sha256:short"])
def test_publish_refuses_a_non_id_before_calling_the_manager(tmp_path: Path, bad: str) -> None:
    result, calls = _call(tmp_path, f'publish_release_pointer "{bad}"')
    assert result.returncode == 2
    assert calls == []


def test_failed_publish_is_loud_and_prints_the_rerun_command(tmp_path: Path) -> None:
    result, _ = _call(tmp_path, f'publish_release_pointer "{_ID}"', FAKE_EXIT_ADOPT="2")
    assert result.returncode == 2
    assert "NOT published" in result.stderr
    assert f"migrate={_ID}" in result.stderr


def test_admin_reuses_the_current_migrate_id(tmp_path: Path) -> None:
    result, calls = _call(tmp_path, 'publish_release_pointer "$(current_migrate_image_id)"')
    assert result.returncode == 0, result.stderr
    assert calls[-1][-1] == f"migrate={_ID}"


def test_backend_deploy_verifies_before_any_change_and_publishes_only_after_health() -> None:
    remote = (_SCRIPTS / "deploy-prod-remote.sh").read_text(encoding="utf-8")
    check = remote.index("  require_release_pointer_in_sync || exit 2")
    assert check < remote.index("\ninstall_transport_override\n")
    assert check < remote.index("\ncompose build\n")
    assert check < remote.index("DEPLOYMENT_REPLACEMENT_STARTED=true")
    publish = remote.index('publish_release_pointer "${migrate_image_id}"')
    assert remote.index("\nDEPLOYMENT_VERIFIED=true\n") < publish
    assert remote.rindex("frontend did not become ready") < publish


def test_admin_deploy_verifies_before_sync_and_publishes_only_after_health() -> None:
    admin = (_SCRIPTS / "deploy-transport-admin-prod.sh").read_text(encoding="utf-8")
    check = admin.index("require_release_pointer_in_sync || exit 2")
    assert check < admin.index("rsync -a --exclude=")
    assert check < admin.index("up -d --build --force-recreate")
    publish = admin.index('publish_release_pointer "$(current_migrate_image_id)"')
    assert admin.index("health check 시간 초과") < publish
