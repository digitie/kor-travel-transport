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
    PortCall,
    KricFileClient,
    KricNetworkError,
    RustfsObjectStore,
    StoredObject,
)
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
PORT_CALL_SOURCE = "komsa_port_call"
# TAGO와 KOMSA 코드는 서로 다르다. 지역을 확정한 TAGO 항구만 조회하며 이름 부분일치나
# 터미널 주소로 지역을 추정하지 않는다(원본 터미널 주소에 타 지역 값이 존재한다).
PORT_CALL_TARGETS = {
    "SEA10100": ("인천", "인천광역시"),
    "SEA30010": ("군산", "전북특별자치도"),
    "SEA31010": ("목포", "전라남도"),
    "SEA40010": ("마산", "경상남도"),
    "SEA42010": ("부산", "부산광역시"),
    "SEA43010": ("포항", "경상북도"),
    "SEA44010": ("동해", "강원특별자치도"),
    "SEA96140": ("여수", "전라남도"),
    "SEA44030": ("묵호", "강원특별자치도"),
    "SEA44060": ("강릉", "강원특별자치도"),
    "SEA22010": ("대천", "충청남도"),
    "SEA22040": ("평택", "경기도"),
    "SEA43030": ("후포", "경상북도"),
    "SEA40050": ("통영", "경상남도"),
    "SEA30020": ("격포", "전북특별자치도"),
    "SEA31020": ("완도", "전라남도"),
    "SEA31910": ("녹동", "전라남도"),
    "SEA35490": ("진도", "전라남도"),
    "SEA50110": ("여수엑스포", "전라남도"),
}


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
            status = "partial_success" if summary["port_location_failed_calls"] or summary["port_location_deferred_count"] else "success"
            await self._finish_run(session, run.id, status)
            logger.info("maritime reference collection finished run_id=%s summary=%s", run.id, summary)
            return {"status": status, "run_id": run.id, **summary}
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
            status = "partial_success" if summary["failed_provider_calls"] else "success"
            await self._finish_run(session, run.id, status)
            logger.info("ferry timetable collection finished run_id=%s summary=%s", run.id, summary)
            return {"status": status, "run_id": run.id, **summary}
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
        # 최초 10일 backfill 도중 provider가 제한·timeout을 반환해도 범위 정리는 남긴다.
        await session.commit()
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
        failed_provider_calls = 0
        consecutive_network_failures = 0
        reused = 0
        operation_count = 0
        last_call_at = None
        async with self._maritime_client_factory(key, timeout=self.settings.api_timeout_seconds) as client:
            # 모든 항구의 오늘 누락분을 먼저 채운 뒤 내일 이후를 보충한다.
            # 항구 하나의 10일치를 먼저 채우면 호출 예산 뒤쪽 항구가 계속 밀린다.
            for service_date in service_dates:
                for port in ports:
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
                    if provider_calls >= self.settings.ferry_timetable_collection_max_provider_calls:
                        # 이후 날짜에 이미 저장된 시간표도 재사용/잔여 집계에 포함한다.
                        # 예산 소진은 외부 요청만 중단하며 저장 범위 확인은 끝까지 한다.
                        continue
                    if last_call_at is not None:
                        elapsed = (now_utc() - last_call_at).total_seconds()
                        wait_seconds = self.settings.ferry_timetable_collection_interval_seconds - elapsed
                        if wait_seconds > 0:
                            await asyncio.sleep(wait_seconds)
                    # 실패도 동일 호출 예산에 포함한다. 한 항구의 일시적인 네트워크 실패가
                    # 전체 누락 보충을 막지 않게 하되 연속 3회면 중단하고 재시도하지 않는다.
                    provider_calls += 1
                    try:
                        operations = await client.get_domestic_ship_operations(
                            departure_port_id=port.port_id,
                            departure_date=service_date,
                        )
                    except KricNetworkError:
                        failed_provider_calls += 1
                        consecutive_network_failures += 1
                        if consecutive_network_failures >= 3:
                            raise
                        continue
                    finally:
                        last_call_at = now_utc()
                    consecutive_network_failures = 0
                    items = [_ferry_operation_payload(item) for item in operations]
                    operation_count += len(items)
                    await _upsert_ferry_timetable_snapshot(
                        session,
                        source=port.source,
                        departure_port_id=port.port_id,
                        service_date=service_date,
                        collected_at=now_utc(),
                        items_json=items,
                    )
                    # 호출 하나의 성공 결과를 즉시 durable하게 만든다. 이후 호출이 실패해도
                    # 이미 채운 항구·운항일은 API가 DB에서 반환할 수 있다.
                    await session.commit()
        deferred_snapshot_count = len(ports) * len(service_dates) - reused - provider_calls + failed_provider_calls
        return {
            "port_count": len(ports),
            "service_date_count": len(service_dates),
            "provider_calls": provider_calls,
            "failed_provider_calls": failed_provider_calls,
            "reused_snapshot_count": reused,
            "operation_count": operation_count,
            "deferred_snapshot_count": deferred_snapshot_count,
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
        _guidelines, archive = await self._fetch_port_guidelines()
        # 항만가이드라인은 항로 안내 자료로만 보관한다. 어느 한 점도 승선 항구로 쓰지 않는다.
        locations: dict[str, tuple[PortCall | None, bool]] = {}
        async with self._maritime_client_factory(key, timeout=self.settings.api_timeout_seconds) as client:
            # 공공데이터 호출량을 예측 가능하게 유지하려고 동시에 세 요청을 보내지 않는다.
            # Provider iterator는 page budget을 넘기면 오류로 끝나므로 첫 페이지 하나만
            # 성공으로 저장하는 일을 막는다. 실시간 운항시간표에는 사용하지 않는다.
            ports = tuple([item async for item in client.iter_ports(page_size=100, max_pages=20)])
            terminals = tuple([item async for item in client.iter_ferry_terminals(page_size=100, max_pages=20)])
            ship_types = tuple([item async for item in client.iter_ferry_ship_types(page_size=100, max_pages=20)])
            for port in ports:
                target = PORT_CALL_TARGETS.get(port.port_id or "")
                if target and port.port_name == target[0]:
                    locations[port.port_id] = await self._port_call_location(session, run_id, client, port.port_id, target)
            for port in ports:
                if port.port_id:
                    location, verified = locations.get(port.port_id, (None, False))
                    await self._upsert_port(session, port, collected_at, location, location_verified=verified)
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
            "port_location_count": sum(location is not None for location, _verified in locations.values()),
            "port_location_deferred_count": sum(not verified for _location, verified in locations.values()),
            "port_guideline_object_stored": int(archive is not None),
            "port_location_failed_calls": int(await session.scalar(select(func.count()).select_from(RawApiResponse).where(
                RawApiResponse.collection_run_id == run_id, RawApiResponse.source == PORT_CALL_SOURCE,
                RawApiResponse.parse_status == "failed",
            )) or 0),
        }

    async def _port_call_location(
        self, session: AsyncSession, run_id: int, client: DataGoKrMaritimeClient,
        port_id: str, target: tuple[str, str],
    ) -> tuple[PortCall | None, bool]:
        """좌표와 정상 재검증 여부를 반환한다. 실패/유예와 정상 무결과를 구분한다."""
        endpoint = f"komsa:port-call:{port_id}"
        # 예약과 예산 검사만 잠근다. 네트워크 대기 중 트랜잭션을 잡고 있지 않는다.
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            await session.execute(text("SELECT pg_advisory_xact_lock(420052)"))
        previous = await session.scalar(select(RawApiResponse).where(
            RawApiResponse.source == PORT_CALL_SOURCE, RawApiResponse.endpoint == endpoint,
        ).order_by(RawApiResponse.received_at.desc(), RawApiResponse.id.desc()).limit(1))
        now = now_utc()
        if previous is not None:
            received = previous.received_at.replace(tzinfo=UTC) if previous.received_at.tzinfo is None else previous.received_at
            ttl = timedelta(days=30 if previous.parse_status == "success" else 1)
            if now - received < ttl and previous.request_params_json == {"name": target[0], "province": target[1]}:
                await session.commit()
                if previous.parse_status == "success":
                    data = json.loads(previous.body_text)["selected"]
                    return (_unique_port_call((PortCall(**data),), target) if data else None), True
                return None, False
        # 제공자 한도는 같은 키의 다른 소비자도 사용한다. 한 번 한도에 도달하면
        # 개별 항구 캐시와 무관하게 이 서비스의 신규 요청을 24시간 유예한다.
        limited = await session.scalar(select(RawApiResponse.id).where(
            RawApiResponse.source == PORT_CALL_SOURCE,
            RawApiResponse.parse_status == "failed",
            RawApiResponse.parse_error == "KricRateLimitError",
            RawApiResponse.received_at >= now - timedelta(days=1),
        ).limit(1))
        if limited is not None:
            await session.commit()
            return None, False
        attempts = await session.scalar(select(func.count()).select_from(RawApiResponse).where(
            RawApiResponse.source == PORT_CALL_SOURCE, RawApiResponse.received_at >= now - timedelta(days=1),
        ))
        if (attempts or 0) >= 80:
            await session.commit()
            return None, False
        reservation = RawApiResponse(collection_run_id=run_id, source=PORT_CALL_SOURCE, endpoint=endpoint,
            request_params_json={"name": target[0], "province": target[1]}, status_code=0,
            body_text="null", received_at=now, parse_status="pending", parse_error=None)
        session.add(reservation)
        await session.commit()
        try:
            candidates = await client.get_port_calls(name=target[0], province=target[1])
            location = _unique_port_call(candidates, target)
            selected = {
                "port_code": location.port_code, "port_name": location.port_name,
                "province_code": location.province_code, "province_name": location.province_name,
                "district_name": location.district_name, "latitude": location.latitude,
                "longitude": location.longitude, "raw": dict(location.raw),
            } if location else None
            reservation.body_text = json.dumps({"selected": selected, "candidates": [dict(item.raw) for item in candidates]}, ensure_ascii=False)
            reservation.status_code = 200
            reservation.parse_status = "success"
            await session.commit()
            return location, True
        except Exception as exc:
            # 기본 항구/시간표 수집은 계속한다. 서비스키가 들어간 예외 문자열은 저장하지 않는다.
            reservation.parse_status = "failed"
            reservation.parse_error = type(exc).__name__
            await session.commit()
            logger.warning("port call lookup failed port_id=%s error_type=%s", port_id, type(exc).__name__)
            return None, False

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
        location: PortCall | None,
        *, location_verified: bool = False,
    ) -> None:
        assert item.port_id is not None
        row = await session.scalar(
            select(FerryPort).where(FerryPort.source == MARITIME_SOURCE, FerryPort.port_id == item.port_id)
        )
        values = {
            "port_name": item.port_name, "last_seen_at": collected_at, "raw_item_json": dict(item.raw),
        }
        if location is not None:
            values.update(latitude=location.latitude, longitude=location.longitude,
                          location_source=PORT_CALL_SOURCE, location_point_count=1)
            values["raw_item_json"]["_komsa_port_call"] = dict(location.raw)
        elif location_verified or row is None or row.location_source == PORT_GUIDELINE_SOURCE or row.port_name != item.port_name:
            # 정상 재검증의 무결과/중복/부적합 좌표는 연결 해제한다. 일시 장애만 기존 값을 보존한다.
            values.update(latitude=None, longitude=None, location_source=None, location_point_count=0)
        elif row.raw_item_json and "_komsa_port_call" in row.raw_item_json:
            values["raw_item_json"]["_komsa_port_call"] = row.raw_item_json["_komsa_port_call"]
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


async def _upsert_ferry_timetable_snapshot(
    session: AsyncSession,
    *,
    source: str,
    departure_port_id: str,
    service_date: Any,
    collected_at: Any,
    items_json: list[dict[str, str | None]],
) -> None:
    """API lazy fill과 Dagster가 경합해도 항구·운항일당 한 스냅샷만 남긴다."""
    values = {
        "source": source,
        "departure_port_id": departure_port_id,
        "service_date": service_date,
        "collected_at": collected_at,
        "items_json": items_json,
    }
    dialect_name = session.bind.dialect.name if session.bind is not None else ""
    if dialect_name == "postgresql":
        statement = postgresql_insert(FerryTimetableSnapshot).values(**values)
    elif dialect_name == "sqlite":
        statement = sqlite_insert(FerryTimetableSnapshot).values(**values)
    else:
        raise RuntimeError(f"unsupported ferry timetable database dialect: {dialect_name}")
    statement = statement.on_conflict_do_update(
        index_elements=["source", "departure_port_id", "service_date"],
        set_={
            "collected_at": statement.excluded.collected_at,
            "items_json": statement.excluded.items_json,
        },
    )
    await session.execute(statement)


def _unique_port_call(candidates: tuple[PortCall, ...], target: tuple[str, str]) -> PortCall | None:
    """지역·이름 정확 일치 한 건만 허용한다. 동명·중복은 임의 대표점으로 합치지 않는다."""
    matches = [item for item in candidates if (item.port_name, item.province_name) == target]
    if len(matches) != 1:
        return None
    item = matches[0]
    if item.latitude is None or item.longitude is None or not (32 <= item.latitude <= 39.5 and 124 <= item.longitude <= 132):
        return None
    return item
