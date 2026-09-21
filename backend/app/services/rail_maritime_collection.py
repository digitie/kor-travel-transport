"""KRIC 공개 파일과 공공데이터포털 여객선 기준정보를 저장한다."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from kric import (
    DataGoKrMaritimeClient,
    DomesticFerryPort,
    FerryShipType,
    FerryTerminal,
    FileStationInfo,
    KricFileClient,
    RustfsObjectStore,
    StoredObject,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.models import (
    CollectionRun,
    FerryPort,
    FerryShipTypeReference,
    FerryTerminalReference,
    RailStationReference,
    RawApiResponse,
)

logger = logging.getLogger(__name__)

KRIC_FILE_SOURCE = "kric_public_file"
MARITIME_SOURCE = "data_go_kr_maritime"


class RailMaritimeCollectionService:
    """저변동 철도·여객선 데이터를 Dagster job에서 안전하게 적재한다.

    운항시간표는 시시각각 변하므로 이 job은 항구·터미널·선박종류 기준정보만 저장한다.
    시간표는 항구 조회 API가 provider에서 실시간으로 받아 반환한다.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        rail_fetcher: Callable[[], Awaitable[tuple[FileStationInfo, ...]]] | None = None,
        maritime_client_factory: Callable[..., DataGoKrMaritimeClient] = DataGoKrMaritimeClient,
    ) -> None:
        self.settings = settings
        self._rail_fetcher = rail_fetcher
        self._maritime_client_factory = maritime_client_factory

    async def collect_rail_reference(
        self, session: AsyncSession, *, trigger: str = "dagster_rail"
    ) -> dict[str, Any]:
        if not self.settings.rail_reference_collection_enabled:
            return {"status": "skipped", "reason": "rail reference collection is disabled"}
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
        async with self._maritime_client_factory(key, timeout=self.settings.api_timeout_seconds) as client:
            # 공공데이터 호출량을 예측 가능하게 유지하려고 동시에 세 요청을 보내지 않는다.
            # Provider iterator는 page budget을 넘기면 오류로 끝나므로 첫 페이지 하나만
            # 성공으로 저장하는 일을 막는다. 실시간 운항시간표에는 사용하지 않는다.
            ports = tuple([item async for item in client.iter_ports(page_size=100, max_pages=20)])
            terminals = tuple([item async for item in client.iter_ferry_terminals(page_size=100, max_pages=20)])
            ship_types = tuple([item async for item in client.iter_ferry_ship_types(page_size=100, max_pages=20)])
            for port in ports:
                if port.port_id:
                    await self._upsert_port(session, port, collected_at)
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
        }

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

    async def _upsert_port(self, session: AsyncSession, item: DomesticFerryPort, collected_at: Any) -> None:
        assert item.port_id is not None
        row = await session.scalar(
            select(FerryPort).where(FerryPort.source == MARITIME_SOURCE, FerryPort.port_id == item.port_id)
        )
        if row is None:
            session.add(
                FerryPort(
                    source=MARITIME_SOURCE,
                    port_id=item.port_id,
                    port_name=item.port_name,
                    first_seen_at=collected_at,
                    last_seen_at=collected_at,
                    raw_item_json=dict(item.raw),
                )
            )
        else:
            row.port_name, row.last_seen_at, row.raw_item_json = item.port_name, collected_at, dict(item.raw)

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
