"""DB transaction 경계를 명시한 Dagster 수집 job 정의."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from dagster import DefaultScheduleStatus, Definitions, Failure, multiprocess_executor, job, op
from kortravelcommon.dagster import RecoveryPolicy, coalescing_schedule, reconciliation_sensor

from app.dagster.recovery import OWNER, collection_owner, owned_session_factory, reconcile_collection_runs

from app.core.config import Settings, get_settings
from app.db.session import create_engine_and_session_factory
from app.services.collection import CollectionService
from app.services.bus_collection import BusReferenceCollectionService
from app.services.kric_collection import KricTimetableCollectionService
from app.services.kakao_place_locations import KakaoPlaceCollectionService
from app.services.place_locations import PlaceLocationCollectionService
from app.services.rail_maritime_collection import RailMaritimeCollectionService
from app.services.rest_area_collection import RestAreaCollectionService
from app.services.transport_collection import CollectionScope, TransportCollectionService

#: 실행 상한(초). 공용 Dagster instance의 전역 상한(6시간, Manager `config/dagster-shared/dagster.yaml`)은
#: 다른 테넌트의 값이라, 옛 전용 instance의 상한(4시간 — 유가 Playwright 수집의 정상 상한 2시간에 여유를 둔
#: 값)을 job마다 tag로 단다. run monitoring이 이 tag를 읽어 넘긴 run을 실패로 끝낸다.
MAX_RUNTIME_SECONDS = 14400


def _job_tags(run_group: str, job_name: str) -> dict[str, str]:
    # provider 호출 실패는 자동 반복하지 않는다. 안전한 관측/기준 upsert만 인프라 재시도한다.
    idempotent = job_name in {"airport_collection_job", "highway_collection_job", "rest_area_reference_collection_job"}
    tags = RecoveryPolicy(MAX_RUNTIME_SECONDS, idempotent=idempotent,
                          infrastructure_retries=1 if idempotent else 0).tags(
                              project="transport", job_name=job_name)
    return {**tags, "kortraveltransport/run_group": run_group,
            "dagster/code_location": "kor-travel-transport"}


async def _run_with_session(
    settings: Settings, action: Callable[..., Awaitable[dict[str, Any]]], *args: Any, **kwargs: Any
) -> dict[str, Any]:
    engine, session_factory = create_engine_and_session_factory(settings.database_url, collector=True)
    if OWNER.get() is not None:
        session_factory = owned_session_factory(engine, OWNER.get())
    try:
        async with session_factory() as session:
            try:
                # async provider는 cancellation 계약을 사용한다. native monitoring보다 먼저 끝낸다.
                async with asyncio.timeout(MAX_RUNTIME_SECONDS - 60):
                    result = await action(session, *args, **kwargs)
                    await session.commit()
                    return result
            except BaseException:
                await session.rollback()
                raise
    finally:
        await engine.dispose()


def _settings() -> Settings:
    settings = get_settings()
    if settings.scheduler_mode != "dagster":
        raise RuntimeError("Dagster code-server requires SCHEDULER_MODE=dagster")
    return settings


@op
def collect_airport_parking(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, CollectionService(settings).collect, trigger="dagster_airport"))
        if result.get("status") in {"failed", "partial_success"}:
            raise Failure(description="공항 수집의 성공분은 저장했지만 일부 수집이 실패했습니다.",
                          metadata={"run_id": result["run_id"], "status": result["status"]}, allow_retries=False)
        return result


async def _collect_transport_in_one_loop(settings: Settings, scope: CollectionScope) -> dict[str, Any]:
    """HTTP client의 생성·수집·종료를 하나의 event loop에서 끝낸다."""
    service = TransportCollectionService(settings)
    try:
        return await _run_with_session(settings, service.collect, trigger=f"dagster_{scope}", scope=scope)
    finally:
        await asyncio.wait_for(service.close(), timeout=10)


def _collect_transport(scope: CollectionScope) -> dict[str, Any]:
    result = asyncio.run(_collect_transport_in_one_loop(_settings(), scope))
    # 성공분·실패 상태를 커밋하고 provider를 닫은 뒤 Dagster에도 실패를 전달한다.
    # 응답 원문을 복제하지 않으며 기존 호출 유예를 자동 재시도로 우회하지 않는다.
    if result.get("status") in {"failed", "partial_success"}:
        raise Failure(
            description="교통정보 수집에 실패했습니다. 저장된 성공분과 호출 유예는 유지합니다.",
            metadata={"run_id": result["run_id"], "status": result["status"], "scope": scope},
            allow_retries=False,
        )
    return result


@op
def collect_highway_transport(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        return _collect_transport("highway")


@op
def collect_fuel_transport(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        return _collect_transport("fuel")


def _collect_reference(kind: str) -> dict[str, Any]:
    settings = _settings()
    service = RailMaritimeCollectionService(settings)
    action = service.collect_rail_reference if kind == "rail" else service.collect_maritime_reference
    result = asyncio.run(_run_with_session(settings, action))
    if result.get("status") == "partial_success" and kind != "maritime":
        raise Failure(description="항구 기준정보는 저장했지만 일부 기항지 위치 조회가 실패하거나 유예됐습니다.",
                      metadata={"run_id": result["run_id"], "failed_provider_calls": result["port_location_failed_calls"],
                                "deferred_port_locations": result.get("port_location_deferred_count", 0)},
                      allow_retries=False)
    return result


def _collect_ferry_timetable() -> dict[str, Any]:
    settings = _settings()
    service = RailMaritimeCollectionService(settings)
    result = asyncio.run(_run_with_session(settings, service.collect_ferry_timetables))
    # 성공분과 partial_success 기록이 커밋된 뒤 실행 상태도 실패로 전달한다.
    # 외부 호출 보호를 위해 Dagster 자동 재시도는 허용하지 않는다.
    if result.get("status") == "partial_success":
        raise Failure(
            description="일부 배편 수집에 실패했습니다. 저장된 성공분은 유지하며 다음 정기 수집에서 보충합니다.",
            metadata={"run_id": result["run_id"], "failed_provider_calls": result["failed_provider_calls"]},
            allow_retries=False,
        )
    return result


def _collect_bus_reference() -> dict[str, Any]:
    settings = _settings()
    return asyncio.run(
        _run_with_session(settings, BusReferenceCollectionService(settings).collect)
    )


@op
def collect_rail_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        return _collect_reference("rail")


@op
def collect_maritime_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        return _collect_reference("maritime")


@op
def collect_ferry_timetable(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        return _collect_ferry_timetable()


@op
def collect_bus_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        return _collect_bus_reference()


@op
def collect_place_locations(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, PlaceLocationCollectionService(settings).collect))
        if result.get("status") == "partial_success":
            raise Failure(description="장소 위치 조회가 유예되거나 실패했습니다. 성공분은 저장했습니다.",
                          metadata={"run_id": result["run_id"], "deferred": result["deferred"]},
                          allow_retries=False)
        return result


@op
def collect_kakao_place_locations(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, KakaoPlaceCollectionService(settings).collect))
        if result.get("status") == "partial_success":
            raise Failure(description="카카오 장소 위치 조회가 유예되거나 실패했습니다. 성공분은 저장했습니다.",
                          metadata={"run_id": result["run_id"], "deferred": result["deferred"]},
                          allow_retries=False)
        return result


@op
def enrich_new_reference_locations(context, reference_result: dict[str, Any]) -> dict[str, Any]:
    with collection_owner(context.run_id):
        """공식 기준정보 적재 직후 기존 수집기의 호출 예산·receipt를 그대로 사용한다."""
        settings = _settings()
        results: dict[str, dict[str, Any]] = {}
        for name, service in (("vworld", PlaceLocationCollectionService), ("kakao", KakaoPlaceCollectionService)):
            try:
                results[name] = asyncio.run(_run_with_session(settings, service(settings).collect))
            except Exception as exc:
                # 한 제공기관의 장애가 다른 제공기관의 독립된 호출 예산을 막지 않는다.
                results[name] = {"status": "failed", "error_type": type(exc).__name__}
        vworld, kakao = results["vworld"], results["kakao"]
        if reference_result.get("status") == "partial_success" or any(
            result.get("status") in ("partial_success", "failed") for result in (vworld, kakao)
        ):
            raise Failure(description="기준정보와 장소 좌표 보강의 성공분은 저장했지만 일부 조회가 실패하거나 유예됐습니다.",
                          metadata={"reference_run_id": reference_result.get("run_id", ""),
                                    "reference_failed_calls": reference_result.get("port_location_failed_calls", 0),
                                    "reference_deferred": reference_result.get("port_location_deferred_count", 0),
                                    "vworld_run_id": vworld.get("run_id", ""),
                                    "kakao_run_id": kakao.get("run_id", ""),
                                    "vworld_status": vworld.get("status", ""),
                                    "kakao_status": kakao.get("status", "")}, allow_retries=False)
        return {"reference_status": reference_result.get("status"), "vworld": vworld, "kakao": kakao}


@op
def collect_kric_timetable(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        settings = _settings()
        return asyncio.run(_run_with_session(settings, KricTimetableCollectionService(settings).collect))


@op
def collect_rest_area_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        settings = _settings()
        return asyncio.run(_run_with_session(settings, RestAreaCollectionService(settings).collect_references))


@op
def collect_rest_area_fuel_prices(context) -> dict[str, Any]:
    with collection_owner(context.run_id):
        settings = _settings()
        return asyncio.run(_run_with_session(settings, RestAreaCollectionService(settings).collect_fuel_prices))


@job(tags=_job_tags("reference", "rest_area_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def rest_area_reference_collection_job() -> None:
    collect_rest_area_reference()


@job(tags=_job_tags("reference", "rest_area_fuel_price_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def rest_area_fuel_price_collection_job() -> None:
    collect_rest_area_fuel_prices()


@job(tags=_job_tags("reference", "kric_timetable_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def kric_timetable_collection_job() -> None:
    collect_kric_timetable()


@job(tags=_job_tags("parking", "airport_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def airport_collection_job() -> None:
    collect_airport_parking()


@job(tags=_job_tags("highway", "highway_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def highway_collection_job() -> None:
    collect_highway_transport()


@job(tags=_job_tags("fuel", "fuel_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def fuel_collection_job() -> None:
    collect_fuel_transport()


@job(tags=_job_tags("reference", "rail_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def rail_reference_collection_job() -> None:
    collect_rail_reference()


@job(tags=_job_tags("reference", "maritime_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def maritime_reference_collection_job() -> None:
    enrich_new_reference_locations(collect_maritime_reference())


@job(tags=_job_tags("reference", "ferry_timetable_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def ferry_timetable_collection_job() -> None:
    collect_ferry_timetable()


@job(tags=_job_tags("reference", "bus_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def bus_reference_collection_job() -> None:
    enrich_new_reference_locations(collect_bus_reference())


@job(tags=_job_tags("reference", "place_location_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def place_location_collection_job() -> None:
    collect_place_locations()


@job(tags=_job_tags("reference", "kakao_place_location_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def kakao_place_location_collection_job() -> None:
    collect_kakao_place_locations()


async def _reconcile_workers(instance) -> int:
    engine, factory = create_engine_and_session_factory(_settings().database_url, collector=True)
    try:
        return await reconcile_collection_runs(factory, instance)
    finally:
        await engine.dispose()


def _reconcile_tick(context) -> int:
    return asyncio.run(_reconcile_workers(context.instance))


worker_recovery = reconciliation_sensor(name="transport_worker_recovery", reconcile=_reconcile_tick,
                                       required_resource_keys=set())


definitions = Definitions(
    sensors=[worker_recovery],
    jobs=[
        airport_collection_job,
        highway_collection_job,
        fuel_collection_job,
        rail_reference_collection_job,
        maritime_reference_collection_job,
        ferry_timetable_collection_job,
        bus_reference_collection_job,
        place_location_collection_job,
        kakao_place_location_collection_job,
        kric_timetable_collection_job,
        rest_area_reference_collection_job,
        rest_area_fuel_price_collection_job,
    ],
    schedules=[
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=airport_collection_job, cron_schedule="*/5 * * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=highway_collection_job, cron_schedule="*/5 * * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=fuel_collection_job, cron_schedule="0 */8 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 매일 due를 평가하되 service가 마지막 성공 뒤 48시간 전에는 provider를 호출하지 않는다.
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=rail_reference_collection_job, cron_schedule="0 3 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=maritime_reference_collection_job, cron_schedule="0 3 */3 * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 한 run의 provider 호출 예산을 지키면서 오늘 포함 10일 범위의 초기 backfill을 재개한다.
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=ferry_timetable_collection_job, cron_schedule="45 */4 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 매일 due를 평가하되 service가 마지막 성공 뒤 72시간 전에는 provider를 호출하지 않는다.
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=bus_reference_collection_job, cron_schedule="30 3 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=place_location_collection_job, cron_schedule="30 4 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=kakao_place_location_collection_job, cron_schedule="30 6 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 실패·강제 종료도 포함해 마지막 시도부터 48시간 guard를 적용한다.
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=kric_timetable_collection_job, cron_schedule="0 * * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 휴게소 기준정보는 저변동(약 200행·1회 호출)이라 하루 한 번, 유가는 4시간마다 갱신한다(ADR-013).
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=rest_area_reference_collection_job, cron_schedule="40 3 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=rest_area_fuel_price_collection_job, cron_schedule="25 */4 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
    ],
)
