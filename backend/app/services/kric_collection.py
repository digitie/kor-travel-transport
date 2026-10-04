"""KRIC 코드 파일과 예정 시간표를 48시간 간격의 제한된 batch로 저장한다."""
from __future__ import annotations

import asyncio
import heapq
import json
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from kric import KricClient, KricFileClient, RustfsObjectStore, StationCodeInfo, StoredObject
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, to_seoul
from app.models import CollectionRun, KricStationCode, KricTimetableSnapshot, RailServiceDay, RailStationReference, RawApiResponse
from app.services.holidays import HolidayService

TRIGGER = "dagster_kric_timetable"


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class KricTimetableCollectionService:
    def __init__(
        self, settings: Settings, *, client_factory: Callable[..., Any] = KricClient,
        code_fetcher: Callable[[], Awaitable[tuple[tuple[StationCodeInfo, ...], StoredObject | None]]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.client_factory = client_factory
        self.code_fetcher = code_fetcher or self._fetch_codes
        self.sleep = sleep

    @asynccontextmanager
    async def _lease(self, session: AsyncSession) -> AsyncIterator[bool]:
        engine = session.bind
        if engine is None or engine.dialect.name != "postgresql":
            yield True
            return
        async with engine.connect() as connection:
            acquired = bool(await connection.scalar(text("SELECT pg_try_advisory_lock(hashtext('transport:kric_timetable'))")))
            try:
                yield acquired
            finally:
                if acquired:
                    await connection.execute(text("SELECT pg_advisory_unlock(hashtext('transport:kric_timetable'))"))

    async def collect(self, session: AsyncSession) -> dict[str, Any]:
        if not self.settings.kric_timetable_collection_enabled or not self.settings.kric_service_key:
            return {"status": "skipped", "reason": "KRIC timetable collection is disabled or unconfigured"}
        async with self._lease(session) as acquired:
            if not acquired:
                return {"status": "skipped", "reason": "another KRIC batch is active"}
            latest = await session.scalar(select(CollectionRun.started_at).where(CollectionRun.trigger == TRIGGER).order_by(CollectionRun.started_at.desc()).limit(1))
            if latest and now_utc() - aware(latest) < timedelta(hours=48):
                return {"status": "skipped", "reason": "KRIC batch is not due for 48 hours since last attempt"}
            run = CollectionRun(started_at=now_utc(), status="running", trigger=TRIGGER)
            session.add(run)
            await session.commit()  # 호출 전에 시도를 영구 기록한다. 실패·강제 종료도 48시간 보호한다.
            run_id = run.id
            try:
                codes, archive = await self.code_fetcher()
                stations = await self._sync_codes(session, codes)
                await self._sync_calendar(session)
                session.add(RawApiResponse(
                    collection_run_id=run_id, source="kric_station_codes", endpoint="data.kric.go.kr:notice-17",
                    request_params_json=None, status_code=200, received_at=now_utc(), parse_status="success",
                    body_text=json.dumps({"station_count": len(stations), "rustfs_object_key": archive.object_key if archive else None,
                        "rustfs_bucket": archive.bucket if archive else None, "checksum_sha256": archive.checksum_sha256 if archive else None}),
                ))
                await session.commit()
                snapshots = {(row.station_id, row.day_code): row for row in (await session.execute(select(
                    KricTimetableSnapshot.id, KricTimetableSnapshot.station_id,
                    KricTimetableSnapshot.day_code, KricTimetableSnapshot.collected_at,
                ))).all()}
                missing_since = datetime.min.replace(tzinfo=UTC)
                today = to_seoul(now_utc()).weekday()
                preferred_day = "7" if today == 5 else "9" if today == 6 else "8"
                candidates = ((station, day) for station in stations for day in ("7", "8", "9")
                    if (station.id, day) not in snapshots or now_utc() - aware(snapshots[(station.id, day)].collected_at) >= timedelta(hours=48))
                candidates = heapq.nsmallest(self.settings.kric_timetable_max_calls, candidates, key=lambda pair: (
                    aware(snapshots[(pair[0].id, pair[1])].collected_at) if (pair[0].id, pair[1]) in snapshots else missing_since,
                    pair[0].rail_station_id is None, pair[1] != preferred_day, pair[0].id, pair[1],
                ))
                count = 0
                async with self.client_factory(self.settings.kric_service_key, timeout=self.settings.api_timeout_seconds) as client:
                    for station, day in candidates:
                        # 4시간 Dagster 상한보다 일찍 종료하고 다음 48시간 batch에서 재개한다.
                        if now_utc() - aware(run.started_at) >= timedelta(hours=3):
                            break
                        if count:
                            await self.sleep(self.settings.kric_timetable_request_interval_seconds)
                        if now_utc() - aware(run.started_at) >= timedelta(hours=3):
                            break
                        rows = await client.get_station_timetable(rail_operator_code=station.operator_code,
                            line_code=station.line_code, station_code=station.station_code, day_code=day)
                        if any((row.rail_operator_code, row.line_code, row.station_code, str(row.day_code)) !=
                               (station.operator_code, station.line_code, station.station_code, day) for row in rows):
                            raise ValueError("KRIC timetable response identity does not match requested station/day")
                        items = [{name: getattr(row, name) for name in ("arrival_time", "departure_time", "origin_station_code", "terminal_station_code", "train_number")} for row in rows]
                        snapshot = snapshots.get((station.id, day))
                        if snapshot is None:
                            snapshot = KricTimetableSnapshot(station_id=station.id, day_code=day, collected_at=now_utc(), items_json=items)
                            session.add(snapshot)
                        else:
                            await session.execute(update(KricTimetableSnapshot).where(KricTimetableSnapshot.id == snapshot.id).values(collected_at=now_utc(), items_json=items))
                        await session.commit()  # 다음 역 실패가 앞서 검증한 정상 저장본을 없애지 않는다.
                        count += 1
                run.status, run.finished_at = "success", now_utc()
                await session.commit()
                return {"status": "success", "run_id": run_id, "station_count": len(stations),
                        "linked_station_count": sum(station.rail_station_id is not None for station in stations),
                        "stored_snapshot_count": count, "deferred_snapshot_count": len(candidates) - count}
            except (Exception, asyncio.CancelledError) as exc:
                await session.rollback()
                stored_run = await session.get(CollectionRun, run_id)
                if stored_run:
                    stored_run.status, stored_run.finished_at, stored_run.error_message = "failed", now_utc(), type(exc).__name__
                    await session.commit()
                if isinstance(exc, asyncio.CancelledError):
                    raise asyncio.CancelledError() from None
                # Dagster가 traceback을 기록해도 provider URL·인증키 원문은 노출하지 않는다.
                raise RuntimeError(f"KRIC collection failed: {type(exc).__name__}") from None

    async def _sync_codes(self, session: AsyncSession, codes: tuple[StationCodeInfo, ...]) -> list[KricStationCode]:
        keys = [(row.rail_operator_code, row.line_code, row.station_code) for row in codes]
        if not codes or any(not all(key) for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("KRIC station code file is empty, incomplete or has duplicate identities")
        if any(not all((row.rail_operator_name, row.line_name, row.station_name)) for row in codes):
            raise ValueError("KRIC station code file has incomplete names")
        places: dict[tuple[str | None, str | None, str | None], list[int]] = defaultdict(list)
        for place in (await session.scalars(select(RailStationReference).where(RailStationReference.source == "kric_public_file"))).all():
            places[(place.rail_operator_name, place.operating_line_name, place.station_name)].append(place.id)
        names = Counter((row.rail_operator_name, row.line_name, row.station_name) for row in codes)
        old = {(row.operator_code, row.line_code, row.station_code): row for row in (await session.scalars(select(KricStationCode))).all()}
        # 명칭 변경·중복에 따른 이전 연결을 먼저 해제한다. 이름 하나만으로 연결하지 않는다.
        await session.execute(update(KricStationCode).values(active=False, rail_station_id=None))
        result = []
        seen_at = now_utc()
        for item, key in zip(codes, keys, strict=True):
            name = (item.rail_operator_name, item.line_name, item.station_name)
            matches = places.get(name, [])
            station = old.get(key)
            if station is None:
                station = KricStationCode(operator_code=key[0], line_code=key[1], station_code=key[2])
                session.add(station)
            station.operator_name, station.line_name, station.station_name = name
            station.rail_station_id = matches[0] if len(matches) == 1 and names[name] == 1 else None
            station.active, station.last_seen_at = True, seen_at
            result.append(station)
        await session.flush()
        return result

    async def _fetch_codes(self) -> tuple[tuple[StationCodeInfo, ...], StoredObject | None]:
        settings = self.settings
        if not settings.rustfs_is_configured:
            raise RuntimeError("RustFS configuration is required for KRIC station code files")
        async with RustfsObjectStore.from_s3_compatible_settings(
            endpoint_url=settings.rustfs_endpoint_url, bucket=settings.rustfs_bucket,
            access_key_id=settings.rustfs_access_key_id, secret_access_key=settings.rustfs_secret_access_key,
            region_name=settings.rustfs_region_name, prefix=settings.rustfs_raw_prefix,
            allow_insecure_http=settings.rustfs_allow_insecure_http,
        ) as store, KricFileClient(timeout=settings.api_timeout_seconds) as client:
            return await client.get_station_codes_to_rustfs(store)

    async def _sync_calendar(self, session: AsyncSession) -> None:
        if not self.settings.data_go_kr_service_key:
            return
        start = to_seoul(now_utc()).date()
        result = await HolidayService(self.settings).get_holidays(start, start + timedelta(days=31))
        if result.status != "success" or result.source != "kasi_holiday_info":
            return  # 확인 실패를 평일로 저장하지 않는다. 기존 정상 달력은 보존한다.
        holidays = {item.local_date for item in result.items if item.is_holiday}
        for offset in range(32):
            day = start + timedelta(days=offset)
            code = "9" if day.weekday() == 6 or day in holidays else "7" if day.weekday() == 5 else "8"
            stored = await session.get(RailServiceDay, day)
            if stored is None:
                session.add(RailServiceDay(service_date=day, day_code=code, verified_at=now_utc()))
            else:
                stored.day_code, stored.verified_at = code, now_utc()
