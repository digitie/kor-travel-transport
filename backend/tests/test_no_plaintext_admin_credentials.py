"""공개 저장소에 운영 관리자 자격증명을 평문으로 두지 않는다.

workflow는 관리자 로그인 비밀번호를 Actions secret 참조로만 받고, 예시 env 파일은 값을 비워 둔다.
(2026-10-27 live E2E workflow에 운영 비밀번호가 평문으로 들어가 있던 사고의 회귀 방지.)
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
# 관리자 UI 로그인·쓰기 토큰·세션 비밀처럼 운영값과 같아질 수 있는 키.
ADMIN_KEY = re.compile(r"\b(?:E2E_)?TRANSPORT_(?:UI_PASSWORD|ADMIN_WRITE_TOKEN|UI_SESSION_SECRET)\b")
SECRET_REF = re.compile(r"^\$\{\{\s*secrets\.[A-Z0-9_]+\s*\}\}$")
EXAMPLE_ENV_FILES = (
    ROOT / ".env.prod.example",
    ROOT / "packages" / "kor-travel-transport-admin" / "frontend" / ".env.example",
)


def _strip(value: str) -> str:
    return value.split(" #", 1)[0].strip().strip("\"'")


@pytest.mark.skipif(not WORKFLOWS.is_dir(), reason="저장소 checkout 밖(이미지 안)에서는 workflow가 없다")
def test_workflows_take_admin_credentials_only_from_secrets():
    offenders = []
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"^\s*([A-Z0-9_]+)\s*:\s*(.*)$", line)
            if not match or not ADMIN_KEY.fullmatch(match.group(1)):
                continue
            value = _strip(match.group(2))
            if value and not SECRET_REF.match(value):
                offenders.append(f"{path.relative_to(ROOT)}:{number} {match.group(1)}")
    assert not offenders, f"관리자 자격증명은 ${{{{ secrets.* }}}}로만 넘긴다: {offenders}"


def test_example_env_files_leave_admin_password_empty():
    checked = 0
    offenders = []
    for path in EXAMPLE_ENV_FILES:
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            key, sep, value = line.partition("=")
            if sep and key.strip() == "TRANSPORT_UI_PASSWORD":
                checked += 1
                if _strip(value):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")
    if not any(path.is_file() for path in EXAMPLE_ENV_FILES):
        pytest.skip("저장소 checkout 밖(이미지 안)에서는 예시 env 파일이 없다")
    assert checked, "예시 env 파일에서 TRANSPORT_UI_PASSWORD 줄을 찾지 못했다(검사 대상이 사라졌다)"
    assert not offenders, f"예시 env의 TRANSPORT_UI_PASSWORD는 비워 둔다: {offenders}"
