"""원천 주소·정방향 좌표를 보존하며 Geo 없이 파생 주소를 갱신한다."""
from datetime import UTC, datetime

from kortravelcommon.reverse_address import (
    AddressResolver,
    DatabaseAddressSource,
    refresh_reverse_addresses,
)
from sqlalchemy import String, cast, create_engine, insert, literal, select

from app.core.config import Settings
from app.models import (
    Base,
    BusTerminalReference,
    FerryPort,
    FuelStation,
    RailStationReference,
    RestAreaReference,
)
from app.services.address_refresh import address_source, run_address_refresh


class Resolver(AddressResolver):
    provider_id = "vworld-kakao-reverse-v1"

    def reverse(self, target):
        return {"provider": "fixture", "address": {"full": "변경 주소"}, "region": {"sido": "새 지역"}}


def test_transport_coordinate_sources_keep_original_fields(tmp_path):
    url = "sqlite:///" + str(tmp_path / "address.db")
    settings = Settings(_env_file=None, database_url=url)
    engine = create_engine(url)
    tables = [model.__table__ for model in (FuelStation, BusTerminalReference, FerryPort, RailStationReference, RestAreaReference)]
    tables.extend([Base.metadata.tables["reverse_address_entries"], Base.metadata.tables["reverse_address_control"]])
    Base.metadata.create_all(engine, tables=tables)
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(insert(FuelStation), {
            "id": 1, "source": "fixture", "identity_key": "a", "name": "주유소",
            "address": "원천 주소", "longitude": 127, "latitude": 37,
            "query_level": "sigungu", "sido_value": "11", "sido_name": "검색 문맥",
            "sigungu_value": "11000", "sigungu_name": "검색 지역",
            "source_kinds": [], "first_seen_at": now, "last_seen_at": now,
        })
    try:
        result = run_address_refresh(settings, force=True, resolver=Resolver())
        assert result["requests"] == 1
        with address_source(settings) as source:
            assert source.summary()["total"] == 1
            assert source.sample()[0]["target_key"] == "fuel_station:1"
            assert source.sample()[0]["address"]["full"] == "변경 주소"
        with engine.connect() as conn:
            row = conn.execute(select(FuelStation.__table__)).mappings().one()
        assert row["address"] == "원천 주소"
        assert (row["sido_name"], row["sigungu_name"]) == ("검색 문맥", "검색 지역")
        assert (row["longitude"], row["latitude"]) == (127, 37)
    finally:
        engine.dispose()


def test_admin_summary_is_read_only_and_fail_closed(test_settings, monkeypatch):
    from fastapi.testclient import TestClient
    from kortravelcommon.address_providers import VworldKakaoAddressResolver

    from app.main import create_app

    def no_provider(*args):
        raise AssertionError("상태 조회에서 provider를 호출했습니다.")

    monkeypatch.setattr(VworldKakaoAddressResolver, "reverse", no_provider)
    settings = test_settings.model_copy(update={"transport_admin_write_token": "a" * 40,
                                               "vworld_api_key": "private-provider-key"})
    with TestClient(create_app(settings)) as client:
        path = "/v1/transport/admin/address-refresh"
        assert client.get(path).status_code == 404
        result = client.get(path, headers={"x-transport-admin-token": "a" * 40})
        assert result.status_code == 200
        assert result.json()["refresh_months"] == 6
        assert result.json()["configured"] is True
        assert "private-provider-key" not in result.text


class RecordingResolver(Resolver):
    def __init__(self):
        self.calls = []

    def reverse(self, target):
        self.calls.append(target.key)
        return super().reverse(target)


def ferry_address_fixture(tmp_path):
    url = "sqlite:///" + str(tmp_path / "ferry-address.db")
    settings = Settings(_env_file=None, database_url=url)
    engine = create_engine(url)
    models = (FuelStation, BusTerminalReference, FerryPort, RailStationReference, RestAreaReference)
    tables = [model.__table__ for model in models]
    tables.extend(Base.metadata.tables[name] for name in ("reverse_address_entries", "reverse_address_control"))
    Base.metadata.create_all(engine, tables=tables)
    now = datetime.now(UTC)
    rows = [
        {"id": i, "source": "data_go_kr_maritime", "port_id": str(i), "port_name": "시험 항구 " + str(i),
         "longitude": 127 + i * 0.1, "latitude": 37 + i * 0.1,
         "location_source": origin, "first_seen_at": now, "last_seen_at": now}
        for i, origin in enumerate(("data_go_kr_port_guideline", "admin_manual", None), start=1)
    ]
    with engine.begin() as conn:
        conn.execute(insert(FerryPort), rows)
    return settings, engine


def test_legacy_ferry_guideline_is_not_reverse_geocoded_and_sources_are_preserved(tmp_path):
    settings, engine = ferry_address_fixture(tmp_path)
    resolver = RecordingResolver()
    try:
        with engine.connect() as conn:
            before = [dict(row) for row in conn.execute(select(FerryPort.__table__)).mappings()]
        result = run_address_refresh(settings, force=True, resolver=resolver)
        assert result["requests"] == 2
        assert set(resolver.calls) == {"ferry_port:2", "ferry_port:3"}
        with address_source(settings) as source:
            assert source.summary()["total"] == 2
            assert {row["target_key"] for row in source.sample()} == {"ferry_port:2", "ferry_port:3"}
            assert source.store.row("ferry_port:1") is None
        with engine.connect() as conn:
            after = [dict(row) for row in conn.execute(select(FerryPort.__table__)).mappings()]
        assert after == before
    finally:
        engine.dispose()


def test_existing_derived_address_for_legacy_ferry_is_hidden(tmp_path):
    settings, engine = ferry_address_fixture(tmp_path)
    try:
        with address_source(settings) as source:
            # 이전 admission으로 저장된 결과를 실제 공통 엔진으로 만든다.
            old_selection = select(
                (literal("ferry_port:") + cast(FerryPort.id, String)).label("target_key"),
                FerryPort.longitude, FerryPort.latitude, FerryPort.port_name.label("display_name"),
            )
            old_source = DatabaseAddressSource(source.store, old_selection)
            refresh_reverse_addresses(
                source.store, Resolver(), old_source.page, old_source.retries,
                pending_failures=old_source.pending_failures, force=True,
            )
            assert source.store.row("ferry_port:1")["status"] == "ok"
            assert {row["target_key"] for row in source.sample()} == {"ferry_port:2", "ferry_port:3"}
            assert source.summary()["total"] == 2
    finally:
        engine.dispose()


def test_legacy_only_result_does_not_set_current_summary_confirmation(tmp_path):
    settings, engine = ferry_address_fixture(tmp_path)
    try:
        with address_source(settings) as source:
            old_selection = select(
                (literal("ferry_port:") + cast(FerryPort.id, String)).label("target_key"),
                FerryPort.longitude, FerryPort.latitude, FerryPort.port_name.label("display_name"),
            ).where(FerryPort.id == 1)
            old_source = DatabaseAddressSource(source.store, old_selection)
            refresh_reverse_addresses(
                source.store, Resolver(), old_source.page, old_source.retries,
                pending_failures=old_source.pending_failures, force=True,
            )
            original = source.store.row("ferry_port:1")
            assert original["status"] == "ok"
            summary = source.summary()
            assert summary["total"] == summary["due"] == 2
            assert summary["items"] == []
            assert summary["last_resolved_at"] is None
            assert source.store.row("ferry_port:1") == original
    finally:
        engine.dispose()
