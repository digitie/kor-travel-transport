"""관리자 경로 인증 회귀 테스트 (2026-10-02 공개 백업 노출 사고, ADR-012).

/v1/admin/collector-status를 뺀 모든 /v1/admin/* 경로는 `x-transport-admin-token`이
설정된 관리자 토큰과 일치할 때만 열린다. 불일치는 경로 존재를 숨기는 404이고, 백업 서비스
함수는 호출되지 않아야 한다(복원 업로드는 본문을 저장하기 전에 거부).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

TOKEN = "t" * 40

PROTECTED_REQUESTS = [
    ("GET", "/v1/admin/backups"),
    ("GET", "/v1/admin/backups/"),
    ("POST", "/v1/admin/backups"),
    ("POST", "/v1/admin/backups/"),
    ("GET", "/v1/admin/backups/kor-travel-transport-20261002T000000Z.dump"),
    ("GET", "/v1/admin/back%75ps"),
    ("GET", "/v1/admin/back%75ps/kor-travel-transport-20261002T000000Z.dump"),
    ("GET", "/v1/admin%2Fbackups"),
    ("GET", "/v1/admin/./backups"),
    ("GET", "/v1/parking/../admin/backups"),
    ("GET", "/v1/ADMIN/BACKUPS"),
    ("POST", "/v1/admin/backups/restore"),
    ("POST", "/v1/admin/collect"),
    ("GET", "/v1/admin/unknown"),
]


def _client(tmp_path: Path, token: str | None) -> TestClient:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "kor-travel-transport-20261002T000000Z.dump").write_bytes(b"PGDMP-secret-data")
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}",
        seed_sample_data=True,
        enable_scheduler=False,
        manual_collect_enabled=True,
        manual_collect_min_interval_seconds=0,
        data_go_kr_service_key=None,
        use_sample_client_when_no_key=True,
        airport_codes_csv="GMP,PUS,CJU",
        cors_origins_csv="http://localhost:3000",
        backup_dir=str(backup_dir),
        transport_admin_write_token=token,
    )
    return TestClient(create_app(settings))


def _send(client: TestClient, method: str, path: str, headers: dict[str, str]):
    if path.endswith("/restore"):
        return client.post(
            path, headers=headers,
            files={"file": ("restore.dump", b"PGDMP-attacker", "application/octet-stream")},
        )
    return client.request(method, path, headers=headers, follow_redirects=False)


@pytest.fixture(scope="module")
def guarded_client(tmp_path_factory: pytest.TempPathFactory):
    with _client(tmp_path_factory.mktemp("guarded"), TOKEN) as client:
        yield client


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-transport-admin-token": ""},
        {"x-transport-admin-token": "wrong"},
        {"x-transport-admin-token": TOKEN[:-1]},
        {"x-transport-admin-token": TOKEN + "x"},
        {"x-transport-admin-token": ("é" * 40).encode("latin-1")},
        {"authorization": f"Bearer {TOKEN}"},
    ],
    ids=["missing", "empty", "wrong", "prefix", "longer", "non-ascii", "bearer-only"],
)
@pytest.mark.parametrize(("method", "path"), PROTECTED_REQUESTS)
def test_admin_routes_hide_without_valid_token(guarded_client: TestClient, method: str, path: str, headers) -> None:
    create = AsyncMock()
    restore = AsyncMock()
    save = AsyncMock()
    listing = AsyncMock(return_value=[])
    with patch("app.main.create_backup", create), patch("app.main.restore_backup", restore), \
            patch("app.main.save_uploaded_backup", save), patch("app.main.list_backups", listing):
        response = _send(guarded_client, method, path, headers)

    assert response.status_code == 404, response.text
    assert b"PGDMP" not in response.content
    for fake in (create, restore, save, listing):
        fake.assert_not_called()


@pytest.mark.parametrize("configured", [None, "", "short-token"])
def test_admin_routes_closed_when_token_unset_or_weak(tmp_path: Path, configured) -> None:
    create = AsyncMock()
    with patch("app.main.create_backup", create), _client(tmp_path, configured) as client:
        statuses = {
            (method, path): _send(client, method, path, {"x-transport-admin-token": configured or ""}).status_code
            for method, path in PROTECTED_REQUESTS
        }

    assert set(statuses.values()) == {404}, statuses
    create.assert_not_called()


def test_admin_backups_work_with_valid_token(tmp_path: Path) -> None:
    headers = {"x-transport-admin-token": TOKEN}
    with _client(tmp_path, TOKEN) as client:
        listing = client.get("/v1/admin/backups", headers=headers)
        download = client.get("/v1/admin/backups/kor-travel-transport-20261002T000000Z.dump", headers=headers)

    assert listing.status_code == 200
    assert [item["filename"] for item in listing.json()["items"]] == ["kor-travel-transport-20261002T000000Z.dump"]
    assert download.status_code == 200
    assert download.content == b"PGDMP-secret-data"


def test_collector_status_stays_public(tmp_path: Path) -> None:
    with _client(tmp_path, TOKEN) as client:
        response = client.get("/v1/admin/collector-status")
        bootstrap = client.get("/v1/dashboard/bootstrap")

    assert response.status_code == 200
    assert bootstrap.status_code == 200
