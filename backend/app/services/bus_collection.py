"""TAGO 고속·시외버스의 저변동 터미널 기준정보 수집."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, timedelta
from typing import Any

from datagokr import DataGoKrClient, TagoBusTerminal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.models import BusTerminalReference, CollectionRun, RawApiResponse

TAGO_BUS_SOURCE = "data_go_kr_tago"


class BusReferenceCollectionService:
    """시간표를 저장하지 않고 TAGO 터미널 기준정보만 3일 주기로 적재한다."""

    def __init__(
        self,
        settings: Settings,
        *,
        client_factory: Callable[..., DataGoKrClient] = DataGoKrClient,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory

    async def collect(
        self, session: AsyncSession, *, trigger: str = "dagster_bus_reference"
    ) -> dict[str, Any]:
        if not self.settings.bus_reference_collection_enabled:
            return {"status": "skipped", "reason": "bus reference collection is disabled"}
        if not self.settings.data_go_kr_service_key:
            return {"status": "skipped", "reason": "DATA_GO_KR_SERVICE_KEY is required"}
        latest_success = await session.scalar(
            select(CollectionRun.finished_at)
            .where(
                CollectionRun.trigger == trigger,
                CollectionRun.status == "success",
                CollectionRun.finished_at.is_not(None),
            )
            .order_by(CollectionRun.finished_at.desc())
            .limit(1)
        )
        if latest_success is not None:
            if latest_success.tzinfo is None:
                latest_success = latest_success.replace(tzinfo=UTC)
            if now_utc() - latest_success < timedelta(days=3):
                return {"status": "skipped", "reason": "TAGO bus reference is not due for 72 hours"}

        run = CollectionRun(started_at=now_utc(), status="running", trigger=trigger)
        session.add(run)
        await session.commit()
        try:
            summary = await self._collect_references(session)
            session.add(
                RawApiResponse(
                    collection_run_id=run.id,
                    source=TAGO_BUS_SOURCE,
                    endpoint="data.go.kr:TAGO-bus-reference",
                    request_params_json=None,
                    status_code=200,
                    body_text=json.dumps(summary, ensure_ascii=False, sort_keys=True),
                    received_at=now_utc(),
                    parse_status="success",
                    parse_error=None,
                )
            )
            run.status = "success"
            run.finished_at = now_utc()
            await session.commit()
            return {"status": "success", "run_id": run.id, **summary}
        except asyncio.CancelledError as exc:
            await self._fail(session, run, exc)
            raise
        except Exception as exc:
            await self._fail(session, run, exc)
            raise

    async def _collect_references(self, session: AsyncSession) -> dict[str, int]:
        key = self.settings.data_go_kr_service_key
        assert key is not None
        collected_at = now_utc()
        counts: dict[str, int] = {}
        async with self._client_factory(api_key=key, timeout=self.settings.api_timeout_seconds) as client:
            for service_type, provider in (
                ("express", client.express_bus),
                ("intercity", client.intercity_bus),
            ):
                terminals = tuple(
                    [item async for item in provider.iter_terminals(num_of_rows=100, max_pages=100)]
                )
                # 도시·등급은 시간표 입력 보조 기준정보다. 개별 row 테이블은 필요하지 않아
                # 수집 receipt에만 수량을 남긴다. provider가 paging 없이 한 번에 제공한다.
                cities = await provider.city_list()
                classes = await provider.class_list()
                for item in terminals:
                    if item.terminal_id:
                        await self._upsert_terminal(session, service_type, item, collected_at)
                counts[f"{service_type}_terminal_count"] = len(terminals)
                counts[f"{service_type}_city_count"] = len(cities.items)
                counts[f"{service_type}_class_count"] = len(classes.items)
        return counts

    async def _upsert_terminal(
        self,
        session: AsyncSession,
        service_type: str,
        item: TagoBusTerminal,
        collected_at: Any,
    ) -> None:
        assert item.terminal_id is not None
        row = await session.scalar(
            select(BusTerminalReference).where(
                BusTerminalReference.source == TAGO_BUS_SOURCE,
                BusTerminalReference.service_type == service_type,
                BusTerminalReference.terminal_id == item.terminal_id,
            )
        )
        values = {
            "terminal_name": item.terminal_name,
            "city_name": item.city_name,
            "last_seen_at": collected_at,
            "raw_item_json": dict(item.raw),
        }
        if row is None:
            session.add(
                BusTerminalReference(
                    source=TAGO_BUS_SOURCE,
                    service_type=service_type,
                    terminal_id=item.terminal_id,
                    first_seen_at=collected_at,
                    **values,
                )
            )
        else:
            for name, value in values.items():
                setattr(row, name, value)

    async def _fail(self, session: AsyncSession, run: CollectionRun, exc: BaseException) -> None:
        await session.rollback()
        stored_run = await session.get(CollectionRun, run.id)
        if stored_run is not None:
            stored_run.status = "failed"
            stored_run.finished_at = now_utc()
            # provider 예외 문자열에는 요청 URL·인증정보가 들어갈 수 있으므로 유형만 보존한다.
            stored_run.error_message = type(exc).__name__
            await session.commit()
