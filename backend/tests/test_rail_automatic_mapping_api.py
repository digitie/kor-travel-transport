"""자동 연결 관리자 API와 기존 수동 API 계약의 호환성."""
import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.main import create_app
from app.models import KricStationCode, KricStationMappingRegistry
from test_rail_automatic_mapping_db import seed

PATH = "/v1/transport/admin/rail-station-mappings/automatic"
MANUAL_PATH = "/v1/transport/admin/rail-station-mappings"
TOKEN = "automatic-test-" + "a" * 32
HEADERS = {"x-transport-admin-token": TOKEN}


@pytest.fixture
def automatic_client(test_settings):
    settings = test_settings.model_copy(update={"transport_admin_write_token": TOKEN, "seed_sample_data": False})
    with TestClient(create_app(settings)) as client:
        yield client


def body(preview):
    return {key: preview[key] for key in ("expected_revision", "candidate_revision")}


def test_automatic_api_previews_applies_and_preserves_existing_manual_contract(automatic_client):
    client = automatic_client
    asyncio.run(seed(client.app.state.session_factory))
    response = client.get(PATH, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store, private"
    preview = response.json()
    assert preview["before"]["station_count"] == 3
    assert preview["before"]["mapped_count"] == 2 and preview["after"]["mapped_count"] == 3
    assert preview["can_apply"] and preview["changes"][0]["change_type"] == "added"
    assert "note" not in response.text and "legacy_metadata" not in response.text
    old = client.get(MANUAL_PATH, headers=HEADERS).json()
    assert old["revision"] == preview["expected_revision"]
    saved = client.post(PATH, headers=HEADERS, json=body(preview))
    assert saved.status_code == 200, saved.text
    assert saved.headers["cache-control"] == "no-store, private"
    assert saved.json()["status"] == "applied" and saved.json()["changed_link_count"] == 1
    current = client.get(MANUAL_PATH, headers=HEADERS).json()
    assert current["revision"] == saved.json()["revision"]
    assert current["manual_mapped_count"] == 1 and current["automatic_mapped_count"] == 2
    assert current["mappings"] == old["mappings"]
    refreshed = client.get(PATH, headers=HEADERS).json()
    assert not refreshed["has_changes"] and refreshed["can_apply"]
    noop = client.post(PATH, headers=HEADERS, json=body(refreshed))
    assert noop.status_code == 200 and noop.json()["status"] == "unchanged"
    assert noop.json()["changed_link_count"] == 0


@pytest.mark.parametrize("field", ["expected_revision", "candidate_revision"])
def test_automatic_api_stale_hash_is_string_detail_409(automatic_client, field):
    client = automatic_client
    asyncio.run(seed(client.app.state.session_factory))
    payload = body(client.get(PATH, headers=HEADERS).json())
    payload[field] = "0" * 64
    failed = client.post(PATH, headers=HEADERS, json=payload)
    assert failed.status_code == 409 and isinstance(failed.json()["detail"], str)
    assert failed.headers["cache-control"] == "no-store, private"


def test_automatic_api_rejects_unprepared_store_and_extra_manual_input(automatic_client):
    client = automatic_client
    missing = client.get(PATH, headers=HEADERS)
    assert missing.status_code == 503 and isinstance(missing.json()["detail"], str)
    assert missing.headers["cache-control"] == "no-store, private"
    invalid = client.post(PATH, headers=HEADERS, json={"expected_revision": "a" * 64,
        "candidate_revision": "b" * 64, "mappings": []})
    assert invalid.status_code == 422


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_automatic_api_auth_precedes_body_validation(automatic_client, method):
    response = automatic_client.request(method, PATH, content="{invalid")
    assert response.status_code == 404


def test_automatic_api_openapi_documents_models_and_errors(automatic_client):
    schema = automatic_client.app.openapi()
    get, post = schema["paths"][PATH]["get"], schema["paths"][PATH]["post"]
    assert get["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("KricAutomaticMappingPreview")
    assert post["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("KricAutomaticMappingApplyRequest")
    assert post["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("KricAutomaticMappingApplyResponse")
    for operation in (get, post):
        for status in ("404", "409", "503"):
            assert "application/problem+json" in operation["responses"][status]["content"]
    request_schema = schema["components"]["schemas"]["KricAutomaticMappingApplyRequest"]
    assert set(request_schema["required"]) == {"expected_revision", "candidate_revision"}
    assert request_schema["additionalProperties"] is False


def test_existing_manual_save_makes_automatic_preview_stale(automatic_client):
    client = automatic_client
    asyncio.run(seed(client.app.state.session_factory))
    preview = client.get(PATH, headers=HEADERS).json()
    old = client.get(MANUAL_PATH, headers=HEADERS).json()
    mappings = old["mappings"]
    mappings[0]["note"] = "다른 관리자 변경"
    saved = client.post(MANUAL_PATH, headers=HEADERS, json={"expected_revision": old["revision"], "mappings": mappings})
    assert saved.status_code == 200
    stale = client.post(PATH, headers=HEADERS, json=body(preview))
    assert stale.status_code == 409 and isinstance(stale.json()["detail"], str)


@pytest.mark.parametrize("bucket", ["automatic", "manual"])
def test_missing_stored_target_returns_503_without_repair_or_writes(automatic_client, monkeypatch, bucket):
    client = automatic_client
    asyncio.run(seed(client.app.state.session_factory))
    valid_preview = client.get(PATH, headers=HEADERS).json()

    async def corrupt_stored_input():
        async with client.app.state.session_factory() as session:
            registry = await session.get(KricStationMappingRegistry, 1)
            field = bucket + "_mappings_json"
            records = deepcopy(getattr(registry, field))
            item = {"operator_code": "KR", "line_code": "K4", "station_code": "P313",
                "rail_station_identity_key": "ghost", "legacy_metadata": {"원문": True}}
            if bucket == "automatic":
                item["match_method"] = "exact_identity"
            else:
                item["note"] = "  없는 대상도 자동 정정하지 않는 원문 🙂  "
            records.append(item)
            setattr(registry, field, records)
            await session.commit()

    async def stored_state():
        async with client.app.state.session_factory() as session:
            registry = await session.get(KricStationMappingRegistry, 1)
            links = (await session.execute(select(KricStationCode.station_code, KricStationCode.rail_station_id)
                .order_by(KricStationCode.station_code))).all()
            return deepcopy({"automatic": registry.automatic_mappings_json, "manual": registry.manual_mappings_json,
                "catalog": registry.catalog_json, "sha": registry.catalog_sha256,
                "updated_at": registry.updated_at, "mappings_updated_at": registry.mappings_updated_at,
                "links": [tuple(row) for row in links]})

    asyncio.run(corrupt_stored_input())
    before = asyncio.run(stored_state())
    assert dict(before["links"])["P313"] is None
    writes = []
    event.listen(client.app.state.engine.sync_engine, "before_cursor_execute",
        lambda conn, cursor, sql, params, ctx, many: writes.append(sql) if sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) else None)
    provider_guard = AsyncMock(side_effect=AssertionError("미준비 입력에서 외부 조회 금지"))
    monkeypatch.setattr(httpx.AsyncClient, "request", provider_guard)
    monkeypatch.setattr(client.app.state.transport_collection_service, "collect", provider_guard)
    get = client.get(PATH, headers=HEADERS)
    post = client.post(PATH, headers=HEADERS, json=body(valid_preview))
    assert get.status_code == post.status_code == 503
    assert "기준 역에 없는" in get.json()["detail"]
    assert "기준 역에 없는" in post.json()["detail"]
    assert get.headers["cache-control"] == post.headers["cache-control"] == "no-store, private"
    assert asyncio.run(stored_state()) == before
    assert not writes
    provider_guard.assert_not_awaited()
