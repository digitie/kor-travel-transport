"""공용 Dagster 합류의 펜스 전 가드(2026-10-03 적대 리뷰 H1·M2·M3).

- H1: code-server의 dagster는 공용 plane 호스트와 **같은 버전**이어야 한다. 높으면 공용 webserver가 unhealthy가 되어
  전 테넌트가 내려간다(버전 상한). 그래서 Dagster 계열을 정확히 고정하고(`pyproject.toml`·`uv.lock`), 배포 스크립트가
  빌드 직후 이미지의 버전을 공용 webserver의 버전과 대조한다.
- M2: Manager 전환은 code-server만 다시 만들고 Alembic migrate를 돌리지 않는다 — prepare가 운영 DB가 이 release의
  head인지 본다.
- M3: 운영 UI 배포는 `TRANSPORT_DAGSTER_INTERNAL_URL`이 비었거나 공용 webserver(11002)일 때만 한다.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = next(
    (candidate for candidate in (_BACKEND_ROOT / "scripts", _BACKEND_ROOT.parent / "scripts")
     if (candidate / "deploy-server14-remote.sh").is_file()),
    _BACKEND_ROOT.parent / "scripts",
)
_REMOTE = _SCRIPTS / "deploy-server14-remote.sh"
_ADMIN = _SCRIPTS / "deploy-transport-admin-server14.sh"
_DAGSTER_FAMILY = ("dagster", "dagster-postgres", "dagster-webserver")


def _function(text: str, name: str) -> str:
    start = text.index(f"{name}() {{\n")
    return text[start : text.index("\n}\n", start) + 3]


# ── H1 ──────────────────────────────────────────────────────────────────


def test_the_dagster_family_is_pinned_exactly_and_the_lock_agrees() -> None:
    pyproject = tomllib.loads((_BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pins: dict[str, str] = {}
    for requirement in pyproject["project"]["dependencies"]:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*(.*)", requirement)
        assert match
        if match.group(1).lower() in _DAGSTER_FAMILY:
            pins[match.group(1).lower()] = match.group(2)
    assert set(pins) == set(_DAGSTER_FAMILY), pins
    for name, spec in pins.items():
        assert re.fullmatch(r"==\d+\.\d+\.\d+", spec), f"{name}{spec}는 정확한 고정(==)이 아니다"
    lock = tomllib.loads((_BACKEND_ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = {package["name"]: package["version"] for package in lock["package"]}
    for name, spec in pins.items():
        assert locked[name] == spec[2:], (name, locked[name], spec)
    # dagster 1.x와 dagster-postgres 0.(x+16)는 같은 release다 — 패치가 같아야 한다.
    assert pins["dagster"] == pins["dagster-webserver"]
    assert pins["dagster"].rsplit(".", 1)[1] == pins["dagster-postgres"].rsplit(".", 1)[1]


def _version_guard() -> str:
    text = _REMOTE.read_text(encoding="utf-8")
    start = text.index('image_version="$(image_dagster_version)"')
    return text[start : text.index("\nfi\n", start) + 4]


@pytest.mark.parametrize(
    ("image", "host", "code", "said"),
    [
        ("1.13.25", "1.13.24", 2, "has dagster 1.13.25, the shared Dagster plane runs 1.13.24"),
        ("1.13.23", "1.13.24", 2, "has dagster 1.13.23"),
        ("1.13.24", "1.13.24", 0, "PASSED"),
    ],
)
def test_deploy_refuses_an_image_whose_dagster_differs_from_the_shared_plane(
    image: str, host: str, code: int, said: str
) -> None:
    script = (
        "BACKEND_RUNTIME_IMAGE=kor-travel-transport-backend:rel-x\n"
        f"image_dagster_version() {{ echo {image}; }}\nshared_dagster_version() {{ echo {host}; }}\n"
        + _version_guard() + "echo PASSED\n"
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == code, result.stderr
    assert said in result.stdout + result.stderr


def test_the_version_guard_runs_after_the_build_and_before_any_container_change() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    build = text.index("\ncompose build\n")
    guard = text.index('image_version="$(image_dagster_version)"')
    prepare = text.index('if [[ "${DEPLOY_MODE}" == "prepare-shared-dagster-cutover" ]]; then')
    up = text.index("\ncompose up -d --no-build\n")
    assert build < guard < prepare < up
    image = _function(text, "image_dagster_version")
    assert "--network none" in image and 'm.version("dagster")' in image
    assert '{"query":"{ version }"}' in _function(text, "shared_dagster_version")


# ── M2 ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("current", "at_head"),
    [("0023_rest_area_fuel (head)\n", True), ("0022_fuel_latest_prices\n", False), ("", False)],
)
def test_prepare_requires_the_database_at_the_release_head(current: str, at_head: bool) -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    script = (
        f"compose() {{ printf '%s' {current!r}; }}\n" + _function(text, "database_at_release_head")
        + "database_at_release_head\n"
    )
    result = subprocess.run(["bash", "-c", "set -o pipefail\n" + script], capture_output=True, text=True, check=False)
    assert (result.returncode == 0) is at_head, result.stderr
    assert "compose run --rm --no-deps -T migrate alembic current" in text


def test_prepare_checks_the_head_before_it_writes_the_cutover_env() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    block = text[text.index('if [[ "${DEPLOY_MODE}" == "prepare-shared-dagster-cutover" ]]; then') :]
    assert block.index("database_at_release_head ||") < block.index('cutover_env_tmp="$(mktemp')


# ── M3 ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("line", "code"),
    [
        ("TRANSPORT_DAGSTER_INTERNAL_URL=http://127.0.0.1:14004\n", 2),
        ("TRANSPORT_DAGSTER_INTERNAL_URL=http://127.0.0.1:12302\n", 2),
        ("TRANSPORT_DAGSTER_INTERNAL_URL=http://127.0.0.1:11002\n", 0),
        ('TRANSPORT_DAGSTER_INTERNAL_URL="http://127.0.0.1:11002"\n', 0),
        ("", 0),
    ],
)
def test_admin_deploy_requires_the_shared_dagster_url_or_none(tmp_path: Path, line: str, code: int) -> None:
    text = _ADMIN.read_text(encoding="utf-8")
    start = text.index('dagster_url="$(')
    guard = text[start : text.index("unset dagster_url\n", start) + len("unset dagster_url\n")]
    (tmp_path / ".env.server14").write_text("OTHER=1\n" + line, encoding="utf-8")
    script = f"set -euo pipefail\nREMOTE_APP_DIR={tmp_path}\nREMOTE_ENV_FILE=.env.server14\n" + guard + "echo PASSED\n"
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == code, result.stderr
    assert ("PASSED" in result.stdout) is (code == 0)
    # preflight(복사·빌드 전)에 있다.
    assert start < text.index("PREFLIGHT\n", text.index("<<'PREFLIGHT'") + 1)
