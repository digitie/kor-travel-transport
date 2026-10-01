"""운영 Dagster 실행/worker 교차 검증은 고아 실행을 놓치지 않는다."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


def _verifier():
    test_file = Path(__file__).resolve()
    path = next(candidate for candidate in (
        test_file.parents[1] / "scripts/verify-dagster-workers-server14.py",
        test_file.parents[2] / "scripts/verify-dagster-workers-server14.py",
    ) if candidate.is_file())
    spec = importlib.util.spec_from_file_location("verify_dagster_workers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_started_run_requires_matching_live_worker_parent() -> None:
    verifier = _verifier()
    run = [{"runId": "abc-123", "status": "STARTED"}]
    alive = "PID PPID COMMAND\n100 1 python -B -c multiprocessing.spawn\n101 100 tail /app/dagster_home/storage/abc-123/compute_logs/op.out\n"
    orphan = "PID PPID COMMAND\n101 1 tail /app/dagster_home/storage/abc-123/compute_logs/op.out\n"
    assert verifier.missing_started_workers(run, alive) == []
    assert verifier.missing_started_workers(run, orphan) == ["abc-123"]
    assert verifier.missing_started_workers(run, "PID PPID COMMAND\n") == ["abc-123"]


def test_starting_run_does_not_need_compute_log_worker_yet() -> None:
    verifier = _verifier()
    assert verifier.missing_started_workers([{"runId": "abc-123", "status": "STARTING"}],
                                            "PID PPID COMMAND\n") == []


def test_worker_without_active_dagster_run_is_detected() -> None:
    verifier = _verifier()
    table = ("PID PPID COMMAND\n"
             "100 1 python -B -c multiprocessing.spawn\n"
             "101 100 tail /app/dagster_home/storage/retired-run/compute_logs/op.out\n")
    assert verifier.untracked_workers([], table) == ["retired-run"]
    assert verifier.untracked_workers([{"runId": "retired-run", "status": "STARTED"}], table) == []
    assert verifier.untracked_workers([], "PID PPID COMMAND\n100 1 python -c multiprocessing.spawn\n") == [
        "worker-pid:100"
    ]
    mixed = ("PID PPID COMMAND\n"
             "100 1 python -c multiprocessing.spawn\n"
             "101 100 tail /storage/live-run/compute_logs/op.out\n"
             "200 1 python -c multiprocessing.spawn\n")
    assert verifier.untracked_workers([{"runId": "live-run", "status": "STARTED"}], mixed) == [
        "worker-pid:200"
    ]


def test_audit_fails_when_worker_remains_after_run_disappears(monkeypatch, capsys) -> None:
    verifier = _verifier()
    monkeypatch.setattr(verifier, "active_runs", lambda: [])
    monkeypatch.setattr(verifier, "running_app_runs", lambda: [])
    monkeypatch.setattr(verifier.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        stdout="PID PPID COMMAND\n100 1 python -c multiprocessing.spawn\n"
               "101 100 tail /storage/retired-run/compute_logs/op.out\n"
    ))
    monkeypatch.setattr(verifier.time, "sleep", lambda _seconds: None)
    assert verifier.main() == 1
    assert "추적되지 않은 worker 의심: retired-run" in capsys.readouterr().err


def test_app_running_run_requires_matching_active_dagster_run() -> None:
    verifier = _verifier()
    started = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
    app = [{"id": 17, "trigger": "transport_dagster_fuel", "started_at": started.isoformat()}]
    dagster = [{"runId": "dagster-1", "jobName": "fuel_collection_job", "status": "STARTED",
                "startTime": (started - timedelta(seconds=20)).timestamp()}]
    assert verifier.orphaned_app_runs(app, dagster) == []
    assert verifier.orphaned_app_runs(app, []) == [17]
    assert verifier.orphaned_app_runs(app, [{**dagster[0], "jobName": "highway_collection_job"}]) == [17]
    assert verifier.orphaned_app_runs(app, [{**dagster[0], "status": "CANCELING"}]) == [17]
    assert verifier.orphaned_app_runs(app, [{**dagster[0], "startTime":
                                            (started - timedelta(minutes=30)).timestamp()}]) == [17]


def test_one_active_dagster_run_cannot_hide_two_app_running_runs() -> None:
    verifier = _verifier()
    started = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
    app = [{"id": 17, "trigger": "transport_dagster_fuel", "started_at": started.isoformat()},
           {"id": 18, "trigger": "transport_dagster_fuel", "started_at":
            (started + timedelta(seconds=30)).isoformat()}]
    dagster = [{"runId": "dagster-1", "jobName": "fuel_collection_job", "status": "STARTED",
                "startTime": started.timestamp()}]
    assert verifier.orphaned_app_runs(app, dagster) == [18]


def test_audit_fails_after_worker_failure_leaves_app_run_running(monkeypatch, capsys) -> None:
    verifier = _verifier()
    started = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(verifier, "active_runs", lambda: [])  # Dagster가 이미 FAILURE로 종료했다.
    monkeypatch.setattr(verifier, "running_app_runs", lambda: [
        {"id": 17, "trigger": "transport_dagster_fuel", "started_at": started.isoformat()}
    ])
    monkeypatch.setattr(verifier.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(stdout="PID PPID COMMAND\n"))
    monkeypatch.setattr(verifier.time, "sleep", lambda seconds: None)

    assert verifier.main() == 1
    assert "앱 고아 수집 실행 의심: 17" in capsys.readouterr().err


def test_audit_fails_when_canceling_run_lost_worker_but_app_is_running(monkeypatch, capsys) -> None:
    verifier = _verifier()
    started = datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(verifier, "active_runs", lambda: [
        {"runId": "dagster-1", "jobName": "fuel_collection_job", "status": "CANCELING",
         "startTime": started.timestamp()}
    ])
    monkeypatch.setattr(verifier, "running_app_runs", lambda: [
        {"id": 17, "trigger": "transport_dagster_fuel", "started_at": started.isoformat()}
    ])
    monkeypatch.setattr(verifier.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(stdout="PID PPID COMMAND\n"))
    monkeypatch.setattr(verifier.time, "sleep", lambda seconds: None)

    assert verifier.main() == 1
    assert "앱 고아 수집 실행 의심: 17" in capsys.readouterr().err
