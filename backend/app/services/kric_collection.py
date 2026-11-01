"""KRIC 예정 시간표를 역·운행일별 하루 한 번 저장하고 미수집분은 다음 배치로 이어간다."""
from __future__ import annotations

import asyncio
import heapq
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from kric import KricClient, KricFileClient, KricNetworkError, KricNoDataError, KricServerError, RustfsObjectStore, StationCodeInfo, StoredObject
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, to_seoul
from app.models import (
    CollectionRun, KricStationCode, KricStationMappingRegistry, KricTimetableSnapshot,
    RailServiceDay, RailStationReference, RawApiResponse, KricTimetableAttempt,
)
from app.services.rail_station_mapping import (
    automatic_station_mappings,
    catalog_digest,
    effective_station_mappings,
    station_catalog,
)
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
            latest = await session.scalar(select(CollectionRun).where(CollectionRun.trigger == TRIGGER).order_by(CollectionRun.started_at.desc()).limit(1))
            if latest:
                # 공통 인증/할당량 오류는 원천 전체 보호, 그 외에는 다음 시간에 미수집분을 계속한다.
                delay = 24 if latest.error_message in {"KricAuthError", "KricRateLimitError"} else 1
                # 다음 정시 실행이 몇 초 빨리 시작해도 한 시간 전체를 건너뛰지 않는다.
                same_hour = now_utc().replace(minute=0, second=0, microsecond=0) == aware(latest.started_at).replace(minute=0, second=0, microsecond=0)
                if (delay == 24 and now_utc() - aware(latest.started_at) < timedelta(hours=24)) or (delay == 1 and same_hour):
                    return {"status": "skipped", "reason": "KRIC batch retry interval has not elapsed"}
            run = CollectionRun(started_at=now_utc(), status="running", trigger=TRIGGER)
            session.add(run)
            await session.commit()
            run_id = run.id
            try:
                stations = list((await session.scalars(select(KricStationCode).where(KricStationCode.active.is_(True)))).all())
                catalog_fresh = stations and all(now_utc() - aware(row.last_seen_at) < timedelta(hours=24) for row in stations)
                archive = None
                if not catalog_fresh:
                    codes, archive = await self.code_fetcher()
                    stations = await self._sync_codes(session, codes)
                await self._sync_calendar(session)
                if not catalog_fresh:
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
                attempts = {(row.station_id, row.day_code): row for row in (await session.scalars(select(KricTimetableAttempt))).all()}
                missing_since = datetime.min.replace(tzinfo=UTC)
                today = to_seoul(now_utc()).weekday()
                preferred_day = "7" if today == 5 else "9" if today == 6 else "8"
                candidate_count = 0
                def eligible_candidates():
                    nonlocal candidate_count
                    for station in stations:
                        for day in ("7", "8", "9"):
                            previous = snapshots.get((station.id, day))
                            attempt = attempts.get((station.id, day))
                            if ((previous is None or now_utc() - aware(previous.collected_at) >= timedelta(hours=24))
                                    and (attempt is None or now_utc() - aware(attempt.attempted_at) >= timedelta(hours=24))):
                                candidate_count += 1
                                yield station, day
                candidates = eligible_candidates()
                candidates = heapq.nsmallest(self.settings.kric_timetable_max_calls, candidates, key=lambda pair: (
                    aware(snapshots[(pair[0].id, pair[1])].collected_at) if (pair[0].id, pair[1]) in snapshots else missing_since,
                    pair[1] != preferred_day, pair[0].id, pair[1],
                ))
                count = 0
                attempted = 0
                failures = 0
                no_data = 0
                consecutive_failures = 0
                async with self.client_factory(self.settings.kric_service_key, timeout=self.settings.api_timeout_seconds) as client:
                    for station, day in candidates:
                        # 4시간 Dagster 상한 전에 끝내고 다음 시간 배치에서 미수집 역을 재개한다.
                        if now_utc() - aware(run.started_at) >= timedelta(hours=3):
                            break
                        if attempted:
                            await self.sleep(self.settings.kric_timetable_request_interval_seconds)
                        if now_utc() - aware(run.started_at) >= timedelta(hours=3):
                            break
                        attempted += 1
                        attempt = attempts.get((station.id, day))
                        if attempt is None:
                            attempt = KricTimetableAttempt(station_id=station.id, day_code=day, attempted_at=now_utc(), outcome="pending")
                            session.add(attempt)
                        else:
                            attempt.attempted_at = now_utc()
                            attempt.outcome = "pending"
                        await session.commit()  # 실패/강제 종료 때도 같은 역을 하루에 반복 호출하지 않는다.
                        try:
                            rows = await client.get_station_timetable(rail_operator_code=station.operator_code,
                                line_code=station.line_code, station_code=station.station_code, day_code=day)
                        except KricNoDataError:
                            no_data += 1
                            consecutive_failures = 0
                            attempt.outcome = "no_data"
                            session.add(RawApiResponse(collection_run_id=run_id, source="kric_timetable",
                                endpoint="convenientInfo/stationTimetable", status_code=200,
                                request_params_json={"operator_code": station.operator_code, "line_code": station.line_code,
                                    "station_code": station.station_code, "day_code": day},
                                received_at=now_utc(), parse_status="no_data", body_text='{"resultCode":"03"}'))
                            await session.commit()  # 마지막 정상 저장본을 빈 응답으로 덮어쓰지 않는다.
                            continue
                        except (KricNetworkError, KricServerError) as exc:
                            # 개별 역의 서버/스키마 실패가 뒤의 모든 역을 48시간 막지 않게 한다.
                            # 인증·할당량 오류와 응답 정체 불일치는 기존처럼 배치를 즉시 중단한다.
                            failures += 1
                            attempt.outcome = "error"
                            consecutive_failures += 1
                            session.add(RawApiResponse(collection_run_id=run_id, source="kric_timetable",
                                endpoint="convenientInfo/stationTimetable", status_code=0,
                                request_params_json={"operator_code": station.operator_code, "line_code": station.line_code,
                                    "station_code": station.station_code, "day_code": day},
                                received_at=now_utc(), parse_status="error", parse_error=type(exc).__name__,
                                body_text=json.dumps({"error_type": type(exc).__name__})))
                            await session.commit()
                            if consecutive_failures >= 3:
                                break
                            continue
                        consecutive_failures = 0
                        if any((row.rail_operator_code, row.line_code, row.station_code, str(row.day_code)) !=
                               (station.operator_code, station.line_code, station.station_code, day) for row in rows):
                            raise ValueError("KRIC timetable response identity does not match requested station/day")
                        items = [{name: getattr(row, name) for name in ("arrival_time", "departure_time", "origin_station_code", "terminal_station_code", "train_number")} for row in rows]
                        attempt.outcome = "stored"
                        snapshot = snapshots.get((station.id, day))
                        if snapshot is None:
                            snapshot = KricTimetableSnapshot(station_id=station.id, day_code=day, collected_at=now_utc(), items_json=items)
                            session.add(snapshot)
                        else:
                            await session.execute(update(KricTimetableSnapshot).where(KricTimetableSnapshot.id == snapshot.id).values(collected_at=now_utc(), items_json=items))
                        await session.commit()  # 다음 역 실패가 앞서 검증한 정상 저장본을 없애지 않는다.
                        count += 1
                run.status = "partial" if failures and count else "failed" if failures else "success"
                run.finished_at = now_utc()
                run.error_message = json.dumps({"failed_snapshot_count": failures,
                    "stopped_after_consecutive_failures": consecutive_failures >= 3}) if failures else None
                await session.commit()
                return {"status": run.status, "run_id": run_id, "station_count": len(stations),
                        "linked_station_count": sum(station.rail_station_id is not None for station in stations),
                        "stored_snapshot_count": count, "failed_snapshot_count": failures,
                        "no_data_snapshot_count": no_data,
                        "attempted_snapshot_count": attempted, "deferred_snapshot_count": candidate_count - attempted}
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
        place_rows = (await session.scalars(
            select(RailStationReference).where(RailStationReference.source == "kric_public_file")
        )).all()
        registry = await session.scalar(
            select(KricStationMappingRegistry).where(KricStationMappingRegistry.id == 1).with_for_update()
        )
        if registry is None:
            registry = KricStationMappingRegistry(
                id=1, catalog_json=[], automatic_mappings_json=[], manual_mappings_json=[], updated_at=now_utc(),
            )
            session.add(registry)
        catalog = station_catalog(codes)
        automatic = automatic_station_mappings(codes, place_rows)
        effective = effective_station_mappings(
            codes, place_rows, automatic, registry.manual_mappings_json or [],
        )
        old = {
            (row.operator_code, row.line_code, row.station_code): row
            for row in (await session.scalars(select(KricStationCode))).all()
        }
        # KRIC 코드 목록 JSON과 수동 연결 JSON을 함께 저장한다. 새 코드 목록이 올 때
        # 관리자가 고친 매핑은 유지하고, 유일한 코드·역번호·역명 대조만 자동 적용한다.
        await session.execute(update(KricStationCode).values(active=False, rail_station_id=None))
        result = []
        seen_at = now_utc()
        place_ids = {str(place.identity_key): place.id for place in place_rows}
        for item, key in zip(codes, keys, strict=True):
            name = (item.rail_operator_name, item.line_name, item.station_name)
            station = old.get(key)
            if station is None:
                station = KricStationCode(operator_code=key[0], line_code=key[1], station_code=key[2])
                session.add(station)
            station.operator_name, station.line_name, station.station_name = name
            resolved = effective.get(key)
            station.rail_station_id = place_ids.get(resolved[0]) if resolved else None
            station.active, station.last_seen_at = True, seen_at
            result.append(station)
        registry.catalog_json = catalog
        registry.automatic_mappings_json = automatic
        registry.catalog_sha256 = catalog_digest(catalog)
        registry.catalog_updated_at = seen_at
        registry.updated_at = seen_at
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
        existing = await session.get(RailServiceDay, start)
        if existing and now_utc() - aware(existing.verified_at) < timedelta(hours=24):
            return
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
