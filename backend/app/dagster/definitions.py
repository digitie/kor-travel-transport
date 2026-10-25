"""DB transaction 경계를 명시한 Dagster 수집 job 정의."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import re
import sys
import time
import traceback
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, unquote

from .address_refresh import address_refresh_job, address_refresh_sensor

from dagster import (
    DagsterExecutionInterruptedError, DefaultScheduleStatus, Definitions, Failure, multiprocess_executor, job, op,
)
from sqlalchemy.engine import make_url
from kortravelcommon.deadline import call_with_deadline
from kortravelcommon.dagster import RecoveryPolicy, coalescing_schedule, infrastructure_retry_sensor, reconciliation_sensor

from app.dagster import recovery
from app.dagster.recovery import (
    AIRPORT_TRIGGER, OWNER, RECOVERY_BUDGET_SECONDS, CollectionLeaseLost, ScanPosition,
    collection_owner, ensure_collection_owner_active, format_stall_alert, owned_session_factory,
    run_recovery_tick,
)

from app.core.config import Settings, get_settings
from app.db.session import create_engine_and_session_factory
from app.services.collection import CollectionService
from app.services.analytics_cache import refresh_default_analytics_cache
from app.services.flight_status import sanitize_upstream_error
from app.services.bus_collection import BusReferenceCollectionService
from app.services.kric_collection import KricTimetableCollectionService
from app.services.kakao_place_locations import KakaoPlaceCollectionService
from app.services.place_locations import PlaceLocationCollectionService
from app.services.rail_maritime_collection import RailMaritimeCollectionService
from app.services.vadahub_collection import VadaHubCollectionService
from app.services.rest_area_collection import RestAreaCollectionService
from app.services.transport_collection import CollectionScope, TransportCollectionService

#: 실행 상한(초). 공용 Dagster instance의 전역 상한(6시간, Manager `config/dagster-shared/dagster.yaml`)은
#: 다른 테넌트의 값이라, 옛 전용 instance의 상한(4시간)을 job마다 tag로 단다. run monitoring이 이 tag를 읽어
#: 넘긴 run을 실패로 끝낸다. 유가 Playwright 수집의 상한(`FUEL_FETCH_TIMEOUT_SECONDS`, 3.5시간)과 저장 여유가
#: 이 안(`- 60`초)에 들어야 한다.
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


async def _collect_airport_with_analytics(session, *, settings: Settings, trigger: str) -> dict[str, Any]:
    result = await CollectionService(settings).collect(session, trigger=trigger)
    if result.get("snapshot_count", 0) > 0 or result.get("status") == "success":
        try:
            # collect는 성공분과 실행 상태를 이미 commit했다. 파생 결과 실패로 원본을 되돌리지 않는다.
            # 중복 관측뿐인 정상 tick도 이전 실패·재시작으로 놓친 cache를 복구한다.
            result["analytics_cache_count"] = await refresh_default_analytics_cache(session, settings)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            result["analytics_cache_error"] = _redacted_causes([str(exc)])
    return result


@op
@_redact_op_errors
def collect_airport_parking(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(
            settings, functools.partial(_collect_airport_with_analytics, settings=settings), trigger=AIRPORT_TRIGGER,
        ))
        cache_error = result.get("analytics_cache_error")
        cache_metadata = {"analytics_cache_error": cache_error} if cache_error else {}
        if result.get("status") in {"failed", "partial_success"}:
            raise Failure(description="공항 수집의 성공분은 저장했지만 일부 수집이 실패했습니다.",
                          metadata={"run_id": result["collection_run_id"], "status": result["status"], **cache_metadata},
                          allow_retries=False)
        if cache_error:
            raise Failure(description="공항 관측은 저장했지만 주차 분석 캐시 갱신에 실패했습니다.",
                          metadata={"run_id": result["collection_run_id"], "status": result["status"], **cache_metadata},
                          allow_retries=False)
        return result


async def _collect_transport_in_one_loop(settings: Settings, scope: CollectionScope) -> dict[str, Any]:
    """HTTP client의 생성·수집·종료를 하나의 event loop에서 끝낸다."""
    service = TransportCollectionService(settings)
    try:
        # highway의 trigger(`dagster_highway`)는 회수 sensor의 신선도 판정이 본다(`recovery.HIGHWAY_TRIGGER`).
        return await _run_with_session(settings, service.collect, trigger=f"dagster_{scope}", scope=scope)
    finally:
        await asyncio.wait_for(service.close(), timeout=10)


#: Failure 설명에 담는 오류 하나의 상한. 차단 페이지 HTML 같은 긴 문장은 잘라 둔다.
MAX_FAILURE_CAUSE_CHARS = 300
_HTML_TAG = re.compile(r"<(?!redacted>)[^<>]{1,200}>")


def _redacted_causes(errors: Any) -> str:
    """수집 서비스가 남긴 오류 문장들을 공용 event log에 실어도 되는 한 줄로 만든다.

    서비스의 `_safe_error`는 두 키만 가린다. 여기서 설정된 모든 비밀값의 모든 형태와 URL의 `serviceKey=` 값을
    더 가리고, HTML 태그를 걷고, 중복을 합치고, 길이를 자른다. 진단에 DB 접근이 필요 없게 하려는 것이다.
    """
    if not isinstance(errors, (list, tuple)) or not errors:
        return "원인 미기록"
    forms = _secret_forms()
    causes: list[str] = []
    for error in errors:
        try:
            # 먼저 가린 뒤 태그를 걷는다(태그 제거가 비밀값을 쪼개 가림을 피해 가지 않게).
            text = _HTML_TAG.sub(" ", _redact_text(sanitize_upstream_error(str(error), None), forms))
        except Exception:  # noqa: BLE001 — 가림에 실패한 문장은 싣지 않는다.
            text = "<unavailable>"
        text = " ".join(text.split())
        if len(text) > MAX_FAILURE_CAUSE_CHARS:
            text = text[: MAX_FAILURE_CAUSE_CHARS - 3] + "..."
        if text not in causes:
            causes.append(text)
    return " | ".join(causes)


def _collect_transport(scope: CollectionScope) -> dict[str, Any]:
    result = asyncio.run(_collect_transport_in_one_loop(_settings(), scope))
    # 성공분·실패 상태를 커밋하고 provider를 닫은 뒤 Dagster에도 실패를 전달한다.
    # 원인은 가린 한 줄로 설명에 싣는다(다음 진단이 DB를 보지 않아도 되게). 기존 호출 유예를 자동 재시도로
    # 우회하지 않는다.
    if result.get("status") in {"failed", "partial_success"} or (
        scope == "fuel" and result.get("status") == "skipped" and result.get("fuel_ready") is not True
    ):
        errors = result.get("errors")
        reason = ", skip_reason=collector_busy" if result.get("skip_reason") == "collector_busy" else ""
        description = (f"교통정보 수집에 실패했습니다(status={result['status']}{reason}): {_redacted_causes(errors)}. "
                       "저장된 성공분과 호출 유예는 유지합니다.")
        if len(description) > MAX_FAILURE_DESCRIPTION_CHARS:
            description = description[: MAX_FAILURE_DESCRIPTION_CHARS - 3] + "..."
        raise Failure(
            description=description,
            metadata={"run_id": result["collection_run_id"], "status": result["status"], "scope": scope,
                      "error_count": len(errors) if isinstance(errors, (list, tuple)) else 0,
                      **({"skip_reason": "collector_busy"} if reason else {})},
            allow_retries=False,
        )
    return result


@op
@_redact_op_errors
def collect_highway_transport(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        return _collect_transport("highway")


#: 유가 op 동안 Dagster event log로 넘기는 logger. 오피넷 수집기의 단계별 진행(지역 탐색, 탭별 시도 진행,
#: 경과 시간)과 수집 서비스의 수집·저장 경과 시간이다. code-server는 logging을 설정하지 않아 INFO가 버려진다.
FUEL_PROGRESS_LOGGERS = ("opinet.experimental.browser", "app.services.transport_collection")
#: event log에 싣는 진행 로그 한 줄의 상한.
MAX_FORWARDED_LOG_CHARS = 1000


class _DagsterLogForwarder(logging.Handler):
    """Python logging 레코드를 가린 뒤 op의 `context.log`로 넘긴다(공용 event log라 비밀값을 먼저 가린다)."""

    def __init__(self, context: Any, forms: list[str]) -> None:
        super().__init__(level=logging.INFO)
        self._context = context
        self._forms = forms

    def emit(self, record: logging.LogRecord) -> None:
        try:
            text = _redact_text(sanitize_upstream_error(record.getMessage(), None), self._forms)
            text = " ".join(text.split())
            if len(text) > MAX_FORWARDED_LOG_CHARS:
                text = text[: MAX_FORWARDED_LOG_CHARS - 3] + "..."
            log = self._context.log.warning if record.levelno >= logging.WARNING else self._context.log.info
            log(f"[{record.name}] {text}")
        except Exception:  # noqa: BLE001 — 진행 로그 전달의 실패가 수집을 멈추면 안 된다.
            pass


@contextlib.contextmanager
def _forward_progress_logs(context: Any, names: tuple[str, ...] = FUEL_PROGRESS_LOGGERS) -> Any:
    """op 동안 `names` logger의 INFO 이상을 Dagster event log로 넘기고, 끝나면 원래 상태로 되돌린다."""
    handler = _DagsterLogForwarder(context, _secret_forms())
    loggers = [logging.getLogger(name) for name in names]
    previous_levels = [item.level for item in loggers]
    previous_propagation = [item.propagate for item in loggers]
    previous_context_level = context.log.level
    if context.log.getEffectiveLevel() > logging.INFO:
        # 공용 instance의 python_log_level=WARNING도 이 op 안에서만 완화한다.
        # provider logger만 낮추면 최종 context.log.info에서 진행 로그가 버려진다.
        context.log.setLevel(logging.INFO)
    for item in loggers:
        item.addHandler(handler)
        # 공용 root capture가 원문을 중복 기록하지 않도록 가린 전달 경로만 사용한다.
        item.propagate = False
        if item.getEffectiveLevel() > logging.INFO:
            item.setLevel(logging.INFO)
    try:
        yield
    finally:
        for item, level, propagate in zip(loggers, previous_levels, previous_propagation):
            item.removeHandler(handler)
            item.setLevel(level)
            item.propagate = propagate
        context.log.setLevel(previous_context_level)


@op
@_redact_op_errors
def collect_fuel_transport(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance), _forward_progress_logs(context):
        result = _collect_transport("fuel")
        context.add_output_metadata({key: value for key, value in result.items()
                                     if key in {"status", "collection_run_id", "fuel_station_count", "fuel_price_count",
                                                "fuel_ready", "next_fuel_due_at", "last_fuel_success_at", "skip_reason"}})
        if result.get("status") == "skipped":
            if result.get("skip_reason") == "collector_busy":
                context.log.warning("유가 수집은 다른 수집기가 체크포인트를 사용 중이어서 실행하지 않았습니다(status=skipped).")
            else:
                context.log.warning("유가 수집은 호출 유예 중이어서 실행하지 않았습니다(status=skipped).")
        return result


def _place_collection_error(result: dict[str, Any]) -> bool:
    """장소 좌표 조회 결과에 실제 오류가 있는가(유예와 구분한다).

    실제 오류: 예외로 끝난 수집(`failed`), 제공기관 호출 실패(`provider_failed>0`), 그리고 유예로 설명되지 않는
    `partial_success`(지금의 서비스는 만들지 않지만, 설명 없는 부분 성공은 실패 쪽으로 둔다).
    유예: 일일·월간 호출 예산, VWorld `incomplete`(결과가 페이지 상한을 넘어 확정 불가), 카카오 429 뒤 24시간 유예.
    """
    status = result.get("status")
    return (status == "failed" or bool(result.get("provider_failed", 0))
            or (status == "partial_success" and not result.get("deferred", 0)))


def _place_metadata(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result.get(key, default) for key, default in (
        ("run_id", ""), ("status", ""), ("provider_calls", 0), ("deferred", 0), ("provider_failed", 0),
        ("incomplete", 0), ("unmatched", 0), ("bus_locations", 0), ("port_locations", 0))}


def _finish_place_collection(context, result: dict[str, Any], provider: str) -> dict[str, Any]:
    """독립 장소 좌표 job의 끝맺음. bus_reference의 좌표 보강(PR #73)과 같은 규칙이다."""
    metadata = _place_metadata(result)
    if _place_collection_error(result):
        raise Failure(description=f"{provider} 장소 위치 조회 중 제공기관 호출이 실패했습니다"
                                  f"(provider_failed={metadata['provider_failed']}, status={metadata['status']}). "
                                  "성공분은 저장했고 유예분은 다음 정기 수집에서 다시 봅니다.",
                      metadata=metadata, allow_retries=False)
    if metadata["deferred"]:
        context.log.warning(f"{provider} 장소 위치 조회에서 {metadata['deferred']}건이 유예됐습니다(오류 없음). "
                            "다음 정기 수집에서 다시 봅니다.")
    context.add_output_metadata(metadata)
    return result


def _reference_error(result: dict[str, Any]) -> bool:
    """기준정보 수집(버스·항구) 결과에 실제 오류가 있는가.

    항구 기준정보는 기항지 위치 조회가 실패(`port_location_failed_calls>0`)하거나 유예(`port_location_deferred_count>0`
    — 실패 TTL, 429 뒤 24시간 유예, 일일 80회 예산)되면 `partial_success`다. 이번 실행의 호출 실패만 실제 오류다.
    """
    if result.get("status") == "failed":
        return True
    if result.get("status") != "partial_success":
        return False
    return bool(result.get("port_location_failed_calls", 0)) or not result.get("port_location_deferred_count", 0)


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
        return _finish_place_collection(context, result, "VWorld")


@op
@_redact_op_errors
def collect_kakao_place_locations(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, KakaoPlaceCollectionService(settings).collect))
        return _finish_place_collection(context, result, "카카오")


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
        # 검색 결과가 페이지 상한을 넘어 확정할 수 없는 `incomplete`, 항구 기항지 조회의 실패 TTL·예산)는 성공분을
        # 저장한 정상 결과다 — 같은 이름이 매일 유예돼 job이 매일 FAILURE가 되면 진짜 장애가 묻힌다.
        # 유예 건수는 metadata로 남긴다.
        failed = [name for name, failed in (
            ("reference", _reference_error(reference_result)),
            ("vworld", _place_collection_error(vworld)),
            ("kakao", _place_collection_error(kakao)),
        ) if failed]
        if failed:
            raise Failure(description=(
                f"제공기관 호출 실패가 있습니다({', '.join(failed)}): 예외로 끝난 수집, provider_failed>0, "
                "또는 이번 실행의 기항지 위치 조회 실패(reference_failed_calls>0). 유예만 있는 날은 실패가 아닙니다. "
                "기준정보와 좌표 보강의 성공분은 저장했습니다."),
                metadata={**metadata, "failed_parts": ",".join(failed)}, allow_retries=False)
        deferred = sum(int(result.get("deferred", 0) or 0) for result in (vworld, kakao))
        if deferred:
            context.log.warning(f"장소 좌표 보강에서 {deferred}건이 유예됐습니다(오류 없음). 다음 정기 수집에서 다시 봅니다.")
        reference_deferred = int(reference_result.get("port_location_deferred_count", 0) or 0)
        if reference_deferred:
            context.log.warning(f"기항지 위치 조회에서 {reference_deferred}건이 유예됐습니다(이번 실행의 호출 실패 없음). "
                                "다음 정기 수집에서 다시 봅니다.")
        context.add_output_metadata(metadata)
        return {"reference_status": reference_result.get("status"), "vworld": vworld, "kakao": kakao}


@op
@_redact_op_errors
def collect_kric_timetable(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, KricTimetableCollectionService(settings).collect))
        if result.get("status") in {"partial", "failed"}:
            raise Failure(description="도시철도 시간표 일부 조회에 실패했습니다. 정상 저장분은 유지했습니다.",
                metadata={name: result.get(name, 0) for name in ("stored_snapshot_count", "failed_snapshot_count", "attempted_snapshot_count", "deferred_snapshot_count")},
                allow_retries=False)
        return result


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


@op
@_redact_op_errors
def collect_vadahub_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, VadaHubCollectionService(settings).collect))
        if result["status"] == "partial_success":
            raise Failure(description="일부 배편 기준자료 수집에 실패했습니다. 마지막 정상 자료를 유지합니다.",
                          metadata={"failed_datasets": ", ".join(result["failed_datasets"])}, allow_retries=False)
        context.log.info("VadaHub 배편 기준자료: %s", result)
        return result


@job(tags=_job_tags("reference", "vadahub_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def vadahub_reference_collection_job() -> None:
    collect_vadahub_reference()


@job(tags=_job_tags("reference", "bus_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def bus_reference_collection_job() -> None:
    enrich_new_reference_locations(collect_bus_reference())


@job(tags=_job_tags("reference", "place_location_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def place_location_collection_job() -> None:
    collect_place_locations()


@job(tags=_job_tags("reference", "kakao_place_location_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def kakao_place_location_collection_job() -> None:
    collect_kakao_place_locations()


#: 회수 keyset 위치. sensor cursor는 common 정체 시계가 소유하므로 code-server 프로세스에 둔다.
_RECOVERY_POSITION = ScanPosition()


#: 5분 수집 trigger → 그 수집을 예약하는 schedule 이름(common `coalescing_schedule`은 `<job>_schedule`).
_TRIGGER_SCHEDULES = {
    recovery.FIVE_MINUTE_TRIGGERS[0]: f"{airport_collection_job.name}_schedule",
    recovery.FIVE_MINUTE_TRIGGERS[1]: f"{highway_collection_job.name}_schedule",
}
_LOCATION_NAME = "kor-travel-transport"


def _stopped_schedules(instance) -> set[str]:
    """이 location에서 사용자가 STOPPED로 바꾼 schedule 이름. 상태 행이 없거나 RUNNING/DECLARED_IN_CODE면
    코드 기본값(RUNNING)이다. 같은 이름의 상태가 여럿이면(옛 repository origin) 모두 STOPPED일 때만 멈춘
    것으로 본다(애매하면 경보 쪽)."""
    from dagster._core.scheduler.instigation import InstigatorStatus, InstigatorType

    if getattr(instance, "schedule_storage", None) is None:
        return set()  # schedule 저장소가 없는 instance(ephemeral)는 저장된 상태가 없다 = 코드 기본값
    statuses: dict[str, set[Any]] = {}
    for state in instance.all_instigator_state(instigator_type=InstigatorType.SCHEDULE):
        try:
            location = state.origin.repository_origin.code_location_origin.location_name
        except AttributeError:
            continue
        if location == _LOCATION_NAME and state.instigator_name in _TRIGGER_SCHEDULES.values():
            statuses.setdefault(state.instigator_name, set()).add(state.status)
    return {name for name, seen in statuses.items() if seen == {InstigatorStatus.STOPPED}}


async def _reconcile_workers(instance, remaining, paused: list[str] | None = None) -> int:
    def work_remaining() -> float:
        return remaining() - recovery.CLEANUP_RESERVE_SECONDS

    stopped_cache: list[set[str]] = []

    def collection_scheduled(trigger: str) -> bool:
        if not stopped_cache:
            if work_remaining() <= recovery.METADATA_TIMEOUT_SECONDS:
                raise recovery.RecoveryMetadataUnavailable("schedule 상태를 확인할 예산이 남지 않았습니다.")
            try:
                stopped_cache.append(call_with_deadline(
                    lambda: _stopped_schedules(instance), timeout_seconds=recovery.METADATA_TIMEOUT_SECONDS))
            except Exception as exc:
                raise recovery.RecoveryMetadataUnavailable("schedule 상태를 확인하지 못했습니다.") from exc
        return _TRIGGER_SCHEDULES[trigger] not in stopped_cache[0]

    engine, factory = create_engine_and_session_factory(
        _settings().database_url, collector=True, statement_timeout_seconds=recovery.RECOVERY_STATEMENT_TIMEOUT_SECONDS,
    )
    try:
        # 첫 접속의 dialect 초기화·빈 page 확인까지 포함한 작업 전체를 정리 시간 앞에서 끊는다.
        async with asyncio.timeout(max(0.0, work_remaining())):
            return await run_recovery_tick(
                factory, instance, position=_RECOVERY_POSITION, remaining=work_remaining,
                collection_scheduled=collection_scheduled, paused=paused,
            )
    finally:
        # dispose도 정리 시간 안에서 끝낸다. 넘으면 연결 정리를 포기한다(프로세스가 GC로 닫는다).
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(engine.dispose(), timeout=0.8 * recovery.CLEANUP_RESERVE_SECONDS)


def _reconcile_tick(context, remaining) -> int:
    # 예산을 넘겨 끊긴 thread는 tick 뒤에도 돌 수 있다. context는 instance를 꺼낸 뒤에는 예산이 남아 있을
    # 때만 쓴다(common 계약).
    instance = context.instance
    paused: list[str] = []
    recovered = asyncio.run(_reconcile_workers(instance, remaining, paused))
    if paused and remaining() > 0:
        # 점검으로 멈춘 schedule은 정체가 아니다. traceback 없이 한 줄만 남긴다.
        context.log.warning("5분 수집 schedule이 STOPPED라 신선도 판정에서 제외합니다: " + ", ".join(sorted(paused)))
    return recovered


_STALL_LOGGER = logging.getLogger("app.dagster.recovery")


def _alert_stall(context, clock) -> None:
    """정체 경보. 별도 경보 테이블·채널이 없어 고정 event 이름 한 줄로 두 곳에 남긴다.

    sensor tick 로그(Dagster UI)와 code-server 프로세스 stderr(컨테이너 로그, `docker logs`·로그 수집기).
    """
    line = format_stall_alert(clock, now=time.time())
    context.log.error(line)
    _STALL_LOGGER.error(line)


worker_recovery = reconciliation_sensor(
    name="transport_worker_recovery", reconcile=_reconcile_tick, required_resource_keys=set(),
    budget_seconds=RECOVERY_BUDGET_SECONDS, on_stall=_alert_stall,
)


definitions = Definitions(
    sensors=[address_refresh_sensor, worker_recovery, *[
        infrastructure_retry_sensor(
            name=f"transport_infra_retry_{retry_job.name}",
            project="transport", location_name="kor-travel-transport", job=retry_job,
            policy=RecoveryPolicy(MAX_RUNTIME_SECONDS, idempotent=True, infrastructure_retries=1),
        )
        for retry_job in (airport_collection_job, highway_collection_job, rest_area_reference_collection_job)
    ]],
    jobs=[
        address_refresh_job,
        airport_collection_job,
        highway_collection_job,
        fuel_collection_job,
        rail_reference_collection_job,
        maritime_reference_collection_job,
        vadahub_reference_collection_job,
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
        # 매일 누락/실패 원천만 보충하고 정상 자료는 7일간 재호출하지 않는다.
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=vadahub_reference_collection_job, cron_schedule="15 3 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
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
