"""DB transaction 경계를 명시한 Dagster 수집 job 정의."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from dagster import DefaultScheduleStatus, Definitions, Failure, ScheduleDefinition, job, op

from app.core.config import Settings, get_settings
from app.db.session import create_engine_and_session_factory
from app.services.collection import CollectionService
from app.services.bus_collection import BusReferenceCollectionService
from app.services.kric_collection import KricTimetableCollectionService
from app.services.rail_maritime_collection import RailMaritimeCollectionService
from app.services.transport_collection import CollectionScope, TransportCollectionService


async def _run_with_session(
    settings: Settings, action: Callable[..., Awaitable[dict[str, Any]]], *args: Any, **kwargs: Any
) -> dict[str, Any]:
    engine, session_factory = create_engine_and_session_factory(settings.database_url)
    try:
        async with session_factory() as session:
            result = await action(session, *args, **kwargs)
            await session.commit()
            return result
    except Exception:
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
def collect_airport_parking() -> dict[str, Any]:
    settings = _settings()
    return asyncio.run(_run_with_session(settings, CollectionService(settings).collect, trigger="dagster_airport"))


async def _collect_transport_in_one_loop(settings: Settings, scope: CollectionScope) -> dict[str, Any]:
    """HTTP client의 생성·수집·종료를 하나의 event loop에서 끝낸다."""
    service = TransportCollectionService(settings)
    try:
        return await _run_with_session(settings, service.collect, trigger=f"dagster_{scope}", scope=scope)
    finally:
        await service.close()


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
def collect_highway_transport() -> dict[str, Any]:
    return _collect_transport("highway")


@op
def collect_fuel_transport() -> dict[str, Any]:
    return _collect_transport("fuel")


def _collect_reference(kind: str) -> dict[str, Any]:
    settings = _settings()
    service = RailMaritimeCollectionService(settings)
    action = service.collect_rail_reference if kind == "rail" else service.collect_maritime_reference
    result = asyncio.run(_run_with_session(settings, action))
    if result.get("status") == "partial_success":
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
def collect_rail_reference() -> dict[str, Any]:
    return _collect_reference("rail")


@op
def collect_maritime_reference() -> dict[str, Any]:
    return _collect_reference("maritime")


@op
def collect_ferry_timetable() -> dict[str, Any]:
    return _collect_ferry_timetable()


@op
def collect_bus_reference() -> dict[str, Any]:
    return _collect_bus_reference()


@op
def collect_kric_timetable() -> dict[str, Any]:
    settings = _settings()
    return asyncio.run(_run_with_session(settings, KricTimetableCollectionService(settings).collect))


@job(tags={"kortraveltransport/run_group": "reference"})
def kric_timetable_collection_job() -> None:
    collect_kric_timetable()


@job(tags={"kortraveltransport/run_group": "parking"})
def airport_collection_job() -> None:
    collect_airport_parking()


@job(tags={"kortraveltransport/run_group": "highway"})
def highway_collection_job() -> None:
    collect_highway_transport()


@job(tags={"kortraveltransport/run_group": "fuel"})
def fuel_collection_job() -> None:
    collect_fuel_transport()


@job(tags={"kortraveltransport/run_group": "reference"})
def rail_reference_collection_job() -> None:
    collect_rail_reference()


@job(tags={"kortraveltransport/run_group": "reference"})
def maritime_reference_collection_job() -> None:
    collect_maritime_reference()


@job(tags={"kortraveltransport/run_group": "reference"})
def ferry_timetable_collection_job() -> None:
    collect_ferry_timetable()


@job(tags={"kortraveltransport/run_group": "reference"})
def bus_reference_collection_job() -> None:
    collect_bus_reference()


definitions = Definitions(
    jobs=[
        airport_collection_job,
        highway_collection_job,
        fuel_collection_job,
        rail_reference_collection_job,
        maritime_reference_collection_job,
        ferry_timetable_collection_job,
        bus_reference_collection_job,
        kric_timetable_collection_job,
    ],
    schedules=[
        ScheduleDefinition(job=airport_collection_job, cron_schedule="*/5 * * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        ScheduleDefinition(job=highway_collection_job, cron_schedule="*/5 * * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        ScheduleDefinition(job=fuel_collection_job, cron_schedule="0 */8 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 매일 due를 평가하되 service가 마지막 성공 뒤 48시간 전에는 provider를 호출하지 않는다.
        ScheduleDefinition(job=rail_reference_collection_job, cron_schedule="0 3 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        ScheduleDefinition(job=maritime_reference_collection_job, cron_schedule="0 3 */3 * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 한 run의 provider 호출 예산을 지키면서 오늘 포함 10일 범위의 초기 backfill을 재개한다.
        ScheduleDefinition(job=ferry_timetable_collection_job, cron_schedule="45 */4 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 매일 due를 평가하되 service가 마지막 성공 뒤 72시간 전에는 provider를 호출하지 않는다.
        ScheduleDefinition(job=bus_reference_collection_job, cron_schedule="30 3 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 실패·강제 종료도 포함해 마지막 시도부터 48시간 guard를 적용한다.
        ScheduleDefinition(job=kric_timetable_collection_job, cron_schedule="0 * * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
    ],
)
