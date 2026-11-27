"""휴게소 먹거리 수집(KREX 0615 코드 + 0502 메뉴)과 `/v1/service/exports/rest-area-food`."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from app.core.time_utils import now_utc
from app.dagster.definitions import definitions
from app.services.rest_area_collection import (
    REST_AREA_FOOD_SOURCE,
    EmptyRestAreaCollectionError,
    RestAreaCollectionService,
)
from fastapi.testclient import TestClient
from krex import Direction, MenuSeason, RestAreaCode, RestAreaFoodMenu, ServiceAreaClass

from test_service_exports import HEADERS, _run, _set_state, export_client  # noqa: F401 — fixture 재사용

PATH = "/v1/service/exports/rest-area-food"


def _code(code: str, name: str, *, cls: str = "0", direction: str = "1", route_name: str | None = None) -> RestAreaCode:
    return RestAreaCode(
        std_rest_code=code, name=name, facility_class=ServiceAreaClass(cls), direction=Direction(direction),
        route_code="0010", route_name=route_name, service_area_code=("A" if cls == "0" else "B") + code[1:],
        address="경기 어딘가", postal_code=None, phone_number="0310000000", head_office_code=None,
        head_office_name=None, branch_office_code=None, branch_office_name=None, raw={"svarCd": code, "svarNm": name},
    )


def _menu(code: str, seq: str, name: str, price: int | None, *, best: bool = False,
          season: MenuSeason | None = MenuSeason.ALL_YEAR, rest_name: str = "서울만남(부산)휴게소") -> RestAreaFoodMenu:
    return RestAreaFoodMenu(
        std_rest_code=code, rest_area_name=rest_name, rest_code="S" + code, seq=seq, food_name=name, price=price,
        description=None, ingredients=None, is_recommended=False, is_best=best, is_premium=False, season=season,
        app_listed=True, route_code="0010", route_name="경부선", address="서울 서초구", menu_updated_on=date(2025, 8, 28),
        source_updated_on=date(2026, 11, 27), raw={"stdRestCd": code, "seq": seq},
    )


class FakeKrex:
    def __init__(self, codes, menus) -> None:
        self.codes, self.menus = codes, menus
        self.restarea = self
        self.menu_pages: list[int] = []

    async def service_area_codes(self):
        return SimpleNamespace(items=tuple(self.codes), total_count=len(self.codes), num_of_rows=None)

    async def food_menus(self, *, num_of_rows: int, page_no: int):
        self.menu_pages.append(page_no)
        start = (page_no - 1) * num_of_rows
        chunk = self.menus[start:start + num_of_rows]
        return SimpleNamespace(items=tuple(chunk), total_count=len(self.menus), num_of_rows=num_of_rows)

    async def aclose(self) -> None:
        return None


def _service(client: TestClient, fake: FakeKrex) -> RestAreaCollectionService:
    settings = client.app.state.settings
    settings.rest_area_collection_enabled = True
    settings.kex_ex_api_key = "ex-key"
    return RestAreaCollectionService(settings, client_factory=lambda **_: fake)


def test_food_export_is_hidden_until_collected_then_serves_codes_with_menus(export_client: TestClient) -> None:
    settings = export_client.app.state.settings
    assert _run(export_client, RestAreaCollectionService(settings).collect_food)["status"] == "skipped"
    assert export_client.get(PATH, headers=HEADERS).status_code == 503

    menus = [_menu("000001", str(seq), f"메뉴{seq}", 1000 * seq, best=seq == 2) for seq in range(1, 101)]
    menus.append(_menu("000161", "1", "함양 국밥", 9000, rest_name="함양(대전)휴게소"))
    fake = FakeKrex([
        _code("000001", "서울만남(부산)휴게소"),
        _code("000002", "서울만남(부산)주유소", cls="1"),
        _code("000003", "죽전(서울)휴게소", direction="0", route_name="경부선"),
    ], menus)
    result = _run(export_client, _service(export_client, fake).collect_food)
    assert result["status"] == "success"
    assert fake.menu_pages == [1, 2]  # 99행 페이지 두 장
    assert result["stored"] == 4 + 101  # 0615 3 + 0502에만 있는 코드 1 + 메뉴 101

    payload = export_client.get(PATH, headers=HEADERS, params={"limit": 2}).json()
    assert payload["collection"]["source"] == REST_AREA_FOOD_SOURCE
    assert payload["has_more"] is True
    first = payload["items"][0]
    assert first["std_rest_code"] == "000001" and first["service_area_code"] == "A00001"
    assert first["facility_class"] == "rest_area" and first["direction"] == "down"
    assert first["route_name"] == "경부선"  # 0615가 비워 준 노선명을 메뉴 행에서 채운다
    assert [menu["seq"] for menu in first["menus"][:3]] == ["1", "2", "3"]  # 숫자 순
    assert first["menus"][1] == {
        "seq": "2", "name": "메뉴2", "price": 2000, "is_best": True, "is_premium": False, "is_recommended": False,
        "season": "all_year", "app_listed": True, "menu_updated_on": "2025-08-28",
    }
    assert payload["items"][1]["facility_class"] == "gas_station" and payload["items"][1]["menus"] == []
    rest = export_client.get(PATH, headers=HEADERS, params={"cursor": payload["next_cursor"]}).json()
    assert [item["std_rest_code"] for item in rest["items"]] == ["000003", "000161"]
    orphan = rest["items"][1]
    assert orphan["name"] == "함양(대전)휴게소" and orphan["facility_class"] is None
    assert [menu["name"] for menu in orphan["menus"]] == ["함양 국밥"]

    # 다음 수집에서 빠진 메뉴는 바로 사라진다(3일 여유 없음). 가격 변경은 덮어쓴다.
    fake.menus = [_menu("000001", "1", "메뉴1", 1500), _menu("000003", "7", "호두과자", 5000)]
    _run(export_client, _service(export_client, fake).collect_food)
    items = {item["std_rest_code"]: item for item in export_client.get(PATH, headers=HEADERS).json()["items"]}
    assert [(menu["seq"], menu["price"]) for menu in items["000001"]["menus"]] == [("1", 1500)]
    assert "000161" not in items  # 이번 수집이 보지 않은 메뉴 전용 코드
    assert [menu["name"] for menu in items["000003"]["menus"]] == ["호두과자"]


@pytest.mark.parametrize("codes, menus", [
    ([], [_menu("000001", "1", "우동", 7000)]),
    ([_code("000001", "서울만남(부산)휴게소")], []),
])
def test_food_collection_with_an_empty_side_fails_and_keeps_the_last_set(export_client: TestClient, codes, menus) -> None:
    fake = FakeKrex([_code("000001", "서울만남(부산)휴게소")], [_menu("000001", "1", "우동", 7000)])
    service = _service(export_client, fake)
    _run(export_client, service.collect_food)
    fake.codes, fake.menus = codes, menus
    with pytest.raises(EmptyRestAreaCollectionError):
        _run(export_client, service.collect_food)
    served = export_client.get(PATH, headers=HEADERS).json()
    assert served["items"][0]["menus"][0]["name"] == "우동"
    assert served["collection"]["last_attempt_failed"] is True
    _run(export_client, lambda session: _set_state(
        session, REST_AREA_FOOD_SOURCE, last_success_at=now_utc() - timedelta(days=3, minutes=1)))
    assert export_client.get(PATH, headers=HEADERS).status_code == 503


def test_food_job_is_scheduled_daily() -> None:
    schedule = definitions.get_schedule_def("rest_area_food_collection_job_schedule")
    assert schedule.cron_schedule == "50 3 * * *"
    assert schedule.execution_timezone == "Asia/Seoul"
    assert schedule.default_status.name == "RUNNING"
