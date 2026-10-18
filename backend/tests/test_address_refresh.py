"""원천 주소·정방향 좌표를 보존하며 Geo 없이 파생 주소를 갱신한다."""
from datetime import UTC, datetime

from sqlalchemy import create_engine, insert, select

from app.core.config import Settings
from app.models import Base, BusTerminalReference, FerryPort, FuelStation, RailStationReference, RestAreaReference
from app.services.address_refresh import address_source, run_address_refresh
from kortravelcommon.reverse_address import AddressResolver


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
    from app.main import create_app
    from kortravelcommon.address_providers import VworldKakaoAddressResolver

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
