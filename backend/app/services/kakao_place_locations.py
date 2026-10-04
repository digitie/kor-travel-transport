"""카카오 키워드 검색으로 VWorld에서 놓친 항구·버스 터미널 위치를 보강한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import UTC, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.place_targets import iter_missing_place_targets, matching_place_names, missing_place_count
from app.core.config import Settings
from app.core.time_utils import now_utc
from app.models import BusTerminalReference, CollectionRun, FerryPort, RawApiResponse
from app.services.place_locations import _province


SOURCE = "kakao_place"
TRIGGER = "dagster_kakao_place_locations"
URL = "https://dapi.kakao.com/v2/local/search/keyword.json"


def choose_kakao_location(items: list[Mapping[str, Any]], *, query: str, kind: str,
                          city_name: str | None = None, service_type: str | None = None) -> dict[str, Any] | None:
    """이름·시설 종류·시도가 일치하는 고유 시설점만 선택한다."""
    if not query or "_" in query:
        return None
    matches: dict[tuple[float, float], dict[str, Any]] = {}
    for item in items:
        title = str(item.get("place_name") or "").strip()
        category = str(item.get("category_name") or "")
        if title != query:
            continue
        if kind == "port":
            if "항구,포구" not in category:
                continue
        elif "고속,시외버스터미널" not in category:
            continue
        if kind == "bus" and ((service_type == "express" and "시외" in title) or
                              (service_type == "intercity" and "고속" in title)):
            continue
        address = str(item.get("address_name") or "")
        if kind == "bus" and _province(city_name or "") and _province(city_name or "") != _province(address):
            continue
        try:
            lon, lat = float(item["x"]), float(item["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (124 <= lon <= 132 and 32 <= lat <= 39.5):
            continue
        matches[(lon, lat)] = {"title": title, "category": category, "address": address,
                               "longitude": lon, "latitude": lat, "provider_id": str(item.get("id") or "")}
    return next(iter(matches.values())) if len(matches) == 1 else None


class KakaoPlaceCollectionService:
    """단일 순차 배치와 DB 영수증으로 카카오 앱 키의 호출량을 제한한다."""

    def __init__(self, settings: Settings, *, client_factory: Any = httpx.AsyncClient) -> None:
        self.settings = settings
        self.client_factory = client_factory

    async def collect(self, session: AsyncSession) -> dict[str, Any]:
        if not self.settings.kakao_place_collection_enabled or not self.settings.kakao_rest_api_key:
            return {"status": "skipped", "reason": "Kakao place collection or REST API key is disabled"}
        async with self._lease(session) as acquired:
            if not acquired:
                return {"status": "skipped", "reason": "another Kakao place collection is active"}
            return await self._collect_unlocked(session)

    @asynccontextmanager
    async def _lease(self, session: AsyncSession):
        engine = session.bind
        if engine is None or engine.dialect.name != "postgresql":
            yield True
            return
        async with engine.connect() as connection:
            acquired = bool(await connection.scalar(text(
                "SELECT pg_try_advisory_lock(hashtext('kor_travel_transport:kakao_place_collection'))"
            )))
            await connection.commit()
            try:
                yield acquired
            finally:
                if acquired:
                    released = bool(await connection.scalar(text(
                        "SELECT pg_advisory_unlock(hashtext('kor_travel_transport:kakao_place_collection'))"
                    )))
                    await connection.commit()
                    if not released:
                        raise RuntimeError("Kakao place collection advisory lock was not released")

    async def _collect_unlocked(self, session: AsyncSession) -> dict[str, Any]:
        run = CollectionRun(started_at=now_utc(), status="running", trigger=TRIGGER)
        session.add(run)
        await session.commit()
        summary = {"provider_calls": 0, "bus_locations": 0, "port_locations": 0,
                   "unmatched": 0, "incomplete": 0, "deferred": 0, "provider_failed": 0}
        try:
            key_fingerprint = hashlib.sha256(self.settings.kakao_rest_api_key.encode()).hexdigest()
            budget_time = now_utc()
            day_calls = int(await session.scalar(select(func.count()).select_from(RawApiResponse).where(
                RawApiResponse.source == SOURCE,
                RawApiResponse.received_at >= budget_time - timedelta(days=1),
            )) or 0)
            month_calls = int(await session.scalar(select(func.count()).select_from(RawApiResponse).where(
                RawApiResponse.source == SOURCE,
                RawApiResponse.received_at >= budget_time - timedelta(days=31),
            )) or 0)
            # 429는 키 전체의 한도 응답이다. 재실행이 다른 장소를 다시 호출하지
            # 않도록 24시간 유예한다. 401/403은 키 교체 직후 재검증할 수 있어야 한다.
            recent_quota_error = await session.scalar(select(RawApiResponse.id).where(
                RawApiResponse.source == SOURCE,
                RawApiResponse.status_code == 429,
                RawApiResponse.received_at >= budget_time - timedelta(days=1),
                RawApiResponse.request_params_json["key_fingerprint"].as_string() == key_fingerprint,
            ).limit(1))
            target_count = await missing_place_count(session)
            if target_count and recent_quota_error is not None:
                summary["deferred"] = target_count
                run.status = "partial_success"
                run.finished_at = now_utc()
                await session.commit()
                return {"status": run.status, "run_id": run.id, **summary}
            async with self.client_factory(timeout=self.settings.api_timeout_seconds,
                                           headers={"Authorization": f"KakaoAK {self.settings.kakao_rest_api_key}"}) as client:
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
                        endpoint = f"kakao:bus:{row.service_type}:{row.terminal_id}"
                    else:
                        if await matching_place_names(session, kind, row) != 1:
                            continue
                        name = row.port_name.strip()
                        query = name if name.endswith("항") else name + "항"
                        endpoint = f"kakao:port:{row.port_id}"
                    if not name or "_" in name:
                        continue
                    now = now_utc()
                    previous = await session.scalar(select(RawApiResponse).where(
                        RawApiResponse.source == SOURCE, RawApiResponse.endpoint == endpoint,
                    ).order_by(RawApiResponse.received_at.desc(), RawApiResponse.id.desc()).limit(1))
                    if previous is not None:
                        received = previous.received_at.replace(tzinfo=UTC) if previous.received_at.tzinfo is None else previous.received_at
                        params = previous.request_params_json or {}
                        if (previous.status_code not in (401, 403) and
                                not (previous.status_code == 429 and
                                     params.get("key_fingerprint") != key_fingerprint) and
                                params.get("query") == query and params.get("name") == name and
                                params.get("city_name") == (row.city_name if kind == "bus" else None) and
                                now - received < timedelta(days=30 if previous.parse_status == "success" else 1)):
                            continue
                    # session-level lease가 같은 collector의 동시 실행을 배제한다.
                    if (day_calls >= self.settings.kakao_place_max_calls_per_day or
                            month_calls >= self.settings.kakao_place_max_calls_per_month):
                        summary["deferred"] += 1
                        await session.commit()
                        break
                    receipt = RawApiResponse(collection_run_id=run.id, source=SOURCE, endpoint=endpoint,
                        request_params_json={"query": query, "name": name,
                            "city_name": row.city_name if kind == "bus" else None,
                            "key_fingerprint": key_fingerprint, "page": 1}, status_code=0,
                        body_text="null", received_at=now, parse_status="pending", parse_error=None)
                    session.add(receipt)
                    await session.commit()
                    summary["provider_calls"] += 1
                    day_calls += 1
                    month_calls += 1
                    try:
                        response = await client.get(URL, params={"query": query, "page": 1, "size": 15})
                        response.raise_for_status()
                        payload = response.json()
                        items, meta = payload.get("documents"), payload.get("meta")
                        if not isinstance(items, list) or not isinstance(meta, dict):
                            raise ValueError("Kakao response is missing documents or meta")
                        try:
                            total = int(meta["total_count"])
                        except (KeyError, TypeError, ValueError):
                            total = None
                        incomplete = meta.get("is_end") is not True or total is None or total != len(items)
                        selected = None if incomplete else choose_kakao_location(
                            items, query=query, kind=kind, city_name=row.city_name if kind == "bus" else None,
                            service_type=row.service_type if kind == "bus" else None,
                        )
                        receipt.status_code = response.status_code
                        receipt.parse_status = "incomplete" if incomplete else "success"
                        receipt.body_text = json.dumps({"selected": selected, "returned": len(items),
                            "total": meta.get("total_count")}, ensure_ascii=False)
                        if incomplete:
                            summary["incomplete"] += 1
                        elif selected is None:
                            summary["unmatched"] += 1
                        else:
                            await session.refresh(row, with_for_update=True)
                            if row.latitude is None and row.location_source != "admin_manual":
                                row.latitude, row.longitude = selected["latitude"], selected["longitude"]
                                row.location_source = SOURCE
                                row.raw_item_json = {**(row.raw_item_json or {}), "_kakao_place": selected}
                                summary["bus_locations" if kind == "bus" else "port_locations"] += 1
                        await session.commit()
                    except Exception as exc:
                        await session.rollback()
                        stored = await session.get(RawApiResponse, receipt.id)
                        assert stored is not None
                        stored.parse_status = "failed"
                        stored.parse_error = type(exc).__name__
                        if isinstance(exc, httpx.HTTPStatusError):
                            stored.status_code = exc.response.status_code
                        await session.commit()
                        summary["deferred"] += 1
                        summary["provider_failed"] += 1
                        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (401, 403, 429):
                            break
                        await asyncio.sleep(2)
                        continue
                    await asyncio.sleep(self.settings.kakao_place_request_interval_seconds)
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
