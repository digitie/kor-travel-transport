"""DB transaction 경계를 명시한 Dagster 수집 job 정의."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from dagster import DefaultScheduleStatus, Definitions, ScheduleDefinition, job, op

from app.core.config import Settings, get_settings
from app.db.session import create_engine_and_session_factory
from app.services.collection import CollectionService
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
    return asyncio.run(_collect_transport_in_one_loop(_settings(), scope))


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
    return asyncio.run(_run_with_session(settings, action))


@op
def collect_rail_reference() -> dict[str, Any]:
    return _collect_reference("rail")


@op
def collect_maritime_reference() -> dict[str, Any]:
    return _collect_reference("maritime")


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


definitions = Definitions(
    jobs=[
        airport_collection_job,
        highway_collection_job,
        fuel_collection_job,
        rail_reference_collection_job,
        maritime_reference_collection_job,
    ],
    schedules=[
        ScheduleDefinition(job=airport_collection_job, cron_schedule="*/5 * * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        ScheduleDefinition(job=highway_collection_job, cron_schedule="*/5 * * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        ScheduleDefinition(job=fuel_collection_job, cron_schedule="0 */8 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 매일 due를 평가하되 service가 마지막 성공 뒤 48시간 전에는 provider를 호출하지 않는다.
        ScheduleDefinition(job=rail_reference_collection_job, cron_schedule="0 3 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        ScheduleDefinition(job=maritime_reference_collection_job, cron_schedule="0 3 */3 * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
    ],
)
