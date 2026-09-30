"""운영 쓰기 토큰 부트스트랩은 비밀값을 출력하지 않고 재실행에 안전해야 한다."""

import importlib.util
import os
from pathlib import Path

import pytest


def _module():
    path = Path(__file__).parents[2] / "scripts" / "set-transport-admin-write-token.py"
    if not path.exists():
        path = Path("/app/scripts/set-transport-admin-write-token.py")
    spec = importlib.util.spec_from_file_location("set_transport_admin_write_token", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_admin_write_token_bootstrap_is_atomic_idempotent_and_quiet(tmp_path, monkeypatch, capsys):
    module = _module()
    env = tmp_path / ".env.server14"
    env.write_text("TRANSPORT_UI_PASSWORD=ad.min\n", encoding="utf-8")
    module.ENV_PATH = env
    module.BACKUP_DIR = tmp_path / "backups"
    monkeypatch.setattr(module.socket, "gethostname", lambda: "digitie-at-n150")
    module.main()
    lines = env.read_text(encoding="utf-8").splitlines()
    token = next(line.partition("=")[2] for line in lines if line.startswith("TRANSPORT_ADMIN_WRITE_TOKEN="))
    assert len(token) >= 32
    assert token not in capsys.readouterr().out
    assert os.stat(env).st_mode & 0o777 == 0o600
    backups = list(module.BACKUP_DIR.glob("*.bak"))
    assert len(backups) == 1
    assert os.stat(backups[0]).st_mode & 0o777 == 0o600
    module.main()
    assert env.read_text(encoding="utf-8").count("TRANSPORT_ADMIN_WRITE_TOKEN=") == 1
    assert len(list(module.BACKUP_DIR.glob("*.bak"))) == 1


def test_admin_write_token_bootstrap_rejects_other_host(tmp_path, monkeypatch):
    module = _module()
    module.ENV_PATH = tmp_path / ".env.server14"
    module.ENV_PATH.write_text("TRANSPORT_UI_PASSWORD=ad.min\n", encoding="utf-8")
    monkeypatch.setattr(module.socket, "gethostname", lambda: "wrong-host")
    with pytest.raises(SystemExit, match="n150"):
        module.main()
