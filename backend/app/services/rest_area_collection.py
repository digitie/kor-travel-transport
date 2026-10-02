"""고속도로 휴게소 기준정보와 휴게소 주유소 현재 유가 수집 (ADR-013).

- 기준정보: data.go.kr 표준데이터 `tn_pubr_public_rest_area_api`(`krex.restarea.list_all`,
  data.go.kr 키). 원천에 안정 식별자가 없어 `name::route_name::direction`(strip→lower)을
  자연키로 쓴다 — kor-travel-map이 같은 원천에서 쓰던 키와 같아야 이관 뒤 Feature가 이어진다.
- 유가: 한국도로공사 EX `curStateStation`(`krex.restarea.fuel_prices`, EX 키). 휴게소 코드
  (`service_area_code`)별 현재값 1행만 유지한다. 원천에 관측 시각이 없어 수집 시각을 쓴다.

두 수집 모두 성공한 수집 시각을 `transport_collection_states.last_success_at`과 각 행의
`last_seen_at`에 같은 값으로 남긴다. service export는 이 값으로 "마지막 수집이 본 집합"을 고른다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from krex import KrexClient, RestArea, RestAreaFuelPrice as KrexRestAreaFuelPrice
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.models import CollectionRun, RawApiResponse, RestAreaFuelPrice, RestAreaReference
from app.services.transport_collection import _collect_krex_pages, _plain_json, get_or_create_state

REST_AREA_SOURCE = "krex_rest_area"
REST_AREA_FUEL_SOURCE = "krex_rest_area_fuel"
REST_AREA_TRIGGER = "dagster_rest_area_reference"
REST_AREA_FUEL_TRIGGER = "dagster_rest_area_fuel"


def rest_area_identity(name: str | None, route_name: str | None, direction: str | None) -> str:
    """휴게소 자연키. kor-travel-map `_rest_area_natural_key`와 같은 규칙이다."""
    return "::".join((value or "").strip().lower() for value in (name, route_name, direction))


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
                stored_run.status = "failed"
                stored_run.finished_at = now_utc()
                stored_run.error_message = message
            state = await get_or_create_state(session, source)
            state.last_error = message
            state.updated_at = now_utc()
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
                "gasoline_price": item.gasoline_price,
                "diesel_price": item.diesel_price,
                "lpg_price": item.lpg_price,
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
        await session.flush()
        return stored
