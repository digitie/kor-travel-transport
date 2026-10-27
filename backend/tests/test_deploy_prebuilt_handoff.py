"""외부 controller handoff를 실제 공식 자식의 분기와 읽기 전용 probe로 검산한다."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts" if (_ROOT / "scripts").is_dir() else Path("/app/scripts")
_HELPER = _SCRIPTS / "verify-prebuilt-handoff.py"
_REMOTE = _SCRIPTS / "deploy-prod-remote.sh"
_SHA = "c" * 40
_CID = "d" * 64
_ID = "sha256:" + "a" * 64


@pytest.fixture
def guard():
    spec = importlib.util.spec_from_file_location("prebuilt_handoff", _HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receipt(guard, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "run.json").write_text("latest")
    fingerprint = guard.scan_state(state)
    return {"version": 1, "release_sha": _SHA,
        "images": {"backend": _ID, "frontend": "sha256:" + "b" * 64, "dagster-code-server": _ID},
        "schema_revisions": ["0072_head"],
        "instigators": [{"location": guard.LOCATION, "repository": "transport", "kind": "schedule",
                          "name": "airport", "status": "RUNNING"}],
        "state": {"source_container": _CID, "manifest": guard.state_manifest(fingerprint),
                  "fingerprint": fingerprint}}


class Runtime:
    def __init__(self, guard, value):
        self.guard, self.value = guard, value
        self.runs = []
        self.states = copy.deepcopy(value["instigators"])
        self.states[0]["status"] = "STOPPED"
        self.workers = []
        self.cid = _CID
        self.state = copy.deepcopy(value["state"]["fingerprint"])
        self.image_ids = {"kor-travel-transport-backend:rel-" + _SHA[:12]: _ID,
                          "kor-travel-transport-frontend": value["images"]["frontend"]}
        self.schema = value["schema_revisions"]
        self.heads = value["schema_revisions"]
        self.calls = []

    def command(self, args):
        self.calls.append(args)
        if args[:3] == ["docker", "image", "inspect"]:
            return [{"Id": self.image_ids[args[3]], "Architecture": "arm64"}]
        if args[:2] == ["docker", "inspect"]:
            return [{"Id": self.cid, "State": {"Running": True}, "Config": {"Labels": {
                "com.docker.compose.project": "kor-travel-transport",
                "com.docker.compose.service": "dagster-code-server"}}}]
        if args[:2] == ["docker", "run"]:
            return self.heads
        if args[:2] == ["docker", "exec"]:
            code = args[-1]
            if code == self.guard.WORKER_PROBE:
                return self.workers
            if code == self.guard.SCHEMA_PROBE:
                return self.schema
            return self.state
        raise AssertionError(args)

    def graphql(self, query):
        if "runsOrError" in query:
            return {"runsOrError": {"__typename": "Runs", "results": self.runs}}
        nodes = {}
        for row in self.states:
            repo = nodes.setdefault((row["location"], row["repository"]), {
                "name": row["repository"], "location": {"name": row["location"]}, "schedules": [], "sensors": []})
            repo[row["kind"] + "s"].append({"name": row["name"], row["kind"] + "State": {"status": row["status"]}})
        return {"repositoriesOrError": {"__typename": "RepositoryConnection", "nodes": list(nodes.values())}}


def run_row(status="STARTED", origin="kor-travel-transport", tag="kor-travel-transport"):
    return {"runId": "run", "status": status, "repositoryOrigin": {"repositoryLocationName": origin},
            "tags": [] if tag is None else [{"key": "dagster/code_location", "value": tag}]}


def test_empty_fresh_handoff_passes_without_build_or_migration(guard, tmp_path):
    value = receipt(guard, tmp_path)
    runtime = Runtime(guard, value)
    guard.verify(value, _SHA, runtime.command, runtime.graphql)
    assert not any("build" in args or "upgrade" in args for args in runtime.calls)


@pytest.mark.parametrize("status", ["NOT_STARTED", "QUEUED", "STARTING", "STARTED", "CANCELING"])
def test_all_five_transport_states_refuse_without_waiting(guard, tmp_path, status):
    value = receipt(guard, tmp_path)
    runtime = Runtime(guard, value)
    runtime.runs = [run_row(status)]
    with pytest.raises(guard.ContractError, match="active"):
        guard.verify(value, _SHA, runtime.command, runtime.graphql)


@pytest.mark.parametrize("rows", [
    [run_row(origin=None, tag=None)], [run_row(origin="foreign")],
    [run_row()] * 1000,
    [run_row(tag=None)], [run_row(origin=None)],
])
def test_missing_or_disagreeing_identity_and_truncation_refuse(guard, tmp_path, rows):
    value = receipt(guard, tmp_path)
    runtime = Runtime(guard, value)
    runtime.runs = rows
    with pytest.raises(guard.ContractError):
        guard.verify(value, _SHA, runtime.command, runtime.graphql)


@pytest.mark.parametrize("change", ["worker", "running", "catalog", "cid", "image", "schema", "heads", "state", "completed-run"])
def test_changed_handoff_refuses_even_when_no_run_remains(guard, tmp_path, change):
    value = receipt(guard, tmp_path)
    runtime = Runtime(guard, value)
    if change == "worker": runtime.workers = [{"pid": 80, "ppid": 1, "started_ticks": 2, "kind": "execute_run"}]
    if change == "running": runtime.states[0]["status"] = "RUNNING"
    if change == "catalog": runtime.states[0]["name"] = "changed"
    if change == "cid": runtime.cid = "e" * 64
    if change == "image": runtime.image_ids["kor-travel-transport-frontend"] = _ID
    if change == "schema": runtime.schema = ["old"]
    if change == "heads": runtime.heads = ["new"]
    if change == "state": runtime.state["entries"]["run.json"]["sha256"] = "f" * 64
    if change == "completed-run": runtime.state["entries"]["run.json"]["ctime_ns"] += 1
    with pytest.raises(guard.ContractError):
        guard.verify(value, _SHA, runtime.command, runtime.graphql)


def test_receipt_bytes_symlink_and_candidate_are_checked(guard, tmp_path, monkeypatch):
    value = receipt(guard, tmp_path)
    assert guard.RECEIPT_UID == 0
    monkeypatch.setattr(guard, "RECEIPT_UID", os.getuid())
    tmp_path.chmod(0o711)
    path = tmp_path / "handoff.json"
    data = json.dumps(value).encode()
    path.write_bytes(data)
    path.chmod(0o644)
    digest = hashlib.sha256(data).hexdigest()
    assert guard.load_receipt(path, digest) == value
    with pytest.raises(guard.ContractError): guard.load_receipt(path, "0" * 64)
    linked = tmp_path / "link.json"
    linked.symlink_to(path)
    with pytest.raises(guard.ContractError): guard.load_receipt(linked, digest)
    runtime = Runtime(guard, value)
    with pytest.raises(guard.ContractError): guard.verify(value, "a" * 40, runtime.command, runtime.graphql)


@pytest.mark.parametrize("change", ["directory-mode", "file-mode", "hardlink", "owner"])
def test_receipt_security_metadata_refuses(guard, tmp_path, monkeypatch, change):
    value = receipt(guard, tmp_path)
    monkeypatch.setattr(guard, "RECEIPT_UID", os.getuid())
    tmp_path.chmod(0o711)
    path = tmp_path / "receipt.json"
    data = json.dumps(value).encode()
    path.write_bytes(data)
    path.chmod(0o644)
    if change == "directory-mode": tmp_path.chmod(0o755)
    if change == "file-mode": path.chmod(0o666)
    if change == "hardlink": os.link(path, tmp_path / "duplicate")
    if change == "owner": monkeypatch.setattr(guard, "RECEIPT_UID", os.getuid() + 1)
    with pytest.raises(guard.ContractError):
        guard.load_receipt(path, hashlib.sha256(data).hexdigest())


def test_an_extra_empty_transport_repository_is_ambiguous(guard, tmp_path):
    value = receipt(guard, tmp_path)
    runtime = Runtime(guard, value)

    def graphql(query):
        data = runtime.graphql(query)
        if "repositoriesOrError" in data:
            data["repositoriesOrError"]["nodes"].append({"name": "empty", "location": {"name": guard.LOCATION},
                                                        "schedules": [], "sensors": []})
        return data

    with pytest.raises(guard.ContractError, match="ambiguous"):
        guard.verify(value, _SHA, runtime.command, graphql)


def test_source_fingerprint_detects_same_bytes_rewritten_and_add_remove(guard, tmp_path):
    value = receipt(guard, tmp_path)
    before = value["state"]["fingerprint"]
    file = tmp_path / "state/run.json"
    file.write_text("latest")
    assert guard.scan_state(file.parent) != before
    before = guard.scan_state(file.parent)
    other = file.parent / "finished-run"
    other.write_text("finished")
    other.unlink()
    assert guard.scan_state(file.parent) != before


@pytest.mark.parametrize("change", ["run", "worker", "instigator"])
def test_scan_is_followed_by_a_fresh_drain_probe(guard, tmp_path, change):
    value = receipt(guard, tmp_path)
    runtime = Runtime(guard, value)

    def command(args):
        result = runtime.command(args)
        if args[-1] == guard.state_probe():
            if change == "run": runtime.runs = [run_row("QUEUED")]
            if change == "worker": runtime.workers = [{"pid": 80}]
            if change == "instigator": runtime.states[0]["status"] = "RUNNING"
        return result

    with pytest.raises(guard.ContractError):
        guard.verify(value, _SHA, command, runtime.graphql)


def test_foreign_location_is_read_only_but_state_change_refuses(guard, tmp_path):
    value = receipt(guard, tmp_path)
    value["instigators"].append({"location": "weather", "repository": "weather", "kind": "sensor",
                                 "name": "weather_sensor", "status": "RUNNING"})
    runtime = Runtime(guard, value)
    runtime.runs = [run_row(origin="weather", tag=None)]
    guard.verify(value, _SHA, runtime.command, runtime.graphql)
    runtime.states[1]["status"] = "STOPPED"
    with pytest.raises(guard.ContractError, match="instigators"):
        guard.verify(value, _SHA, runtime.command, runtime.graphql)


@pytest.mark.parametrize("change", ["short-release", "missing-role", "extra-role", "different-cs", "missing-times", "copy-diff"])
def test_old_or_incomplete_receipt_never_falls_back(guard, tmp_path, change):
    value = receipt(guard, tmp_path)
    runtime = Runtime(guard, value)
    if change == "short-release": value["release_sha"] = _SHA[:12]
    if change == "missing-role": del value["images"]["frontend"]
    if change == "extra-role": value["images"]["migrate"] = _ID
    if change == "different-cs": value["images"]["dagster-code-server"] = "sha256:" + "e" * 64
    if change == "missing-times": del value["state"]["fingerprint"]["entries"]["run.json"]["ctime_ns"]
    if change == "copy-diff": value["state"]["manifest"]["run.json"]["bytes"] += 1
    with pytest.raises(guard.ContractError):
        guard.verify(value, _SHA, runtime.command, runtime.graphql)


def test_official_build_branch_skips_build_for_strict_handoff(tmp_path):
    text = _REMOTE.read_text()
    start = text.index('if [[ "${DEPLOY_MODE}" == "deploy-prebuilt" ]]; then', text.index('compose config --format json'))
    branch = text[start:text.index('\nfi\n', start) + 4]
    log = tmp_path / "build-calls"
    script = ('set -euo pipefail\nDEPLOY_MODE=deploy-prebuilt\nREMOTE_APP_DIR="$APP"\n'
              + 'strict_prebuilt_gate() { echo gate >> "$CALLS"; echo "{}"; }\n'
              + 'compose() { echo "$*" >> "$CALLS"; }\n' + branch)
    result = subprocess.run(["bash", "-c", script], env={**os.environ, "CALLS": str(log), "APP": str(tmp_path)},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == ["gate", "config -q"]


@pytest.mark.parametrize("change", [None, "env", "label", "image", "tag", "project"])
def test_default_rollback_capture_accepts_only_a_verified_strict_predecessor(tmp_path, change):
    text = _REMOTE.read_text()
    start = text.index("capture_previous_code_server_image() {\n")
    body = text[start:text.index("\n}\n", start) + 3]
    data = {"Image": _ID, "Config": {"Image": _ID, "Env": ["RELEASE_SHA=" + _SHA], "Labels": {
        "io.kor-travel-transport.prebuilt-release": _SHA, "com.docker.compose.project": "kor-travel-transport",
        "com.docker.compose.service": "dagster-code-server"}}}
    tag_id = _ID
    if change == "env": data["Config"]["Env"] = ["RELEASE_SHA=" + "a" * 40]
    if change == "label": data["Config"]["Labels"]["io.kor-travel-transport.prebuilt-release"] = "short"
    if change == "image": data["Image"] = "sha256:" + "f" * 64
    if change == "tag": tag_id = "sha256:" + "f" * 64
    if change == "project": data["Config"]["Labels"]["com.docker.compose.project"] = "foreign"
    script = ('set -euo pipefail\ndagster_code_server=kor-travel-transport-dagster-code-server-1\n'
              + 'docker() { if [[ "$*" == "inspect -f {{.Config.Image}} "* ]]; then echo "$ID"; '
              + 'elif [[ "$*" == "image inspect -f "* ]]; then echo "$TAG_ID"; '
              + 'elif [[ "$1" == inspect ]]; then echo "$INSPECT"; else return 0; fi; }\n'
              + body + '\ncapture_previous_code_server_image\nprintf "%s" "$PREVIOUS_CODE_SERVER_IMAGE"\n')
    result = subprocess.run(["bash", "-c", script], env={**os.environ, "ID": _ID, "TAG_ID": tag_id,
                            "INSPECT": json.dumps([data])}, capture_output=True, text=True)
    assert (result.returncode == 0) is (change is None), result.stderr
    if change is None:
        assert result.stdout == "kor-travel-transport-backend:rel-" + _SHA[:12]


def test_official_strict_branch_has_no_build_wait_fallback_or_child_rollback(tmp_path):
    text = _REMOTE.read_text()
    assert '"deploy-prebuilt"' in text
    branch = text[text.index('# BEGIN replacement gate'):text.index('# END replacement gate')]
    for busy in (False, True):
        log = tmp_path / ("busy" if busy else "empty")
        script = ('set -euo pipefail\nDEPLOY_MODE=deploy-prebuilt\n'
            + 'strict_prebuilt_gate() { echo probe >> "$CALLS"; ' + ('return 2; ' if busy else '') + '}\n'
            + 'compose() { printf "%s\\n" "$*" >> "$CALLS"; }\n'
            + 'capture_previous_code_server_image() { echo capture >> "$CALLS"; }\n'
            + 'verify_manager_instance_config() { return 0; }\n'
            + 'in_flight_runs() { echo unexpected >> "$CALLS"; return 2; }\n'
            + 'sleep() { echo unexpected-sleep >> "$CALLS"; exit 77; }\n'
            + branch)
        result = subprocess.run(["bash", "-c", script], env={**os.environ, "CALLS": str(log)}, capture_output=True, text=True)
        calls = log.read_text().splitlines()
        assert result.returncode == (2 if busy else 0), result.stderr
        assert calls == (["probe"] if busy else ["probe", "up -d --no-build --pull never --no-deps backend frontend dagster-code-server"])


@pytest.mark.parametrize("change", [None, "admin-id", "gateway-id", "release", "missing-release", "architecture", "missing-input"])
def test_admin_handoff_checks_only_its_two_pinned_images(guard, change):
    admin = {"Id": _ID, "Architecture": "arm64", "Config": {"Env": ["TRANSPORT_ADMIN_RELEASE_SHA=" + _SHA]}}
    gateway = {"Id": "sha256:" + "b" * 64, "Architecture": "arm64"}
    admin_id = _ID
    if change == "admin-id": admin["Id"] = gateway["Id"]
    if change == "gateway-id": gateway["Id"] = _ID
    if change == "release": admin["Config"]["Env"] = ["TRANSPORT_ADMIN_RELEASE_SHA=" + "a" * 40]
    if change == "missing-release": admin["Config"]["Env"] = []
    if change == "architecture": admin["Architecture"] = "amd64"
    if change == "missing-input": admin_id = None
    calls = []

    def command(args):
        calls.append(args)
        assert args[:3] == ["docker", "image", "inspect"]
        return [admin if args[3].endswith("transport-admin-web") else gateway]

    if change:
        with pytest.raises(guard.ContractError):
            guard.admin_overlay(_SHA, admin_id, "sha256:" + "b" * 64, command)
    else:
        overlay = guard.admin_overlay(_SHA, admin_id, gateway["Id"], command)
        assert set(overlay["services"]) == {"transport-admin-web", "transport-api-gateway"}
        assert overlay["services"]["transport-admin-web"]["image"] == _ID
        assert len(calls) == 2


@pytest.mark.parametrize("failed", [False, True])
def test_official_admin_branch_has_no_build_and_never_falls_back(tmp_path, failed):
    text = (_SCRIPTS / "deploy-transport-admin-prod.sh").read_text()
    branch = text[text.index("# BEGIN admin replacement gate"):text.index("# END admin replacement gate")]
    log = tmp_path / "admin-calls"
    script = ('set -euo pipefail\nadmin_deploy_mode=deploy-prebuilt\n'
              + 'stage="$APP"\nCANDIDATE_SHA="$SHA"\nprebuilt_admin_id="$ID"\nprebuilt_gateway_id="$ID"\nREMOTE_ENV_FILE=.env.prod\n'
              + 'python3() { echo validate >> "$CALLS"; ' + ('return 2; ' if failed else 'echo "{}"; ') + '}\n'
              + 'docker() { echo "$*" >> "$CALLS"; }\n' + branch)
    result = subprocess.run(["bash", "-c", script], env={**os.environ, "APP": str(tmp_path), "SHA": _SHA,
                            "ID": _ID, "CALLS": str(log)}, capture_output=True, text=True)
    calls = log.read_text().splitlines()
    assert result.returncode == (2 if failed else 0), result.stderr
    assert calls[0] == "validate"
    assert len(calls) == (1 if failed else 2)
    if not failed:
        assert "--no-build --pull never --no-deps --force-recreate transport-api-gateway transport-admin-web" in calls[1]
        assert "--build" not in calls[1]
        assert "dagster" not in calls[1]
