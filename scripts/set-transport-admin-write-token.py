"""n150 비추적 운영 환경에 관리자 쓰기 토큰을 한 번만 안전하게 추가한다."""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import tempfile
from datetime import UTC, datetime
from pathlib import Path


ENV_PATH = Path("/home/digitie/apps/kor-travel-transport/.env.server14")
BACKUP_DIR = Path("/home/digitie/backups/transport-config")
KEY = "TRANSPORT_ADMIN_WRITE_TOKEN"


def main() -> None:
    if socket.gethostname() != "digitie-at-n150" or not ENV_PATH.is_file():
        raise SystemExit("n150의 지정된 운영 환경 파일에서만 실행할 수 있습니다.")
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    found = [line.partition("=")[2] for line in lines if line.startswith(f"{KEY}=")]
    if len(found) > 1:
        raise SystemExit("쓰기 토큰 항목이 중복되어 자동 변경하지 않습니다.")
    if found and len(found[0]) >= 32:
        print("관리자 쓰기 토큰이 이미 설정되어 있습니다. 값을 표시하지 않습니다.")
        return
    if found and found[0]:
        raise SystemExit("기존 쓰기 토큰이 짧습니다. 수동 점검 후 재시도하세요.")

    BACKUP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"env-before-admin-write-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}.bak"
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as target, ENV_PATH.open("rb") as source:
        shutil.copyfileobj(source, target)
    token = secrets.token_urlsafe(48)
    updated = [f"{KEY}={token}" if line.startswith(f"{KEY}=") else line for line in lines]
    if not found:
        updated.append(f"{KEY}={token}")
    descriptor, temporary = tempfile.mkstemp(prefix=".env.server14.admin-write-", dir=ENV_PATH.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as target:
            target.write("\n".join(updated) + "\n")
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, ENV_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("관리자 쓰기 토큰을 설정하고 이전 환경을 0600 백업했습니다. 값은 표시하지 않습니다.")


if __name__ == "__main__":
    main()
