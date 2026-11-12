"""KRIC 일반철도·KTX 공개 역 목록을 별도 source로 완결 게시한다."""

from dataclasses import asdict
from datetime import timedelta

from kric import KricGeneralStationClient
from sqlalchemy import select

from app.core.time_utils import now_utc, serialize_utc
from app.models import CollectionRun, RailStationReference, ReferenceExportState
from app.services.rail_locations import preserve_rail_address_location
from app.services.rail_station_mapping import lock_rail_station_reference_catalog
from app.services.reference_exports import mark_reference_failure, promote_reference

KRIC_GENERAL_SOURCE = "kric_general_portal"
KRIC_GENERAL_SCOPE = "kric-general"
TRIGGER = "dagster_kric_general_reference"


class GeneralRailReferenceCollectionService:
    def __init__(self, settings, *, client_factory=KricGeneralStationClient):
        self.settings = settings
        self.client_factory = client_factory

    async def collect(self, session):
        # API의 export import에서 Dagster를 로드하지 않고, 실제 수집에서만 소유권을 사용한다.
        from app.dagster.recovery import CollectionLeaseLost

        if not self.settings.rail_reference_collection_enabled or not self.settings.transport_map_current_enabled:
            return {"status": "skipped", "reason": "rail reference export is disabled"}
        head = await session.get(ReferenceExportState, ("rail-station", KRIC_GENERAL_SCOPE))
        if head and now_utc() - serialize_utc(head.confirmed_at) < timedelta(hours=48):
            return {"status": "skipped", "reason": "KRIC general rail reference is not due for 48 hours"}
        previous_count = len(head.member_ids) if head else 0
        await session.rollback()
        run = CollectionRun(trigger=TRIGGER, status="running", started_at=now_utc())
        session.add(run)
        await session.commit()
        run_id = run.id
        try:
            # 제공자 transport/TPS/파싱은 기존 SDK에 맡긴다. 네트워크 중 DB 연결을 보유하지 않는다.
            stations = await self._fetch()
            await lock_rail_station_reference_catalog(session)
            current = await session.scalar(select(ReferenceExportState).where(
                ReferenceExportState.kind == "rail-station", ReferenceExportState.scope_key == KRIC_GENERAL_SCOPE,
            ).with_for_update())
            denominator = max(previous_count, len(current.member_ids) if current else 0)
            if denominator and len(stations) < denominator * 0.25:
                raise ValueError("KRIC 일반철도 역 급감 집합은 이전 승인 목록을 보존합니다")
            collected_at = now_utc()
            saved = {row.identity_key: row for row in (await session.scalars(select(RailStationReference).where(
                RailStationReference.source == KRIC_GENERAL_SOURCE,
            ))).all()}
            members = []
            for station_id, item in sorted(stations.items()):
                identity = KRIC_GENERAL_SOURCE + ":" + station_id
                row = saved.get(identity)
                if row is None:
                    row = RailStationReference(source=KRIC_GENERAL_SOURCE, identity_key=identity,
                                               first_seen_at=collected_at)
                    session.add(row)
                row.station_name = item.station_name
                # 이 코드는 공식 연결된 코레일 코드이며 KRIC 도시철도 stinCd가 아니다.
                row.station_number = item.station_code
                row.operating_line_name = ", ".join(item.route_labels) or None
                row.station_type = ", ".join(item.station_kinds) or None
                row.road_address = item.address
                values = {"station_name": item.station_name, "road_address": item.address, "lot_address": None,
                          "latitude": item.latitude, "longitude": item.longitude,
                          "raw_item_json": {**asdict(item), "coordinate_source": "korail_public_link" if item.latitude is not None else None}}
                preserve_rail_address_location(row, values)
                row.latitude, row.longitude = values["latitude"], values["longitude"]
                row.last_seen_at = collected_at
                row.raw_item_json = values["raw_item_json"]
                members.append(row)
            await session.flush()
            await promote_reference(session, kind="rail-station", scope=KRIC_GENERAL_SCOPE, run_id=run_id,
                confirmed_at=collected_at, member_ids=[row.id for row in members],
                proof={"complete": True, "item_count": len(members),
                       "directory_row_count": sum(len(s.directory_rows) for s in stations.values()),
                       "source": KRIC_GENERAL_SOURCE, "contract": "python-kric-api:general-and-ktx-directory-v1"})
            run.status = "success"
            run.finished_at = now_utc()
            await session.commit()
            return {"status": "success", "run_id": run_id, "station_count": len(members)}
        except CollectionLeaseLost:
            await session.rollback()
            raise
        except BaseException as exc:
            await session.rollback()
            stored_run = await session.get(CollectionRun, run_id)
            await mark_reference_failure(session, kind="rail-station", scope=KRIC_GENERAL_SCOPE,
                                         run_id=run_id, error=type(exc).__name__)
            if stored_run is not None:
                stored_run.status = "failed"
                stored_run.finished_at = now_utc()
                stored_run.error_message = type(exc).__name__
            await session.commit()
            raise

    async def _fetch(self):
        from app.dagster.recovery import ensure_collection_owner_active

        async with self.client_factory(timeout=self.settings.api_timeout_seconds,
                                       before_request=ensure_collection_owner_active) as client:
            ensure_collection_owner_active()
            rows = await client.get_general_stations()
        if not rows or len(rows) > 10000:
            raise ValueError("KRIC 일반철도 전국 목록이 완결되지 않았습니다")
        stations = {}
        for item in rows:
            if (not item.reference_id or len(item.reference_id) > 300 or item.reference_id in stations
                    or not item.station_name or len(item.station_name) > 160
                    or item.station_code is not None and len(item.station_code) > 80
                    or len(", ".join(item.route_labels)) > 160 or len(", ".join(item.station_kinds)) > 80
                    or item.address is not None and len(item.address) > 300
                    or not item.directory_rows):
                raise ValueError("KRIC 일반철도 역 식별자·필드·완결성을 확인해야 합니다")
            stations[item.reference_id] = item
        return stations
