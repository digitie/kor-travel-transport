#!/usr/bin/env python3
"""운영 배포 임시 파일을 검증한 NVMe의 전용 디렉터리에만 만든다."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import sys

APP = Path("/home/digitie/apps/kor-travel-transport")
NVME = Path("/mnt/media")
BUILD = NVME / "kor-travel/build"


def validate_storage(app: Path, nvme: Path, build: Path) -> Path:
    resolved = app.resolve(strict=True)
    root = nvme.resolve(strict=True)
    stage_root = build.resolve(strict=True)
    if not resolved.is_dir() or not stage_root.is_dir():
        raise ValueError("required directories absent")
    environment = (resolved / ".env.prod").resolve(strict=True)
    if not environment.is_file():
        raise ValueError("environment absent")
    device = root.stat().st_dev
    if any(path.stat().st_dev != device for path in (resolved, stage_root, environment)) or device == Path("/").stat().st_dev:
        raise ValueError("wrong storage device")
    # bind mount는 realpath에 NVMe 경로가 드러나지 않으므로 장치와 mount를 확인한다.
    for path in (root, resolved, stage_root, environment):
        mount = subprocess.run(
            ["findmnt", "-T", str(path), "-n", "-o", "SOURCE"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        if not mount.startswith("/dev/nvme"):
            raise ValueError("NVMe unavailable")
    if not os.access(stage_root, os.W_OK | os.X_OK):
        raise ValueError("NVMe unavailable")
    return build


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.app_dir != str(APP):
            raise ValueError("unapproved app directory")
        root = validate_storage(APP, NVME, BUILD)
        if not args.check_only:
            # mkdtemp는 기존 경로를 재사용하지 않으며 mode0700으로 만든다.
            print(tempfile.mkdtemp(prefix="transport-deploy.", dir=root))
    except (OSError, ValueError, subprocess.SubprocessError):
        print("배포 거절: 승인된 checkout과 NVMe staging 효과 검증 실패.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
