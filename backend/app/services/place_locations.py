"""공식 장소 검색에서 검증된 항구·버스 터미널 위치만 저속으로 보강한다."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from vworld import VworldClient, VworldNetworkError, VworldNoDataError, parse_search_response, process_search_response

from app.services.place_targets import iter_missing_place_targets, matching_place_names
from app.core.config import Settings
from app.core.time_utils import now_utc
from app.models import BusTerminalReference, CollectionRun, FerryPort, RawApiResponse

LOCATION_SOURCE = "vworld_place"
TRIGGER = "dagster_place_locations"


def _province(value: str) -> str:
    for prefix, canonical in (
        ("강원", "강원"), ("경기", "경기"), ("경상남", "경남"), ("경상북", "경북"),
        ("전라남", "전남"), ("전남광주", "전남"), ("전라북", "전북"),
        ("충청남", "충남"), ("충청북", "충북"), ("제주", "제주"),
        ("서울", "서울"), ("부산", "부산"), ("대구", "대구"), ("인천", "인천"),
        ("광주", "광주"), ("대전", "대전"), ("울산", "울산"), ("세종", "세종"),
    ):
        if value.startswith(prefix):
            return canonical
    return ""


def _candidate(item: Mapping[str, Any]) -> dict[str, Any] | None:
    point = item.get("point")
    address = item.get("address")
    if not isinstance(point, Mapping):
        return None
    try:
        lon, lat = float(point.get("x")), float(point.get("y"))
    except (TypeError, ValueError):
        return None
    if not (124 <= lon <= 132 and 32 <= lat <= 39.5):
        return None
    return {
        "title": str(item.get("title") or "").strip(),
        "category": str(item.get("category") or ""),
        "address": str((address.get("parcel") or address.get("road") or "") if isinstance(address, Mapping) else ""),
        "longitude": lon,
        "latitude": lat,
    }


def choose_bus_location(
    items: list[Mapping[str, Any]], *, name: str, service_type: str, city_name: str | None,
) -> dict[str, Any] | None:
    """이름·시설 분류·시도가 일치하는 단일 승차 터미널만 채택한다."""
    if not name or "_" in name:
        return None
    expected = {name, *(name + suffix for suffix in ("고속버스터미널", "시외버스터미널", "종합버스터미널", "버스터미널", "터미널"))}
    target_subtype = "고속버스터미널" if service_type == "express" else "시외버스터미널"
    matches: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        candidate = _candidate(item)
        if candidate is None or candidate["title"] not in expected:
            continue
        category = candidate["category"]
        if "버스터미널/정류장" not in category or "버스정류장" in category:
            continue
        if target_subtype not in category and "종합버스터미널" not in category and not category.endswith("버스터미널/정류장"):
            continue
        if _province(city_name or "") and _province(city_name or "") != _province(candidate["address"]):
            continue
        priority = 2 if target_subtype in category else 1
        matches.append((priority, candidate))
    if not matches:
        return None
    highest = max(priority for priority, _ in matches)
    precise = {(candidate["longitude"], candidate["latitude"]): candidate
               for priority, candidate in matches if priority == highest}
    return next(iter(precise.values())) if len(precise) == 1 else None


def choose_port_location(items: list[Mapping[str, Any]], *, name: str) -> dict[str, Any] | None:
    """섬 중심점·항로 안내 점을 제외하고 이름이 정확한 단일 여객항 시설만 채택한다."""
    if not name or "_" in name:
        return None
    expected = name if name.endswith("항") else name + "항"
    matches = []
    for item in items:
        candidate = _candidate(item)
        if candidate and candidate["title"] == expected and "항만시설 > 페리/해운" in candidate["category"]:
            matches.append(candidate)
    distinct = {(candidate["longitude"], candidate["latitude"]): candidate for candidate in matches}
    return next(iter(distinct.values())) if len(distinct) == 1 else None


class PlaceLocationCollectionService:
    """한 키의 외부 검색 총량을 24시간 단위로 제한하며 미확인 장소를 순차 보강한다."""

    def __init__(self, settings: Settings, *, client_factory: Callable[..., VworldClient] = VworldClient) -> None:
        self.settings = settings
        self.client_factory = client_factory

    async def collect(self, session: AsyncSession) -> dict[str, Any]:
        if not self.settings.place_location_collection_enabled or not self.settings.vworld_api_key:
            return {"status": "skipped", "reason": "place location collection or VWorld key is disabled"}
        async with self._postgres_collection_lease(session) as acquired:
            if not acquired:
                return {"status": "skipped", "reason": "another VWorld place collection is active"}
            return await self._collect_unlocked(session)

    @asynccontextmanager
    async def _postgres_collection_lease(self, session: AsyncSession) -> AsyncIterator[bool]:
        engine = session.bind
        if engine is None or engine.dialect.name != "postgresql":
            yield True
            return
        async with engine.connect() as connection:
            acquired = bool(await connection.scalar(text(
                "SELECT pg_try_advisory_lock(hashtext('kor_travel_transport:vworld_place_collection'))"
            )))
            # Session-level lock은 transaction commit 뒤에도 유지된다. 긴 검색 동안 idle transaction을 남기지 않는다.
            await connection.commit()
            try:
                yield acquired
            finally:
                if acquired:
                    released = bool(await connection.scalar(text(
                        "SELECT pg_advisory_unlock(hashtext('kor_travel_transport:vworld_place_collection'))"
                    )))
                    await connection.commit()
                    if not released:
                        raise RuntimeError("VWorld place collection advisory lock was not released")

    async def _collect_unlocked(self, session: AsyncSession) -> dict[str, Any]:
        run = CollectionRun(started_at=now_utc(), status="running", trigger=TRIGGER)
        session.add(run)
        await session.commit()
        summary = {"provider_calls": 0, "bus_locations": 0, "port_locations": 0, "unmatched": 0,
                   "deferred": 0, "provider_failed": 0}
        try:
            async with self.client_factory(
                api_key=self.settings.vworld_api_key, timeout=self.settings.api_timeout_seconds,
                max_retries=0, max_rps=100.0,
            ) as client:
                async for kind, row in iter_missing_place_targets(session):
                    await session.refresh(row)
                    if row.latitude is not None or row.location_source == "admin_manual":
                        continue
                    if kind == "bus":
                        if await matching_place_names(session, kind, row) != 1:
                            continue
                        name = row.terminal_name.strip()
                        suffix = "고속버스터미널" if row.service_type == "express" else "시외버스터미널"
                        query = name if "터미널" in name else name + suffix
                        endpoint = f"vworld:bus:{row.service_type}:{row.terminal_id}"
                    else:
                        if await matching_place_names(session, kind, row) != 1:
                            continue
                        name = row.port_name.strip()
                        query = name if name.endswith("항") else name + "항"
                        endpoint = f"vworld:port:{row.port_id}"
                    if not name or "_" in name:
                        continue
                    previous = await session.scalar(select(RawApiResponse).where(
                        RawApiResponse.source == LOCATION_SOURCE, RawApiResponse.endpoint == endpoint,
                    ).order_by(RawApiResponse.received_at.desc(), RawApiResponse.id.desc()).limit(1))
                    now = now_utc()
                    if previous is not None:
                        received = previous.received_at.replace(tzinfo=UTC) if previous.received_at.tzinfo is None else previous.received_at
                        if ((previous.request_params_json or {}).get("query") == query
                                and (previous.request_params_json or {}).get("name") == name
                                and (previous.request_params_json or {}).get("city_name") == (
                                    row.city_name if kind == "bus" else None)
                                and now - received < timedelta(
                            days=30 if previous.parse_status == "success" else 1
                        )):
                            continue
                    if session.bind is not None and session.bind.dialect.name == "postgresql":
                        await session.execute(text("SELECT pg_advisory_xact_lock(420053)"))
                    # 다른 Dagster 실행이 먼저 예약했을 수 있으므로 lock 아래서 다시 확인한다.
                    latest_id = await session.scalar(select(RawApiResponse.id).where(
                        RawApiResponse.source == LOCATION_SOURCE, RawApiResponse.endpoint == endpoint,
                        RawApiResponse.received_at >= now - timedelta(days=1),
                    ).order_by(RawApiResponse.received_at.desc(), RawApiResponse.id.desc()).limit(1))
                    if latest_id is not None and (previous is None or latest_id != previous.id):
                        await session.commit()
                        continue
                    calls = int(await session.scalar(select(func.count()).select_from(RawApiResponse).where(
                        RawApiResponse.source == LOCATION_SOURCE,
                        RawApiResponse.received_at >= now - timedelta(days=1),
                    )) or 0)
                    if calls >= self.settings.place_location_max_calls_per_day:
                        summary["deferred"] += 1
                        await session.commit()
                        break
                    receipt = RawApiResponse(collection_run_id=run.id, source=LOCATION_SOURCE,
                        endpoint=endpoint, request_params_json={"query": query, "name": name,
                            "city_name": row.city_name if kind == "bus" else None}, status_code=0,
                        body_text="null", received_at=now, parse_status="pending", parse_error=None)
                    session.add(receipt)
                    await session.commit()
                    summary["provider_calls"] += 1
                    try:
                        try:
                            raw = await client.search_place(query, size=100)
                        except VworldNoDataError:
                            processed = None
                        else:
                            processed = process_search_response(parse_search_response(raw))
                            if processed.status not in ("OK", "NOT_FOUND"):
                                raise RuntimeError("VWorld search failed")
                        raw_total = (processed.record or {}).get("total") if processed is not None else 0
                        try:
                            count = int(raw_total) if raw_total is not None else None
                        except (TypeError, ValueError):
                            count = None
                        incomplete = processed is not None and processed.status == "OK" and (
                            count is None or count != len(processed.items)
                        )
                        selected = None
                        if processed is not None and not incomplete:
                            selected = (choose_bus_location(processed.items, name=name,
                                service_type=row.service_type, city_name=row.city_name) if kind == "bus"
                                else choose_port_location(processed.items, name=name))
                        receipt.status_code = 200
                        receipt.parse_status = "incomplete" if incomplete else "success"
                        receipt.body_text = json.dumps({"selected": selected, "returned": len(processed.items) if processed else 0,
                            "total": count}, ensure_ascii=False)
                        if incomplete:
                            summary["deferred"] += 1
                        elif selected is None:
                            summary["unmatched"] += 1
                        else:
                            await session.refresh(row, with_for_update=True)
                            if row.latitude is None and row.location_source != "admin_manual":
                                row.latitude = selected["latitude"]
                                row.longitude = selected["longitude"]
                                row.location_source = LOCATION_SOURCE
                                row.raw_item_json = {**(row.raw_item_json or {}), "_vworld_place": selected}
                                summary["bus_locations" if kind == "bus" else "port_locations"] += 1
                        await session.commit()
                    except Exception as exc:
                        await session.rollback()
                        stored = await session.get(RawApiResponse, receipt.id)
                        assert stored is not None
                        stored.parse_status = "failed"
                        stored.parse_error = type(exc).__name__
                        await session.commit()
                        summary["deferred"] += 1
                        summary["provider_failed"] += 1
                        if isinstance(exc, VworldNetworkError):
                            await asyncio.sleep(2)
                            continue
                        break
                    await asyncio.sleep(self.settings.place_location_request_interval_seconds)
            run.status = "partial_success" if summary["deferred"] else "success"
            run.finished_at = now_utc()
            await session.commit()
            return {"status": run.status, "run_id": run.id, **summary}
        except BaseException as exc:
            await session.rollback()
            stored = await session.get(CollectionRun, run.id)
            if stored is not None:
                stored.status = "failed"
                stored.finished_at = now_utc()
                stored.error_message = type(exc).__name__
                await session.commit()
            raise
