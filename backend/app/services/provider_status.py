"""수집 작업 전체의 읽기 전용 운영 목록. 설정과 실행 성공을 구분한다."""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc, to_seoul
from app.models import CollectionRun, FerryPort, FerryTimetableSnapshot, TransportCollectionState
from app.schemas import ProviderCollectionStatus, ProviderStatusResponse


async def provider_status(session: AsyncSession, settings: Settings) -> ProviderStatusResponse:
    transport = settings.transport_collection_enabled
    keyed = bool(settings.data_go_kr_service_key)
    catalog = [
        ("kac_parking", "한국공항공사 주차", "airport_collection_job", "dagster_airport", keyed, settings.collect_interval_seconds),
        ("incheon_parking", "인천공항 주차", "airport_collection_job", "dagster_airport", keyed and settings.enable_incheon_collection, settings.collect_interval_seconds),
        ("kac_fee", "한국공항공사 주차요금", "airport_collection_job", "dagster_airport", keyed and settings.enable_fee_collection, settings.collect_interval_seconds),
        ("incheon_fee", "인천공항 주차요금", "airport_collection_job", "dagster_airport", keyed and settings.enable_incheon_fee_collection, settings.collect_interval_seconds),
        ("krex_traffic_flow", "고속도로 소통", "highway_collection_job", "transport_dagster_highway", transport and bool(settings.kex_ex_api_key), settings.transport_collect_interval_seconds),
        ("krex_traffic_incident", "고속도로 돌발", "highway_collection_job", "transport_dagster_highway", transport and bool(settings.kex_ex_api_key), settings.transport_collect_interval_seconds),
        ("opinet_browser", "오피넷 주유소·유가", "fuel_collection_job", "transport_dagster_fuel", transport and settings.opinet_browser_enabled, 28800),
        ("kric_public_file", "KRIC 역·노선 파일", "rail_reference_collection_job", "dagster_rail", settings.rail_reference_collection_enabled, 172800),
        ("data_go_kr_maritime", "여객항구·선종", "maritime_reference_collection_job", "dagster_maritime", keyed and settings.maritime_reference_collection_enabled, 259200),
        ("ferry_timetable", "여객선 10일 운항시간표", "ferry_timetable_collection_job", "dagster_ferry_timetable", keyed and settings.ferry_timetable_collection_enabled, 14400),
        ("data_go_kr_tago", "TAGO 고속·시외버스 터미널", "bus_reference_collection_job", "dagster_bus_reference", keyed and settings.bus_reference_collection_enabled, 259200),
    ]
    triggers = {row[3] for row in catalog}
    ranked = select(CollectionRun.id, func.row_number().over(partition_by=CollectionRun.trigger, order_by=(CollectionRun.started_at.desc(), CollectionRun.id.desc())).label("rank")).where(CollectionRun.trigger.in_(triggers), CollectionRun.status != "skipped").subquery()
    runs = (await session.scalars(select(CollectionRun).join(ranked, CollectionRun.id == ranked.c.id).where(ranked.c.rank == 1))).all()
    by_trigger = {row.trigger: row for row in runs}
    successes = dict((await session.execute(select(CollectionRun.trigger, func.max(CollectionRun.finished_at)).where(CollectionRun.trigger.in_(triggers), CollectionRun.status == "success").group_by(CollectionRun.trigger))).all())
    states = {row.source: row for row in (await session.scalars(select(TransportCollectionState))).all()}
    items = []
    for source, name, job, trigger, enabled, interval in catalog:
        run, state = by_trigger.get(trigger), states.get(source)
        last_success = state.last_success_at if state else successes.get(trigger)
        last_started = state.last_started_at if state else run.started_at if run else None
        failed = bool(state.last_error) if state else bool(run and run.status in {"failed", "failure", "partial", "partial_success"})
        status = "disabled" if not enabled else "failed" if failed else run.status if run else "not_collected"
        # 공항은 같은 job을 공유한다. job 성공을 개별 provider 성공으로 단정하지 않는다.
        if source in {"kac_parking", "incheon_parking", "kac_fee", "incheon_fee"} and enabled:
            status = "shared_job_" + status
        items.append(ProviderCollectionStatus(source=source, name=name, job_name=job, enabled=enabled,
            status=status, interval_seconds=interval, last_started_at=serialize_utc(last_started) if last_started else None,
            last_success_at=serialize_utc(last_success) if last_success else None,
            next_due_at=serialize_utc(state.next_due_at) if state and state.next_due_at else None,
            error_code="collection_failed" if failed else None))
    for source, name, enabled in [("flights", "공항 출도착", keyed and settings.enable_flight_status_markers), ("bus_timetable", "TAGO 버스 시간표", keyed)]:
        items.append(ProviderCollectionStatus(source=source, name=name, mode="on_demand", enabled=enabled, status="on_demand" if enabled else "disabled"))
    for source, name in [("kric_timetable", "KRIC 역별 다음 열차"), ("seoulgokr", "서울 교통정보"), ("rest_area", "휴게소 기준정보")]:
        items.append(ProviderCollectionStatus(source=source, name=name, mode="unconnected", enabled=False, status="unconnected"))
    today = to_seoul(now_utc()).date()
    end = today + timedelta(days=settings.ferry_timetable_storage_days)
    ports = int(await session.scalar(select(func.count()).select_from(FerryPort).where(FerryPort.source == "data_go_kr_maritime")) or 0)
    stored = int(await session.scalar(select(func.count()).select_from(FerryTimetableSnapshot).join(FerryPort, (FerryPort.source == FerryTimetableSnapshot.source) & (FerryPort.port_id == FerryTimetableSnapshot.departure_port_id)).where(FerryTimetableSnapshot.service_date >= today, FerryTimetableSnapshot.service_date < end, FerryPort.source == "data_go_kr_maritime")) or 0)
    return ProviderStatusResponse(generated_at=now_utc(), items=items, ferry_window_start=today, ferry_window_end=end - timedelta(days=1), ferry_expected_snapshots=ports * settings.ferry_timetable_storage_days, ferry_stored_snapshots=stored)
