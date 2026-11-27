"""고속도로 휴게소 기준정보와 휴게소 주유소 현재 유가 수집 (ADR-013).

- 기준정보: data.go.kr 표준데이터 `tn_pubr_public_rest_area_api`(`krex.restarea.list_all`,
  data.go.kr 키). 원천에 안정 식별자가 없어 `name::route_name::direction`(strip→lower)을
  자연키로 쓴다 — kor-travel-map이 같은 원천에서 쓰던 키와 같아야 이관 뒤 Feature가 이어진다.
- 유가: 한국도로공사 EX `curStateStation`(`krex.restarea.fuel_prices`, EX 키). 휴게소 코드
  (`service_area_code`)별 현재값 1행만 유지한다. 원천에 관측 시각이 없어 수집 시각을 쓴다.
- 먹거리: 한국도로공사 EX 0615 휴게소코드정보(`krex.restarea.service_area_codes`)와 0502 푸드메뉴
  (`krex.restarea.food_menus`). 두 원천을 한 수집·한 transaction으로 받아 같은 시각으로 남긴다 — 코드와
  메뉴가 서로 다른 세대가 되지 않게 한다. 휴게소 기준정보(data.go.kr)와의 대응은 소비자(Map)가 맞춘다.

두 수집 모두 성공한 수집 시각을 `transport_collection_states.last_success_at`과 각 행의
`last_seen_at`에 같은 값으로 남긴다. service export는 이 값으로 "마지막 수집이 본 집합"을 고른다.
"""

from __future__ import annotations

from app.services.fuel_statistics import STATISTICS_PRICE_LIMIT, cleanup_fuel_statistics, try_publish_fuel_statistics

import asyncio
from datetime import timedelta
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from krex import KrexClient, RestArea, RestAreaCode as KrexRestAreaCode, RestAreaFoodMenu as KrexRestAreaFoodMenu
from krex import RestAreaFuelPrice as KrexRestAreaFuelPrice
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.models import (
    CollectionRun,
    RawApiResponse,
    RestAreaCode,
    RestAreaFoodMenu,
    RestAreaFuelPrice,
    RestAreaReference,
)
from app.services.transport_collection import (
    _collect_krex_pages,
    _plain_json,
    get_or_create_state,
)

logger = logging.getLogger(__name__)

REST_AREA_SOURCE = "krex_rest_area"
REST_AREA_FUEL_SOURCE = "krex_rest_area_fuel"
REST_AREA_TRIGGER = "dagster_rest_area_reference"
REST_AREA_FUEL_TRIGGER = "dagster_rest_area_fuel"
REST_AREA_FOOD_SOURCE = "krex_rest_area_food"
REST_AREA_FOOD_TRIGGER = "dagster_rest_area_food"
#: 0502는 서버가 한 페이지를 99행으로 자른다(2026-11-27 실측 7,291행 = 74페이지).
FOOD_MENU_PAGE_SIZE = 99
#: 0502 페이지 상한(약 29,700행). 공용 KREX 상한(100페이지 = 9,900행)은 지금 행 수의 1.36배뿐이라 따로 둔다.
FOOD_MENU_MAX_PAGES = 300
#: 엄격 파서(krex)가 버린 행 비율의 상한. 넘으면 계약이 바뀐 것으로 보고 수집을 실패시킨다. 그 아래면 행만 빼고
#: 건수를 경고로 남긴다 — 모르는 값 한 행이 매일 수집 전체를 막지 않게 한다.
FOOD_MAX_INVALID_RATIO = 0.01
#: 직전 성공 집합 대비 이보다 줄면 실패(상류가 일부만 준 날 Map이 메뉴를 대량 삭제로 읽지 않게).
FOOD_MIN_KEEP_RATIO = {"codes": 0.9, "menus": 0.8}
#: 직전 집합이 이보다 작으면 비율 하한을 보지 않는다(운영은 코드 약 585·메뉴 약 7,300행).
FOOD_KEEP_RATIO_BASELINE = 50
#: 마지막 성공이 이보다 오래면 비율 하한을 보지 않는다 — 원천이 정당하게 크게 줄었을 때 매일 실패로 굳지 않고
#: 다음날(약 48시간 뒤) 수집이 새 집합을 받는다. export stale(3일)보다 먼저 풀린다.
FOOD_KEEP_RATIO_MAX_AGE = timedelta(hours=36)
_FACILITY_CLASSES = {"0": "rest_area", "1": "gas_station"}
_DIRECTIONS = {"0": "up", "1": "down"}
_SEASONS = {"4": "all_year", "S": "summer", "W": "winter"}


def rest_area_identity(name: str | None, route_name: str | None, direction: str | None) -> str:
    """휴게소 자연키. kor-travel-map `_rest_area_natural_key`와 같은 규칙이다."""
    return "::".join((value or "").strip().lower() for value in (name, route_name, direction))


class EmptyRestAreaCollectionError(RuntimeError):
    """휴게소 기준정보·휴게소 유가 수집이 저장할 행을 0건 받았다.

    두 원천은 전국 집합이라 0건은 "휴게소가 없다"가 아니라 상류 장애·계약 변화다. 성공으로 남기면
    3일 창이 지난 뒤 export가 빈 200을 내고 소비자(Map)가 전량 삭제로 읽는다. 실패로 남겨 export가
    503이 되게 한다(ADR-013).
    """


class ShrunkRestAreaFoodCollectionError(EmptyRestAreaCollectionError):
    """휴게소 먹거리 집합이 직전 성공보다 크게 줄었다(상류 일부 응답 의심). 직전 집합을 유지한다."""


class InvalidRestAreaFoodRowsError(RuntimeError):
    """0502/0615 응답에서 파싱하지 못한 행이 상한을 넘었다(계약 변화 의심)."""


async def _collect_food_pages(
    fetch: Callable[[int], Awaitable[Any]], endpoint: str, *, max_pages: int,
) -> tuple[tuple[Any, ...], int]:
    """전 페이지를 읽어 (파싱된 행, 버린 행 수)를 돌려준다. 원문 행 합계는 `count`와 같아야 한다.

    공용 `_collect_krex_pages`는 파싱된 행 수를 `count`와 맞춰 한 행만 못 읽어도 실패한다. 여기서는 원문 행
    수(`raw.list`)로 완결을 확인하고, 버린 행은 :data:`FOOD_MAX_INVALID_RATIO` 안에서만 받아들인다.
    """
    items: list[Any] = []
    received = 0
    expected: int | None = None
    for page_no in range(1, max_pages + 1):
        page = await fetch(page_no)
        raw = getattr(page, "raw", None)
        raw_rows = raw.get("list") if isinstance(raw, dict) else None
        page_received = len(raw_rows) if isinstance(raw_rows, list) else len(page.items)
        if page.total_count is not None:
            if expected is None:
                expected = page.total_count
            elif page.total_count != expected:
                raise RuntimeError(f"{endpoint} changed total_count while paging")
        items.extend(page.items)
        received += page_received
        if expected is not None and received > expected:
            raise RuntimeError(f"{endpoint} returned more rows than total_count")
        if expected is not None and received >= expected:
            break
        if page_received == 0:
            if expected is None:
                break
            raise RuntimeError(f"{endpoint} pagination ended early: expected {expected}, received {received}")
        if expected is None and page_received < (page.num_of_rows or FOOD_MENU_PAGE_SIZE):
            break
    else:
        raise RuntimeError(f"{endpoint} exceeded the {max_pages}-page safety limit")
    invalid = received - len(items)
    if invalid > max(received, 1) * FOOD_MAX_INVALID_RATIO:
        raise InvalidRestAreaFoodRowsError(f"{endpoint}: {invalid}/{received} rows failed to parse")
    if invalid:
        logger.warning("rest_area_food_invalid_rows endpoint=%s invalid=%d received=%d", endpoint, invalid, received)
    return tuple(items), invalid


class RestAreaCollectionService:
    def __init__(self, settings: Settings, *, client_factory: Callable[..., KrexClient] = KrexClient) -> None:
        self.settings = settings
        self._client_factory = client_factory

    async def collect_references(self, session: AsyncSession, *, trigger: str = REST_AREA_TRIGGER) -> dict[str, Any]:
        if not self.settings.rest_area_collection_enabled:
            return {"status": "skipped", "reason": "rest area collection is disabled"}
        if not self.settings.data_go_kr_service_key:
            return {"status": "skipped", "reason": "DATA_GO_KR_SERVICE_KEY is required"}

        async def fetch(client: KrexClient) -> tuple[RestArea, ...]:
            return await _collect_krex_pages(
                lambda page_no: client.restarea.list_all(num_of_rows=1000, page_no=page_no),
                "python-krex-api:restarea.list_all",
            )

        return await self._run(session, trigger, REST_AREA_SOURCE, "python-krex-api:restarea.list_all",
                               fetch, self._store_references)

    async def collect_fuel_prices(self, session: AsyncSession, *, trigger: str = REST_AREA_FUEL_TRIGGER) -> dict[str, Any]:
        if not self.settings.rest_area_collection_enabled:
            return {"status": "skipped", "reason": "rest area collection is disabled"}
        if not self.settings.kex_ex_api_key:
            return {"status": "skipped", "reason": "KEX_EX_API_KEY is required"}

        async def fetch(client: KrexClient) -> tuple[KrexRestAreaFuelPrice, ...]:
            return await _collect_krex_pages(
                lambda page_no: client.restarea.fuel_prices(num_of_rows=1000, page_no=page_no),
                "python-krex-api:restarea.fuel_prices",
            )

        return await self._run(session, trigger, REST_AREA_FUEL_SOURCE, "python-krex-api:restarea.fuel_prices",
                               fetch, self._store_fuel_prices)

    async def collect_food(self, session: AsyncSession, *, trigger: str = REST_AREA_FOOD_TRIGGER) -> dict[str, Any]:
        """0615 휴게소 코드(1회 호출)와 0502 푸드메뉴(전 페이지)를 함께 받는다."""
        if not self.settings.rest_area_collection_enabled:
            return {"status": "skipped", "reason": "rest area collection is disabled"}
        if not self.settings.kex_ex_api_key:
            return {"status": "skipped", "reason": "KEX_EX_API_KEY is required"}

        async def fetch(client: KrexClient) -> tuple[Any, ...]:
            # 0615는 페이지 인자를 무시하고 전체를 한 번에 준다. `count`가 없는 응답은 완결을 알 수 없어 실패다(의도).
            codes, invalid_codes = await _collect_food_pages(
                lambda page_no: client.restarea.service_area_codes(),
                "python-krex-api:restarea.service_area_codes", max_pages=1,
            )
            menus, invalid_menus = await _collect_food_pages(
                lambda page_no: client.restarea.food_menus(num_of_rows=FOOD_MENU_PAGE_SIZE, page_no=page_no),
                "python-krex-api:restarea.food_menus", max_pages=FOOD_MENU_MAX_PAGES,
            )
            self._food_invalid_rows = invalid_codes + invalid_menus
            return (*codes, *menus)

        return await self._run(session, trigger, REST_AREA_FOOD_SOURCE,
                               "python-krex-api:restarea.service_area_codes+food_menus", fetch, self._store_food)

    async def _run(
        self,
        session: AsyncSession,
        trigger: str,
        source: str,
        endpoint: str,
        fetch: Callable[[KrexClient], Awaitable[tuple[Any, ...]]],
        store: Callable[[AsyncSession, tuple[Any, ...], Any], Awaitable[int]],
    ) -> dict[str, Any]:
        run = CollectionRun(started_at=now_utc(), status="running", trigger=trigger)
        session.add(run)
        state = await get_or_create_state(session, source)
        state.last_started_at = run.started_at
        state.updated_at = now_utc()
        await session.commit()
        run_id = run.id
        raw_committed = False
        try:
            client = self._client_factory(
                ex_api_key=self.settings.kex_ex_api_key,
                go_api_key=self.settings.data_go_kr_service_key,
                timeout=self.settings.api_timeout_seconds,
            )
            try:
                items = await fetch(client)
            finally:
                await client.aclose()
            collected_at = now_utc()
            stored = await store(session, items, collected_at)
            if stored == 0:
                raise EmptyRestAreaCollectionError(f"{source}: received {len(items)}, stored 0")
            summary = {"received": len(items), "stored": stored}
            session.add(RawApiResponse(
                collection_run_id=run_id, source=source, endpoint=endpoint, request_params_json=None,
                status_code=200, body_text=json.dumps(summary, sort_keys=True), received_at=collected_at,
                parse_status="success", parse_error=None,
            ))
            state = await get_or_create_state(session, source)
            state.last_success_at = collected_at
            state.last_error = None
            state.next_due_at = None
            state.updated_at = now_utc()
            # 원본 저장을 먼저 확정하고, 아직 running인 실행의 소유권 아래 통계를 게시한다.
            await session.commit()
            raw_committed = True
            if source == REST_AREA_FUEL_SOURCE:
                # 발행 실패는 원천 성공을 취소하지 않는다. 결과에만 남겨 op metadata로 보이게 한다.
                summary["fuel_statistics_published"] = await try_publish_fuel_statistics(session, source, collected_at)
                await session.commit()
                summary.update((await cleanup_fuel_statistics(session, source)).metadata())
            stored_run = await session.get(CollectionRun, run_id)
            stored_run.status = "success"
            stored_run.finished_at = now_utc()
            await session.commit()
            return {"status": "success", "run_id": run_id, **summary}
        except (Exception, asyncio.CancelledError) as exc:
            await session.rollback()
            # provider 예외 문자열에는 요청 URL·인증정보가 들어갈 수 있으므로 유형만 보존한다.
            message = type(exc).__name__
            stored_run = await session.get(CollectionRun, run_id)
            if stored_run is not None:
                stored_run.status = "partial_success" if raw_committed else "failed"
                stored_run.finished_at = now_utc()
                stored_run.error_message = message
            if not raw_committed:
                state = await get_or_create_state(session, source)
                state.last_error = message
                state.updated_at = now_utc()
            # 파생 통계/정리 취소가 이미 확정된 원천 성공을 실패로 바꿔 export를 막지 않는다.
            # 실행은 부분 성공으로 기록하고 원래 예외/취소는 Dagster로 전달한다.
            await session.commit()
            raise

    async def _store_references(self, session: AsyncSession, items: tuple[RestArea, ...], collected_at: Any) -> int:
        stored = 0
        seen: set[str] = set()
        for item in items:
            if not (item.name or "").strip():
                continue
            identity = rest_area_identity(item.name, item.route_name, item.direction)
            if identity in seen:
                continue
            seen.add(identity)
            values = {
                "name": item.name.strip(),
                "route_name": item.route_name,
                "direction": item.direction,
                "latitude": item.lat,
                "longitude": item.lon,
                "has_gas_station": item.has_gas_station,
                "has_lpg_station": item.has_lpg_station,
                "has_ev_charger": item.has_ev_charger,
                "phone_number": item.phone_number,
                "data_reference_date": item.reference_date.isoformat() if item.reference_date else None,
                "last_seen_at": collected_at,
                "raw_item_json": _plain_json(dict(item.raw)),
            }
            row = await session.scalar(select(RestAreaReference).where(
                RestAreaReference.source == REST_AREA_SOURCE, RestAreaReference.identity_key == identity,
            ))
            if row is None:
                session.add(RestAreaReference(
                    source=REST_AREA_SOURCE, identity_key=identity, first_seen_at=collected_at, **values,
                ))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            stored += 1
        await session.flush()
        return stored

    async def _store_fuel_prices(
        self, session: AsyncSession, items: tuple[KrexRestAreaFuelPrice, ...], collected_at: Any,
    ) -> int:
        stored = 0
        seen: set[str] = set()
        rejected = 0

        def price(code: str, product: str, value: Any) -> int | None:
            # 저장 경계 검사(공급자 파싱은 krex 몫, ADR-004): 정수가 아니거나 1억 이상(통계 NUMERIC(10,2) 밖)·-2^31 미만(INTEGER 밖)인 값만
            # 미제공(null)으로 둔다. 그런 값이 한 건이라도 오면 예전에는 수집 또는 통계 공개 transaction 전체가 실패했다. 0·음수는
            # 예전처럼 그대로 저장한다(공급자가 "판매 안 함"을 0으로 줄 수 있고 export 계약을 바꾸지 않는다; 통계는 0 이하를 뺀다).
            # 원문은 raw_item_json에 남는다.
            nonlocal rejected
            if value is None:
                return None
            if isinstance(value, bool) or not isinstance(value, int) or not -(2**31) <= value < STATISTICS_PRICE_LIMIT:
                rejected += 1
                if rejected == 1:
                    logger.warning("rest_area_fuel_price_out_of_range station_key=%s product=%s", code, product)
                return None
            return value
        for item in items:
            code = (item.service_area_code or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            values = {
                "service_area_code2": item.service_area_code2,
                "service_area_name": item.service_area_name,
                "route_code": item.route_code,
                "route_name": item.route_name,
                "direction": item.direction,
                "oil_company": item.oil_company,
                "has_lpg": item.has_lpg,
                "phone_number": item.phone_number,
                "address": item.address,
                "gasoline_price": price(code, "B027", item.gasoline_price),
                "diesel_price": price(code, "D047", item.diesel_price),
                "lpg_price": price(code, "K015", item.lpg_price),
                "last_seen_at": collected_at,
                "raw_item_json": _plain_json(dict(item.raw)),
            }
            row = await session.scalar(select(RestAreaFuelPrice).where(
                RestAreaFuelPrice.source == REST_AREA_FUEL_SOURCE, RestAreaFuelPrice.service_area_code == code,
            ))
            if row is None:
                session.add(RestAreaFuelPrice(
                    source=REST_AREA_FUEL_SOURCE, service_area_code=code, first_seen_at=collected_at, **values,
                ))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            stored += 1
        if rejected:
            logger.warning("rest_area_fuel_prices_out_of_range count=%d limit=%d", rejected, STATISTICS_PRICE_LIMIT)
        await session.flush()
        return stored

    async def _store_food(self, session: AsyncSession, items: tuple[Any, ...], collected_at: Any) -> int:
        """코드와 메뉴를 upsert한다. 어느 한쪽이 0건이면 0을 돌려 수집을 실패로 남긴다(전국 집합)."""
        codes = [item for item in items if isinstance(item, KrexRestAreaCode)]
        menus = [item for item in items if isinstance(item, KrexRestAreaFoodMenu)]
        if not codes or not menus:
            return 0
        await self._refuse_shrunk_food_set(session, len({item.std_rest_code for item in codes}),
                                           len({(item.std_rest_code, item.seq) for item in menus}))
        code_values: dict[str, dict[str, Any]] = {}
        for item in codes:
            code = item.std_rest_code.strip()
            if not code or code in code_values:
                continue
            code_values[code] = {
                "name": item.name.strip()[:160],
                "facility_class": _FACILITY_CLASSES.get(getattr(item.facility_class, "value", "")),
                "direction": _DIRECTIONS.get(getattr(item.direction, "value", "")),
                "route_code": item.route_code,
                "route_name": item.route_name,
                "service_area_code": item.service_area_code,
                "address": item.address,
                "phone_number": item.phone_number,
                "last_seen_at": collected_at,
                "raw_item_json": _plain_json(dict(item.raw)),
            }
        menu_values: dict[tuple[str, str], dict[str, Any]] = {}
        for item in menus:
            key = (item.std_rest_code.strip(), item.seq.strip())
            if not key[0] or not key[1] or key in menu_values:
                continue
            menu_values[key] = {
                "food_name": item.food_name.strip()[:200],
                "price": item.price if item.price is not None and 0 <= item.price < 2**31 else None,
                "is_best": item.is_best,
                "is_premium": item.is_premium,
                "is_recommended": item.is_recommended,
                "season": _SEASONS.get(getattr(item.season, "value", "")),
                "app_listed": item.app_listed,
                "menu_updated_on": item.menu_updated_on,
                "last_seen_at": collected_at,
                "raw_item_json": _plain_json(dict(item.raw)),
            }
            # 0615에는 노선명이 비어 오는 행이 있다. 같은 휴게소 메뉴의 노선명으로 채우고, 0615에 없는 휴게소
            # 코드(2026-11-27 함양 2곳)는 메뉴 행에서 코드 행을 만든다(분류·방향은 모른다).
            values = code_values.get(key[0])
            if values is None:
                code_values[key[0]] = {
                    "name": (item.rest_area_name or key[0]).strip()[:160], "facility_class": None, "direction": None,
                    "route_code": item.route_code, "route_name": item.route_name, "service_area_code": None,
                    "address": item.address, "phone_number": None, "last_seen_at": collected_at, "raw_item_json": None,
                }
            elif values["route_name"] is None and item.route_name and (
                    values["route_code"] is None or values["route_code"] == item.route_code):
                values["route_name"] = item.route_name
        existing_codes = {row.std_rest_code: row for row in (await session.scalars(
            select(RestAreaCode).where(RestAreaCode.source == REST_AREA_FOOD_SOURCE))).all()}
        for code, values in code_values.items():
            row = existing_codes.get(code)
            if row is None:
                session.add(RestAreaCode(source=REST_AREA_FOOD_SOURCE, std_rest_code=code,
                                         first_seen_at=collected_at, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        existing_menus = {(row.std_rest_code, row.seq): row for row in (await session.scalars(
            select(RestAreaFoodMenu).where(RestAreaFoodMenu.source == REST_AREA_FOOD_SOURCE))).all()}
        for (code, seq), values in menu_values.items():
            row = existing_menus.get((code, seq))
            if row is None:
                session.add(RestAreaFoodMenu(source=REST_AREA_FOOD_SOURCE, std_rest_code=code, seq=seq,
                                             first_seen_at=collected_at, **values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        await session.flush()
        logger.info("rest_area_food_stored codes=%d menus=%d invalid_rows=%d", len(code_values), len(menu_values),
                    getattr(self, "_food_invalid_rows", 0))
        return len(code_values) + len(menu_values)

    async def _refuse_shrunk_food_set(self, session: AsyncSession, codes: int, menus: int) -> None:
        """직전 성공 집합(마지막 성공이 본 행)보다 크게 줄면 실패한다 — export가 축소 집합을 200으로 내지 않게."""
        state = await get_or_create_state(session, REST_AREA_FOOD_SOURCE)
        if state.last_success_at is None:
            return
        seen_from = state.last_success_at
        if now_utc() - serialize_utc(seen_from) > FOOD_KEEP_RATIO_MAX_AGE:
            logger.warning("rest_area_food_shrink_guard_released last_success_at=%s", seen_from)
            return
        previous = {
            "codes": await session.scalar(select(func.count()).select_from(RestAreaCode).where(
                RestAreaCode.source == REST_AREA_FOOD_SOURCE, RestAreaCode.last_seen_at >= seen_from)) or 0,
            "menus": await session.scalar(select(func.count()).select_from(RestAreaFoodMenu).where(
                RestAreaFoodMenu.source == REST_AREA_FOOD_SOURCE, RestAreaFoodMenu.last_seen_at >= seen_from)) or 0,
        }
        current = {"codes": codes, "menus": menus}
        for kind, ratio in FOOD_MIN_KEEP_RATIO.items():
            if previous[kind] >= FOOD_KEEP_RATIO_BASELINE and current[kind] < previous[kind] * ratio:
                raise ShrunkRestAreaFoodCollectionError(
                    f"{REST_AREA_FOOD_SOURCE}: {kind} {current[kind]} < {ratio:.0%} of previous {previous[kind]}")
