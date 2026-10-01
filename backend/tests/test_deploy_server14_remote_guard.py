"""`scripts/deploy-server14-remote.sh`의 배포 식별자 계약을 진짜 스크립트로 본다.

- 승인된 앱 디렉터리·Compose project·실행 위치가 아니면 docker를 부르기 전에 멈춘다. ADR-010의 임시
  개명 guard는 cutover 정리와 함께 지웠다(ADR-011).
- `DAGSTER_POSTGRES_URL`은 운영 env 그대로의 `postgresql+psycopg2://`도 받는다.
- 백엔드 계열 이미지는 release마다 `kor-travel-transport-backend:rel-<sha12>`를 셸 env로 받는다.
- 공용 Dagster 제어 평면(Manager ADR-54) 합류 뒤의 배포: 공용 daemon을 멈추지 않고 이 location의 run·worker가
  0일 때 교체하며, 합류 전(공용 plane이 location을 모르거나 옛 daemon이 돌 때)에는 거부한다.
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
    build = text.index("\ncompose build\n")
    up = text.index("\ncompose up -d --no-build\n")
    # env 파일을 source한 뒤에 export해야 파일의 값(다른 배포가 적어 둔 draft 이미지·옛 RELEASE_SHA)을 덮는다.
    # `set -a; source`가 둘을 셸 env로 export하고, 셸 env는 --env-file보다 우선한다.
    assert source < pin < build < up
    assert source < sha < build < up
    assert "awk '!/^(RELEASE_SHA|BACKEND_RUNTIME_IMAGE)=/'" in text


def _function(text: str, name: str) -> str:
    """스크립트에서 함수 하나의 정의(`name() {` … 첫 `\\n}\\n`)."""

    start = text.index(f"{name}() {{\n")
    return text[start : text.index("\n}\n", start) + 3]


def test_shared_plane_deploy_drains_this_location_without_stopping_the_shared_daemon() -> None:
    """공용 daemon은 다른 테넌트도 돌린다 — 멈추지 않고 이 location의 run·worker가 0일 때 교체한다."""

    text = _REMOTE.read_text(encoding="utf-8")
    build = text.index("\ncompose build\n")
    prepare_exit = text.index('if [[ "${DEPLOY_MODE}" == "prepare-shared-dagster-cutover" ]]; then')
    plane_guard = text.index('plane_state="$(location_state)"')
    drain = text.index('if runs="$(in_flight_runs)" && [[ -z "${runs}" ]]; then')
    up = text.index("\ncompose up -d --no-build\n")
    assert build < prepare_exit < plane_guard < drain < up
    assert text.index('wait_code_server_health\nwait_location_loaded\n') > up
    # 옛 전용 daemon을 멈추고 되살리던 길은 없다.
    assert "docker stop" not in text
    assert "docker start" not in text
    assert "dagster-daemon-1\"" not in text
    # 공용 webserver에 이 location으로 좁혀 묻는다(다른 테넌트의 run을 세지 않는다).
    assert 'dagster_graphql_url="http://127.0.0.1:11002/graphql"' in text
    assert 'dagster_location="kor-travel-transport"' in text
    assert "14004" not in text


def test_runs_query_is_valid_json_scoped_to_the_location() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if line.startswith("dagster_runs_query="))
    result = subprocess.run(
        ["bash", "-c", 'dagster_location=kor-travel-transport\n' + line + '\nprintf "%s" "$dagster_runs_query"'],
        capture_output=True, text=True, check=True,
    )
    query = json.loads(result.stdout)["query"]
    assert 'statuses:[STARTED,STARTING,CANCELING]' in query
    assert 'tags:[{key:"dagster/code_location",value:"kor-travel-transport"}]' in query


@pytest.mark.parametrize(
    ("workspace", "expected"),
    [
        ({"__typename": "Workspace", "locationEntries": [{"name": "kor-travel-transport", "locationOrLoadError": {"__typename": "RepositoryLocation"}}]}, "RepositoryLocation"),
        ({"__typename": "Workspace", "locationEntries": [{"name": "kor-travel-transport", "locationOrLoadError": {"__typename": "PythonError"}}]}, "PythonError"),
        ({"__typename": "Workspace", "locationEntries": [{"name": "kortravelmap.dagster.definitions", "locationOrLoadError": {"__typename": "RepositoryLocation"}}]}, "absent"),
    ],
)
def test_location_state_reads_only_this_location(workspace: dict[str, object], expected: str) -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    script = ("set -o pipefail\n" + _function(text, "location_state")
              + 'dagster_location=kor-travel-transport\ndagster_workspace_query=q\ndagster_graphql_url=u\n'
              + 'curl() { printf "%s" "$PAYLOAD"; }\nlocation_state\n')
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False,
                            env={**os.environ, "PAYLOAD": json.dumps({"data": {"workspaceOrError": workspace}})})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_deploy_refuses_before_the_plane_carries_the_location_or_while_the_old_daemon_runs() -> None:
    """합류 전 배포는 code-server만 공용 instance로 옮겨 Manager 전환의 펜스를 건너뛴다 — 거부한다."""

    text = _REMOTE.read_text(encoding="utf-8")
    guard = text[text.index('plane_state="$(location_state)"') : text.index("drain_deadline=")]
    for plane, legacy_running, expected in (
        ("absent", "false", "does not list kor-travel-transport yet"),
        ("RepositoryLocation", "true", "still runs next to the shared plane"),
        ("RepositoryLocation", "false", "PASSED"),
    ):
        script = ('COMPOSE_PROJECT_NAME=kor-travel-transport\ndagster_location=kor-travel-transport\n'
                  + f'location_state() {{ echo {plane}; }}\n'
                  + f'docker() {{ echo {legacy_running}; }}\n'
                  + guard + 'echo PASSED\n')
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
        assert expected in result.stdout + result.stderr, (plane, legacy_running, result.stderr)
        assert (result.returncode == 0) is (expected == "PASSED")


def test_code_server_health_wait_rejects_a_dead_code_server_and_accepts_a_healthy_one() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    definition = _function(text, "wait_code_server_health")
    for state, expected in (("false unhealthy", 1), ("true healthy", 0)):
        script = (definition + 'dagster_code_server=test-code-server\n'
                  + f'docker() {{ printf "%s\\n" "{state}"; }}\n'
                  + 'sleep() { :; }\nwait_code_server_health\n')
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
        assert result.returncode == expected, result.stderr
        if expected:
            assert "Dagster code-server가 healthy가 되지 않았다" in result.stderr


def test_deploy_worker_probe_detects_orphan_and_fails_closed() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    definition = _function(text, "in_flight_workers")
    script = ('set -o pipefail\n' + definition
              + 'dagster_code_server=transport-dagster-code-server-1\n'
              + 'docker() { printf "%s" "$PROCESS_TABLE"; }\n'
              + 'in_flight_workers\n')
    for process_table, expected in (
        ('PID PPID COMMAND\n1 0 dagster code-server start\n', ''),
        ('PID PPID COMMAND\n1 0 dagster code-server start\n2 1 python -c multiprocessing.spawn /storage/run-id/\n',
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


def test_prepare_mode_builds_and_writes_the_cutover_env_without_touching_containers() -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    block = text[text.index('if [[ "${DEPLOY_MODE}" == "prepare-shared-dagster-cutover" ]]; then') :]
    block = block[: block.index("\nfi\n")]
    assert "compose up" not in block and "docker " not in block
    assert 'printf \'BACKEND_RUNTIME_IMAGE=%s\\n\' "${BACKEND_RUNTIME_IMAGE}"' in block
    assert 'chmod 600 "${cutover_env_tmp}"' in block
    assert "exit 0" in block
    # 공용 password 검사는 prepare·deploy 둘 다 지난다(빌드 전).
    assert text.index("KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD:-}\" =~") < text.index("\ncompose build\n")
    # 배포 동기화(rsync --delete)가 n150에서 만든 전환 env 파일을 지우지 않는다.
    backend = (_SCRIPTS / "deploy-server14.sh").read_text(encoding="utf-8")
    assert '--exclude=".env.server14.shared-dagster-cutover"' in backend
    assert "DEPLOY_MODE='${DEPLOY_MODE}'" in backend


@pytest.mark.parametrize(
    ("password", "accepted"),
    [("Abc123._~-", True), ("", False), ("has space", False), ("p@ss", False), ("a/b", False)],
)
def test_shared_password_check_matches_the_manager_rule(password: str, accepted: bool) -> None:
    text = _REMOTE.read_text(encoding="utf-8")
    match = re.search(r'"\$\{KOR_TRAVEL_DAGSTER_SHARED_APP_PASSWORD:-\}" =~ (\S+) \]\]', text)
    assert match
    result = subprocess.run(["bash", "-c", '[[ $1 =~ $2 ]]', "_", password, match.group(1)],
                            capture_output=True, text=True, check=False)
    assert (result.returncode == 0) is accepted



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
    remote = _REMOTE.read_text(encoding="utf-8")

    assert backend.index('rm -f -- "${STAGE_MARKER}"') < backend.index("rsync -a --delete")
    assert backend.index("rsync -a --delete") < backend.index('mv -f -- "${stage_marker_tmp}" "${STAGE_MARKER}"')
    assert admin.index('rm -f -- "${REMOTE_APP_DIR}/.staged-release-sha"') < admin.index("rsync -a --exclude=")
    assert 'bash ./scripts/verify-release-stage.sh "${REMOTE_APP_DIR}" "${CANDIDATE_SHA}"' in remote


def test_all_shared_checkout_writers_hold_the_same_release_lock() -> None:
    names = ("deploy-server14.sh", "deploy-transport-admin-server14.sh", "deploy-server14-remote.sh")
    lock_path = "/home/digitie/apps/.kor-travel-transport-deploy.lock"
    for name in names:
        source = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert lock_path in source, name
        assert "flock -n 9" in source, name
    backend, admin, remote = ((_SCRIPTS / name).read_text(encoding="utf-8") for name in names)
    assert backend.index("flock -n 9") < backend.index("rsync -a --delete")
    assert admin.index("flock -n 9") < admin.index("rsync -a --exclude=")
    assert remote.index("flock -n 9") < remote.index('bash ./scripts/verify-release-stage.sh')
    # 옛 전용 Dagster 세 서비스 긴급 교체 스크립트는 공용 plane 합류로 없어졌다(되살아나면 옛 daemon을 띄운다).
    assert not (_SCRIPTS / "redeploy-dagster-services-server14.sh").exists()




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
