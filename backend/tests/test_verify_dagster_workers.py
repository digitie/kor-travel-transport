"""운영 Dagster 실행/worker 교차 검증은 고아 실행을 놓치지 않는다."""

import importlib.util
from pathlib import Path


def _verifier():
    path = Path(__file__).resolve().parents[2] / "scripts/verify-dagster-workers-server14.py"
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
