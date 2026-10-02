from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import time
from uuid import uuid4
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

BACKUP_NAME_PATTERN = re.compile(r"^kor-travel-transport-[0-9T]{15}Z(?:-[A-Za-z0-9_-]+)?\.dump$")
MAX_BACKUP_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_BACKUP_STORAGE_LIMIT_BYTES = 8 * 1024 * 1024 * 1024
STAGING_BACKUP_PREFIX = ".kor-travel-transport-"
STAGING_BACKUP_MAX_AGE_SECONDS = 3600


@dataclass(frozen=True)
class BackupFileInfo:
    filename: str
    size_bytes: int
    created_at: datetime


def _backup_path(backup_dir: str, filename: str) -> Path:
    if not BACKUP_NAME_PATTERN.fullmatch(filename):
        raise ValueError("허용되지 않는 백업 파일명입니다.")
    directory = Path(backup_dir).resolve()
    # The filename grammar has no path separators. Keep the raw directory
    # entry so callers can reject a symlink before opening it.
    path = directory / filename
    if path.parent != directory:
        raise ValueError("백업 경로가 올바르지 않습니다.")
    return path


def _cleanup_staging_backups_sync(backup_dir: str) -> None:
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - STAGING_BACKUP_MAX_AGE_SECONDS
    for path in directory.iterdir():
        if path.is_symlink() or not path.name.startswith(STAGING_BACKUP_PREFIX) or path.suffix != ".dump":
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
        except FileNotFoundError:
            continue


def _database_url_without_async_driver(database_url: str) -> str:
    return database_url.replace("+asyncpg", "", 1)


def _run_command(command: list[str], timeout_seconds: int, env: dict[str, str] | None = None) -> None:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("PostgreSQL 백업 도구(pg_dump/pg_restore)를 찾지 못했습니다.") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "알 수 없는 PostgreSQL 오류").strip()
        raise RuntimeError(f"PostgreSQL 백업 작업에 실패했습니다: {detail[-500:]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("PostgreSQL 백업 작업이 제한 시간 안에 끝나지 않았습니다.") from exc
    if completed.returncode != 0:
        raise RuntimeError("PostgreSQL 백업 작업에 실패했습니다.")


def _list_backups_sync(backup_dir: str) -> list[BackupFileInfo]:
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _cleanup_staging_backups_sync(backup_dir)
    items: list[BackupFileInfo] = []
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or not BACKUP_NAME_PATTERN.fullmatch(path.name):
            continue
        stat = path.stat()
        items.append(
            BackupFileInfo(
                filename=path.name,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )
        )
    return sorted(items, key=lambda item: item.created_at, reverse=True)


def _enforce_storage_limit_sync(
    backup_dir: str,
    storage_limit_bytes: int,
    protected_filename: str | None = None,
    protected_filenames: set[str] | None = None,
) -> None:
    if storage_limit_bytes <= 0:
        raise ValueError("백업 저장소 한도는 0보다 커야 합니다.")
    items = _list_backups_sync(backup_dir)
    total_bytes = sum(item.size_bytes for item in items)
    protected = set(protected_filenames or ())
    if protected_filename:
        protected.add(protected_filename)
    candidates: list[BackupFileInfo] = []
    reclaimable_bytes = 0
    for item in reversed(items):
        if total_bytes <= storage_limit_bytes:
            break
        if item.filename in protected:
            continue
        candidates.append(item)
        reclaimable_bytes += item.size_bytes
        if total_bytes - reclaimable_bytes <= storage_limit_bytes:
            break
    if total_bytes - reclaimable_bytes > storage_limit_bytes:
        raise ValueError("백업 저장소의 aggregate 용량 한도를 초과했습니다.")
    for item in candidates:
        _backup_path(backup_dir, item.filename).unlink(missing_ok=True)
        total_bytes -= item.size_bytes
    if total_bytes > storage_limit_bytes:
        raise ValueError("백업 저장소의 aggregate 용량 한도를 초과했습니다.")


def _make_room_for_upload_sync(
    backup_dir: str,
    storage_limit_bytes: int,
    incoming_bytes: int,
    protected_filename: str,
    protected_filenames: set[str] | None = None,
) -> None:
    """Free old backups after a staged upload has completed."""

    if storage_limit_bytes <= 0:
        raise ValueError("백업 저장소 한도는 0보다 커야 합니다.")
    if incoming_bytes > storage_limit_bytes:
        raise ValueError("업로드 파일이 백업 저장소의 aggregate 용량 한도를 초과했습니다.")
    items = _list_backups_sync(backup_dir)
    total_bytes = sum(item.size_bytes for item in items)
    protected = set(protected_filenames or ())
    protected.add(protected_filename)
    if total_bytes + incoming_bytes <= storage_limit_bytes:
        return
    candidates: list[BackupFileInfo] = []
    reclaimable_bytes = 0
    for item in reversed(items):
        if item.filename in protected:
            continue
        candidates.append(item)
        reclaimable_bytes += item.size_bytes
        if total_bytes - reclaimable_bytes + incoming_bytes <= storage_limit_bytes:
            break
    if total_bytes - reclaimable_bytes + incoming_bytes > storage_limit_bytes:
        raise ValueError("백업 저장소의 aggregate 용량 한도를 초과했습니다.")
    for item in candidates:
        _backup_path(backup_dir, item.filename).unlink(missing_ok=True)
        total_bytes -= item.size_bytes
    if total_bytes + incoming_bytes <= storage_limit_bytes:
        return
    raise RuntimeError("백업 저장소 용량 정리 후에도 업로드 공간을 확보하지 못했습니다.")


async def list_backups(backup_dir: str) -> list[BackupFileInfo]:
    return await asyncio.to_thread(_list_backups_sync, backup_dir)


def _postgres_command_database(database_url: str) -> tuple[str, dict[str, str]]:
    parsed = make_url(_database_url_without_async_driver(database_url))
    password = parsed.password
    # ``URL.set(password=None)`` leaves the existing password untouched in
    # SQLAlchemy.  Replace it explicitly so the secret is supplied only via
    # PGPASSWORD and never accidentally becomes the literal ``***`` mask in
    # the pg_dump/pg_restore connection URL.
    safe_url = parsed._replace(password=None).render_as_string(hide_password=False)
    environment = os.environ.copy()
    if password:
        environment["PGPASSWORD"] = password
    return safe_url, environment


def _prune_backups_sync(
    backup_dir: str,
    retention_count: int,
    storage_limit_bytes: int,
    protected_filename: str | None = None,
) -> None:
    for item in _list_backups_sync(backup_dir)[max(0, retention_count) :]:
        _backup_path(backup_dir, item.filename).unlink(missing_ok=True)
    _enforce_storage_limit_sync(backup_dir, storage_limit_bytes, protected_filename=protected_filename)


async def create_backup(
    backup_dir: str,
    database_url: str,
    retention_count: int,
    timeout_seconds: int,
    storage_limit_bytes: int = DEFAULT_BACKUP_STORAGE_LIMIT_BYTES,
) -> BackupFileInfo:
    def run() -> BackupFileInfo:
        directory = Path(backup_dir)
        directory.mkdir(parents=True, exist_ok=True)
        _cleanup_staging_backups_sync(backup_dir)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"kor-travel-transport-{timestamp}.dump"
        path = _backup_path(backup_dir, filename)
        if path.exists():
            filename = f"kor-travel-transport-{timestamp}-{uuid4().hex[:12]}.dump"
            path = _backup_path(backup_dir, filename)
        safe_database_url, environment = _postgres_command_database(database_url)
        _enforce_storage_limit_sync(backup_dir, storage_limit_bytes)
        if shutil.disk_usage(directory).free < MAX_BACKUP_BYTES:
            raise ValueError("백업을 생성할 충분한 디스크 여유 공간이 없습니다.")
        # Keep the staging file on the same filesystem as the bind-mounted backup directory.
        # A /tmp -> /app/backups rename can fail with EXDEV on server14.
        temporary_fd, temporary_name = tempfile.mkstemp(
            dir=directory,
            prefix=".kor-travel-transport-",
            suffix=".dump",
        )
        os.close(temporary_fd)
        temporary_path = Path(temporary_name)
        try:
            _run_command(
                [
                    "pg_dump",
                    "--format=custom",
                    "--no-owner",
                    "--no-acl",
                    "--file",
                    str(temporary_path),
                    safe_database_url,
                ],
                timeout_seconds,
                environment,
            )
            temporary_size = temporary_path.stat().st_size
            if temporary_size > MAX_BACKUP_BYTES:
                raise ValueError("백업 파일 크기가 허용 한도를 초과했습니다.")
            _make_room_for_upload_sync(
                backup_dir,
                storage_limit_bytes,
                temporary_size,
                protected_filename=filename,
            )
            temporary_path.replace(path)
            _prune_backups_sync(
                backup_dir,
                retention_count,
                storage_limit_bytes,
                protected_filename=filename,
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            temporary_path.unlink(missing_ok=True)
        stat = path.stat()
        return BackupFileInfo(filename=filename, size_bytes=stat.st_size, created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))

    return await asyncio.to_thread(run)


async def restore_backup(
    backup_dir: str,
    database_url: str,
    filename: str,
    timeout_seconds: int,
) -> BackupFileInfo:
    path = _backup_path(backup_dir, filename)

    def run() -> BackupFileInfo:
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(filename)
        if path.stat().st_size > MAX_BACKUP_BYTES:
            raise ValueError("백업 파일 크기가 허용 한도를 초과했습니다.")
        safe_database_url, environment = _postgres_command_database(database_url)
        _run_command(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-acl",
                "--single-transaction",
                "--exit-on-error",
                "--dbname",
                safe_database_url,
                str(path),
            ],
            timeout_seconds,
            environment,
        )
        stat = path.stat()
        return BackupFileInfo(filename=filename, size_bytes=stat.st_size, created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))

    return await asyncio.to_thread(run)


async def save_uploaded_backup(
    uploaded_file,
    backup_dir: str,
    storage_limit_bytes: int = DEFAULT_BACKUP_STORAGE_LIMIT_BYTES,
    protected_filenames: set[str] | None = None,
    upload_timeout_seconds: int = 600,
) -> BackupFileInfo:
    if upload_timeout_seconds <= 0:
        raise ValueError("업로드 제한 시간은 0보다 커야 합니다.")
    directory = Path(backup_dir)
    directory.mkdir(parents=True, exist_ok=True)
    _cleanup_staging_backups_sync(backup_dir)
    safe_stem = re.sub(r"[^A-Za-z0-9_-]", "-", Path(uploaded_file.filename or "upload").stem)[:48] or "upload"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"kor-travel-transport-{timestamp}-{safe_stem}.dump"
    path = _backup_path(backup_dir, filename)
    if path.exists() or path.is_symlink():
        filename = f"kor-travel-transport-{timestamp}-{uuid4().hex[:12]}-{safe_stem}.dump"
        path = _backup_path(backup_dir, filename)

    temporary_fd, temporary_name = tempfile.mkstemp(
        dir=directory,
        prefix=".kor-travel-transport-upload-",
        suffix=".dump",
    )
    os.close(temporary_fd)
    temporary_path = Path(temporary_name)

    written = 0
    try:
        if shutil.disk_usage(directory).free < MAX_BACKUP_BYTES:
            raise ValueError("업로드를 처리할 충분한 디스크 여유 공간이 없습니다.")
        upload_deadline = asyncio.get_running_loop().time() + upload_timeout_seconds
        with temporary_path.open("wb") as output:
            while True:
                remaining_seconds = upload_deadline - asyncio.get_running_loop().time()
                if remaining_seconds <= 0:
                    raise ValueError("백업 업로드가 제한 시간 안에 끝나지 않았습니다.")
                try:
                    chunk = await asyncio.wait_for(uploaded_file.read(1024 * 1024), remaining_seconds)
                except asyncio.TimeoutError as exc:
                    raise ValueError("백업 업로드가 제한 시간 안에 끝나지 않았습니다.") from exc
                if not chunk:
                    break
                chunk_size = len(chunk)
                if written + chunk_size > MAX_BACKUP_BYTES:
                    raise ValueError("업로드 파일 크기가 허용 한도를 초과했습니다.")
                output.write(chunk)
                written += chunk_size
            output.flush()
            os.fsync(output.fileno())
        _make_room_for_upload_sync(
            backup_dir,
            storage_limit_bytes,
            written,
            protected_filename=filename,
            protected_filenames=protected_filenames,
        )
        temporary_path.replace(path)
        _enforce_storage_limit_sync(
            backup_dir,
            storage_limit_bytes,
            protected_filename=filename,
            protected_filenames=protected_filenames,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        temporary_path.unlink(missing_ok=True)
    return BackupFileInfo(
        filename=filename,
        size_bytes=written,
        created_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
    )


def backup_path_for_download(backup_dir: str, filename: str) -> Path:
    return _backup_path(backup_dir, filename)


async def remove_backup(backup_dir: str, filename: str) -> None:
    path = _backup_path(backup_dir, filename)
    await asyncio.to_thread(path.unlink, missing_ok=True)
