"""`scripts/deploy-server14-remote.sh`의 개명 관련 계약을 진짜 스크립트로 본다.

- 임시 guard: 개명 전 `kor-travel-airport` project 컨테이너가 하나라도 떠 있으면 새 project를 올리지
  않는다(두 host-network 스택, 같은 metadata DB의 두 dagster-daemon). guard는 디렉터리 검사 전에 돌므로
  CI에서도 진짜 스크립트를 실행해 볼 수 있다. guard를 통과하면 다음 검사(승인된 디렉터리)에서 멈춘다.
- `DAGSTER_POSTGRES_URL`은 운영 env 그대로의 `postgresql+psycopg2://`도 받는다.
- 백엔드 계열 이미지는 release마다 `kor-travel-transport-backend:rel-<sha12>`를 셸 env로 받는다.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = next(
    (candidate for candidate in (_BACKEND_ROOT / "scripts", _BACKEND_ROOT.parent / "scripts") if candidate.is_dir()),
    _BACKEND_ROOT.parent / "scripts",
)
_REMOTE = _SCRIPTS / "deploy-server14-remote.sh"
_SHA = "c" * 40

_FAKE_DOCKER = r'''
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
if sys.argv[1] == "ps":
    if os.environ.get("FAKE_PS_EXIT"):
        print("Cannot connect to the Docker daemon", file=sys.stderr)
        sys.exit(int(os.environ["FAKE_PS_EXIT"]))
    sys.stdout.write(os.environ.get("FAKE_PS_OUTPUT", ""))
    sys.exit(0)
print(f"fake docker: unexpected {sys.argv[1:]}", file=sys.stderr)
sys.exit(3)
'''


def _run(tmp_path: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(f"#!{sys.executable}\n{_FAKE_DOCKER}", encoding="utf-8")
    docker.chmod(0o755)
    log = tmp_path / "docker.jsonl"
    log.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(_REMOTE)],
        cwd=tmp_path,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin", "CANDIDATE_SHA": _SHA, "FAKE_LOG": str(log), **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


_GUARD_CALL = ["ps", "-q", "--filter", "label=com.docker.compose.project=kor-travel-airport"]


def test_deploy_refuses_while_a_pre_rename_container_runs(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, FAKE_PS_OUTPUT="0123456789ab\n")
    assert result.returncode == 2
    assert "pre-rename kor-travel-airport project still runs containers" in result.stderr
    assert calls == [_GUARD_CALL]  # compose도, 다른 docker 명령도 부르지 않았다.


def test_deploy_passes_the_guard_when_no_pre_rename_container_runs(tmp_path: Path) -> None:
    result, calls = _run(tmp_path)
    # guard 다음 검사(승인된 디렉터리에서 실행하는가)에서 멈춘다. 테스트 디렉터리는 승인된 디렉터리가 아니다.
    assert result.returncode == 2
    assert "run from the staged approved app directory" in result.stderr
    assert calls == [_GUARD_CALL]


def test_deploy_refuses_when_docker_cannot_list_containers(tmp_path: Path) -> None:
    result, calls = _run(tmp_path, FAKE_PS_EXIT="1")
    assert result.returncode == 2
    assert "could not list containers of the pre-rename" in result.stderr
    assert calls == [_GUARD_CALL]


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"REMOTE_APP_DIR": "/home/digitie/apps/kor-travel-airport"}, "only the approved app directory may be used"),
        ({"COMPOSE_PROJECT_NAME": "kor-travel-airport"}, "unexpected environment file or Compose project"),
    ],
)
def test_deploy_refuses_the_pre_rename_directory_and_project(tmp_path: Path, env: dict[str, str], message: str) -> None:
    result, calls = _run(tmp_path, **env)
    assert result.returncode == 2
    assert message in result.stderr
    assert calls == []  # 문자열 검사에서 멈춰 guard까지 가지 않는다.


def _dagster_dsn_regex() -> str:
    text = _REMOTE.read_text(encoding="utf-8")
    match = re.search(r'"\$\{DAGSTER_POSTGRES_URL:-\}" =~ (\S+) \]\]', text)
    assert match, "DAGSTER_POSTGRES_URL 검사 줄을 찾지 못했다"
    return match.group(1)


@pytest.mark.parametrize(
    ("dsn", "accepted"),
    [
        ("postgresql+psycopg2://dagster:pw@127.0.0.1:11000/kor_travel_transport_dagster", True),
        ("postgresql://dagster:pw@127.0.0.1:11000/kor_travel_transport_dagster", True),
        ("postgresql+asyncpg://dagster:pw@127.0.0.1:11000/kor_travel_transport_dagster", False),
        ("postgresql+psycopg://dagster:pw@127.0.0.1:11000/kor_travel_transport_dagster", False),
        ("postgresql+psycopg2://dagster:pw@127.0.0.2:11000/kor_travel_transport_dagster", False),
        ("postgresql+psycopg2://dagster:pw@127.0.0.1:11000/kor_travel_transport", False),
    ],
)
def test_dagster_dsn_check_accepts_the_psycopg2_scheme_only_for_the_metadata_db(dsn: str, accepted: bool) -> None:
    result = subprocess.run(
        ["bash", "-c", '[[ $1 =~ $2 ]]', "_", dsn, _dagster_dsn_regex()],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted


def test_release_image_is_pinned_per_release_through_the_shell_env() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    source = text.index('source "${REMOTE_ENV_FILE}"')
    pin = text.index('export BACKEND_RUNTIME_IMAGE="kor-travel-transport-backend:rel-${CANDIDATE_SHA:0:12}"')
    up = text.index("up -d --build")
    # env 파일을 source한 뒤에 export해야 파일의 값(다른 배포가 적어 둔 draft 이미지)을 덮는다.
    assert source < pin < up
    assert "awk '!/^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE)=/'" in text


def test_deploy_scripts_accept_only_the_renamed_directory_and_project() -> None:
    for name in ("deploy-server14.sh", "deploy-server14-remote.sh", "deploy-transport-admin-server14.sh"):
        text = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert "/home/digitie/apps/kor-travel-transport" in text, name
        assert "/home/digitie/apps/kor-travel-airport" not in text, name
    for name in ("deploy-server14.sh", "deploy-server14-remote.sh"):
        text = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert 'COMPOSE_PROJECT_NAME:-kor-travel-transport}' in text, name
