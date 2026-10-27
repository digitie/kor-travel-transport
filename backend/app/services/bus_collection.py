"""TAGO 고속·시외버스의 저변동 터미널 기준정보 수집."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, timedelta
from typing import Any

from datagokr import DataGoKrClient, TagoBusTerminal
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.models import BusTerminalReference, CollectionRun, RawApiResponse, ReferenceExportState
from app.services.reference_exports import MAX_REFERENCE_MEMBERS, mark_reference_failure, promote_reference

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
        async with self._postgres_collection_lease(session) as acquired:
            if not acquired:
                return {"status": "skipped", "reason": "another TAGO bus reference collection is active"}
            return await self._collect_unlocked(session, trigger=trigger)

    @asynccontextmanager
    async def _postgres_collection_lease(self, session: AsyncSession) -> AsyncIterator[bool]:
        """Dagster process가 겹쳐도 TAGO 기준정보 호출은 한 번만 수행한다.

        PostgreSQL session advisory lock은 수집 transaction과 별도 connection으로 소유한다.
        따라서 수집 중 ``session.commit()``해도 lock이 반납되지 않으며, SQLite 단위 테스트는
        provider 호출 없이 기존 단일 process 동작을 유지한다.
        """
        engine = session.bind
        if engine is None or engine.dialect.name != "postgresql":
            yield True
            return

        async with engine.connect() as lock_connection:
            acquired = bool(
                await lock_connection.scalar(
                    text("SELECT pg_try_advisory_lock(hashtext('kor_travel_transport:tagobus_reference'))")
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    released = bool(
                        await lock_connection.scalar(
                            text("SELECT pg_advisory_unlock(hashtext('kor_travel_transport:tagobus_reference'))")
                        )
                    )
                    if not released:
                        raise RuntimeError("TAGO bus reference advisory lock was not released by its owner connection")

    async def _collect_unlocked(
        self, session: AsyncSession, *, trigger: str
    ) -> dict[str, Any]:
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
            # Map 플래그를 켰는데 express·intercity head 중 하나라도 없으면 최근 성공(플래그 OFF 수집)이 있어도
            # due다 — bus-terminals export가 최대 3일 동안 503으로 남지 않게 첫 head를 바로 만든다.
            bootstrap = False
            if self.settings.transport_map_current_enabled:
                heads = set((await session.scalars(select(ReferenceExportState.scope_key).where(
                    ReferenceExportState.kind == "bus-terminal"))).all())
                bootstrap = bool({"express", "intercity"} - heads)
            if not bootstrap and now_utc() - latest_success < timedelta(days=3):
                return {"status": "skipped", "reason": "TAGO bus reference is not due for 72 hours"}

        run = CollectionRun(started_at=now_utc(), status="running", trigger=trigger)
        session.add(run)
        await session.commit()
        run_id = run.id
        try:
            summary = await self._collect_references(session, run_id=run_id)
            session.add(
                RawApiResponse(
                    collection_run_id=run_id,
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
            stored_run = await session.get(CollectionRun, run_id)
            stored_run.status = "success"
            stored_run.finished_at = now_utc()
            await session.commit()
            return {"status": "success", "run_id": run_id, **summary}
        except asyncio.CancelledError as exc:
            await self._fail(session, run_id, exc)
            raise
        except Exception as exc:
            await self._fail(session, run_id, exc)
            raise

    async def _fetch_terminals(self, provider):
        """provider public page API의 typed 결과·완결 수량을 확인한다."""
        if not self.settings.transport_map_current_enabled:
            items = tuple([item async for item in provider.iter_terminals(num_of_rows=100, max_pages=100)])
            return items, {"complete": False, "item_count": len(items)}
        items = []
        total = None
        pages = 0
        async for page in provider.terminals.iter_pages(num_of_rows=100, max_pages=100):
            pages += 1
            if (type(page.total_count) is not int or not 0 <= page.total_count <= MAX_REFERENCE_MEMBERS
                    or page.page_no != pages or page.num_of_rows != 100):
                raise ValueError("TAGO terminal page의 완결 metadata가 없습니다")
            if total is None:
                total = page.total_count
            if page.total_count != total or len(page.items) != min(100, max(0, total - len(items))):
                raise ValueError("TAGO terminal page 수량이 변했습니다")
            items.extend(page.items)
        if total is None or len(items) != total:
            raise ValueError("TAGO terminal 전체 page가 완료되지 않았습니다")
        return tuple(items), {"complete": True, "item_count": len(items), "pages": pages, "page_size": 100}

    @staticmethod
    def _terminal_identity(items):
        keys = [(item.terminal_id, item.terminal_name, item.city_name) for item in items]
        if (not keys or len(keys) > MAX_REFERENCE_MEMBERS
                or any(not key[0] or not key[1] for key in keys)
                or len({key[0] for key in keys}) != len(keys)):
            raise ValueError("빈 목록·누락 이름/코드·중복 터미널은 승인할 수 없습니다")
        return sorted(keys, key=lambda key: key[0])

    async def _confirmed_terminals(self, provider):
        for attempt in range(2):
            try:
                terminals, proof = await self._fetch_terminals(provider)
                if not self.settings.transport_map_current_enabled:
                    # 엄격 identity는 Map membership용이다. 플래그 OFF는 이전처럼 id 없는 항목만 저장에서 건너뛰고
                    # 이름 없는 행·중복 id(마지막 값이 이긴다)를 허용한다.
                    return terminals, proof, None
                return terminals, proof, self._terminal_identity(terminals)
            except ValueError:
                if attempt:
                    raise
        raise AssertionError("unreachable")

    async def _collect_references(self, session: AsyncSession, *, run_id: int) -> dict[str, int]:
        key = self.settings.data_go_kr_service_key
        assert key is not None
        counts: dict[str, int] = {}
        previous_counts = dict((await session.execute(select(
            BusTerminalReference.service_type, func.count(),
        ).where(BusTerminalReference.source == TAGO_BUS_SOURCE).group_by(BusTerminalReference.service_type))).all())
        for state in (await session.scalars(select(ReferenceExportState).where(
            ReferenceExportState.kind == "bus-terminal",
        ))).all():
            previous_counts[state.scope_key] = len(state.member_ids)
        # 직전 native run 생성은 이미 commit됐다. 네트워크 대기 중 read pool/transaction을 반환한다.
        await session.rollback()
        fetched = []
        async with self._client_factory(api_key=key, timeout=self.settings.api_timeout_seconds) as client:
            for service_type, provider in (("express", client.express_bus), ("intercity", client.intercity_bus)):
                terminals, proof, identity = await self._confirmed_terminals(provider)
                previous_count = previous_counts.get(service_type, 0)
                if previous_count and len(terminals) < previous_count * 0.25:
                    again, confirmation, confirmed_identity = await self._confirmed_terminals(provider)
                    if (not proof.get("complete") or not confirmation.get("complete") or confirmed_identity != identity):
                        raise ValueError("TAGO terminal 급감 집합의 완결 재확인이 필요합니다")
                cities = await provider.city_list()
                classes = await provider.class_list()
                fetched.append((service_type, terminals, proof, len(cities.items), len(classes.items)))
        # 두 종류의 완결/부차 fetch를 마친 뒤에만 원자적 저장 transaction을 연다.
        collected_at = now_utc()
        for service_type, terminals, proof, cities, classes in fetched:
            for item in terminals:
                if item.terminal_id:  # 플래그 ON은 identity 검사가 이미 모든 id를 보장한다.
                    await self._upsert_terminal(session, service_type, item, collected_at)
            await session.flush()
            if self.settings.transport_map_current_enabled:
                ids = list((await session.scalars(select(BusTerminalReference.id).where(
                    BusTerminalReference.source == TAGO_BUS_SOURCE,
                    BusTerminalReference.service_type == service_type,
                    BusTerminalReference.terminal_id.in_([item.terminal_id for item in terminals]),
                ))).all())
                if len(ids) != len(terminals):
                    raise ValueError("저장 terminal membership이 일치하지 않습니다")
                await promote_reference(session, kind="bus-terminal", scope=service_type, run_id=run_id,
                                        confirmed_at=collected_at, member_ids=ids, proof=proof)
            counts[f"{service_type}_terminal_count"] = len(terminals)
            counts[f"{service_type}_city_count"] = cities
            counts[f"{service_type}_class_count"] = classes
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
            ).with_for_update()
        )
        values = {
            "terminal_name": item.terminal_name,
            "city_name": item.city_name,
            "last_seen_at": collected_at,
            "raw_item_json": dict(item.raw),
        }
        if row is not None:
            if (row.location_source == "admin_manual" and
                    row.terminal_name == item.terminal_name and row.city_name == item.city_name):
                values["raw_item_json"]["_manual_location"] = (row.raw_item_json or {}).get("_manual_location")
            elif row.terminal_name != item.terminal_name or row.city_name != item.city_name:
                values.update(latitude=None, longitude=None, location_source=None)
            elif row.raw_item_json:
                for provenance in ("_vworld_place", "_kakao_place"):
                    if provenance in row.raw_item_json:
                        values["raw_item_json"][provenance] = row.raw_item_json[provenance]
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

    async def _fail(self, session: AsyncSession, run_id: int, exc: BaseException) -> None:
        await session.rollback()
        stored_run = await session.get(CollectionRun, run_id)
        await mark_reference_failure(session, kind="bus-terminal", run_id=run_id, error=type(exc).__name__)
        if stored_run is not None:
            stored_run.status = "failed"
            stored_run.finished_at = now_utc()
            # provider 예외 문자열에는 요청 URL·인증정보가 들어갈 수 있으므로 유형만 보존한다.
            stored_run.error_message = type(exc).__name__
            await session.commit()
