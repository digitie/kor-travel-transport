"""DB transaction 경계를 명시한 Dagster 수집 job 정의."""

from __future__ import annotations

import asyncio
import functools
import sys
import traceback
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, unquote

from dagster import (
    DagsterExecutionInterruptedError, DefaultScheduleStatus, Definitions, Failure, multiprocess_executor, job, op,
)
from sqlalchemy.engine import make_url
from kortravelcommon.dagster import RecoveryPolicy, coalescing_schedule, infrastructure_retry_sensor, reconciliation_sensor

from app.dagster.recovery import (
    OWNER, CollectionLeaseLost, collection_owner, ensure_collection_owner_active,
    owned_session_factory, reconcile_collection_runs,
)

from app.core.config import Settings, get_settings
from app.db.session import create_engine_and_session_factory
from app.services.collection import CollectionService
from app.services.flight_status import sanitize_upstream_error
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


#: Failure 설명의 상한(응답 본문 같은 긴 문장을 공용 event log에 그대로 두지 않는다).
MAX_FAILURE_DESCRIPTION_CHARS = 2000
#: metadata `frames`에 남기는 frame 수.
MAX_FAILURE_FRAMES = 50
#: 그대로 통과시키는 중단 신호. 나머지 BaseException(CancelledError·BaseExceptionGroup 등)은 가린다.
_PASSTHROUGH_ERRORS = (KeyboardInterrupt, SystemExit, DagsterExecutionInterruptedError)


def _secret_forms() -> list[str]:
    """가릴 비밀값의 원문·URL 디코딩형·인코딩형·이중 인코딩형(긴 것부터)."""
    try:
        settings = get_settings()
        secrets = [settings.data_go_kr_service_key, settings.kric_service_key, settings.kex_ex_api_key,
                   settings.vworld_api_key, settings.kakao_rest_api_key, settings.rustfs_secret_access_key,
                   settings.transport_admin_write_token, settings.transport_service_export_token]
        try:
            secrets.append(make_url(settings.database_url).password)
        except Exception:  # noqa: BLE001 — 해석할 수 없는 URL은 통째로 가린다.
            secrets.append(settings.database_url)
    except Exception:  # noqa: BLE001 — 설정을 못 읽어도 pattern 가림은 한다.
        secrets = []
    forms: set[str] = set()
    for secret in filter(None, secrets):
        for base in {secret, unquote(secret)}:
            encoded = quote(base, safe="")
            forms.update({base, encoded, quote(encoded, safe="")})
    return sorted(forms, key=len, reverse=True)


def _type_name(error: BaseException) -> str:
    kind = type(error)
    return f"{kind.__module__}.{kind.__qualname__}"


def _redact_text(text: str, forms: list[str]) -> str:
    for form in forms:
        text = text.replace(form, "<redacted>")
    return text


def _sanitize_op_error(error: BaseException, forms: list[str]) -> str:
    """`sanitize_upstream_error`(URL의 serviceKey= 값)에 설정된 비밀값의 모든 형태를 더 가린다.

    sanitizer 자체가 실패하면(예: 읽지 않은 응답의 `httpx.ResponseNotRead`) 원문 대신 `<unavailable>`.
    """
    try:
        return _redact_text(sanitize_upstream_error(error, None), forms)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return "<unavailable>"


def _error_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and all(current is not seen for seen in chain):
        chain.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return chain


def _redacted_failure(error: BaseException) -> Failure:
    """예외 종류·가린 문장·안전한 코드 위치만 담은 Failure. 가린 전체 traceback은 stderr로 보낸다.

    stderr는 run 컨테이너의 compute log(로컬 파일)로 가고 공용 event log에는 들어가지 않는다.
    """
    forms = _secret_forms()
    error_type = _redact_text(_type_name(error), forms)
    description = f"{error_type}: {_sanitize_op_error(error, forms)}"
    if len(description) > MAX_FAILURE_DESCRIPTION_CHARS:
        description = description[: MAX_FAILURE_DESCRIPTION_CHARS - 3] + "..."
    metadata: dict[str, str] = {"error_type": error_type}
    try:
        chain = _error_chain(error)
        frames = traceback.extract_tb(error.__traceback__)
        if len(frames) > MAX_FAILURE_FRAMES:
            # 가장 안쪽(raise 지점 쪽) frame을 남기고 생략한 개수를 적는다.
            metadata["frames_omitted"] = str(len(frames) - MAX_FAILURE_FRAMES)
            frames = frames[-MAX_FAILURE_FRAMES:]
        metadata["frames"] = _redact_text(
            "\n".join(f"{frame.filename}:{frame.lineno} {frame.name}" for frame in frames), forms)
        metadata["error_chain"] = _redact_text("\n".join(_type_name(item) for item in chain), forms)
        blocks = []
        for item in reversed(chain):
            tb_text = "".join(traceback.format_tb(item.__traceback__))
            blocks.append(_redact_text(f"Traceback (most recent call last):\n{tb_text}{_type_name(item)}: ", forms)
                          + f"{_sanitize_op_error(item, forms)}\n")
        print("\nThe above exception was the direct cause of the following exception:\n\n".join(blocks),
              file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 — 진단 보강의 실패가 원문을 사슬에 매달면 안 된다.
        pass
    return Failure(description=description, metadata=metadata, allow_retries=False)


def _redact_op_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
    """op에서 빠져나가는 예외를 가린 `Failure`로 바꾼다.

    공용 Dagster event log(`dagster_shared`)는 모든 테넌트 UI가 읽는다. Dagster는 step 실패의 `str(exc)`·
    traceback·`__cause__`/`__context__` 사슬을 그대로 직렬화하는데, code-server는 `app.main`의 logging
    filter를 import하지 않는다. 그래서 op 경계에서 예외 종류·가린 문장·코드 위치만 남기고 사슬은 끊는다.
    의도된 `Failure`(고정 문구·메타데이터)와 중단 신호(`_PASSTHROUGH_ERRORS`)는 그대로 둔다.
    step 실패는 원래부터 재시도하지 않으므로(op RetryPolicy 없음, `retry_on_asset_or_op_failure=false`,
    infra 재시도 sensor는 STEP_FAILURE가 있으면 건너뜀) `allow_retries=False`는 의미를 바꾸지 않는다.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (Failure, *_PASSTHROUGH_ERRORS):
            raise
        except BaseException as exc:  # noqa: BLE001 — 경계에서 모든 원문을 가린다.
            try:
                failure = _redacted_failure(exc)
            except Exception:  # noqa: BLE001
                failure = Failure(description=f"{_type_name(exc)}: <unavailable>",
                                  metadata={"error_type": _type_name(exc)}, allow_retries=False)
            del exc
        # except 블록 밖에서 던져 __context__에도 원래 예외가 걸리지 않게 한다.
        failure.__suppress_context__ = True
        raise failure

    return wrapper


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
    ensure_collection_owner_active()
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
@_redact_op_errors
def collect_airport_parking(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, CollectionService(settings).collect, trigger="dagster_airport"))
        if result.get("status") in {"failed", "partial_success"}:
            raise Failure(description="공항 수집의 성공분은 저장했지만 일부 수집이 실패했습니다.",
                          metadata={"run_id": result["collection_run_id"], "status": result["status"]},
                          allow_retries=False)
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
            metadata={"run_id": result["collection_run_id"], "status": result["status"], "scope": scope},
            allow_retries=False,
        )
    return result


@op
@_redact_op_errors
def collect_highway_transport(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        return _collect_transport("highway")


@op
@_redact_op_errors
def collect_fuel_transport(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
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
@_redact_op_errors
def collect_rail_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        return _collect_reference("rail")


@op
@_redact_op_errors
def collect_maritime_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        return _collect_reference("maritime")


@op
@_redact_op_errors
def collect_ferry_timetable(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        return _collect_ferry_timetable()


@op
@_redact_op_errors
def collect_bus_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        return _collect_bus_reference()


@op
@_redact_op_errors
def collect_place_locations(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, PlaceLocationCollectionService(settings).collect))
        if result.get("status") == "partial_success":
            raise Failure(description="장소 위치 조회가 유예되거나 실패했습니다. 성공분은 저장했습니다.",
                          metadata={"run_id": result["run_id"], "deferred": result["deferred"]},
                          allow_retries=False)
        return result


@op
@_redact_op_errors
def collect_kakao_place_locations(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, KakaoPlaceCollectionService(settings).collect))
        if result.get("status") == "partial_success":
            raise Failure(description="카카오 장소 위치 조회가 유예되거나 실패했습니다. 성공분은 저장했습니다.",
                          metadata={"run_id": result["run_id"], "deferred": result["deferred"]},
                          allow_retries=False)
        return result


@op
@_redact_op_errors
def enrich_new_reference_locations(context, reference_result: dict[str, Any]) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        """공식 기준정보 적재 직후 기존 수집기의 호출 예산·receipt를 그대로 사용한다."""
        settings = _settings()
        results: dict[str, dict[str, Any]] = {}
        for name, service in (("vworld", PlaceLocationCollectionService), ("kakao", KakaoPlaceCollectionService)):
            try:
                results[name] = asyncio.run(_run_with_session(settings, service(settings).collect))
            except CollectionLeaseLost:
                # 소유권 회수는 provider 장애가 아니다. 후속 provider/session을 시작하지 않는다.
                raise
            except Exception as exc:
                # 한 제공기관의 장애가 다른 제공기관의 독립된 호출 예산을 막지 않는다.
                results[name] = {"status": "failed", "error_type": type(exc).__name__}
        vworld, kakao = results["vworld"], results["kakao"]
        metadata: dict[str, Any] = {
            "reference_run_id": reference_result.get("run_id", ""),
            "reference_failed_calls": reference_result.get("port_location_failed_calls", 0),
            "reference_deferred": reference_result.get("port_location_deferred_count", 0),
        }
        for name, result in (("vworld", vworld), ("kakao", kakao)):
            metadata.update({f"{name}_run_id": result.get("run_id", ""), f"{name}_status": result.get("status", ""),
                             f"{name}_deferred": result.get("deferred", 0),
                             f"{name}_provider_failed": result.get("provider_failed", 0)})
        # 실제 오류(예외로 끝난 수집, 호출 실패)만 실패로 올린다. 유예(일일 호출 예산, 429 유예,
        # 검색 결과가 페이지 상한을 넘어 확정할 수 없는 `incomplete`)는 성공분을 저장한 정상 결과다 —
        # 같은 이름이 매일 유예돼 job이 매일 FAILURE가 되면 진짜 장애가 묻힌다. 유예 건수는 metadata로 남긴다.
        provider_error = any(result.get("status") == "failed" or result.get("provider_failed", 0)
                             for result in (vworld, kakao))
        if reference_result.get("status") == "partial_success" or provider_error:
            raise Failure(description="기준정보와 장소 좌표 보강의 성공분은 저장했지만 일부 조회가 실패하거나 유예됐습니다.",
                          metadata=metadata, allow_retries=False)
        deferred = sum(int(result.get("deferred", 0) or 0) for result in (vworld, kakao))
        if deferred:
            context.log.warning(f"장소 좌표 보강에서 {deferred}건이 유예됐습니다(오류 없음). 다음 정기 수집에서 다시 봅니다.")
        context.add_output_metadata(metadata)
        return {"reference_status": reference_result.get("status"), "vworld": vworld, "kakao": kakao}


@op
@_redact_op_errors
def collect_kric_timetable(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        return asyncio.run(_run_with_session(settings, KricTimetableCollectionService(settings).collect))


@op
@_redact_op_errors
def collect_rest_area_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        return asyncio.run(_run_with_session(settings, RestAreaCollectionService(settings).collect_references))


@op
@_redact_op_errors
def collect_rest_area_fuel_prices(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
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
    sensors=[worker_recovery, *[
        infrastructure_retry_sensor(
            name=f"transport_infra_retry_{retry_job.name}",
            project="transport", location_name="kor-travel-transport", job=retry_job,
            policy=RecoveryPolicy(MAX_RUNTIME_SECONDS, idempotent=True, infrastructure_retries=1),
        )
        for retry_job in (airport_collection_job, highway_collection_job, rest_area_reference_collection_job)
    ]],
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
