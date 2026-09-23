"""한국도로공사 휴게소 기준정보의 저빈도 async 수집."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, timedelta
from typing import Any

from krex import KrexClient, RestArea
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.models import CollectionRun, RawApiResponse, RestAreaReference


REST_AREA_SOURCE = "data_go_kr_rest_area"
REST_AREA_PAGE_SIZE = 1000
REST_AREA_MAX_PAGES = 10
REST_AREA_REFRESH_INTERVAL = timedelta(days=3)


class RestAreaCollectionService:
    """휴게소 위치·기본 편의정보를 최대 3일에 한 번만 저장한다."""

    def __init__(
        self,
        settings: Settings,
        *,
        fetcher: Callable[[], Awaitable[tuple[RestArea, ...]]] | None = None,
        client_factory: Callable[..., KrexClient] = KrexClient,
    ) -> None:
        self.settings = settings
        self._fetcher = fetcher
        self._client_factory = client_factory

    async def collect_reference(
        self, session: AsyncSession, *, trigger: str = "dagster_rest_area"
    ) -> dict[str, Any]:
        if not self.settings.rest_area_reference_collection_enabled:
            return {"status": "skipped", "reason": "rest area reference collection is disabled"}
        if not self.settings.data_go_kr_service_key:
            return {"status": "skipped", "reason": "DATA_GO_KR_SERVICE_KEY is required"}

        latest_success = await session.scalar(
            select(CollectionRun.finished_at)
            .where(
                CollectionRun.trigger.startswith("dagster_rest_area", autoescape=True),
                CollectionRun.status == "success",
                CollectionRun.finished_at.is_not(None),
            )
            .order_by(CollectionRun.finished_at.desc(), CollectionRun.id.desc())
            .limit(1)
        )
        if latest_success is not None:
            if latest_success.tzinfo is None:
                latest_success = latest_success.replace(tzinfo=UTC)
            if now_utc() - latest_success < REST_AREA_REFRESH_INTERVAL:
                return {"status": "skipped", "reason": "rest area reference is not due for 72 hours"}

        run = CollectionRun(
            started_at=now_utc(), finished_at=None, status="running", trigger=trigger, error_message=None
        )
        session.add(run)
        await session.commit()
        try:
            items = await self._fetch_rest_areas()
            collected_at = now_utc()
            for item in items:
                await self._upsert(session, item, collected_at)
            session.add(
                RawApiResponse(
                    collection_run_id=run.id,
                    source=REST_AREA_SOURCE,
                    endpoint="python-krex-api:restarea.list_all",
                    request_params_json={"page_size": REST_AREA_PAGE_SIZE},
                    status_code=200,
                    body_text=json.dumps({"count": len(items)}, ensure_ascii=False),
                    received_at=collected_at,
                    parse_status="success",
                    parse_error=None,
                )
            )
            run.status = "success"
            run.finished_at = now_utc()
            await session.commit()
            return {"status": "success", "run_id": run.id, "rest_area_count": len(items)}
        except BaseException as exc:
            await session.rollback()
            failed_run = await session.get(CollectionRun, run.id)
            if failed_run is not None:
                failed_run.status = "failed"
                failed_run.finished_at = now_utc()
                failed_run.error_message = f"{type(exc).__name__}: {str(exc)[:500]}"
                await session.commit()
            raise

    async def _fetch_rest_areas(self) -> tuple[RestArea, ...]:
        if self._fetcher is not None:
            return await self._fetcher()
        key = self.settings.data_go_kr_service_key
        assert key is not None
        async with self._client_factory(
            go_api_key=key, timeout=self.settings.api_timeout_seconds
        ) as client:
            first = await client.restarea.list_all(num_of_rows=REST_AREA_PAGE_SIZE, page_no=1)
            items = list(first.items)
            total = first.total_count or len(items)
            pages = min(
                REST_AREA_MAX_PAGES,
                max(1, (total + REST_AREA_PAGE_SIZE - 1) // REST_AREA_PAGE_SIZE),
            )
            for page_no in range(2, pages + 1):
                page = await client.restarea.list_all(num_of_rows=REST_AREA_PAGE_SIZE, page_no=page_no)
                items.extend(page.items)
            if total > len(items):
                raise RuntimeError("휴게소 기준정보 페이지 상한을 넘어 전체 목록을 읽지 못했습니다")
            return tuple(items)

    async def _upsert(self, session: AsyncSession, item: RestArea, collected_at: Any) -> None:
        identity_key = "|".join(value.strip() for value in (item.name, item.route_name or "", item.direction or ""))
        row = await session.scalar(
            select(RestAreaReference).where(
                RestAreaReference.source == REST_AREA_SOURCE,
                RestAreaReference.identity_key == identity_key,
            )
        )
        values = {
            "name": item.name,
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
            "raw_item_json": dict(item.raw),
        }
        if row is None:
            session.add(
                RestAreaReference(
                    source=REST_AREA_SOURCE,
                    identity_key=identity_key,
                    first_seen_at=collected_at,
                    **values,
                )
            )
        else:
            for name, value in values.items():
                setattr(row, name, value)
