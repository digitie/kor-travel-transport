"""TAGO 일반철도 역의 완결 전국 목록을 별도 source로 게시한다."""

from datetime import timedelta

from datagokr import DataGoKrClient
from sqlalchemy import select

from app.core.time_utils import now_utc, serialize_utc
from app.models import CollectionRun, RailStationReference, ReferenceExportState
from app.services.rail_station_mapping import lock_rail_station_reference_catalog
from app.services.reference_exports import mark_reference_failure, promote_reference

TAGO_TRAIN_SOURCE = "tago_train"
TAGO_TRAIN_SCOPE = "tago"
TRIGGER = "dagster_tago_rail_reference"


class GeneralRailReferenceCollectionService:
    def __init__(self, settings, *, client_factory=DataGoKrClient):
        self.settings = settings
        self.client_factory = client_factory

    async def collect(self, session):
        # API의 export import에서 Dagster를 로드하지 않고, 실제 수집에서만 소유권을 사용한다.
        from app.dagster.recovery import CollectionLeaseLost

        if not self.settings.rail_reference_collection_enabled or not self.settings.transport_map_current_enabled:
            return {"status": "skipped", "reason": "rail reference export is disabled"}
        if not self.settings.data_go_kr_service_key:
            return {"status": "skipped", "reason": "TAGO is unconfigured"}
        head = await session.get(ReferenceExportState, ("rail-station", TAGO_TRAIN_SCOPE))
        if head and now_utc() - serialize_utc(head.confirmed_at) < timedelta(hours=48):
            return {"status": "skipped", "reason": "TAGO rail reference is not due for 48 hours"}
        previous_count = len(head.member_ids) if head else 0
        await session.rollback()
        run = CollectionRun(trigger=TRIGGER, status="running", started_at=now_utc())
        session.add(run)
        await session.commit()
        run_id = run.id
        try:
            # 제공자 transport/TPS/파싱은 기존 SDK에 맡긴다. 네트워크 중 DB 연결을 보유하지 않는다.
            stations, city_count = await self._fetch()
            await lock_rail_station_reference_catalog(session)
            current = await session.scalar(select(ReferenceExportState).where(
                ReferenceExportState.kind == "rail-station", ReferenceExportState.scope_key == TAGO_TRAIN_SCOPE,
            ).with_for_update())
            denominator = max(previous_count, len(current.member_ids) if current else 0)
            if denominator and len(stations) < denominator * 0.25:
                raise ValueError("TAGO 역 급감 집합은 이전 승인 목록을 보존합니다")
            collected_at = now_utc()
            saved = {row.identity_key: row for row in (await session.scalars(select(RailStationReference).where(
                RailStationReference.source == TAGO_TRAIN_SOURCE,
            ))).all()}
            members = []
            for station_id, item in sorted(stations.items()):
                identity = TAGO_TRAIN_SOURCE + ":" + station_id
                row = saved.get(identity)
                if row is None:
                    row = RailStationReference(source=TAGO_TRAIN_SOURCE, identity_key=identity,
                                               first_seen_at=collected_at)
                    session.add(row)
                elif row.station_name != item["name"]:
                    row.latitude = row.longitude = None
                row.station_name = item["name"]
                row.station_number = station_id
                row.station_type = "일반철도"
                row.last_seen_at = collected_at
                row.raw_item_json = {"nodeid": station_id, "nodename": item["name"], "cities": item["cities"]}
                members.append(row)
            await session.flush()
            await promote_reference(session, kind="rail-station", scope=TAGO_TRAIN_SCOPE, run_id=run_id,
                confirmed_at=collected_at, member_ids=[row.id for row in members],
                proof={"complete": True, "item_count": len(members), "city_count": city_count,
                       "source": TAGO_TRAIN_SOURCE, "contract": "python-datagokr-api:tago-train:all-cities-v1"})
            run.status = "success"
            run.finished_at = now_utc()
            await session.commit()
            return {"status": "success", "run_id": run_id, "station_count": len(members), "city_count": city_count}
        except CollectionLeaseLost:
            await session.rollback()
            raise
        except BaseException as exc:
            await session.rollback()
            stored_run = await session.get(CollectionRun, run_id)
            await mark_reference_failure(session, kind="rail-station", scope=TAGO_TRAIN_SCOPE,
                                         run_id=run_id, error=type(exc).__name__)
            if stored_run is not None:
                stored_run.status = "failed"
                stored_run.finished_at = now_utc()
                stored_run.error_message = type(exc).__name__
            await session.commit()
            raise

    async def _fetch(self):
        from app.dagster.recovery import ensure_collection_owner_active

        stations = {}
        async with self.client_factory(api_key=self.settings.data_go_kr_service_key,
                                      timeout=self.settings.api_timeout_seconds, max_rps=1) as client:
            ensure_collection_owner_active()
            page = await client.train.city_list()
            cities = {row.city_code: row.city_name for row in page.items}
            if (not cities or len(cities) != len(page.items) or page.total_count != len(cities)
                    or len(cities) > 100 or any(not code or not name for code, name in cities.items())):
                raise ValueError("TAGO 지역 목록이 완결되지 않았습니다")
            for code, name in sorted(cities.items()):
                ensure_collection_owner_active()
                page = await client.train.station_list(city_code=code, num_of_rows=1000)
                if page.total_count is None or page.total_count != len(page.items) or len(page.items) > 1000:
                    raise ValueError("TAGO 지역별 역 목록이 완결되지 않았습니다")
                city_ids = set()
                for row in page.items:
                    if (not row.station_id or len(row.station_id) > 80 or not row.station_name
                            or len(row.station_name) > 160 or row.station_id in city_ids):
                        raise ValueError("TAGO 역 식별자·역명·중복을 확인해야 합니다")
                    city_ids.add(row.station_id)
                    item = stations.setdefault(row.station_id, {"name": row.station_name, "cities": []})
                    if item["name"] != row.station_name:
                        raise ValueError("TAGO 동일 역 코드의 역명이 다릅니다")
                    item["cities"].append({"code": code, "name": name, "raw": dict(row.raw)})
            if not stations or len(stations) > 10000:
                raise ValueError("TAGO 전국 역 수량을 확인해야 합니다")
        return stations, len(cities)
