"""DB 값이 같은 완료 집합은 재구성하지 않고, 변경·상태·cursor 경계는 그대로 지킨다."""

# ruff: noqa: F811

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, update

from app.core.time_utils import now_utc, serialize_utc
from app.models import KricStationCode, KricStationMappingRegistry, RailStationReference, ReferenceExportState, ReferenceExportArtifactItem, ServiceExportSnapshot
from app.services import export_current, export_references
from test_rail_export import PATH, seed
from test_service_exports import HEADERS, _run, export_client  # noqa: F401


def _prepare(client):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 입력 지문·RR 통합 검증")
    client.app.state.settings.transport_map_current_enabled = True
    client.app.state.settings.release_sha = "reference-reuse-test-v1"
    _run(client, seed)


def _get(client, **kwargs):
    return client.get(PATH, headers=HEADERS, params={"limit": 1, **kwargs})


def test_completed_snapshot_and_next_epoch_do_not_rebuild_payload(export_client, monkeypatch):
    c = export_client
    _prepare(c)
    moment = now_utc()
    monkeypatch.setattr(export_references, "now_utc", lambda: moment)
    first = _get(c)
    assert first.status_code == 200, first.text
    original = first.json()
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("완료 집합 재사용에서 source/주소 DTO를 다시 구성했습니다")
    monkeypatch.setattr(export_references, "export_admin_addresses", forbidden)
    same = c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["ETag"]}, params={"limit": 1})
    assert same.status_code == 304, same.text
    later = moment + export_current.SNAPSHOT_TTL
    monkeypatch.setattr(export_references, "now_utc", lambda: later)
    monkeypatch.setattr(export_current, "now_utc", lambda: later)
    renewed = _get(c)
    assert renewed.status_code == 200, renewed.text
    value = renewed.json()
    assert value["snapshot_id"] != original["snapshot_id"]
    assert value["items"] == original["items"]
    assert serialize_utc(datetime.fromisoformat(value["snapshot_expires_at"].replace("Z", "+00:00"))) >= later + timedelta(minutes=15)
    assert _get(c, cursor=original["next_cursor"]).status_code == 200
    assert _get(c, cursor=value["next_cursor"]).status_code == 200
    expired = later + timedelta(minutes=31)
    monkeypatch.setattr(export_references, "now_utc", lambda: expired)
    assert _get(c, cursor=original["next_cursor"]).status_code == 410


@pytest.mark.parametrize("change,expected", [
    ("name", 200), ("coordinates", 200), ("code_name", 200), ("inactive", 200),
    ("registry", 200), ("invalid_registry", 503), ("missing_row", 503), ("wrong_confirmation", 503),
])
def test_mutations_without_a_timestamp_bump_never_reuse_old_payload(export_client, change, expected):
    c = export_client
    _prepare(c)
    first = _get(c)
    assert first.status_code == 200, first.text
    old = first.json()
    async def mutate(s):
        if change == "name":
            await s.execute(update(RailStationReference).where(RailStationReference.identity_key == "rail-0").values(station_name="새 역명"))
        elif change == "coordinates":
            await s.execute(update(RailStationReference).where(RailStationReference.identity_key == "rail-0").values(latitude=37.6))
        elif change == "code_name":
            await s.execute(update(KricStationCode).values(station_name="새 공식명"))
        elif change == "inactive":
            await s.execute(update(KricStationCode).values(active=False))
        elif change == "registry":
            await s.execute(update(KricStationMappingRegistry).values(catalog_sha256="b" * 64))
        elif change == "invalid_registry":
            await s.execute(update(KricStationMappingRegistry).values(manual_mappings_json=[{"operator_code": "00"}]))
        elif change == "missing_row":
            await s.execute(delete(RailStationReference).where(RailStationReference.identity_key == "rail-1"))
        else:
            await s.execute(update(RailStationReference).values(last_seen_at=now_utc() + timedelta(seconds=1)))
    _run(c, mutate)
    response = _get(c)
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.json()["snapshot_id"] != old["snapshot_id"]
        assert response.json()["items"] != old["items"]


def test_failed_source_status_changes_immediately_without_payload_rebuild(export_client, monkeypatch):
    c = export_client
    _prepare(c)
    first = _get(c)
    assert first.status_code == 200, first.text
    async def fail(s):
        await s.execute(update(ReferenceExportState).values(last_error="new failure", last_attempt_at=now_utc()))
    _run(c, fail)
    async def forbidden(*_args, **_kwargs):
        raise AssertionError("상태 변경을 이유로 불변 본문을 다시 구성했습니다")
    monkeypatch.setattr(export_references, "export_admin_addresses", forbidden)
    result = c.get(PATH, headers={**HEADERS, "If-None-Match": first.headers["ETag"]}, params={"limit": 1})
    assert result.status_code == 200, result.text
    assert result.json()["meta"]["source_status"] == "stale"
    assert result.json()["snapshot_id"] == first.json()["snapshot_id"]


def test_incomplete_previous_epoch_snapshot_is_not_copied(export_client, monkeypatch):
    c = export_client
    _prepare(c)
    moment = now_utc()
    monkeypatch.setattr(export_references, "now_utc", lambda: moment)
    first = _get(c)
    assert first.status_code == 200, first.text
    async def remove(s):
        snapshot = await s.get(ServiceExportSnapshot, first.json()["snapshot_id"])
        await s.execute(delete(ReferenceExportArtifactItem).where(ReferenceExportArtifactItem.artifact_id == snapshot.artifact_id, ReferenceExportArtifactItem.ordinal == 2))
    _run(c, remove)
    monkeypatch.setattr(export_references, "now_utc", lambda: moment + export_current.SNAPSHOT_TTL)
    result = _get(c)
    assert result.status_code == 503, result.text


def test_rail_catalog_projection_preserves_linked_and_unlinked_places(export_client):
    c = export_client
    _run(c, seed)
    async def add(s):
        s.add(KricStationCode(operator_code="01", line_code="02", station_code="0003", operator_name="운영사",
                              line_name="노선", station_name="좌표 없음", active=True, last_seen_at=now_utc()))
    _run(c, add)
    from app.services.rail_catalog import metro_station_catalog
    async def read(s):
        result = await metro_station_catalog(s)
        assert len(s.identity_map) == 0
        return result
    result = _run(c, read)
    assert len(result.items) == 2
    assert result.items[0].provider_id == "00/01/001"
    assert result.items[0].name == "중앙역" and result.items[0].line_names == ["다른 노선 표기"]
    assert result.items[0].latitude == 37.5 and result.items[0].longitude == 127.1
    assert result.items[1].provider_id == "01/02/0003" and result.items[1].latitude is None
    assert result.items[1].address is None and result.items[1].facilities == []
    response = c.get("/v1/transport/rail/stations")
    assert response.status_code == 200
    assert response.json()["items"] == result.model_dump(mode="json")["items"]
