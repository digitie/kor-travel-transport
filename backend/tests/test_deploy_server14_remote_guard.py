"""`scripts/deploy-server14-remote.sh`의 배포 식별자 계약을 진짜 스크립트로 본다.

- 승인된 앱 디렉터리·Compose project·실행 위치가 아니면 docker를 부르기 전에 멈춘다. ADR-010의 임시
  개명 guard는 cutover 정리와 함께 지웠다(ADR-011).
- `DAGSTER_POSTGRES_URL`은 운영 env 그대로의 `postgresql+psycopg2://`도 받는다.
- 백엔드 계열 이미지는 release마다 `kor-travel-transport-backend:rel-<sha12>`를 셸 env로 받는다.
"""

from __future__ import annotations

import json
import os
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


def test_deploy_refuses_outside_the_approved_directory_before_calling_docker(tmp_path: Path) -> None:
    result, calls = _run(tmp_path)
    # 테스트 디렉터리는 승인된 디렉터리가 아니다. compose도, 다른 docker 명령도 부르지 않는다.
    assert result.returncode == 2
    assert "run from the staged approved app directory" in result.stderr
    assert calls == []


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"REMOTE_APP_DIR": "/home/digitie/apps/other"}, "only the approved app directory may be used"),
        ({"COMPOSE_PROJECT_NAME": "other"}, "unexpected environment file or Compose project"),
    ],
)
def test_deploy_refuses_an_unapproved_directory_and_project(tmp_path: Path, env: dict[str, str], message: str) -> None:
    result, calls = _run(tmp_path, **env)
    assert result.returncode == 2
    assert message in result.stderr
    assert calls == []  # 문자열 검사에서 멈춘다.


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
    preflight = text.index('initial_runs="$(in_flight_runs)"')
    stop = text.index('docker stop "${dagster_daemon}" >/dev/null\n')
    drain = text.index('if runs="$(in_flight_runs)" && [[ -z "${runs}" ]]')
    final_probe = text.index('runs="$(in_flight_runs)" || { echo "서비스 교체 직전에')
    worker_probe = text.index('workers="$(in_flight_workers)" || { echo "서비스 교체 직전에')
    up = text.index('up -d --no-build\n', final_probe)
    assert build < preflight < stop < drain < final_probe < worker_probe < up
    assert 'trap resume_dagster_daemon EXIT' in text
    assert 'docker start "${dagster_daemon}"' in text
    assert 'cleanup_remote\n  exit "${status}"' in text
    assert '((SECONDS >= drain_deadline))' in text
    assert '[[ -z "${runs}" ]] ||' in text
    assert 'Dagster daemon이 없지만 활성 실행이 있다' in text
    assert 'Dagster daemon이 없지만 worker가 살아 있다' in text
    assert text.index('cutover_started=1\n') < up
    assert '혼합 릴리스를 막기 위해 daemon을 중지했다' in text
    assert text.index('wait_dagster_daemon_health() {') < text.index('trap resume_dagster_daemon EXIT') < up
    assert text.index('wait_dagster_daemon_health\nhealth_payload=""') < text.rindex('daemon_stopped=0')
    assert 'BACKEND_RUNTIME_IMAGE="${old_daemon_image}" docker compose' in text
    assert '"${restored_image}" != "${old_daemon_image}"' in text
    assert '"${daemon_health}" == "true healthy"' in text
    assert 'Dagster daemon이 healthy가 되지 않았다' in text


def test_deploy_daemon_health_probe_rejects_dead_daemon_and_accepts_healthy_one() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    body = text.split('wait_dagster_daemon_health() {\n', 1)[1].split('\n}\ndaemon_stopped=0', 1)[0]
    definition = 'wait_dagster_daemon_health() {\n' + body + '\n}\n'
    for state, expected in (("false unhealthy", 1), ("true healthy", 0)):
        script = (definition + 'dagster_daemon=test-daemon\n'
                  + f'docker() {{ printf "%s\\n" "{state}"; }}\n'
                  + 'sleep() { :; }\nwait_dagster_daemon_health\n')
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
        assert result.returncode == expected, result.stderr
        if expected:
            assert "Dagster daemon이 healthy가 되지 않았다" in result.stderr


def test_deploy_worker_probe_detects_orphan_and_fails_closed() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    body = text.split('in_flight_workers() {\n', 1)[1].split('\n}\nwait_dagster_daemon_health()', 1)[0]
    definition = 'in_flight_workers() {\n' + body + '\n}\n'
    script = ('set -o pipefail\n' + definition
              + 'dagster_code_server=transport-dagster-code-server-1\n'
              + 'docker() { printf "%s" "$PROCESS_TABLE"; }\n'
              + 'in_flight_workers\n')
    for process_table, expected in (
        ('PID PPID COMMAND\n1 0 dagster api grpc\n', ''),
        ('PID PPID COMMAND\n1 0 dagster api grpc\n2 1 python -c multiprocessing.spawn /storage/run-id/\n',
         'multiprocessing.spawn'),
    ):
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                env={**os.environ, "PROCESS_TABLE": process_table}, check=False)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected or expected in result.stdout
    broken = subprocess.run(["bash", "-c", 'set -o pipefail\n' + definition
                             + 'docker() { return 17; }\nin_flight_workers\n'],
                            capture_output=True, text=True, check=False)
    assert broken.returncode == 17


def test_failed_deploy_before_cutover_restores_previous_daemon_image() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    body = text.split('resume_dagster_daemon() {\n', 1)[1].split('\n}\ntrap resume_dagster_daemon EXIT', 1)[0]
    script = ('resume_dagster_daemon() {\n' + body + '\n}\n'
              + 'daemon_stopped=1\ndaemon_stopping=0\ncutover_started=0\n'
              + 'dagster_daemon=transport-dagster-daemon-1\n'
              + 'old_daemon_container_id=old-container\nold_daemon_image=sha256:old-image\n'
              + 'COMPOSE_PROJECT_NAME=transport\nRUNTIME_ENV_FILE=/tmp/runtime.env\nrestored=0\n'
              + 'docker() {\n'
              + '  if [[ "$1 $2 $3" == "inspect -f {{.Id}}" ]]; then echo new-container; return; fi\n'
              + '  if [[ "$1 $2 $3" == "inspect -f {{.Image}}" ]]; then\n'
              + '    if ((restored)); then echo sha256:old-image; else echo sha256:new-image; fi\n'
              + '    return\n'
              + '  fi\n'
              + '  if [[ "$1 $2" == "image inspect" ]]; then return 0; fi\n'
              + '  if [[ "$1" == "compose" ]]; then\n'
              + '    [[ "$BACKEND_RUNTIME_IMAGE" == "sha256:old-image" ]] || return 1\n'
              + '    restored=1\n'
              + '    return 0\n'
              + '  fi\n'
              + '  return 1\n}\n'
              + 'wait_dagster_daemon_health() { ((restored)) && echo restored-old-image; }\n'
              + 'cleanup_remote() { :; }\ntrap resume_dagster_daemon EXIT\nexit 17\n')
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 17, result.stderr
    assert "restored-old-image" in result.stdout
    assert "자동 복구하지 못했다" not in result.stderr


@pytest.mark.parametrize("running,expected", [
    ("false", "혼합 릴리스를 막기 위해 daemon을 중지했다"),
    ("true", "치명적 부분 배포 실패: daemon 중지를 확인하지 못했다"),
])
def test_failed_deploy_after_cutover_does_not_restore_old_daemon(running: str, expected: str) -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    body = text.split('resume_dagster_daemon() {\n', 1)[1].split('\n}\ntrap resume_dagster_daemon EXIT', 1)[0]
    script = ('resume_dagster_daemon() {\n' + body + '\n}\n'
              + 'cutover_started=1\ndaemon_stopped=1\ndaemon_stopping=0\n'
              + 'dagster_daemon=transport-dagster-daemon-1\n'
              + 'BACKEND_RUNTIME_IMAGE=candidate\nold_daemon_image=sha256:old-image\n'
              + 'docker() {\n'
              + f'  if [[ "$1 $2" == "inspect -f" ]]; then echo {running}; return 0; fi\n'
              + f'  if [[ "$1" == "stop" ]]; then return {0 if running == "false" else 1}; fi\n'
              + '  if [[ "$1" == "compose" ]]; then echo unsafe-rollback; return 1; fi\n'
              + '  return 1\n}\n'
              + 'wait_dagster_daemon_health() { return 1; }\n'
              + 'cleanup_remote() { :; }\ntrap resume_dagster_daemon EXIT\nexit 17\n')
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 17, result.stderr
    assert expected in result.stderr
    assert "unsafe-rollback" not in result.stdout


def test_remote_deploy_script_has_valid_bash_syntax() -> None:
    result = subprocess.run(["bash", "-n", str(_REMOTE)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_deploy_scripts_accept_only_the_renamed_directory_and_project() -> None:
    for name in ("deploy-server14.sh", "deploy-server14-remote.sh", "deploy-transport-admin-server14.sh"):
        text = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert "/home/digitie/apps/kor-travel-transport" in text, name
        assert "kor-travel-airport" not in text, name
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
