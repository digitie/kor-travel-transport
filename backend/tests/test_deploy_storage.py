"""NVMe staging은 실제 경로·장치·mount 증거를 모두 요구한다."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND if (BACKEND / "scripts").is_dir() else BACKEND.parent
spec = importlib.util.spec_from_file_location("deploy_storage", ROOT / "scripts/prepare-deploy-storage.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def storage(tmp_path, monkeypatch):
    nvme = tmp_path / "nvme"
    app = nvme / "app"
    build = nvme / "build"
    app.mkdir(parents=True)
    build.mkdir()
    (app / ".env.prod").write_text("FIXTURE=1\n")
    link = tmp_path / "approved"
    link.symlink_to(app, target_is_directory=True)
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        # 디렉터리/권한 확인은 실제 파일, 장치번호만 합성한다.
        values = list(result)
        values[2] = 1 if path == Path("/") else 2
        return type(result)(values)

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "/dev/nvme0n1[/build]\n", ""))
    return link, nvme, build


def test_nvme_symlink_checkout_is_accepted(storage):
    assert module.validate_storage(*storage) == storage[2]


@pytest.mark.parametrize("escape", ["app", "build", "env"])
def test_other_device_is_rejected(storage, tmp_path, monkeypatch, escape):
    app, nvme, build = storage
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / ".env.prod").write_text("FIXTURE=1")
    original = Path.stat
    def other_device(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        values = list(result)
        if path == outside or path.is_relative_to(outside):
            values[2] = 3
        return type(result)(values)
    monkeypatch.setattr(Path, "stat", other_device)
    if escape == "app":
        app.unlink()
        app.symlink_to(outside, target_is_directory=True)
    elif escape == "env":
        target = outside / ".env.prod"
        target.write_text("FIXTURE=1")
        (app / ".env.prod").unlink()
        (app / ".env.prod").symlink_to(target)
    else:
        build.rmdir()
        build.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="device"):
        module.validate_storage(app, nvme, build)


def test_root_filesystem_is_rejected(storage, monkeypatch):
    original = Path.stat
    def stat(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        values = list(result)
        values[2] = 1
        return type(result)(values)
    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(ValueError, match="device"):
        module.validate_storage(*storage)


def test_non_nvme_mount_is_rejected(storage, monkeypatch):
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "/dev/mmcblk0p2", ""))
    with pytest.raises(ValueError, match="NVMe"):
        module.validate_storage(*storage)


def test_check_only_creates_nothing_and_creation_is_owned(storage, monkeypatch):
    app, nvme, build = storage
    monkeypatch.setattr(module, "APP", app)
    monkeypatch.setattr(module, "NVME", nvme)
    monkeypatch.setattr(module, "BUILD", build)
    assert module.main(["--app-dir", str(app), "--check-only"]) == 0
    assert list(build.iterdir()) == []
    assert module.main(["--app-dir", str(app)]) == 0
    children = list(build.iterdir())
    assert len(children) == 1 and children[0].name.startswith("transport-deploy.")
    assert children[0].stat().st_mode & 0o777 == 0o700


def test_unapproved_directory_is_rejected_before_any_creation(tmp_path):
    assert module.main(["--app-dir", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == []


def test_remote_working_directory_guard_accepts_only_resolved_checkout(tmp_path):
    script = (ROOT / "scripts/deploy-prod-remote.sh").read_text()
    start = script.index('if [[ "$(pwd -P)"')
    block = script[start:script.index("\nfi", start) + 3]
    actual = tmp_path / "nvme-app"
    actual.mkdir()
    (actual / ".env.prod").write_text("FIXTURE=1\n")
    link = tmp_path / "approved"
    link.symlink_to(actual, target_is_directory=True)
    env = {"PATH": "/usr/bin:/bin", "REMOTE_APP_DIR": str(link), "REMOTE_ENV_FILE": ".env.prod"}
    good = subprocess.run(["bash", "-c", block], cwd=actual, env=env, capture_output=True, text=True)
    assert good.returncode == 0
    bad = subprocess.run(["bash", "-c", block], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert bad.returncode == 2


def test_remote_archive_and_extract_never_use_system_tmp():
    backend = (ROOT / "scripts/deploy-prod.sh").read_text()
    admin = (ROOT / "scripts/deploy-transport-admin-prod.sh").read_text()
    assert 'REMOTE_ARCHIVE="/tmp/' not in backend
    assert 'remote_archive="/tmp/' not in admin
    assert "mktemp -d /tmp/" not in backend + admin
    assert "prepare-deploy-storage.py" in backend and "prepare-deploy-storage.py" in admin
    assert "/mnt/media/kor-travel/build/transport-deploy" in backend + admin

def test_bind_mount_checkout_outside_nvme_prefix_is_accepted(storage, tmp_path):
    app, nvme, build = storage
    bound = tmp_path / "bound-app"
    bound.mkdir()
    (bound / ".env.prod").write_text("FIXTURE=1")
    app.unlink()
    app.symlink_to(bound, target_is_directory=True)
    assert module.validate_storage(app, nvme, build) == build

