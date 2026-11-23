"""Transport compute-log retention against the pinned Dagster record and file layout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from dagster import DagsterEvent, DagsterEventType, DagsterInstance, DagsterRunStatus, job, op
from dagster._core.events import ComputeLogsCaptureData
from dagster._core.remote_origin import RegisteredCodeLocationOrigin, RemoteJobOrigin, RemoteRepositoryOrigin
from dagster._core.storage.local_compute_log_manager import LocalComputeLogManager
import pytest

from app.dagster import compute_log_retention as retention

# ctime measures the fixture creation time. A future sweep time lets tests exercise
# both fresh and quiet files without altering the kernel's clock.
NOW = datetime.now(UTC) + 2 * retention.WRITE_GRACE
OLD_END = (NOW - retention.RETENTION - timedelta(seconds=1)).timestamp()


class Instance:
    def __init__(self) -> None:
        self.records = {}
        self.events = {}
        self.refresh = None

    def add_run(
        self, *, status=DagsterRunStatus.SUCCESS, end=OLD_END,
        origin=retention.LOCATION, tags=None, keys=("abcdefgh",),
    ) -> str:
        run_id = str(uuid4())
        remote = SimpleNamespace(location_name=origin)
        self.records[run_id] = SimpleNamespace(
            dagster_run=SimpleNamespace(
                run_id=run_id,
                status=status,
                remote_job_origin=remote if origin else None,
                tags=(
                    {retention.LOCATION_TAG: retention.LOCATION, retention.PROJECT_TAG: "transport"}
                    if tags is None else tags
                ),
            ),
            end_time=end,
            update_timestamp=NOW - timedelta(days=30),
        )
        self.events[run_id] = [ComputeLogsCaptureData(file_key=key, step_keys=[]) for key in keys]
        return run_id

    def get_run_records(self, *, filters):
        return [self.records[run_id] for run_id in filters.run_ids if run_id in self.records]

    def get_run_record_by_id(self, run_id):
        if self.refresh:
            self.refresh(run_id)
        return self.records.get(run_id)

    def get_records_for_run(self, run_id, *, of_type):
        assert of_type is DagsterEventType.LOGS_CAPTURED
        return SimpleNamespace(records=[
            SimpleNamespace(event_log_entry=SimpleNamespace(
                run_id=run_id, dagster_event=SimpleNamespace(logs_captured_data=data),
            ))
            for data in self.events[run_id]
        ])


def capture(state: Path, run_id: str, key: str = "abcdefgh", *, suffix: str = "out") -> Path:
    manager = LocalComputeLogManager(str(state / "compute_logs"))
    path = Path(manager.get_captured_local_path(manager.build_log_key_for_run(run_id, key), suffix))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"log\n")
    return path


@pytest.mark.parametrize("status", [DagsterRunStatus.SUCCESS, DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED])
def test_exact_keys_dry_run_apply_and_repeat(tmp_path, status):
    instance = Instance()
    run = instance.add_run(status=status, keys=("abcdefgh", "ijklmnop"))
    eligible = [capture(tmp_path, run, suffix=suffix) for suffix in retention.SUFFIXES]
    eligible += [capture(tmp_path, run, "ijklmnop", suffix="err")]
    unknown = [
        capture(tmp_path, run, "abcdefgh2"),
        capture(tmp_path, run, suffix="out.backup"),
        capture(tmp_path, run, "external"),
    ]
    instance.events[run].append(ComputeLogsCaptureData(
        file_key="external", step_keys=[], external_stdout_url="https://example.invalid/log",
    ))
    artifacts = tmp_path / "artifacts"
    artifacts.write_text("artifact")
    checkpoint = tmp_path / "collector-state"
    checkpoint.write_text("checkpoint")

    planned = retention.Report("dry-run")
    retention.sweep(instance, tmp_path, NOW, planned)
    assert (planned.eligible_keys, planned.eligible_files, planned.eligible_bytes, planned.removed_files) == (2, 6, 24, 0)
    assert planned.skipped_entries["unproven_log_file"] == 3
    assert all(path.is_file() for path in eligible + unknown)

    applied = retention.Report("apply")
    retention.sweep(instance, tmp_path, NOW, applied)
    assert (applied.eligible_files, applied.removed_files, applied.removed_bytes) == (6, 6, 24)
    assert all(not path.exists() for path in eligible)
    assert all(path.is_file() for path in unknown + [artifacts, checkpoint])
    assert instance.records[run].dagster_run.status == status
    assert instance.records[run].end_time == OLD_END
    assert len(instance.events[run]) == 3

    repeat = retention.Report("apply")
    retention.sweep(instance, tmp_path, NOW, repeat)
    assert repeat.eligible_files == repeat.removed_files == 0


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"status": DagsterRunStatus.STARTED}, "active"),
        ({"status": DagsterRunStatus.CANCELING}, "active"),
        ({"status": DagsterRunStatus.QUEUED}, "active"),
        ({"end": (NOW - retention.RETENTION).timestamp()}, "within_retention"),
        ({"end": NOW.timestamp()}, "within_retention"),
        ({"end": None}, "missing_end_time"),
        ({"end": float("nan")}, "missing_end_time"),
        ({"origin": None}, "ambiguous_owner"),
        ({"origin": "geo"}, "ambiguous_owner"),
        ({"tags": {retention.LOCATION_TAG: retention.LOCATION}}, "ambiguous_owner"),
        ({"tags": {retention.LOCATION_TAG: "geo", retention.PROJECT_TAG: "transport"}}, "ambiguous_owner"),
        ({"tags": {retention.LOCATION_TAG: retention.LOCATION, retention.PROJECT_TAG: "transport",
                   retention.HOLD_TAG: ""}}, "held"),
    ],
)
def test_skip_run_based_on_durable_metadata(tmp_path, options, reason):
    instance = Instance()
    run = instance.add_run(**options)
    path = capture(tmp_path, run)
    report = retention.Report("apply")
    retention.sweep(instance, tmp_path, NOW, report)
    assert report.skipped_runs == {reason: 1}
    assert report.removed_files == 0
    assert path.is_file()


def test_missing_metadata_or_symlink_namespace(tmp_path):
    instance = Instance()
    orphan = capture(tmp_path, str(uuid4()))
    target = tmp_path / "unrelated"
    target.mkdir()
    run = instance.add_run()
    symlink_dir = orphan.parents[2] / run
    symlink_dir.mkdir()
    (symlink_dir / "compute_logs").symlink_to(target, target_is_directory=True)
    symlink_run = orphan.parents[2] / instance.add_run()
    symlink_run.symlink_to(orphan.parents[1], target_is_directory=True)

    report = retention.Report("apply")
    retention.sweep(instance, tmp_path, NOW, report)
    assert report.skipped_runs == {"missing_metadata": 1, "unsafe_log_directory": 2}
    assert orphan.is_file()


def test_recent_writes_symlinks_and_hardlinks_protect_entire_key(tmp_path):
    instance = Instance()
    run = instance.add_run(keys=("recent", "symlink", "hardlink"))
    recent = capture(tmp_path, run, "recent")
    recent_sibling = capture(tmp_path, run, "recent", suffix="err")
    os.utime(recent, (NOW.timestamp(), NOW.timestamp()))
    symlink = capture(tmp_path, run, "symlink")
    symlink.unlink()
    symlink.symlink_to(recent)
    symlink_sibling = capture(tmp_path, run, "symlink", suffix="err")
    hardlink = capture(tmp_path, run, "hardlink")
    extra_link = tmp_path / "outside-compute-logs"
    extra_link.hardlink_to(hardlink)

    report = retention.Report("apply")
    retention.sweep(instance, tmp_path, NOW, report)
    assert report.skipped_keys == {"recent_write": 1, "unsafe_file": 2}
    assert report.removed_files == 0
    assert all(path.exists() for path in [recent, recent_sibling, symlink, symlink_sibling, hardlink, extra_link])


@pytest.mark.parametrize("change", ["hold", "append", "new_sibling", "replace_directory", "replace_root"])
def test_apply_rechecks_run_and_files(tmp_path, change):
    instance = Instance()
    run = instance.add_run()
    path = capture(tmp_path, run)

    def refresh(run_id):
        if change == "hold":
            instance.records[run_id].dagster_run.tags[retention.HOLD_TAG] = "ticket"
        elif change == "append":
            with path.open("ab") as stream:
                stream.write(b"more")
        elif change == "new_sibling":
            capture(tmp_path, run, suffix="err")
        elif change == "replace_directory":
            path.parent.rename(path.parent.with_name("saved"))
            capture(tmp_path, run)
        else:
            (tmp_path / "compute_logs").rename(tmp_path / "saved")
            capture(tmp_path, run)

    instance.refresh = refresh
    report = retention.Report("apply")
    retention.sweep(instance, tmp_path, NOW, report)
    assert report.skipped_keys == {"run_changed" if change == "hold" else "files_changed": 1}
    assert report.eligible_files == report.removed_files == 0
    assert path.is_file()


@pytest.mark.parametrize(("args", "mode"), [([], "dry-run"), (["--dry-run"], "dry-run"), (["--apply"], "apply")])
def test_cli_fails_closed_without_state_mount(monkeypatch, capsys, args, mode):
    def missing_mount(self):
        return "35 24 0:33 / / rw - overlay overlay rw\n"

    monkeypatch.setattr(Path, "read_text", missing_mount)
    assert retention.main(args) == 1
    out, err = capsys.readouterr()
    summary = json.loads(out)
    assert (summary["schema_version"], summary["mode"], summary["ok"], summary["removed_files"]) == (1, mode, False, 0)
    assert "dedicated state mount is absent" in err


def test_repeat_invocation_cannot_sweep_while_directory_is_locked(tmp_path):
    instance = Instance()
    path = capture(tmp_path, instance.add_run())
    root_fd = os.open(tmp_path / "compute_logs", os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(root_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = retention.Report("apply")
        with pytest.raises(retention.RetentionUnavailable, match="another retention sweep is running"):
            retention.sweep(instance, tmp_path, NOW, report)
    finally:
        os.close(root_fd)
    assert path.is_file()
    assert report.runs_seen == report.removed_files == 0


def test_real_dagster_stores_end_and_capture_event_and_retains_history(tmp_path):
    @op
    def noop():
        return None

    @job
    def example():
        noop()

    home = tmp_path / "home"
    home.mkdir()
    with DagsterInstance.local_temp(str(home)) as instance:
        run = instance.create_run_for_job(
            example,
            tags={retention.LOCATION_TAG: retention.LOCATION, retention.PROJECT_TAG: "transport"},
            remote_job_origin=RemoteJobOrigin(
                RemoteRepositoryOrigin(RegisteredCodeLocationOrigin(retention.LOCATION), "__repository__"),
                example.name,
            ),
        )
        instance.report_dagster_event(
            DagsterEvent(
                event_type_value=DagsterEventType.LOGS_CAPTURED.value,
                job_name=example.name,
                event_specific_data=ComputeLogsCaptureData(file_key="abcdefgh", step_keys=["noop"]),
            ),
            run.run_id,
            timestamp=OLD_END - 1,
        )
        instance.report_dagster_event(
            DagsterEvent(event_type_value=DagsterEventType.RUN_SUCCESS.value, job_name=example.name),
            run.run_id,
            timestamp=OLD_END,
        )
        before = instance.get_run_record_by_id(run.run_id)
        assert before is not None and before.end_time == OLD_END
        history = instance.get_records_for_run(run.run_id).records
        path = capture(tmp_path, run.run_id)

        report = retention.Report("apply")
        retention.sweep(instance, tmp_path, NOW, report)

        assert report.removed_files == 1
        assert not path.exists()
        assert instance.get_run_record_by_id(run.run_id) == before
        assert instance.get_records_for_run(run.run_id).records == history


def test_recent_restore_with_preserved_mtime_is_deferred(tmp_path):
    now = datetime.now(UTC)
    instance = Instance()
    run = instance.add_run(end=(now - timedelta(days=8)).timestamp())
    path = capture(tmp_path, run)
    old_mtime = (now - timedelta(days=9)).timestamp()
    os.utime(path, (old_mtime, old_mtime))

    report = retention.Report("apply")
    retention.sweep(instance, tmp_path, now, report)

    assert report.skipped_keys == {"recent_write": 1}
    assert report.removed_files == 0
    assert path.is_file()
