"""Expire Transport compute logs in the Odroid code server's local state mount."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager, redirect_stdout
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import fcntl
import json
from math import isfinite
import os
from pathlib import Path
import re
import stat
import sys

from dagster import DagsterEventType, DagsterInstance, DagsterRunStatus, RunsFilter
from dagster._core.storage.dagster_run import RunRecord
from dagster._core.storage.local_compute_log_manager import LocalComputeLogManager

STATE = Path("/opt/dagster/state")
NAMESPACE = "compute_logs"
LOCATION = "kor-travel-transport"
LOCATION_TAG = "dagster/code_location"
PROJECT_TAG = "kortravelcommon/project"
HOLD_TAG = "kortraveltransport/compute-log-retention-hold"
RETENTION = timedelta(hours=168)
WRITE_GRACE = timedelta(hours=1)
TERMINAL = {DagsterRunStatus.SUCCESS, DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED}
RUN_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
FILE_KEY = re.compile(r"[A-Za-z0-9_-]{1,128}")
SUFFIXES = ("out", "err", "out.partial", "err.partial", "complete")


@dataclass
class Report:
    mode: str
    runs_seen: int = 0
    eligible_keys: int = 0
    eligible_files: int = 0
    eligible_bytes: int = 0
    removed_files: int = 0
    removed_bytes: int = 0
    skipped_runs: Counter[str] = field(default_factory=Counter)
    skipped_keys: Counter[str] = field(default_factory=Counter)
    skipped_entries: Counter[str] = field(default_factory=Counter)


class RetentionUnavailable(RuntimeError):
    pass


@contextmanager
def _directory(name: str, parent: int | None = None) -> Iterator[int]:
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        yield fd
    finally:
        os.close(fd)


def _run_skip(record: RunRecord | None, cutoff: float) -> str | None:
    if record is None:
        return "missing_metadata"
    run = record.dagster_run
    origin = run.remote_job_origin
    if (
        origin is None
        or origin.location_name != LOCATION
        or run.tags.get(LOCATION_TAG) != LOCATION
        or run.tags.get(PROJECT_TAG) != "transport"
    ):
        return "ambiguous_owner"
    if HOLD_TAG in run.tags:
        return "held"
    if run.status not in TERMINAL:
        return "active"
    end = record.end_time
    if end is None or not isfinite(end) or end <= 0:
        return "missing_end_time"
    return "within_retention" if end >= cutoff else None


def _local_keys(instance: DagsterInstance, run_id: str) -> set[str]:
    local, external = set(), set()
    records = instance.get_records_for_run(run_id, of_type=DagsterEventType.LOGS_CAPTURED).records
    for record in records:
        entry = record.event_log_entry
        event = entry.dagster_event
        if entry.run_id == run_id and event is not None:
            data = event.logs_captured_data
            if data.external_url or data.external_stdout_url or data.external_stderr_url:
                external.add(data.file_key)
            else:
                local.add(data.file_key)
    return local - external


def _stat(name: str, directory: int) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _same_directory(name: str, parent: int, opened: int) -> bool:
    info = _stat(name, parent)
    return (
        info is not None and stat.S_ISDIR(info.st_mode)
        and _identity(info) == _identity(os.fstat(opened))
    )


def _snapshot(key: str, directory: int) -> dict[str, os.stat_result]:
    return {
        name: info
        for suffix in SUFFIXES
        if (info := _stat(name := f"{key}.{suffix}", directory)) is not None
    }


def _unchanged(before: os.stat_result, after: os.stat_result | None) -> bool:
    # Ignore atime since reading a log must not postpone expiry.
    return (
        after is not None and _identity(before) == _identity(after)
        and before.st_mode == after.st_mode and before.st_nlink == after.st_nlink
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns and before.st_ctime_ns == after.st_ctime_ns
    )


def _sweep_run(
    instance: DagsterInstance, state_dir: int, root: int, run_id: str, record: RunRecord | None,
    cutoff: float, quiet_before_ns: int, report: Report,
) -> None:
    with ExitStack() as opened:
        try:
            run_dir = opened.enter_context(_directory(run_id, root))
            directory = opened.enter_context(_directory(NAMESPACE, run_dir))
        except FileNotFoundError:
            report.skipped_runs["missing_log_directory"] += 1
            return
        except NotADirectoryError:
            # With O_NOFOLLOW|O_DIRECTORY Linux reports ENOTDIR for symlinks as well.
            report.skipped_runs["unsafe_log_directory"] += 1
            return

        device = os.fstat(root).st_dev
        if os.fstat(run_dir).st_dev != device or os.fstat(directory).st_dev != device:
            report.skipped_runs["unsafe_log_directory"] += 1
            return
        names = os.listdir(directory)
        reason = _run_skip(record, cutoff) if names else "empty_log_directory"
        if reason:
            report.skipped_runs[reason] += 1
            return

        event_keys = _local_keys(instance, run_id)
        names_by_key = defaultdict(list)
        for name in names:
            key, _, suffix = name.partition(".")
            if FILE_KEY.fullmatch(key) and suffix in SUFFIXES and key in event_keys:
                names_by_key[key].append(name)
            else:
                report.skipped_entries["unproven_log_file"] += 1

        for key, listed in sorted(names_by_key.items()):
            files = _snapshot(key, directory)
            if set(files) != set(listed):
                report.skipped_keys["files_changed"] += 1
                continue
            if any(
                not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_dev != device
                for info in files.values()
            ):
                report.skipped_keys["unsafe_file"] += 1
                continue
            if any(max(info.st_mtime_ns, info.st_ctime_ns) >= quiet_before_ns for info in files.values()):
                report.skipped_keys["recent_write"] += 1
                continue
            if report.mode == "apply":
                # Refresh run status, origin and holds after inspecting disk and events.
                fresh = instance.get_run_record_by_id(run_id)
                if (
                    fresh is None or record is None or _run_skip(fresh, cutoff)
                    or fresh.end_time != record.end_time
                ):
                    report.skipped_keys["run_changed"] += 1
                    continue
                latest = _snapshot(key, directory)
                if (
                    not _same_directory(NAMESPACE, state_dir, root)
                    or not _same_directory(run_id, root, run_dir)
                    or not _same_directory(NAMESPACE, run_dir, directory)
                    or files.keys() != latest.keys()
                    or any(not _unchanged(info, latest[name]) for name, info in files.items())
                ):
                    report.skipped_keys["files_changed"] += 1
                    continue
            report.eligible_keys += 1
            report.eligible_files += len(files)
            report.eligible_bytes += sum(info.st_size for info in files.values())
            if report.mode == "apply":
                for name, info in files.items():
                    if not _unchanged(info, _stat(name, directory)):
                        report.skipped_keys["files_changed"] += 1
                        break
                    os.unlink(name, dir_fd=directory)
                    report.removed_files += 1
                    report.removed_bytes += info.st_size


def sweep(instance: DagsterInstance, state: Path, now: datetime, report: Report) -> None:
    cutoff = (now - RETENTION).timestamp()
    quiet_before_ns = int((now - WRITE_GRACE).timestamp() * 1_000_000_000)
    with ExitStack() as opened:
        state_dir = opened.enter_context(_directory(state.anchor))
        for component in state.parts[1:]:  # Open each component without following symlinks.
            state_dir = opened.enter_context(_directory(component, state_dir))
        try:
            root = opened.enter_context(_directory(NAMESPACE, state_dir))
        except FileNotFoundError:
            return
        if os.fstat(root).st_dev != os.fstat(state_dir).st_dev:
            raise RetentionUnavailable("compute-log directory is on a different device")
        try:
            fcntl.flock(root, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RetentionUnavailable("another retention sweep is running") from exc
        entries = os.listdir(root)
        run_ids = sorted(name for name in entries if RUN_ID.fullmatch(name))
        report.skipped_entries["unrecognized_run_entry"] += len(entries) - len(run_ids)
        for offset in range(0, len(run_ids), 200):
            batch = run_ids[offset:offset + 200]
            records = {
                record.dagster_run.run_id: record
                for record in instance.get_run_records(filters=RunsFilter(run_ids=batch))
            }
            for run_id in batch:
                report.runs_seen += 1
                _sweep_run(instance, state_dir, root, run_id, records.get(run_id), cutoff, quiet_before_ns, report)


def _require_local_manager(instance: DagsterInstance) -> None:
    manager = instance.compute_log_manager
    if (
        type(manager) is not LocalComputeLogManager
        or manager.inst_data is None
        or manager.inst_data.config_dict.get("base_dir") != str(STATE / NAMESPACE)
        or list(manager.build_log_key_for_run("run-id", "file-key")) != ["run-id", NAMESPACE, "file-key"]
    ):
        raise RetentionUnavailable("unexpected compute-log manager or key layout")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report eligible files (default)")
    mode.add_argument("--apply", action="store_true", help="remove eligible compute-log files")
    args = parser.parse_args(argv)
    report = Report("apply" if args.apply else "dry-run")
    error = None
    try:
        # Require the dedicated mount to be present in this namespace. Volume identity and driver
        # are verified by the deployment's host-side proof.
        mounts = Path("/proc/self/mountinfo").read_text().splitlines()
        if not any(line.split()[4] == str(STATE) for line in mounts):
            raise RetentionUnavailable("dedicated state mount is absent")
        with redirect_stdout(sys.stderr), DagsterInstance.get() as instance:
            _require_local_manager(instance)
            sweep(instance, STATE, datetime.now(UTC), report)
    except Exception as exc:
        error = type(exc).__name__
        if isinstance(exc, RetentionUnavailable):
            error = str(exc)
        print(f"Transport compute-log retention stopped: {error}", file=sys.stderr)
    print(json.dumps(vars(report) | {"schema_version": 1, "ok": error is None}, sort_keys=True))
    return 1 if error is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
