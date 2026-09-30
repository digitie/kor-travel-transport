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
    (candidate for candidate in (_BACKEND_ROOT / "scripts", _BACKEND_ROOT.parent / "scripts")
     if (candidate / "deploy-server14-remote.sh").is_file()),
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
    sha = text.index('export RELEASE_SHA="${CANDIDATE_SHA}"')
    build = text.index(' -f docker-compose.shared.yml build')
    up = text.index("up -d --no-build")
    # env 파일을 source한 뒤에 export해야 파일의 값(다른 배포가 적어 둔 draft 이미지·옛 RELEASE_SHA)을 덮는다.
    # `set -a; source`가 둘을 셸 env로 export하고, 셸 env는 --env-file보다 우선한다.
    assert source < pin < build < up
    assert source < sha < build < up
    assert "awk '!/^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE)=/'" in text


def test_deploy_drains_dagster_runs_after_build_and_restores_daemon_on_failure() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    build = text.index(' -f docker-compose.shared.yml build')
    preflight = text.index('in_flight_runs >/dev/null')
    stop = text.index('docker stop "${dagster_daemon}" >/dev/null\n')
    drain = text.index('if runs="$(in_flight_runs)" && [[ -z "${runs}" ]]')
    final_probe = text.index('runs="$(in_flight_runs)" || { echo "서비스 교체 직전에')
    up = text.index('up -d --no-build')
    assert build < preflight < stop < drain < final_probe < up
    assert 'trap resume_dagster_daemon EXIT' in text
    assert 'docker start "${dagster_daemon}"' in text
    assert 'cleanup_remote\n  exit "${status}"' in text
    assert '((SECONDS >= drain_deadline))' in text
    assert '[[ -z "${runs}" ]] ||' in text


def test_remote_deploy_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(_REMOTE)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_deploy_scripts_accept_only_the_renamed_directory_and_project() -> None:
    for name in ("deploy-server14.sh", "deploy-server14-remote.sh", "deploy-transport-admin-server14.sh"):
        text = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert "/home/digitie/apps/kor-travel-transport" in text, name
        assert "/home/digitie/apps/kor-travel-airport" not in text, name
    for name in ("deploy-server14.sh", "deploy-server14-remote.sh"):
        text = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert 'COMPOSE_PROJECT_NAME:-kor-travel-transport}' in text, name


def test_interrupted_sync_preserves_current_release_receipts() -> None:
    text = (_SCRIPTS / "deploy-server14.sh").read_text(encoding="utf-8")
    sync = text.index("rsync -a --delete")
    manifest_update = text.index('"${CANDIDATE_SHA}" > "${REMOTE_APP_DIR}/.release-sha"')
    sync_step = text[sync:manifest_update]

    assert '--exclude=".release-sha"' in sync_step
    assert '--exclude=".transport-admin-release-sha"' in sync_step


def test_stage_receipt_is_invalidated_before_either_shared_checkout_sync() -> None:
    backend = (_SCRIPTS / "deploy-server14.sh").read_text(encoding="utf-8")
    admin = (_SCRIPTS / "deploy-transport-admin-server14.sh").read_text(encoding="utf-8")
    dagster = (_SCRIPTS / "redeploy-dagster-services-server14.sh").read_text(encoding="utf-8")
    remote = _REMOTE.read_text(encoding="utf-8")

    assert backend.index('rm -f -- "${STAGE_MARKER}"') < backend.index("rsync -a --delete")
    assert backend.index("rsync -a --delete") < backend.index('mv -f -- "${stage_marker_tmp}" "${STAGE_MARKER}"')
    assert admin.index('rm -f -- "${REMOTE_APP_DIR}/.staged-release-sha"') < admin.index("rsync -a --exclude=")
    assert dagster.index('rm -f -- "$APP_DIR/.staged-release-sha"') < dagster.index('install -m 664 "$candidate" "$SHARED"')
    assert 'bash ./scripts/verify-release-stage.sh "${REMOTE_APP_DIR}" "${CANDIDATE_SHA}"' in remote


def test_all_shared_checkout_writers_hold_the_same_release_lock() -> None:
    names = (
        "deploy-server14.sh",
        "deploy-transport-admin-server14.sh",
        "redeploy-dagster-services-server14.sh",
        "deploy-server14-remote.sh",
    )
    lock_path = "/home/digitie/apps/.kor-travel-transport-deploy.lock"
    for name in (names[0], names[1], names[3]):
        source = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert lock_path in source, name
        assert "flock -n 9" in source, name
    dagster = (_SCRIPTS / names[2]).read_text(encoding="utf-8")
    assert 'APP_DIR="${APP_DIR:-/home/digitie/apps/kor-travel-transport}"' in dagster
    assert '$(dirname "$APP_DIR")/.kor-travel-transport-deploy.lock' in dagster
    assert dagster.index('APP_DIR="$(realpath -e -- "$APP_DIR")"') < dagster.index('$(dirname "$APP_DIR")/.kor-travel-transport-deploy.lock')
    assert "flock -n 9" in dagster
    backend = (_SCRIPTS / names[0]).read_text(encoding="utf-8")
    admin = (_SCRIPTS / names[1]).read_text(encoding="utf-8")
    remote = (_SCRIPTS / names[3]).read_text(encoding="utf-8")
    assert backend.index("flock -n 9") < backend.index("rsync -a --delete")
    assert admin.index("flock -n 9") < admin.index("rsync -a --exclude=")
    assert dagster.index("flock -n 9") < dagster.index('install -m 664 "$candidate" "$SHARED"')
    assert remote.index("flock -n 9") < remote.index('bash ./scripts/verify-release-stage.sh')


def test_release_lock_is_inherited_by_remote_deploy_child(tmp_path: Path) -> None:
    lock_path = str(tmp_path / "shared-release.lock")
    result = subprocess.run(
        ["bash", "-c", 'exec 9>"$1"; flock -n 9; bash -c \'[[ "$(readlink -f /proc/$$/fd/9)" == "$1" ]] && flock -n 9\' _ "$1"', "_", lock_path],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    contested = subprocess.run(
        ["bash", "-c", 'exec 9>"$1"; flock -n 9; bash -c \'exec 9>&-; exec 9>"$1"; flock -n 9\' _ "$1"; child_status=$?; exit "$child_status"', "_", lock_path],
        capture_output=True,
        text=True,
        check=False,
    )
    assert contested.returncode != 0


def test_remote_stage_guard_refuses_interrupted_or_superseded_sync(tmp_path: Path) -> None:
    verifier = _SCRIPTS / "verify-release-stage.sh"
    marker = tmp_path / ".staged-release-sha"

    def verify() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(verifier), str(tmp_path), _SHA],
            capture_output=True,
            text=True,
            check=False,
        )

    # 이전 배포가 남아 있어도 이번 동기화 시작 시 marker가 제거되면 재배포를 거부한다.
    assert verify().returncode == 2
    marker.write_text("a" * 40 + "\n", encoding="ascii")
    assert verify().returncode == 2
    marker.write_text(_SHA + "\n", encoding="ascii")
    assert verify().returncode == 0
    marker.unlink()
    assert verify().returncode == 2
    marker.symlink_to(tmp_path / "old-receipt")
    assert verify().returncode == 2
