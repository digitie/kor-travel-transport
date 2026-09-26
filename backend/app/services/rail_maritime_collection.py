"""KRIC 공개 파일과 공공데이터포털 여객선 기준정보를 저장한다."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, timedelta
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from kric import (
    DataGoKrMaritimeClient,
    DomesticFerryPort,
    FerryShipType,
    FerryTerminal,
    FileStationInfo,
    PortGuidelineFileClient,
    PortGuidelineLocation,
    KricFileClient,
    RustfsObjectStore,
    StoredObject,
)
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, to_seoul
from app.models import (
    CollectionRun,
    FerryPort,
    FerryShipTypeReference,
    FerryTerminalReference,
    FerryTimetableSnapshot,
    RailStationReference,
    RawApiResponse,
)

logger = logging.getLogger(__name__)

KRIC_FILE_SOURCE = "kric_public_file"
MARITIME_SOURCE = "data_go_kr_maritime"
PORT_GUIDELINE_SOURCE = "data_go_kr_port_guideline"


class RailMaritimeCollectionService:
    """저변동 철도·여객선 데이터를 Dagster job에서 안전하게 적재한다.

    항구·터미널·선박 종류는 기준정보로, 운항시간표는 항구·운항일 단위 스냅샷으로 저장한다.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        rail_fetcher: Callable[[], Awaitable[tuple[FileStationInfo, ...]]] | None = None,
        port_guideline_fetcher: Callable[[], Awaitable[tuple[PortGuidelineLocation, ...]]] | None = None,
        maritime_client_factory: Callable[..., DataGoKrMaritimeClient] = DataGoKrMaritimeClient,
    ) -> None:
        self.settings = settings
        self._rail_fetcher = rail_fetcher
        self._port_guideline_fetcher = port_guideline_fetcher
        self._maritime_client_factory = maritime_client_factory

    async def collect_rail_reference(
        self, session: AsyncSession, *, trigger: str = "dagster_rail"
    ) -> dict[str, Any]:
        if not self.settings.rail_reference_collection_enabled:
            return {"status": "skipped", "reason": "rail reference collection is disabled"}
        latest_success = await session.scalar(
            select(CollectionRun.finished_at)
            .where(
                CollectionRun.trigger == "dagster_rail",
                CollectionRun.status == "success",
                CollectionRun.finished_at.is_not(None),
            )
            .order_by(CollectionRun.finished_at.desc())
            .limit(1)
        )
        if latest_success is not None:
            if latest_success.tzinfo is None:
                latest_success = latest_success.replace(tzinfo=UTC)
            if now_utc() - latest_success < timedelta(days=2):
                return {"status": "skipped", "reason": "KRIC rail reference is not due for 48 hours"}
        run = await self._start_run(session, trigger)
        try:
            stations, archive = await self._fetch_rail_stations()
            collected_at = now_utc()
            stored = 0
            for station in stations:
                await self._upsert_rail_station(session, station, collected_at)
                stored += 1
            await self._store_summary_response(
                session,
                run.id,
                KRIC_FILE_SOURCE,
                "data.kric.go.kr:dataset-1294",
                {
                    "station_count": stored,
                    "rustfs_bucket": archive.bucket if archive else None,
                    "rustfs_object_key": archive.object_key if archive else None,
                    "rustfs_checksum_sha256": archive.checksum_sha256 if archive else None,
                },
            )
            await self._finish_run(session, run.id, "success")
            logger.info("rail reference collection finished run_id=%s station_count=%s", run.id, stored)
            return {"status": "success", "run_id": run.id, "station_count": stored}
        except asyncio.CancelledError as exc:
            await self._fail_run(session, run.id, exc)
            raise
        except Exception as exc:
            await self._fail_run(session, run.id, exc)
            raise

    async def collect_maritime_reference(
        self, session: AsyncSession, *, trigger: str = "dagster_maritime"
    ) -> dict[str, Any]:
        if not self.settings.maritime_reference_collection_enabled:
            return {"status": "skipped", "reason": "maritime reference collection is disabled"}
        if not self.settings.data_go_kr_service_key:
            return {"status": "skipped", "reason": "DATA_GO_KR_SERVICE_KEY is required"}

        run = await self._start_run(session, trigger)
        try:
            summary = await self._collect_maritime_data(session, run.id)
            await self._store_summary_response(
                session, run.id, MARITIME_SOURCE, "data.go.kr:maritime-reference", summary
            )
            await self._finish_run(session, run.id, "success")
            logger.info("maritime reference collection finished run_id=%s summary=%s", run.id, summary)
            return {"status": "success", "run_id": run.id, **summary}
        except asyncio.CancelledError as exc:
            await self._fail_run(session, run.id, exc)
            raise
        except Exception as exc:
            await self._fail_run(session, run.id, exc)
            raise

    async def collect_ferry_timetables(
        self, session: AsyncSession, *, trigger: str = "dagster_ferry_timetable"
    ) -> dict[str, Any]:
        """오늘부터 설정된 보관 범위의 항구별 운항시간표를 DB에 보충한다.

        최초 실행만 모든 항구·운항일을 채운다. 이후에는 새로 추가된 운항일과 당일
        시간표만 provider에서 갱신해 호출량을 예측 가능하게 유지한다.
        """
        if not self.settings.ferry_timetable_collection_enabled:
            return {"status": "skipped", "reason": "ferry timetable collection is disabled"}
        if not self.settings.data_go_kr_service_key:
            return {"status": "skipped", "reason": "DATA_GO_KR_SERVICE_KEY is required"}

        run = await self._start_run(session, trigger)
        try:
            summary = await self._collect_ferry_timetables(session)
            await self._store_summary_response(
                session, run.id, MARITIME_SOURCE, "data.go.kr:ferry-timetable", summary
            )
            await self._finish_run(session, run.id, "success")
            logger.info("ferry timetable collection finished run_id=%s summary=%s", run.id, summary)
            return {"status": "success", "run_id": run.id, **summary}
        except asyncio.CancelledError as exc:
            await self._fail_run(session, run.id, exc)
            raise
        except Exception as exc:
            await self._fail_run(session, run.id, exc)
            raise

    async def _collect_ferry_timetables(self, session: AsyncSession) -> dict[str, int]:
        key = self.settings.data_go_kr_service_key
        assert key is not None
        today = to_seoul(now_utc()).date()
        service_dates = tuple(
            today + timedelta(days=offset)
            for offset in range(self.settings.ferry_timetable_storage_days)
        )
        last_service_date = service_dates[-1]
        await session.execute(
            delete(FerryTimetableSnapshot).where(
                or_(
                    FerryTimetableSnapshot.service_date < today,
                    FerryTimetableSnapshot.service_date > last_service_date,
                )
            )
        )
        ports = tuple(
            (await session.execute(
                select(FerryPort)
                .where(FerryPort.source == MARITIME_SOURCE)
                .order_by(FerryPort.port_id)
            )).scalars().all()
        )
        snapshots = tuple(
            (await session.execute(
                select(FerryTimetableSnapshot).where(
                    FerryTimetableSnapshot.source == MARITIME_SOURCE,
                    FerryTimetableSnapshot.service_date.in_(service_dates),
                )
            )).scalars().all()
        )
        by_port_date = {
            (snapshot.source, snapshot.departure_port_id, snapshot.service_date): snapshot
            for snapshot in snapshots
        }
        collected_at = now_utc()
        provider_calls = 0
        reused = 0
        operation_count = 0
        last_call_at = None
        async with self._maritime_client_factory(key, timeout=self.settings.api_timeout_seconds) as client:
            for port in ports:
                for service_date in service_dates:
                    snapshot = by_port_date.get((port.source, port.port_id, service_date))
                    is_today_snapshot = snapshot is not None and service_date == today
                    snapshot_collected_at = (
                        snapshot.collected_at.replace(tzinfo=UTC)
                        if snapshot is not None and snapshot.collected_at.tzinfo is None
                        else snapshot.collected_at if snapshot is not None else None
                    )
                    is_fresh_today = (
                        is_today_snapshot
                        and snapshot_collected_at is not None
                        and collected_at - snapshot_collected_at < timedelta(days=1)
                    )
                    if snapshot is not None and (service_date > today or is_fresh_today):
                        reused += 1
                        operation_count += len(snapshot.items_json)
                        continue
                    if last_call_at is not None:
                        elapsed = (now_utc() - last_call_at).total_seconds()
                        wait_seconds = self.settings.ferry_timetable_min_interval_seconds - elapsed
                        if wait_seconds > 0:
                            await asyncio.sleep(wait_seconds)
                    operations = await client.get_domestic_ship_operations(
                        departure_port_id=port.port_id,
                        departure_date=service_date,
                    )
                    last_call_at = now_utc()
                    items = [_ferry_operation_payload(item) for item in operations]
                    operation_count += len(items)
                    provider_calls += 1
                    if snapshot is None:
                        snapshot = FerryTimetableSnapshot(
                            source=port.source,
                            departure_port_id=port.port_id,
                            service_date=service_date,
                            collected_at=collected_at,
                            items_json=items,
                        )
                        session.add(snapshot)
                        by_port_date[(port.source, port.port_id, service_date)] = snapshot
                    else:
                        snapshot.collected_at = collected_at
                        snapshot.items_json = items
        return {
            "port_count": len(ports),
            "service_date_count": len(service_dates),
            "provider_calls": provider_calls,
            "reused_snapshot_count": reused,
            "operation_count": operation_count,
        }

    async def _fetch_rail_stations(self) -> tuple[tuple[FileStationInfo, ...], StoredObject | None]:
        if self._rail_fetcher is not None:
            return await self._rail_fetcher(), None
        if not self.settings.rustfs_is_configured:
            raise RuntimeError("RustFS configuration is required for enabled rail reference collection")
        assert self.settings.rustfs_endpoint_url is not None
        assert self.settings.rustfs_access_key_id is not None
        assert self.settings.rustfs_secret_access_key is not None
        async with RustfsObjectStore.from_s3_compatible_settings(
            endpoint_url=self.settings.rustfs_endpoint_url,
            bucket=self.settings.rustfs_bucket,
            access_key_id=self.settings.rustfs_access_key_id,
            secret_access_key=self.settings.rustfs_secret_access_key,
            region_name=self.settings.rustfs_region_name,
            prefix=self.settings.rustfs_raw_prefix,
            allow_insecure_http=self.settings.rustfs_allow_insecure_http,
        ) as store, KricFileClient(timeout=self.settings.api_timeout_seconds) as client:
            return await client.get_nationwide_station_info_to_rustfs(store)

    async def _collect_maritime_data(self, session: AsyncSession, run_id: int) -> dict[str, int]:
        key = self.settings.data_go_kr_service_key
        assert key is not None
        collected_at = now_utc()
        guidelines, archive = await self._fetch_port_guidelines()
        locations = _representative_port_locations(guidelines)
        async with self._maritime_client_factory(key, timeout=self.settings.api_timeout_seconds) as client:
            # 공공데이터 호출량을 예측 가능하게 유지하려고 동시에 세 요청을 보내지 않는다.
            # Provider iterator는 page budget을 넘기면 오류로 끝나므로 첫 페이지 하나만
            # 성공으로 저장하는 일을 막는다. 실시간 운항시간표에는 사용하지 않는다.
            ports = tuple([item async for item in client.iter_ports(page_size=100, max_pages=20)])
            terminals = tuple([item async for item in client.iter_ferry_terminals(page_size=100, max_pages=20)])
            ship_types = tuple([item async for item in client.iter_ferry_ship_types(page_size=100, max_pages=20)])
            for port in ports:
                if port.port_id:
                    await self._upsert_port(session, port, collected_at, locations.get(_port_name_key(port.port_name)))
            for terminal in terminals:
                if terminal.terminal_id:
                    await self._upsert_terminal(session, terminal, collected_at)
            for ship_type in ship_types:
                if ship_type.ship_type_id:
                    await self._upsert_ship_type(session, ship_type, collected_at)

        return {
            "port_count": len(ports),
            "terminal_count": len(terminals),
            "ship_type_count": len(ship_types),
            "port_location_count": len(locations),
            "port_guideline_object_stored": int(archive is not None),
        }

    async def _fetch_port_guidelines(self) -> tuple[tuple[PortGuidelineLocation, ...], StoredObject | None]:
        if not self.settings.port_guideline_collection_enabled:
            return (), None
        if self._port_guideline_fetcher is not None:
            return await self._port_guideline_fetcher(), None
        if not self.settings.rustfs_is_configured:
            raise RuntimeError("RustFS configuration is required for enabled port guideline collection")
        assert self.settings.rustfs_endpoint_url is not None
        assert self.settings.rustfs_access_key_id is not None
        assert self.settings.rustfs_secret_access_key is not None
        async with RustfsObjectStore.from_s3_compatible_settings(
            endpoint_url=self.settings.rustfs_endpoint_url,
            bucket=self.settings.rustfs_bucket,
            access_key_id=self.settings.rustfs_access_key_id,
            secret_access_key=self.settings.rustfs_secret_access_key,
            region_name=self.settings.rustfs_region_name,
            prefix=self.settings.rustfs_raw_prefix,
            allow_insecure_http=self.settings.rustfs_allow_insecure_http,
        ) as store, PortGuidelineFileClient(timeout=self.settings.api_timeout_seconds) as client:
            return await client.get_locations_to_rustfs(store)

    async def _start_run(self, session: AsyncSession, trigger: str) -> CollectionRun:
        run = CollectionRun(
            started_at=now_utc(),
            finished_at=None,
            status="running",
            trigger=trigger,
            error_message=None,
        )
        session.add(run)
        await session.commit()
        return run

    async def _finish_run(self, session: AsyncSession, run_id: int, status: str) -> None:
        run = await session.get(CollectionRun, run_id)
        assert run is not None
        run.status = status
        run.finished_at = now_utc()
        await session.commit()

    async def _fail_run(self, session: AsyncSession, run_id: int, exc: BaseException) -> None:
        await session.rollback()
        run = await session.get(CollectionRun, run_id)
        if run is not None:
            run.status = "failed"
            run.finished_at = now_utc()
            run.error_message = _safe_error(exc)
            await session.commit()

    async def _store_summary_response(
        self, session: AsyncSession, run_id: int, source: str, endpoint: str, summary: Mapping[str, Any]
    ) -> None:
        session.add(
            RawApiResponse(
                collection_run_id=run_id,
                source=source,
                endpoint=endpoint,
                request_params_json=None,
                status_code=200,
                body_text=json.dumps(dict(summary), ensure_ascii=False, sort_keys=True),
                received_at=now_utc(),
                parse_status="success",
                parse_error=None,
            )
        )

    async def _upsert_rail_station(
        self, session: AsyncSession, item: FileStationInfo, collected_at: Any
    ) -> None:
        identity = _identity(item.rail_operator_name, item.operating_line_name, item.station_number, item.station_name)
        row = await session.scalar(
            select(RailStationReference).where(
                RailStationReference.source == KRIC_FILE_SOURCE,
                RailStationReference.identity_key == identity,
            )
        )
        values = {
            "rail_operator_name": item.rail_operator_name, "operating_line_name": item.operating_line_name,
            "station_type": item.station_type, "station_number": item.station_number, "station_name": item.station_name,
            "english_name": item.english_name, "longitude": item.longitude, "latitude": item.latitude,
            "lot_address": item.lot_address, "road_address": item.road_address,
            "station_phone_number": item.station_phone_number, "data_reference_date": item.data_reference_date,
            "last_seen_at": collected_at, "raw_item_json": dict(item.raw),
        }
        if row is None:
            session.add(
                RailStationReference(
                    source=KRIC_FILE_SOURCE,
                    identity_key=identity,
                    first_seen_at=collected_at,
                    **values,
                )
            )
        else:
            for name, value in values.items():
                setattr(row, name, value)

    async def _upsert_port(
        self, session: AsyncSession, item: DomesticFerryPort, collected_at: Any,
        location: tuple[float, float, int] | None,
    ) -> None:
        assert item.port_id is not None
        row = await session.scalar(
            select(FerryPort).where(FerryPort.source == MARITIME_SOURCE, FerryPort.port_id == item.port_id)
        )
        values = {
            "port_name": item.port_name, "last_seen_at": collected_at, "raw_item_json": dict(item.raw),
            "latitude": location[0] if location else None, "longitude": location[1] if location else None,
            "location_source": PORT_GUIDELINE_SOURCE if location else None,
            "location_point_count": location[2] if location else 0,
        }
        if row is None:
            session.add(
                FerryPort(
                    source=MARITIME_SOURCE,
                    port_id=item.port_id,
                    first_seen_at=collected_at,
                    **values,
                )
            )
        else:
            for name, value in values.items():
                setattr(row, name, value)

    async def _upsert_terminal(self, session: AsyncSession, item: FerryTerminal, collected_at: Any) -> None:
        assert item.terminal_id is not None
        row = await session.scalar(
            select(FerryTerminalReference).where(
                FerryTerminalReference.source == MARITIME_SOURCE,
                FerryTerminalReference.terminal_id == item.terminal_id,
            )
        )
        values = {
            "terminal_name": item.terminal_name,
            "address": item.address,
            "telephone": item.telephone,
            "last_seen_at": collected_at,
            "raw_item_json": dict(item.raw),
        }
        if row is None:
            session.add(
                FerryTerminalReference(
                    source=MARITIME_SOURCE,
                    terminal_id=item.terminal_id,
                    first_seen_at=collected_at,
                    **values,
                )
            )
        else:
            for name, value in values.items():
                setattr(row, name, value)

    async def _upsert_ship_type(self, session: AsyncSession, item: FerryShipType, collected_at: Any) -> None:
        assert item.ship_type_id is not None
        row = await session.scalar(
            select(FerryShipTypeReference).where(
                FerryShipTypeReference.source == MARITIME_SOURCE,
                FerryShipTypeReference.ship_type_id == item.ship_type_id,
            )
        )
        values = {
            "ship_type_name": item.ship_type_name,
            "last_seen_at": collected_at,
            "raw_item_json": dict(item.raw),
        }
        if row is None:
            session.add(
                FerryShipTypeReference(
                    source=MARITIME_SOURCE,
                    ship_type_id=item.ship_type_id,
                    first_seen_at=collected_at,
                    **values,
                )
            )
        else:
            for name, value in values.items():
                setattr(row, name, value)


def _identity(*values: str | None) -> str:
    return "|".join((value or "").strip() for value in values)


def _safe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:500]}"


def _ferry_operation_payload(item: Any) -> dict[str, str | None]:
    """provider 객체를 공개 API와 같은 안정된 JSON 계약으로 축소한다."""
    return {
        "vessel_name": item.vessel_name,
        "departure_port_name": item.departure_port_name,
        "arrival_port_name": item.arrival_port_name,
        "departure_planned_time": item.departure_planned_time,
        "arrival_planned_time": item.arrival_planned_time,
        "fare": item.fare,
    }


def _port_name_key(value: str | None) -> str:
    return "".join((value or "").split()).replace("항구", "").replace("항", "")


def _representative_port_locations(
    locations: tuple[PortGuidelineLocation, ...],
) -> dict[str, tuple[float, float, int]]:
    """원문 순서가 가장 이른 안내 지점을 marker로 선택하고 전체 점 수를 함께 남긴다."""
    grouped: dict[str, list[PortGuidelineLocation]] = {}
    for item in locations:
        key = _port_name_key(item.port_name)
        if key and item.latitude is not None and item.longitude is not None:
            grouped.setdefault(key, []).append(item)
    result: dict[str, tuple[float, float, int]] = {}
    for key, items in grouped.items():
        selected = min(items, key=lambda item: (int(item.position_order) if (item.position_order or "").isdigit() else 10**9, item.latitude or 0, item.longitude or 0))
        assert selected.latitude is not None and selected.longitude is not None
        result[key] = (selected.latitude, selected.longitude, len(items))
    return result
