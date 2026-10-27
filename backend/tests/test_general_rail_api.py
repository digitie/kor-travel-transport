from datetime import timedelta
from types import SimpleNamespace

from datagokr.exceptions import TransportError
from fastapi.testclient import TestClient

from app.core.time_utils import now_utc, to_seoul
from app.main import create_app


class FakeTrain:
    def __init__(self):
        self.calls = []
        self.failure = None

    async def city_list(self):
        self.calls.append("cities")
        if self.failure:
            raise self.failure
        return SimpleNamespace(items=[SimpleNamespace(city_code="11", city_name="서울"), SimpleNamespace(city_code="21", city_name="부산")])

    async def class_list(self):
        self.calls.append("classes")
        return SimpleNamespace(items=[SimpleNamespace(grade_id="00", grade_name="KTX"), SimpleNamespace(grade_id="0A", grade_name="KTX-산천")])

    async def station_list(self, **params):
        self.calls.append(params)
        return SimpleNamespace(total_count=2, items=[SimpleNamespace(station_id="NAT010000", station_name="서울"), SimpleNamespace(station_id="NAT014445", station_name="부산")])

    async def timetable_list(self, **params):
        self.calls.append(params)
        return SimpleNamespace(total_count=1, items=[SimpleNamespace(train_number="001", grade_name="KTX", dep_place_name="서울", arr_place_name="부산", dep_planned_time="202610242330", arr_planned_time="202610250130", adult_charge=59800)])


def fake_client(train):
    class Client:
        def __init__(self, **kwargs):
            self.train = train
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            pass
    return Client


def test_train_catalog_stations_and_timetable_persist_and_reuse_success(test_settings, monkeypatch):
    train = FakeTrain()
    monkeypatch.setattr("app.general_rail_routes.DataGoKrClient", fake_client(train))
    settings = test_settings.model_copy(update={"data_go_kr_service_key": "fake-secret"})
    with TestClient(create_app(settings)) as client:
        catalog = client.get("/v1/transport/rail/general/catalog")
        assert catalog.status_code == 200
        assert catalog.json()["train_classes"] == [{"code": "00", "name": "KTX"}, {"code": "0A", "name": "KTX-산천"}]
        assert client.get("/v1/transport/rail/general/catalog").json() == catalog.json()
        assert train.calls == ["cities", "classes"]
        assert client.get("/v1/transport/rail/general/stations", params={"city_code": "9999"}).status_code == 422
        assert train.calls == ["cities", "classes"]
        stations = client.get("/v1/transport/rail/general/stations", params={"city_code": "11"})
        assert stations.status_code == 200 and len(stations.json()["items"]) == 2
        day = to_seoul(now_utc()).date().isoformat()
        params = {"departure_station_id": "NAT010000", "arrival_station_id": "NAT014445", "date": day, "train_grade_code": "0A"}
        result = client.get("/v1/transport/rail/general/timetable", params=params)
        assert result.status_code == 200
        row = result.json()["items"][0]
        assert row["train_number"] == "001" and row["arrival_planned_time"] == "202610250130"
        assert row["adult_fare"] == 59800
        assert client.get("/v1/transport/rail/general/timetable", params=params).json() == result.json()
        assert len(train.calls) == 4
        assert "fake-secret" not in result.text
        params["date"] = (to_seoul(now_utc()).date() + timedelta(days=10)).isoformat()
        assert client.get("/v1/transport/rail/general/timetable", params=params).status_code == 422
        assert len(train.calls) == 4


def test_train_access_denied_is_not_an_empty_catalog_and_stops_repeated_calls(test_settings, monkeypatch):
    train = FakeTrain()
    train.failure = TransportError("secret provider URL must not leak", status_code=403)
    monkeypatch.setattr("app.general_rail_routes.DataGoKrClient", fake_client(train))
    with TestClient(create_app(test_settings.model_copy(update={"data_go_kr_service_key": "fake"}))) as client:
        result = client.get("/v1/transport/rail/general/catalog")
        assert result.status_code == 502
        assert "접근이 거부" in result.text and "secret" not in result.text
        assert client.get("/v1/transport/rail/general/catalog").status_code == 429
        assert train.calls == ["cities"]



def test_public_station_guide_is_keyless_and_independent_of_tago_denial(test_settings, monkeypatch):
    from kric import KorailGuideCategory, KorailGuidePage, KorailStationGuide
    calls = []
    class PublicClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def get_guide_page(self, *, kind):
            calls.append(("catalog", kind))
            return KorailGuidePage(kind, 1, 19, (), (KorailGuideCategory("ktx1", "경부선", kind),))
        async def get_located_category_stations(self, *, kind, category_code):
            calls.append(("located", category_code))
            return KorailGuidePage(kind, 1, 1, (KorailStationGuide("001", "서울", "서울특별시", "1588-7788", ("ktx1",), "0001", 126.97, 37.55),), (KorailGuideCategory("ktx1", "경부선", kind),))
    monkeypatch.setattr("app.general_rail_routes.KorailPublicClient", PublicClient)
    train = FakeTrain()
    train.failure = TransportError("private source error", status_code=403)
    monkeypatch.setattr("app.general_rail_routes.DataGoKrClient", fake_client(train))
    settings = test_settings.model_copy(update={"seed_sample_data": False, "data_go_kr_service_key": "fake"})
    with TestClient(create_app(settings)) as client:
        assert client.get("/v1/transport/rail/general/catalog").status_code == 502
        catalog = client.get("/v1/transport/rail/general/guide")
        assert catalog.status_code == 200 and catalog.json()["items"] == []
        result = client.get("/v1/transport/rail/general/guide", params={"kind": "ktx", "category_code": "ktx1"})
        assert result.status_code == 200
        assert result.json()["items"][0]["provider_id"] == "001"
        assert result.json()["items"][0]["longitude"] == 126.97
        before = len(calls)
        assert client.get("/v1/transport/rail/general/guide", params={"kind": "ktx", "category_code": "ktx1"}).json() == result.json()
        assert len(calls) == before
        assert client.get("/v1/transport/rail/general/guide", params={"category_code": "unknown"}).status_code == 422
        assert client.get("/v1/transport/rail/general/guide", params={"kind": "metro"}).status_code == 422



def _guide_client(monkeypatch, calls, categories):
    from kric import KorailGuidePage

    class PublicClient:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
        async def get_guide_page(self, *, kind):
            calls.append(("catalog", kind))
            return KorailGuidePage(kind, 1, 0, (), categories)
        async def get_located_category_stations(self, *, kind, category_code):
            calls.append(("located", category_code))
            return KorailGuidePage(kind, 1, 0, (), categories)
    monkeypatch.setattr("app.general_rail_routes.KorailPublicClient", PublicClient)


def test_unknown_guide_category_is_checked_against_the_kind_page_before_any_provider_call(test_settings, monkeypatch):
    from kric import KorailGuideCategory
    calls = []
    _guide_client(monkeypatch, calls, (KorailGuideCategory("ktx1", "경부선", "ktx"),))
    with TestClient(create_app(test_settings.model_copy(update={"seed_sample_data": False}))) as client:
        # kind 페이지가 없으면 한 번 받아 저장한 뒤 검증한다.
        assert client.get("/v1/transport/rail/general/guide", params={"category_code": "unknown"}).status_code == 422
        assert calls == [("catalog", "ktx")]
        # 캐시된 kind 페이지로 거절한다 — 일일 호출 횟수를 쓰지 않는다.
        assert client.get("/v1/transport/rail/general/guide", params={"category_code": "other"}).status_code == 422
        assert calls == [("catalog", "ktx")]


def test_daily_cap_retry_after_points_to_the_next_korean_midnight(test_settings, monkeypatch):
    from datetime import datetime, timezone

    from kric import KorailGuideCategory
    calls = []
    _guide_client(monkeypatch, calls, tuple(KorailGuideCategory(f"c{index}", f"권역{index}", "ktx") for index in range(100)))
    fixed = datetime(2026, 10, 27, 11, tzinfo=timezone.utc)  # KST 20:00
    monkeypatch.setattr("app.general_rail_routes.now_utc", lambda: fixed)
    with TestClient(create_app(test_settings.model_copy(update={"seed_sample_data": False}))) as client:
        for index in range(95):  # kind 페이지 1회 + 권역 95회 = 일일 96회
            assert client.get("/v1/transport/rail/general/guide", params={"category_code": f"c{index}"}).status_code == 200
        capped = client.get("/v1/transport/rail/general/guide", params={"category_code": "c99"})
    assert capped.status_code == 429
    # 상한은 KST 자정에 초기화된다. 3600초 뒤 재시도는 자정까지 매번 429다.
    assert capped.headers["retry-after"] == str(4 * 3600)


def test_separate_cache_misses_share_one_provider_rate_limiter(test_settings, monkeypatch):
    import time
    timestamps = []
    limiters = []
    class LimitedTrain(FakeTrain):
        def __init__(self, limiter):
            super().__init__()
            self.limiter = limiter
        async def station_list(self, **params):
            await self.limiter.acquire()
            timestamps.append(time.monotonic())
            return await super().station_list(**params)
    class Client:
        def __init__(self, *, rate_limiter, **kwargs):
            limiters.append(rate_limiter)
            self.train = LimitedTrain(rate_limiter)
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass
    monkeypatch.setattr("app.general_rail_routes.DataGoKrClient", Client)
    with TestClient(create_app(test_settings.model_copy(update={"seed_sample_data": False, "data_go_kr_service_key": "fake"}))) as client:
        assert client.get("/v1/transport/rail/general/catalog").status_code == 200
        for city in ("11", "21"):
            assert client.get("/v1/transport/rail/general/stations", params={"city_code": city}).status_code == 200
    assert len(limiters) == 3 and all(value is limiters[0] for value in limiters)
    assert timestamps[1] - timestamps[0] >= .95
