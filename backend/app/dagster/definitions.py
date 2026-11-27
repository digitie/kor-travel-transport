"""DB transaction 경계를 명시한 Dagster 수집 job 정의."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import logging
import re
import sys
import time
import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote, unquote

from .address_refresh import address_refresh_job, address_refresh_sensor

from dagster import (
    Backoff, DagsterExecutionInterruptedError, DefaultScheduleStatus, Definitions, Failure, Field, Jitter, RetryPolicy,
    multiprocess_executor, job, op,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from kortravelcommon.deadline import call_with_deadline
from kortravelcommon.dagster import RecoveryPolicy, coalescing_schedule, infrastructure_retry_sensor, reconciliation_sensor
from kortravelcommon.scheduling import staggered_cron

from app.dagster import recovery
from app.dagster.recovery import (
    AIRPORT_TRIGGER, OWNER, OWNER_LEASE, RECOVERY_BUDGET_SECONDS, CollectionLeaseLost, FuelFreshnessAlerts,
    FuelFreshnessReport, ScanPosition, collection_owner, ensure_collection_owner_active, format_stall_alert,
    owned_session_factory, run_recovery_tick,
)

from app.core.config import Settings, get_settings
from app.db.session import create_engine_and_session_factory
from app.services.collection import CollectionService
from app.services.analytics_cache import (
    ANALYTICS_REFRESH_ALERT_STATUSES, analytics_refresh_health, refresh_default_analytics_cache,
)
from app.services.parking_global_archive import archive_parking_with_coverage
from app.services.flight_status import sanitize_upstream_error
from app.services.bus_collection import BusReferenceCollectionService
from app.services.kric_collection import KricTimetableCollectionService
from app.services.general_rail_collection import GeneralRailCollectionService
from app.services.general_rail_reference import GeneralRailReferenceCollectionService
from app.services.kakao_place_locations import KakaoPlaceCollectionService
from app.services.place_locations import PlaceLocationCollectionService
from app.services.rail_maritime_collection import RailMaritimeCollectionService
from app.services.vadahub_collection import VadaHubCollectionService
from app.services.rest_area_collection import REST_AREA_FUEL_SOURCE, RestAreaCollectionService
from app.services.public_parking_collection import PublicParkingCollectionService
from app.services.reference_export_preparation import (
    BUSY_ESCALATION_STREAK, COLLECTION_TAIL_PREPARE_BUDGET_SECONDS, PREPARE_TOTAL_BUDGET_SECONDS,
)
from app.services.reference_export_preparation import prepare_reference_exports as prepare_reference_export_bodies
from app.services.transport_collection import (
    DATABASE_FAILURE_REASONS, OPINET_SOURCE, TRAFFIC_STORE_STEPS, CollectionScope, TransportCollectionService,
    _is_transient_database_error,
)
from app.services.traffic_statistics import REPAIR_DEFER_REASONS, REPAIR_STATUSES

#: 실행 상한(초). 공용 Dagster instance의 전역 상한(6시간, Manager `config/dagster-shared/dagster.yaml`)은
#: 다른 테넌트의 값이라, 옛 전용 instance의 상한(4시간)을 job마다 tag로 단다. run monitoring이 이 tag를 읽어
#: 넘긴 run을 실패로 끝낸다. 유가 Playwright 수집의 상한(`FUEL_FETCH_TIMEOUT_SECONDS`, 3.5시간)과 저장 여유가
#: 이 안(`- 60`초)에 들어야 한다.
MAX_RUNTIME_SECONDS = 14400
#: 주기가 짧은 job의 실행 상한(초). coalescing schedule은 같은 job이 QUEUED·STARTED인 동안 tick을 버리므로,
#: 5분 job에 4시간 상한을 두면 걸린 run 하나가 최대 4시간(48 tick) 수집을 막는다(2026-11-23 수집 감사 §2.5 P1 #9).
#: 주기의 몇 배로 정하되 정상 최악 경로를 덮는다.
#: - 공항(5분): KAC·IIAC 전체 집합(원천별 재확인 1회, 최대 20쪽, 요청 15초·SDK 재시도)·일일 요금·파생 분석 캐시에 이어
#:   같은 run의 기준정보 본문 준비 step까지 한 상한을 나눠 쓴다. 느리지만 끝나는 상류(예전 15~20분)를 끊지 않게 6주기 = 1,800초.
#: - 고속도로(5분): 최초 조회 2x120초 + 빈/급감 재확인 2x120초 + 저장(운영 표본 175초+)과 claim 예약(1,140초). 4주기 = 1,200초.
#: op 안의 cancellation deadline은 run **시작** 기준 남은 예산으로 잰다(`_run_deadline_seconds`) — step이 여럿이거나 step 기동이
#: 늦어도 run monitoring보다 먼저 끝나 실패를 직접 기록한다.
#: - 기준정보 파생 본문 준비: 180초(기존 값).
#: 그 밖의 job은 주기가 4시간 이상이거나(유가 브라우저 수집 3.5시간 포함) 이어 하기 backfill이라 `MAX_RUNTIME_SECONDS`를 둔다.
#: - 주차 통계 보관: provider 호출 없는 DB 작업. 정기 실행은 새 배치를 `PARKING_ARCHIVE_SCHEDULED_TIME_BUDGET_SECONDS`(240초)
#:   안에서만 시작한다. 배치 하나가 예상보다 길어도 공항 수집(같은 run group)을 오래 막지 않게 기본 900초에서 끊는다. 긴 수동
#:   backfill은 실행할 때 `dagster/max_runtime` 태그를 늘린다 — op가 run 기록의 태그로 배치 시한을 잰다(`_archive_remaining_runtime`).
JOB_MAX_RUNTIME_SECONDS = {
    "airport_collection_job": 1800,
    "highway_collection_job": 1200,
    "reference_export_prepare_job": 180,
    "parking_statistics_archive_job": 900,
}
#: `dagster/priority`(클수록 큐에서 먼저 시작). 공용 run 큐(odroid `max_concurrent_runs` 5, location 상한)가 찰 때 사용자에게
#: 바로 보이는 실시간 현황(공항 주차·고속도로 소통)을 먼저 띄운다. 이 태그는 공용 instance 전체의 큐 순서라 다른 테넌트(기본 0)와도
#: 비교된다 — 음수는 두지 않아 transport의 backfill이 다른 테넌트 뒤로 굶지 않게 하고, 나머지는 기본 0이다.
JOB_PRIORITIES = {
    "airport_collection_job": 10,
    "highway_collection_job": 10,
    "fuel_collection_job": 5,
    "rest_area_fuel_price_collection_job": 5,
    "reference_export_prepare_job": 5,
    # 주차 통계 보관은 provider 호출 없는 DB 작업이다. 실시간 수집 뒤로(기본값 0을 명시).
    "parking_statistics_archive_job": 0,
}
#: 인프라 재시도(프로세스·launcher 장애)를 허용하는 멱등 job.
IDEMPOTENT_JOBS = frozenset({"airport_collection_job", "highway_collection_job", "rest_area_reference_collection_job",
                             "rest_area_food_collection_job"})

#: 관리자 "재시도"(admin console `retry`)가 새 run에 다는 태그. 값은 재시도한 원래 run ID다.
ADMIN_RETRY_TAG = "kortravel/admin-retry-of"
#: 유가 op의 일시 오류 자동 재시도(같은 run 안의 step 재시도). provider 차단·쿼터·인증·파싱 오류는 재시도하지 않는다
#: (`AUTO_RETRY_ERROR_CODES`만). 오피넷 브라우저 수집은 체크포인트에서 남은 지역만 이어 하고, 재시도는 정기 예약을
#: 옮기지 않는다(`TransportCollectionService.collect(retry_failed_fuel=True)`).
FUEL_RETRY_POLICY = RetryPolicy(max_retries=1, delay=300, backoff=Backoff.EXPONENTIAL, jitter=Jitter.PLUS_MINUS)
#: 휴게소 유가(KREX 1회 호출)는 상태 claim의 DB 잠금 경합만 재시도한다. 4시간 주기라 몇 분 뒤 재시도가 이득이다.
REST_AREA_FUEL_RETRY_POLICY = RetryPolicy(max_retries=2, delay=60, backoff=Backoff.EXPONENTIAL, jitter=Jitter.PLUS_MINUS)
#: 재시도는 같은 run 안에서 돈다. run 상한(`MAX_RUNTIME_SECONDS`)까지 남은 시간이 이보다 적으면 재시도하지 않는다
#: (유가 브라우저 재개는 남은 지역만이라도 수십 분이 걸리고, 상한에 걸려 run monitoring이 끊으면 저장도 못 한다).
MIN_RETRY_BUDGET_SECONDS = 2 * 60 * 60
#: 자동 재시도 대상 오류 코드(`_collection_failure_metadata`). 결과 metadata의 `retryable`(사람이 나중에 다시 해도
#: 되는가)과 다르다 — 쿼터(`PROVIDER_RATE_LIMIT`)·전체 시간 초과(`COLLECTION_TIMEOUT`)는 자동으로 반복하지 않는다.
AUTO_RETRY_ERROR_CODES = frozenset({"OPINET_BROWSER_TIMEOUT", "OPINET_BROWSER_RESOURCE_POLICY", "DATABASE_RETRYABLE"})


def _record_collection_outcome(context, outcome: str) -> None:
    """자기 실행의 관측 태그만 상향한다. 부가 기록 장애로 수집을 실패시키지 않는다."""
    ranks = {"success": 0, "deferred": 1, "partial": 2}
    if outcome not in {"partial", "deferred"}:
        return
    try:
        instance = getattr(context, "instance", None)
        run_id = getattr(context, "run_id", None)
        if instance is None or not run_id:
            return
        run = instance.get_run_by_id(run_id)
        if run is None:
            return
        previous = (getattr(run, "tags", None) or {}).get("kortravel/collection-outcome")
        if previous in ranks and ranks[previous] >= ranks[outcome]:
            return
        instance.add_run_tags(run_id, {"kortravel/collection-outcome": outcome})
    except Exception:
        with contextlib.suppress(Exception):
            context.log.warning("COLLECTION_OUTCOME_TAG_DEFERRED")


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


def _redacted_failure(error: BaseException, *, allow_retries: bool = False) -> Failure:
    """예외 종류·가린 문장·안전한 코드 위치만 담은 Failure. 가린 전체 traceback은 stderr로 보낸다.

    stderr는 run 컨테이너의 compute log(로컬 파일)로 가고 공용 event log에는 들어가지 않는다.
    """
    forms = _secret_forms()
    error_type = _redact_text(_type_name(error), forms)
    description = f"{error_type}: {_sanitize_op_error(error, forms)}"
    if len(description) > MAX_FAILURE_DESCRIPTION_CHARS:
        description = description[: MAX_FAILURE_DESCRIPTION_CHARS - 3] + "..."
    metadata: dict[str, Any] = {"error_type": error_type}
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
    if allow_retries:
        metadata["auto_retry"] = True
    return Failure(description=description, metadata=metadata, allow_retries=allow_retries)


def _is_transient_failure(error: BaseException) -> bool:
    """op 경계까지 올라온 예외가 같은 run 안에서 잠시 뒤 다시 해도 되는 DB 일시 오류인가.

    운영(2026-11-21~23)의 유가·휴게소 유가 실패 다섯 건이 상태 claim의 `lock_timeout`(SQLSTATE 55P03)이었다.
    claim transaction은 provider 호출 전에 rollback되므로 재시도가 외부 요청을 반복하지 않는다.
    """
    # 내장 TimeoutError·ConnectionError는 run 전체 시간 초과(`_run_with_session`)나 provider 전송 오류일 수도 있어
    # 여기서는 SQLAlchemy가 번역한 DB 오류(lock_timeout·statement_timeout·직렬화·교착·연결 무효화)만 본다.
    return any(isinstance(item, DBAPIError) and _is_transient_database_error(item) for item in _error_chain(error))


def _retry_budget_left(context: Any) -> bool:
    """같은 run 안의 재시도가 run 상한 전에 끝날 시간이 남았는가. 확인할 수 없으면 재시도하지 않는다."""
    try:
        record = context.instance.get_run_record_by_id(context.run_id)
        started = record.start_time if record is not None else None
        if started is None:
            return False
        delay = FUEL_RETRY_POLICY.delay or 0
        return MAX_RUNTIME_SECONDS - (time.time() - started) - 2 * delay >= MIN_RETRY_BUDGET_SECONDS
    except Exception:  # noqa: BLE001 — 재시도 판단의 실패는 재시도하지 않는 쪽으로 닫는다.
        return False


def _redact_op_errors(fn: Callable[..., Any] | None = None, *, retry_transient: bool = False) -> Any:
    """op에서 빠져나가는 예외를 가린 `Failure`로 바꾼다.

    공용 Dagster event log(`dagster_shared`)는 모든 테넌트 UI가 읽는다. Dagster는 step 실패의 `str(exc)`·
    traceback·`__cause__`/`__context__` 사슬을 그대로 직렬화하는데, code-server는 `app.main`의 logging
    filter를 import하지 않는다. 그래서 op 경계에서 예외 종류·가린 문장·코드 위치만 남기고 사슬은 끊는다.
    의도된 `Failure`(고정 문구·메타데이터)와 중단 신호(`_PASSTHROUGH_ERRORS`)는 그대로 둔다.
    기본은 `allow_retries=False`다. `retry_transient=True`로 감싼 op(유가·휴게소 유가, op `RetryPolicy` 보유)만
    DB 일시 오류(`_is_transient_failure`)이고 run 상한까지 시간이 남았을 때 step 재시도를 허용한다. 그 밖의
    op에는 RetryPolicy가 없고 run 재시도는 `retry_on_asset_or_op_failure=false`라 의미가 바뀌지 않는다.
    """

    if fn is None:
        return functools.partial(_redact_op_errors, retry_transient=retry_transient)

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except (Failure, *_PASSTHROUGH_ERRORS):
            raise
        except BaseException as exc:  # noqa: BLE001 — 경계에서 모든 원문을 가린다.
            retry = False
            if retry_transient:
                try:
                    retry = _is_transient_failure(exc) and bool(args) and _retry_budget_left(args[0])
                except Exception:  # noqa: BLE001
                    retry = False
            try:
                failure = _redacted_failure(exc, allow_retries=retry)
            except Exception:  # noqa: BLE001
                failure = Failure(description=f"{_type_name(exc)}: <unavailable>",
                                  metadata={"error_type": _type_name(exc)}, allow_retries=False)
            del exc
        # except 블록 밖에서 던져 __context__에도 원래 예외가 걸리지 않게 한다.
        failure.__suppress_context__ = True
        raise failure

    return wrapper


def job_max_runtime_seconds(job_name: str) -> int:
    return JOB_MAX_RUNTIME_SECONDS.get(job_name, MAX_RUNTIME_SECONDS)


def _recovery_policy(job_name: str) -> RecoveryPolicy:
    # provider 호출 실패는 자동 반복하지 않는다. 안전한 관측/기준 upsert만 인프라 재시도한다.
    idempotent = job_name in IDEMPOTENT_JOBS
    return RecoveryPolicy(job_max_runtime_seconds(job_name), idempotent=idempotent,
                          infrastructure_retries=1 if idempotent else 0)


def _job_tags(run_group: str, job_name: str) -> dict[str, str]:
    tags = _recovery_policy(job_name).tags(project="transport", job_name=job_name)
    return {**tags, "dagster/priority": str(JOB_PRIORITIES.get(job_name, 0)),
            "kortraveltransport/run_group": run_group, "dagster/code_location": "kor-travel-transport"}


#: op deadline이 run monitoring보다 먼저 끝내는 여유(초)와 최소 예산.
RUN_DEADLINE_MARGIN_SECONDS = 60
MIN_RUN_DEADLINE_SECONDS = 30


def _run_deadline_seconds(max_runtime_seconds: int) -> float:
    """이 op 안의 cancellation deadline: run 시작부터 잰 실행 상한까지 남은 시간 − 여유.

    run monitoring(`dagster/max_runtime`)은 run 시작부터 잰다. step이 여럿이거나(공항: 수집 → 기준정보 본문 준비) step 기동이
    늦으면 step 시작부터 잰 deadline은 monitoring보다 늦어 run이 밖에서 끊긴다. 실제 run의 태그·시작 시각을 읽고, 못 읽으면
    (Dagster 밖 호출·metadata 장애) step 시작부터 잰다.
    """
    lease = OWNER_LEASE.get()
    fallback = float(max_runtime_seconds - RUN_DEADLINE_MARGIN_SECONDS)
    if lease is None or lease.instance is None:
        return fallback
    try:
        record = call_with_deadline(lambda: lease.instance.get_run_record_by_id(lease.run_id), timeout_seconds=10)
        if record is None or record.start_time is None:
            return fallback
        limit = int((record.dagster_run.tags or {}).get("dagster/max_runtime", max_runtime_seconds))
        remaining = limit - (time.time() - record.start_time) - RUN_DEADLINE_MARGIN_SECONDS
        return max(float(MIN_RUN_DEADLINE_SECONDS), min(remaining, fallback))
    except Exception:  # noqa: BLE001 — 예산 계산의 실패가 수집을 막지 않는다.
        return fallback


async def _run_with_session(
    settings: Settings, action: Callable[..., Awaitable[dict[str, Any]]], *args: Any,
    max_runtime_seconds: int = MAX_RUNTIME_SECONDS, **kwargs: Any,
) -> dict[str, Any]:
    ensure_collection_owner_active()
    engine, session_factory = create_engine_and_session_factory(settings.database_url, collector=True)
    if OWNER.get() is not None:
        session_factory = owned_session_factory(engine, OWNER.get())
    try:
        async with session_factory() as session:
            try:
                # async provider는 cancellation 계약을 사용한다. native monitoring(run의 `dagster/max_runtime`)보다
                # 먼저 끝내 실패 상태를 직접 기록한다.
                async with asyncio.timeout(_run_deadline_seconds(max_runtime_seconds)):
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
            refresh_outcome: dict[str, Any] = {}
            result["analytics_cache_count"] = await refresh_default_analytics_cache(
                session, settings, outcome=refresh_outcome,
            )
            await session.commit()
            if refresh_outcome.get("skipped"):
                # lock 경합으로 건너뛰었다. 실패는 아니지만 이어지면 대시보드가 원본 계산으로 떨어진다(아래 판정이 본다).
                result["analytics_cache_skipped"] = refresh_outcome["skipped"]
        except Exception as exc:
            await session.rollback()
            result["analytics_cache_error"] = _redacted_causes([_sanitize_op_error(exc, _secret_forms())])
    # 사전집계가 밀렸는지(ANALYTICS-REFRESH-ALERT-20261124). 수집·갱신은 이미 commit/rollback했다. 판정은 인덱스 질의 셋이고,
    # 실패하거나 늦어도 수집 결과를 바꾸지 않는다. 서버 쪽 statement_timeout으로 질의를 끊고(연결을 망가뜨리지 않는다),
    # 클라이언트 timeout은 그 뒤의 안전망이다. 정리(rollback)의 오류·지연도 삼킨다.
    try:
        async with asyncio.timeout(ANALYTICS_HEALTH_TIMEOUT_SECONDS):
            if session.bind is not None and session.bind.dialect.name == "postgresql":
                await session.execute(text(f"SET LOCAL statement_timeout = {ANALYTICS_HEALTH_STATEMENT_TIMEOUT_MS}"))
            result["analytics_refresh"] = (await analytics_refresh_health(session, settings)).as_dict()
            await session.commit()  # SET LOCAL을 이 판정 transaction에서 끝낸다.
    except Exception as exc:  # noqa: BLE001 — 부가 판정 실패로 수집을 실패시키지 않는다.
        result["analytics_refresh_check_error"] = type(exc).__name__
        with contextlib.suppress(Exception):
            await asyncio.wait_for(session.rollback(), timeout=5)
    return result


#: 이번 실행에서 시도한 원천(공항 주차) 또는 호출(좌표 보강)이 모두 실패한 run 실패의 고정 오류 코드. 관리자 콘솔이 같은 코드로
#: 원인·대응 문구를 보인다(`lib/dagster-failure-diagnostics.ts`). 부분 실패 기준(건수·비율)과 무관하다(소유자 결정 2026-11-24).
ALL_SOURCES_FAILED = "ALL_SOURCES_FAILED"


def _all_parking_sources_failed(result: dict[str, Any]) -> bool:
    """이번 실행에서 시도한 주차 원천이 하나 이상이고 그 전부가 실패했는가(`CollectionService` 결과 계약)."""
    total, failed = result.get("parking_sources_total"), result.get("parking_sources_failed")
    return (result.get("status") in {"failed", "partial_success"} and type(total) is int and type(failed) is int
            and 0 < total <= failed)


def _all_parking_sources_description(result: dict[str, Any]) -> str:
    return (f"주차 원천 {result['parking_sources_total']}곳이 모두 실패했습니다(ALL_SOURCES_FAILED). 저장한 요금·이력은 "
            "유지했고 주차 현재값은 직전 성공 세대를 유지합니다.")


def _all_parking_sources_metadata(result: dict[str, Any], source_code: Any) -> dict[str, Any]:
    """주차 원천 전량 실패 run의 고정 metadata. `status`는 run 판정(실패)이고, DB 실행 상태(이력이 남으면 `partial_success`)는
    `collection_run_status`, 원래 원인 분류(쿼터·응답 규격 등)는 `source_error_code`로 따로 싣는다."""
    return {"run_id": result["collection_run_id"], "status": "failed", "retryable": False,
            "collection_run_status": str(result.get("status")), "error_code": ALL_SOURCES_FAILED,
            "stage": "provider_fetch", "recovery_hint": "CHECK_RUN_DETAIL", "successful_data_preserved": True,
            "parking_sources_total": result["parking_sources_total"],
            "parking_sources_failed": result["parking_sources_failed"],
            **({"source_error_code": source_code}
               if isinstance(source_code, str) and source_code not in {ALL_SOURCES_FAILED, "COLLECTION_FAILED"} else {})}


#: 사전집계 갱신 판정 질의의 상한. 서버 쪽 문장 상한(ms)과 클라이언트 안전망(초). 공용 PG가 멈춰도 공항 수집 run을 붙잡지 않는다.
ANALYTICS_HEALTH_STATEMENT_TIMEOUT_MS = 5000
ANALYTICS_HEALTH_TIMEOUT_SECONDS = 15
#: 사전집계가 밀렸을 때 공항 run에 다는 태그. 값은 `delayed`·`stale`·`missing`. run 상태(SUCCESS)는 바꾸지 않는다 —
#: 수집은 성공했으므로(감사 2026-11-23 §2.5: 부분 성공을 FAILURE로 올린 소음). Manager가 이 태그나
#: `/v1/transport/providers`의 `airport_analytics_cache.alerting`을 읽는 규칙은 아직 없다(Manager 후속, tasks.md
#: ANALYTICS-REFRESH-ALERT-20261124). 그때까지는 관리 화면 홈·Dagster 로그·결과 metadata로만 보인다.
ANALYTICS_REFRESH_TAG = "kortravel/analytics-refresh"


def _record_analytics_refresh(context, status: str) -> None:
    """자기 run에 사전집계 지연 태그를 단다. 부가 기록 장애로 수집을 실패시키지 않는다."""
    try:
        instance = getattr(context, "instance", None)
        run_id = getattr(context, "run_id", None)
        if instance is not None and run_id:
            instance.add_run_tags(run_id, {ANALYTICS_REFRESH_TAG: status})
    except Exception:
        with contextlib.suppress(Exception):
            context.log.warning("ANALYTICS_REFRESH_TAG_DEFERRED")


@op
@_redact_op_errors
def collect_airport_parking(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(
            settings, functools.partial(_collect_airport_with_analytics, settings=settings), trigger=AIRPORT_TRIGGER,
        ))
        cache_failed = "analytics_cache_error" in result
        cache_metadata = {"analytics_cache_error": result["analytics_cache_error"]} if cache_failed else {}
        if result.get("status") == "failed" or (
            result.get("status") == "partial_success" and not _has_collection_progress(result)
        ):
            if _all_parking_sources_failed(result):
                # 저장분도 없는 전면 장애(가장 흔한 모양)도 같은 고정 코드·원천 수로 보인다.
                source_code = _collection_failure_metadata(result, "airport").get("error_code")
                raise Failure(description=_all_parking_sources_description(result),
                              metadata={**_all_parking_sources_metadata(result, source_code), **cache_metadata},
                              allow_retries=False)
            raise Failure(description="공항 수집의 성공분은 저장했지만 일부 수집이 실패했습니다.",
                          metadata={"run_id": result["collection_run_id"], "status": result["status"], **cache_metadata},
                          allow_retries=False)
        if cache_failed or result.get("status") == "partial_success":
            result["collection_outcome"] = "partial"
            context.log.warning("공항 수집의 정상 저장분은 유지합니다. 미완료 원천·파생 캐시는 후속 실행에서 복구합니다.")
        if cache_failed:
            result["cache_refresh_failed"] = True
        metadata = _collection_output_metadata(result, "airport")
        health = result.get("analytics_refresh")
        if isinstance(health, dict):
            metadata["analytics_refresh_status"] = health["status"]
            if health.get("pending_seconds") is not None:
                metadata["analytics_pending_seconds"] = health["pending_seconds"]
            if health["status"] in ANALYTICS_REFRESH_ALERT_STATUSES:
                # 수집 성공 run만 partial로 올린다. 미뤄진(deferred)·이미 partial인 run의 결과·오류 코드는 그대로 두고
                # 원인은 태그로만 보인다.
                if metadata["collection_outcome"] == "success":
                    metadata["collection_outcome"] = "partial"
                    metadata["error_code"] = "DERIVED_CACHE_DEFERRED"
                # 운영 로그에서 바로 찾도록 한 줄 JSON(비밀·본문 없음).
                context.log.error(json.dumps({
                    "event": "analytics_refresh_alert", "status": health["status"],
                    "generated_at": health["generated_at"], "pending_since": health["pending_since"],
                    "pending_seconds": health["pending_seconds"], "cache_refresh_failed": cache_failed,
                    "cache_refresh_skipped": result.get("analytics_cache_skipped") is not None,
                }, separators=(",", ":")))
                _record_analytics_refresh(context, health["status"])
        if result.get("analytics_cache_skipped") is not None:
            metadata["cache_refresh_skipped"] = True
        if result.get("analytics_refresh_check_error"):
            metadata["analytics_refresh_check_error"] = result["analytics_refresh_check_error"]
            context.log.warning(f"공항 통계 사전집계 갱신 판정을 하지 못했습니다({result['analytics_refresh_check_error']}). "
                                "수집 결과는 그대로입니다.")
        if _all_parking_sources_failed(result):
            # 주차 원천(KAC·인천)이 하나도 성공하지 못했다(제공기관 전면 장애 또는 응답 계약 변경). 요금 갱신이나 거절
            # 원천의 이력 전용 저장이 있어도 주차 현재값은 갱신되지 않았으므로 부분 성공이 아니라 실패다(소유자 결정
            # 2026-11-24: 전량 실패는 건수와 무관하게 실패). 행 격리 상한(20%)·직전 값 유지(1시간)는 그대로다.
            # 사전집계 경보(태그·로그)를 남긴 뒤에 올린다. 원인 분류(쿼터·응답 규격 등)는 `source_error_code`로 둔다.
            source_code = metadata.get("error_code")
            raise Failure(description=_all_parking_sources_description(result),
                          metadata={**{key: value for key, value in metadata.items()
                                       if key not in {"retryable", "collection_outcome", "auto_retry"}},
                                    **cache_metadata, **_all_parking_sources_metadata(result, source_code)},
                          allow_retries=False)
        context.add_output_metadata(metadata)
        _record_collection_outcome(context, metadata["collection_outcome"])
        return result


async def _collect_transport_in_one_loop(
    settings: Settings, scope: CollectionScope, *, retry_failed_fuel: bool = False,
    scheduled_at: datetime | None = None,
) -> dict[str, Any]:
    """HTTP client의 생성·수집·종료를 하나의 event loop에서 끝낸다."""
    service = TransportCollectionService(settings)
    extra: dict[str, Any] = {"retry_failed_fuel": True} if retry_failed_fuel else {}
    if scheduled_at is not None:
        extra["scheduled_at"] = scheduled_at
    try:
        # highway의 trigger(`dagster_highway`)는 회수 sensor의 신선도 판정이 본다(`recovery.HIGHWAY_TRIGGER`).
        # deadline은 run의 실제 `dagster/max_runtime` 태그와 시작 시각으로 잰다(`_run_deadline_seconds`).
        return await _run_with_session(settings, service.collect, trigger=f"dagster_{scope}", scope=scope, **extra)
    finally:
        await asyncio.wait_for(service.close(), timeout=10)


#: 수집 서비스가 무효 원천 행을 격리하고 나머지를 저장했을 때의 오류 문장 표지(`isolated_rows_message`).
ISOLATED_ROWS_MARKER = "isolated invalid rows"
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


def _collection_failure_metadata(result: dict[str, Any], scope: str) -> dict[str, Any]:
    """관리자가 원문·키 없이 실패 단계와 이미 저장한 성공분을 구분한다."""
    errors = result.get("errors")
    messages = " ".join(item for item in errors if isinstance(item, str)) if isinstance(errors, (list, tuple)) else ""
    code, stage, hint, retryable = "COLLECTION_FAILED", "collection", "CHECK_RUN_DETAIL", False
    if "empty incident set after one re-fetch" in messages:
        # 상류(KREX 실시간 문자정보)가 돌발 0건을 두 번 돌려줬다. 마지막 정상 집합을 유지한다(INCIDENT-EMPTY-SET-20261124).
        code, stage, hint = "INCIDENT_EMPTY_SET", "provider_parse", "CHECK_RESPONSE_CONTRACT"
    elif "traffic flow response contains invalid records" in messages:
        code, stage, hint = "TRAFFIC_FLOW_INVALID_RECORDS", "provider_parse", "CHECK_RESPONSE_CONTRACT"
    elif "traffic flow count must match" in messages or "incomplete total_count" in messages:
        code, stage, hint = "TRAFFIC_FLOW_COUNT", "provider_parse", "CHECK_RESPONSE_CONTRACT"
    elif "Opinet browser action failed" in messages and "TimeoutError" in messages:
        code, stage, hint, retryable = "OPINET_BROWSER_TIMEOUT", "provider_fetch", "RETRY_AFTER_BACKOFF", True
    elif "Opinet browser resource policy failed" in messages:
        # 시각 자원 차단(CDP Fetch)의 일시 실패. 체크포인트에서 이어 하므로 재시도는 남은 지역만 요청한다.
        code, stage, hint, retryable = "OPINET_BROWSER_RESOURCE_POLICY", "provider_fetch", "RETRY_AFTER_BACKOFF", True
    elif any(marker in messages for marker in (
        "due to lock timeout", "due to statement timeout", "deadlock detected",
        "could not serialize access", "ConnectionDoesNotExistError", "connection was closed",
    )):
        code, stage, hint, retryable = "DATABASE_RETRYABLE", "storage", "RETRY_AFTER_BACKOFF", True
    elif re.search(r"\bEXCEEDED_LIMIT\b", messages) or any(
        word in messages.lower() for word in ("quota", "rate limit", "too many requests")
    ):
        code, stage, hint, retryable = "PROVIDER_RATE_LIMIT", "provider_fetch", "RETRY_AFTER_BACKOFF", True
    elif re.search(r"\b(?:INVALID_KEY|EXPIRED_KEY|NO_REGISTERED_KEY)\b", messages):
        code, stage = "PROVIDER_AUTH", "provider_fetch"
    elif "TimeoutError" in messages:
        code, stage, hint, retryable = "COLLECTION_TIMEOUT", "collection", "RETRY_AFTER_BACKOFF", True
    elif isinstance(errors, (list, tuple)) and errors and all(
        isinstance(item, str) and ISOLATED_ROWS_MARKER in item for item in errors
    ):
        # 원천은 성공(유효 행 저장)했고 일부 원천 행만 격리했다. 같은 응답의 재시도는 의미가 없다.
        code, stage, hint = "INVALID_ROWS_ISOLATED", "provider_parse", "CHECK_RESPONSE_CONTRACT"
    metadata: dict[str, Any] = {
        "error_code": code, "stage": stage, "scope": scope, "recovery_hint": hint,
        "retryable": retryable, "status": result["status"], "run_id": result["collection_run_id"],
        "error_count": len(errors) if isinstance(errors, (list, tuple)) else 0,
        "successful_data_preserved": True,
        # 소통 저장이 rollback된 실행도 어느 단계에서 얼마를 썼는지 보이게 한다(WLH-06).
        **_traffic_store_metadata(result),
    }
    for key in ("raw_response_count", "traffic_snapshot_count", "incident_snapshot_count", "fuel_station_count",
                "fuel_price_count", "isolated_rows"):
        value = result.get(key)
        if type(value) is int and 0 <= value <= 10_000_000:
            metadata[key] = value
    for key in ("received_rows", "parsed_rows", "invalid_rows"):
        match = re.search(rf"\b{key}=([0-9]{{1,8}})\b", messages)
        if match and int(match[1]) <= 10_000_000:
            metadata[key] = int(match[1])
    if result.get("skip_reason") == "collector_busy":
        metadata["skip_reason"] = "collector_busy"
    return metadata


def _has_collection_progress(result: dict[str, Any]) -> bool:
    """원천의 정상 응답 또는 실제 저장이 있는 부분 완료만 후속 처리를 계속한다."""
    return any(type(result.get(key)) is int and result[key] > 0 for key in (
        "raw_response_count", "snapshot_count", "fee_rule_count", "traffic_snapshot_count",
        "incident_snapshot_count", "fuel_station_count", "fuel_price_count",
    ))


#: 고속도로 소통 저장 계측 metadata 키(`TrafficStoreReport.summary`·`highway_fetch_seconds`, WLH-06).
#: 5분 통계: 원천 안 bucket이 쓴 행, 최근 창 재대조의 추가·수정·삭제(= 어긋남)·그대로 둔 행, 장기 복구 조각의 구간·행·시간.
TRAFFIC_STORE_COUNT_KEYS = (
    "traffic_inserted_rows", "traffic_changed_rows", "traffic_unchanged_rows", "traffic_touched_buckets",
    "traffic_out_of_window_buckets", "traffic_touched_statistics_rows",
    "traffic_statistics_inserted_rows", "traffic_statistics_updated_rows", "traffic_statistics_deleted_rows",
    "traffic_statistics_unchanged_rows", "traffic_statistics_drift_rows",
    "traffic_statistics_repair_chunks", "traffic_statistics_repair_inserted_rows",
    "traffic_statistics_repair_updated_rows", "traffic_statistics_repair_deleted_rows",
    "traffic_statistics_repair_unchanged_rows", "traffic_statistics_repair_drift_rows",
    "traffic_statistics_repair_busy_skips",
)
TRAFFIC_STORE_SECONDS_KEYS = (
    "highway_fetch_seconds", *(f"traffic_{step}_seconds" for step in TRAFFIC_STORE_STEPS),
    "traffic_statistics_repair_seconds",
)
TRAFFIC_STORE_REASON_KEYS = ("traffic_store_failure_reason", "traffic_statistics_deferred_reason")
TRAFFIC_STORE_BOOL_KEYS = (
    "traffic_source_committed", "traffic_statistics_refreshed", "traffic_statistics_repair_sweep_complete",
    "traffic_statistics_repair_budget_exhausted",
)
#: 장기 복구 구간 경계(UTC, 초 단위 `Z`). 형식이 맞는 값만 싣는다.
TRAFFIC_REPAIR_TIME_KEYS = (
    "traffic_statistics_repair_range_start", "traffic_statistics_repair_range_end",
    "traffic_statistics_repair_cursor", "traffic_statistics_repair_horizon_start",
)
_UTC_SECOND = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


def _database_reason(value: Any) -> bool:
    return isinstance(value, str) and (value in DATABASE_FAILURE_REASONS or re.fullmatch(r"sqlstate_[0-9A-Z]{2}", value))


def _traffic_store_metadata(result: dict[str, Any]) -> dict[str, Any]:
    """소통 저장의 행 분류·단계별 시간(초)·원인 코드. 값은 형식·범위를 검사한 고정 값만 싣는다."""
    metadata: dict[str, Any] = {}
    for key in TRAFFIC_STORE_COUNT_KEYS:
        value = result.get(key)
        if type(value) is int and 0 <= value <= 1_000_000_000:
            metadata[key] = value
    for key in TRAFFIC_STORE_SECONDS_KEYS:
        value = result.get(key)
        if type(value) is float and 0 <= value <= 86_400:
            metadata[key] = value
    for key in TRAFFIC_STORE_BOOL_KEYS:
        if type(result.get(key)) is bool:
            metadata[key] = result[key]
    if result.get("traffic_failed_step") in TRAFFIC_STORE_STEPS:
        metadata["traffic_failed_step"] = result["traffic_failed_step"]
    for key in TRAFFIC_STORE_REASON_KEYS:
        if _database_reason(result.get(key)):
            metadata[key] = result[key]
    if result.get("traffic_statistics_repair_status") in REPAIR_STATUSES:
        metadata["traffic_statistics_repair_status"] = result["traffic_statistics_repair_status"]
    repair_reason = result.get("traffic_statistics_repair_reason")
    if repair_reason in REPAIR_DEFER_REASONS or _database_reason(repair_reason):
        metadata["traffic_statistics_repair_reason"] = repair_reason
    for key in TRAFFIC_REPAIR_TIME_KEYS:
        value = result.get(key)
        if isinstance(value, str) and _UTC_SECOND.fullmatch(value):
            metadata[key] = value
    return metadata


def _collection_output_metadata(result: dict[str, Any], scope: str) -> dict[str, Any]:
    """Dagster 실행 완료와 원천 전체 갱신을 구분하는 안전한 결과 metadata."""
    status = result.get("status", "unknown")
    outcome = result.get("collection_outcome") or (
        "deferred" if status in {"skipped", "disabled", "not_ready"}
        else "partial" if status == "partial_success" else "success" if status == "success" else "unknown"
    )
    statistics_deferred = (
        status in {"success", "partial_success"}
        and (result.get("fuel_statistics_published") is False
             or result.get("traffic_statistics_refreshed") is False)
    )
    if statistics_deferred:
        outcome = "partial"
    metadata: dict[str, Any] = {
        "status": status, "collection_outcome": outcome, "previous_data_preserved": True,
    }
    for key in ("collection_run_id", "raw_response_count", "snapshot_count", "fee_rule_count",
                "traffic_snapshot_count", "incident_snapshot_count", "fuel_station_count", "fuel_price_count",
                "isolated_rows", "parking_sources_total", "parking_sources_failed"):
        value = result.get(key)
        if type(value) is int and 0 <= value <= 1_000_000_000:
            metadata[key] = value
    for key in ("fuel_ready", "fuel_statistics_published", "cache_refresh_failed"):
        if type(result.get(key)) is bool:
            metadata[key] = result[key]
    # 고속도로 소통 저장의 행 분류·단계별 시간(초)·원인 코드(WLH-06). 운영 175초+ 저장 transaction을 단계별로 본다.
    metadata.update(_traffic_store_metadata(result))
    # 이전 통계 세대 정리(원천 성공과 분리). 실패·예산 소진도 결과 종류와 행 수로 보이게 한다.
    if result.get("fuel_statistics_cleanup") in {"done", "budget_exhausted", "failed"}:
        metadata["fuel_statistics_cleanup"] = result["fuel_statistics_cleanup"]
        pruned = result.get("fuel_statistics_pruned_rows")
        if type(pruned) is int and 0 <= pruned <= 1_000_000_000:
            metadata["fuel_statistics_pruned_rows"] = pruned
    if outcome == "partial" and result.get("errors"):
        detail = result
        if "collection_run_id" not in result and "run_id" in result:
            # 휴게소 수집도 실제 run 식별자를 같은 진단 경계로 전달한다.
            detail = {**result, "collection_run_id": result["run_id"]}
        metadata.update(_collection_failure_metadata(detail, scope))
    if outcome == "deferred":
        metadata["error_code"] = "COLLECTION_DEFERRED"
        metadata["deferred_reason"] = (
            "collector_busy" if result.get("skip_reason") == "collector_busy" else "cooldown_or_disabled"
        )
    elif (
        result.get("cache_refresh_failed") is True or statistics_deferred
    ) and not result.get("errors"):
        metadata["error_code"] = "DERIVED_CACHE_DEFERRED"
    return metadata


def _scheduled_execution_time(context: Any) -> datetime | None:
    """정기 schedule tick이 띄운 run의 tick 시각(`dagster/scheduled_execution_time`). 수동·재시도 run은 None."""
    try:
        value = (context.run.tags or {}).get("dagster/scheduled_execution_time")
        if not value:
            return None
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else None
    except Exception:  # noqa: BLE001 — 읽지 못하면 시작 기준(예전 동작)이다.
        return None


def _collect_transport(
    scope: CollectionScope, *, retry_failed_fuel: bool = False, retry_budget: Callable[[], bool] | None = None,
    scheduled_at: datetime | None = None,
) -> dict[str, Any]:
    result = asyncio.run(_collect_transport_in_one_loop(
        _settings(), scope, retry_failed_fuel=retry_failed_fuel, scheduled_at=scheduled_at,
    ))
    # 성공분·실패 상태를 커밋하고 provider를 닫은 뒤 Dagster에도 실패를 전달한다.
    # 원인은 가린 한 줄로 설명에 싣는다(다음 진단이 DB를 보지 않아도 되게). 기존 호출 유예를 자동 재시도로
    # 우회하지 않는다.
    if result.get("status") == "failed" or (
        result.get("status") == "partial_success" and not _has_collection_progress(result)
    ):
        errors = result.get("errors")
        reason = ", skip_reason=collector_busy" if result.get("skip_reason") == "collector_busy" else ""
        description = (f"교통정보 수집에 실패했습니다(status={result['status']}{reason}): {_redacted_causes(errors)}. "
                       "저장된 성공분과 호출 유예는 유지합니다.")
        if len(description) > MAX_FAILURE_DESCRIPTION_CHARS:
            description = description[: MAX_FAILURE_DESCRIPTION_CHARS - 3] + "..."
        metadata = _collection_failure_metadata(result, scope)
        # 쿼터·차단·인증·파싱 오류는 자동 반복하지 않는다. 일시 오류만 op RetryPolicy가 같은 run에서 다시 한다.
        # 남은 run 시간은 실패한 시점(브라우저 수집 1~2시간 뒤)에 잰다.
        auto_retry = (retry_budget is not None and metadata["error_code"] in AUTO_RETRY_ERROR_CODES
                      and retry_budget())
        metadata["auto_retry"] = auto_retry
        raise Failure(
            description=description,
            metadata=metadata,
            allow_retries=auto_retry,
        )
    if result.get("status") == "partial_success":
        result["collection_outcome"] = "partial"
    elif result.get("status") == "skipped":
        result["collection_outcome"] = "deferred"
    return result


#: 고속도로 op 동안 Dagster event log로 넘기는 logger(소통 저장 단계 시간·통계 재대조 지연, WLH-06).
HIGHWAY_PROGRESS_LOGGERS = ("app.services.transport_collection",)


@op
@_redact_op_errors
def collect_highway_transport(context) -> dict[str, Any]:
    # 소통 저장 단계 시간 한 줄과 통계 재대조 지연 경고(가린 원인)를 Dagster event log로 넘긴다.
    with collection_owner(context.run_id, context.instance), _forward_progress_logs(context, HIGHWAY_PROGRESS_LOGGERS):
        result = _collect_transport("highway", scheduled_at=_scheduled_execution_time(context))
        metadata = _collection_output_metadata(result, "highway")
        context.add_output_metadata(metadata)
        _record_collection_outcome(context, metadata["collection_outcome"])
        if result.get("collection_outcome") == "partial":
            context.log.warning("고속도로 수집의 정상 원천은 저장했습니다. 실패한 원천은 후속 주기에 다시 수집합니다.")
        if result.get("traffic_statistics_refreshed") is False:
            reason = metadata.get("traffic_statistics_deferred_reason", "unknown")
            context.log.warning(f"고속도로 소통 5분 통계의 최근 두 시간 재대조가 미뤄졌습니다(reason={reason}). "
                                "원본·current·이번 원본의 bucket 통계·성공 상태는 저장했고 다음 정기 수집이 최근 두 "
                                "시간을 다시 맞춥니다.")
        _warn_traffic_statistics_drift(context, metadata)
        return result


def _warn_traffic_statistics_drift(context: Any, metadata: dict[str, Any]) -> None:
    """5분 통계 어긋남(재대조가 바꾼 행)과 장기 복구 실패를 경고 한 줄로 남긴다. 수집 결과(outcome)는 바꾸지 않는다.

    원천 transaction이 자기 bucket을 함께 맞추므로 정상이면 어긋남은 0이다. 재대조가 이미 고쳤으므로 실패가 아니다.
    """
    drift = metadata.get("traffic_statistics_drift_rows", 0)
    if drift:
        context.log.warning(
            f"고속도로 소통 5분 통계 최근 두 시간이 원본과 달라 {drift}행을 바로잡았습니다(추가 "
            f"{metadata.get('traffic_statistics_inserted_rows', 0)}·수정 {metadata.get('traffic_statistics_updated_rows', 0)}·"
            f"삭제 {metadata.get('traffic_statistics_deleted_rows', 0)}). 반복되면 수집 실패 이력과 수동 수정 여부를 확인하세요.")
    repair_drift = metadata.get("traffic_statistics_repair_drift_rows", 0)
    if repair_drift:
        context.log.warning(
            f"고속도로 소통 5분 통계 장기 복구가 {metadata.get('traffic_statistics_repair_range_start', '?')}~"
            f"{metadata.get('traffic_statistics_repair_range_end', '?')}(UTC)에서 원본과 다른 {repair_drift}행을 "
            "바로잡았습니다.")
    if metadata.get("traffic_statistics_repair_status") == "failed":
        context.log.warning(
            "고속도로 소통 5분 통계 장기 복구 구간이 실패했습니다"
            f"(reason={metadata.get('traffic_statistics_repair_reason', 'unknown')}). 수집 결과는 그대로이고 다음 "
            "정기 수집이 같은 위치부터 더 좁은 구간으로 다시 합니다(세 번 연속 실패하면 한 시간씩 쉽니다).")


#: 유가 op 동안 Dagster event log로 넘기는 logger. 오피넷 수집기의 단계별 진행(지역 탐색, 탭별 시도 진행,
#: 경과 시간)과 수집 서비스의 수집·저장 경과 시간, 유가 통계 발행 지연의 한 줄 원인이다. code-server는 logging을
#: 설정하지 않아 INFO가 버려지고 경고도 event log에 닿지 않는다.
FUEL_STATISTICS_LOGGERS = ("app.services.fuel_statistics",)
FUEL_PROGRESS_LOGGERS = ("opinet.experimental.browser", "app.services.transport_collection", *FUEL_STATISTICS_LOGGERS)
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


def _fuel_retry_requested(context: Any) -> bool:
    """이 시도가 실패한 유가 수집의 재시도인가(op 자동 재시도 또는 관리자 "재시도" run)."""
    if int(getattr(context, "retry_number", 0) or 0) > 0:
        return True
    try:
        return bool((context.run.tags or {}).get(ADMIN_RETRY_TAG))
    except Exception:  # noqa: BLE001 — 태그를 못 읽으면 정기 실행으로 본다(예약을 앞당기지 않는 쪽).
        return False


@op(retry_policy=FUEL_RETRY_POLICY)
@_redact_op_errors(retry_transient=True)
def collect_fuel_transport(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance), _forward_progress_logs(context):
        retry = _fuel_retry_requested(context)
        if retry:
            context.log.warning("유가 수집 재시도: 직전 시도가 실패였을 때만 정기 예약을 앞당겨 체크포인트에서 이어 합니다.")
        result = _collect_transport("fuel", retry_failed_fuel=retry,
                                    retry_budget=functools.partial(_retry_budget_left, context))
        context.add_output_metadata({key: value for key, value in result.items()
                                     if key in {"status", "collection_run_id", "fuel_station_count", "fuel_price_count",
                                                "fuel_ready", "next_fuel_due_at", "last_fuel_success_at", "skip_reason",
                                                "fuel_statistics_published"}})
        metadata = _collection_output_metadata(result, "fuel")
        context.add_output_metadata(metadata)
        _record_collection_outcome(context, metadata["collection_outcome"])
        if result.get("status") == "skipped":
            if result.get("skip_reason") == "collector_busy":
                context.log.warning("유가 수집은 다른 수집기가 체크포인트를 사용 중이어서 실행하지 않았습니다(status=skipped).")
            else:
                context.log.warning("유가 수집은 호출 유예 중이어서 실행하지 않았습니다(status=skipped).")
        return result


#: 장소 좌표 보강(VWorld·카카오)의 호출 실패를 run 실패로 올리는 기준. 좌표 보강은 기준정보 저장 뒤의 부가 단계이고
#: 실패한 대상은 영수증 TTL(VWorld·카카오 모두 연속 실패에 따라 1~30일)이 지나면 다시 호출되므로, 대상 몇 곳의 실패는
#: 부분 성공(run SUCCESS + `kortravel/collection-outcome=partial` + 실패 건수 metadata·경고)으로 둔다.
#: 실패로 남기는 것: (1) 수집 자체가 예외로 끝남(`status=failed`), (2) 인증·쿼터·연속 실패로 이번 실행을 멈춤
#: (`provider_blocked`), (3) **이번 실행의 호출이 전부 실패**(제공기관 전면 장애 — 건수와 무관), (4) 실패가
#: `PLACE_FAILURE_MIN_FAILED_CALLS`건 이상이면서 호출의 `PLACE_FAILURE_MAX_RATIO` 이상, (5) 유예로도 호출 실패로도
#: 설명되지 않는 `partial_success`.
#: 운영(2026-11-04~23 odroid): bus_reference·place_location 실패 11건이 전부 같은 철도역 주소 1곳의 VWorld 서버
#: 오류(호출 1건 중 1건 실패)였고, 그 실패가 좌표 보강 뒤의 export 준비까지 건너뛰게 했다(검색어는 #260에서 고쳤다).
#: (3)은 소유자 결정(2026-11-24): 하루 호출이 1~2건뿐이라 (4)만으로는 제공기관이 완전히 죽어도 매일 녹색 부분 완료로만
#: 남는다. 호출이 전부 실패한 실행은 대상 몇 곳의 결함과 구분할 수 없으므로 실패로 올린다 — 같은 대상 하나가 계속
#: 실패하면 영수증 대기(연속 실패 n번째 뒤 2^(n-1)일, 최대 30일) 간격으로 실패 run이 보인다.
PLACE_FAILURE_MIN_FAILED_CALLS = 3
PLACE_FAILURE_MAX_RATIO = 0.5


def _place_call_counts(result: dict[str, Any]) -> tuple[int, int]:
    """(실패 호출 수, 호출 수). 호출 수가 없거나 실패보다 작으면 실패 수를 호출 수로 본다."""
    failed = int(result.get("provider_failed", 0) or 0)
    return failed, max(int(result.get("provider_calls", 0) or 0), failed)


def _place_all_calls_failed(result: dict[str, Any]) -> bool:
    """이번 실행의 호출이 하나 이상이고 하나도 성공하지 않았는가(제공기관 전면 장애와 구분할 수 없는 실행)."""
    failed, calls = _place_call_counts(result)
    return bool(failed) and failed >= calls


def _place_collection_error(result: dict[str, Any]) -> bool:
    """장소 좌표 조회 결과가 run 실패인가(유예·부분 실패와 구분한다). 기준은 `PLACE_FAILURE_*` 주석."""
    status = result.get("status")
    if status == "failed" or result.get("provider_blocked", 0):
        return True
    failed, calls = _place_call_counts(result)
    if _place_all_calls_failed(result):
        # 이번 실행의 호출이 하나도 성공하지 않았다(제공기관 전면 장애). 호출 수와 무관하게 실패다.
        return True
    if failed >= PLACE_FAILURE_MIN_FAILED_CALLS and failed >= PLACE_FAILURE_MAX_RATIO * calls:
        return True
    return status == "partial_success" and not result.get("deferred", 0) and not failed


def _place_collection_partial(result: dict[str, Any]) -> bool:
    """run 실패는 아니지만 이번 실행에 제공기관 호출 실패가 있었는가(부분 성공)."""
    return not _place_collection_error(result) and bool(result.get("provider_failed", 0))


def _place_metadata(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result.get(key, default) for key, default in (
        ("run_id", ""), ("status", ""), ("provider_calls", 0), ("deferred", 0), ("provider_failed", 0),
        ("provider_blocked", 0), ("incomplete", 0), ("unmatched", 0), ("bus_locations", 0), ("port_locations", 0),
        ("rail_locations", 0), ("backoff_skipped", 0))}


def _place_failure_code(*results: dict[str, Any]) -> dict[str, Any]:
    """좌표 실패가 '호출 전량 실패'뿐이면 고정 오류 코드를 단다(그 밖의 실패 사유는 예전처럼 코드 없이 둔다)."""
    if results and all(_place_all_calls_failed(result) and result.get("status") != "failed"
                       and not result.get("provider_blocked", 0) for result in results):
        return {"error_code": ALL_SOURCES_FAILED, "stage": "provider_fetch", "recovery_hint": "CHECK_RUN_DETAIL",
                "successful_data_preserved": True}
    return {}


def _finish_place_collection(context, result: dict[str, Any], provider: str) -> dict[str, Any]:
    """독립 장소 좌표 job의 끝맺음. bus_reference의 좌표 보강과 같은 규칙(`_place_collection_error`)이다."""
    metadata = _place_metadata(result)
    if _place_collection_error(result):
        raise Failure(description=f"{provider} 장소 위치 조회 중 제공기관 호출이 실패했습니다"
                                  f"(provider_failed={metadata['provider_failed']}, "
                                  f"provider_calls={metadata['provider_calls']}, "
                                  f"provider_blocked={metadata['provider_blocked']}, status={metadata['status']}). "
                                  "성공분은 저장했고 유예분은 다음 정기 수집에서 다시 봅니다.",
                      metadata={**metadata, **_place_failure_code(result),
                                **({"status": "failed", "collection_run_status": str(metadata["status"])}
                                   if _place_failure_code(result) else {})},
                      allow_retries=False)
    if _place_collection_partial(result):
        metadata["collection_outcome"] = "partial"
        context.log.warning(f"{provider} 장소 위치 조회에서 {metadata['provider_failed']}건의 호출이 실패했습니다"
                            f"(호출 {metadata['provider_calls']}건). 실패한 대상은 영수증 대기 뒤 다시 조회합니다.")
    if metadata["deferred"]:
        context.log.warning(f"{provider} 장소 위치 조회에서 {metadata['deferred']}건이 유예됐습니다"
                            f"{'' if metadata['provider_failed'] else '(오류 없음)'}. 다음 정기 수집에서 다시 봅니다.")
    context.add_output_metadata(metadata)
    if metadata.get("collection_outcome") == "partial":
        _record_collection_outcome(context, "partial")
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
def collect_general_rail_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        return asyncio.run(_run_with_session(settings, GeneralRailReferenceCollectionService(settings).collect))


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


@op(config_schema={"rail_only": Field(bool, default_value=False, is_required=False)})
@_redact_op_errors
def collect_place_locations(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        service = PlaceLocationCollectionService(settings)
        async def rail_only(session):
            return await service.collect(session, kinds={"rail"})
        collector = rail_only if context.op_config.get("rail_only", False) else service.collect
        result = asyncio.run(_run_with_session(settings, collector))
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
                             f"{name}_provider_calls": result.get("provider_calls", 0),
                             f"{name}_provider_failed": result.get("provider_failed", 0),
                             f"{name}_provider_blocked": result.get("provider_blocked", 0)})
        # 실제 오류만 실패로 올린다(`_place_collection_error`: 예외로 끝난 수집, 인증·쿼터·연속 실패로 멈춤, 호출 전량
        # 실패, 실패가 많고 비율도 높은 호출, 설명 없는 부분 성공 / `_reference_error`: 이번 실행의 기항지 위치 조회 실패).
        # 유예(일일 호출 예산, 429 유예, 검색 결과가 페이지 상한을 넘어 확정할 수 없는 `incomplete`, 항구 기항지
        # 조회의 실패 TTL·예산)와 (다른 호출이 성공한 날의) 대상 몇 곳의 좌표 호출 실패는 기준정보를 저장한 정상 결과다 —
        # 같은 대상이 매일 실패해 job이 매일 FAILURE가 되면 진짜 장애가 묻힌다. 결정적으로 실패하는 대상은 영수증 대기
        # (VWorld·카카오 모두 연속 실패 n번째 뒤 2^(n-1)일, 최대 30일)로 호출 자체를 줄인다. 그래도 그 대상 하나만 호출한
        # 날은 호출 전량 실패라 FAILURE이고, 이때 뒤의 export 준비(`prepare_reference_exports`)는 건너뛴다 — 공항 job이
        # 5분마다 같은 준비를 하므로 지연은 짧다(소유자 결정 2026-11-24가 받아들인 비용). 부분 실패는
        # `collection_outcome=partial` 태그·metadata·경고로 남긴다.
        failed = [name for name, failed in (
            ("reference", _reference_error(reference_result)),
            ("vworld", _place_collection_error(vworld)),
            ("kakao", _place_collection_error(kakao)),
        ) if failed]
        if failed:
            raise Failure(description=(
                f"제공기관 호출 실패가 있습니다({', '.join(failed)}): 예외로 끝난 수집, 인증·쿼터·연속 실패로 멈춤, "
                "호출 전량 실패(건수 무관), "
                f"호출 실패 {PLACE_FAILURE_MIN_FAILED_CALLS}건 이상·{int(PLACE_FAILURE_MAX_RATIO * 100)}% 이상, "
                "또는 이번 실행의 기항지 위치 조회 실패(reference_failed_calls>0). 유예만 있거나, 다른 호출이 성공한 날 대상 "
                "몇 곳만 실패한 것은 실패가 아닙니다. 기준정보와 좌표 보강의 성공분은 저장했습니다."),
                metadata={**metadata, "failed_parts": ",".join(failed),
                          **(_place_failure_code(*({"vworld": vworld, "kakao": kakao}[name] for name in failed))
                             if "reference" not in failed else {})},
                allow_retries=False)
        partial = [name for name, result in (("vworld", vworld), ("kakao", kakao)) if _place_collection_partial(result)]
        if partial:
            metadata["collection_outcome"] = "partial"
            metadata["partial_parts"] = ",".join(partial)
            failed_calls = sum(int(result.get("provider_failed", 0) or 0) for result in (vworld, kakao))
            context.log.warning(f"장소 좌표 보강에서 {failed_calls}건의 호출이 실패했습니다({', '.join(partial)}). "
                                "기준정보와 성공한 좌표는 저장했고 실패한 대상은 영수증 대기 뒤 다시 조회합니다.")
        deferred = sum(int(result.get("deferred", 0) or 0) for result in (vworld, kakao))
        if deferred and not partial:
            context.log.warning(f"장소 좌표 보강에서 {deferred}건이 유예됐습니다(오류 없음). 다음 정기 수집에서 다시 봅니다.")
        reference_deferred = int(reference_result.get("port_location_deferred_count", 0) or 0)
        if reference_deferred:
            context.log.warning(f"기항지 위치 조회에서 {reference_deferred}건이 유예됐습니다(이번 실행의 호출 실패 없음). "
                                "다음 정기 수집에서 다시 봅니다.")
        context.add_output_metadata(metadata)
        if partial:
            _record_collection_outcome(context, "partial")
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
def collect_general_rail_timetable(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, GeneralRailCollectionService(settings).collect))
        if result.get("status") == "failed":
            raise Failure(description="일반철도 시간표 갱신 실패. 이전 정상 저장본은 유지했습니다.", allow_retries=False)
        return result


@op
@_redact_op_errors
def collect_rest_area_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        return asyncio.run(_run_with_session(settings, RestAreaCollectionService(settings).collect_references))


@op
@_redact_op_errors
def collect_public_parking_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, PublicParkingCollectionService(settings).collect))
        if result.get("status") == "failed":
            raise Failure(description="전국주차장 기준정보 갱신 실패. 이전 완료 집합을 보존했습니다.", allow_retries=False)
        return result


@job(tags=_job_tags("reference", "public_parking_reference_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def public_parking_reference_job() -> None:
    collect_public_parking_reference()


@op(retry_policy=REST_AREA_FUEL_RETRY_POLICY)
@_redact_op_errors(retry_transient=True)
def collect_rest_area_fuel_prices(context) -> dict[str, Any]:
    # 통계 발행이 미뤄지면(포화된 ARM의 command_timeout 등) 원인을 event log와 output metadata에서 보이게 한다.
    with collection_owner(context.run_id, context.instance), _forward_progress_logs(context, FUEL_STATISTICS_LOGGERS):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, RestAreaCollectionService(settings).collect_fuel_prices))
        metadata = _collection_output_metadata(result, "fuel")
        context.add_output_metadata(metadata)
        _record_collection_outcome(context, metadata["collection_outcome"])
        return result


@op
@_redact_op_errors
def collect_rest_area_food(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        return asyncio.run(_run_with_session(settings, RestAreaCollectionService(settings).collect_food))


@job(tags=_job_tags("reference", "rest_area_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def rest_area_reference_collection_job() -> None:
    collect_rest_area_reference()


@job(tags=_job_tags("reference", "rest_area_food_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def rest_area_food_collection_job() -> None:
    collect_rest_area_food()


@job(tags=_job_tags("reference", "rest_area_fuel_price_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def rest_area_fuel_price_collection_job() -> None:
    collect_rest_area_fuel_prices()


@job(tags=_job_tags("reference", "kric_timetable_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def kric_timetable_collection_job() -> None:
    collect_kric_timetable()


@job(tags=_job_tags("reference", "general_rail_timetable_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def general_rail_timetable_collection_job() -> None:
    collect_general_rail_timetable()


@op
@_redact_op_errors
def prepare_reference_exports(context, upstream: Any = None, other: Any = None) -> dict[str, Any]:
    settings = _settings()
    if not getattr(settings, "transport_map_current_enabled", False):
        result = {"status": "disabled", "prepared": 0, "reused": 0, "kinds": []}
        context.add_output_metadata({"status": "disabled", "collection_outcome": "deferred"})
        _record_collection_outcome(context, "deferred")
        return result
    dedicated = context.job_name == REFERENCE_EXPORT_PREPARE_JOB
    with collection_owner(context.run_id, context.instance):
        # 전체 예산 하나를 모든 종류·경합 재시도·정리가 나눠 쓴다. run deadline(`_run_with_session`의 cancellation)보다
        # 먼저 끝나야 종류별 결과가 남는다. 수집 job 꼬리는 5분 주기를 막지 않게 더 짧게 둔다.
        cap = PREPARE_TOTAL_BUDGET_SECONDS if dedicated else COLLECTION_TAIL_PREPARE_BUDGET_SECONDS
        budget = max(0.0, min(float(cap), _run_deadline_seconds(MAX_RUNTIME_SECONDS) - PREPARE_DEADLINE_RESERVE_SECONDS))
        result = asyncio.run(_run_with_session(settings, functools.partial(
            prepare_reference_export_bodies, settings=settings, total_budget_seconds=budget)))
    report_reference_prepare(context, result, dedicated=dedicated)
    return result


#: 준비 예산을 run deadline보다 이만큼 먼저 끝낸다(정리 commit·세션 정리 여유).
PREPARE_DEADLINE_RESERVE_SECONDS = 10
#: 준비 자체가 목적인 전용 job. 이 job에서만 "한 종류도 준비하지 못함"이 run 실패다.
REFERENCE_EXPORT_PREPARE_JOB = "reference_export_prepare_job"
#: 이번 run에서 busy였던 종류(쉼표 구분). 다음 run이 연속 busy를 세는 데 쓴다.
REFERENCE_BUSY_TAG = "kortravel/reference-export-busy"
#: 준비 결과 중 공용 event log에 남겨도 되는 종류별 필드(값은 코드 상수·숫자·예외 종류·SQLSTATE뿐이다).
_REFERENCE_PREPARE_KIND_FIELDS = ("kind", "status", "duration_ms", "item_count", "source_status",
                                  "error_type", "sqlstate", "reason")


def _reference_prepare_metadata(result: dict[str, Any]) -> dict[str, Any]:
    # 최상위 `status`는 쓰지 않는다. 관리 콘솔은 `status: failed`를 "저장 결과: 실패"로 읽는데, 수집 job 꼬리의 준비
    # 실패는 수집 실패가 아니다. 준비 결과는 `reference_status`로 따로 둔다.
    metadata: dict[str, Any] = {"reference_status": str(result.get("status", "unknown"))}
    for key in ("prepared", "reused", "busy", "deferred", "failed"):
        metadata[key] = int(result.get(key) or 0)
    rows = result.get("kinds") or []
    kinds = [{key: row[key] for key in _REFERENCE_PREPARE_KIND_FIELDS if key in row} for row in rows]
    if kinds:
        metadata["kinds"] = kinds
    for status in ("failed", "busy", "deferred"):
        names = [row["kind"] for row in rows if row.get("status") == status]
        if names:
            metadata[f"{status}_kinds"] = ",".join(names)
    gc = result.get("gc")
    if isinstance(gc, dict):
        for key in ("expired_handles", "unused_artifacts", "duration_ms"):
            if type(gc.get(key)) is int:
                metadata[f"gc_{key}"] = gc[key]
        if gc.get("busy") is True:
            metadata["gc_busy"] = True
        if gc.get("skipped") == "budget":
            metadata["gc_skipped"] = "budget"
        if isinstance(gc.get("error"), dict):
            metadata["gc_error_type"] = str(gc["error"].get("error_type", "unknown"))
    return metadata


def _persistent_busy_kinds(context, busy_kinds: list[str]) -> set[str]:
    """이번 run과 같은 job의 직전 완료 run들에서도 계속 busy였던 종류(연속 `BUSY_ESCALATION_STREAK`회)."""
    previous = BUSY_ESCALATION_STREAK - 1
    try:
        from dagster import DagsterRunStatus, RunsFilter

        # 공용 instance에는 다른 테넌트의 run도 있다. 이 run의 code location 태그가 있으면 같은 location으로 한정한다.
        location = (getattr(context.run, "tags", None) or {}).get("dagster/code_location")
        runs = call_with_deadline(lambda: context.instance.get_runs(
            filters=RunsFilter(job_name=context.job_name,
                               statuses=[DagsterRunStatus.SUCCESS, DagsterRunStatus.FAILURE],
                               tags={"dagster/code_location": location} if location else None),
            limit=previous,
        ), timeout_seconds=10)
    except Exception:  # noqa: BLE001 — 연속 판정을 못 하면 올리지 않는다(이번 결과는 그대로 busy).
        return set()
    if len(runs) < previous:
        return set()
    persistent = set(busy_kinds)
    for run in runs:
        persistent &= set(((run.tags or {}).get(REFERENCE_BUSY_TAG) or "").split(","))
    return persistent


def report_reference_prepare(context, result: dict[str, Any], *, dedicated: bool) -> dict[str, Any]:
    """준비 결과를 Dagster metadata·run 태그·경고로 남긴다(수집 job 꼬리, 전용 job, 주소 갱신 뒤 공통).

    - 일부 실패: 부분 완료(`REFERENCE_EXPORT_PARTIAL`). 전부 실패: 전용 job은 run 실패, 그 밖은 부분 완료
      (`REFERENCE_EXPORT_FAILED`) — 수집은 이미 commit됐고 첫 export 요청이 본문을 직접 구성한다.
    - 예산 소진(`deferred` 종류)·원천 미완결(`not_ready`): 이월(`REFERENCE_EXPORT_DEFERRED`).
    - 경합(`busy`): 이월(`REFERENCE_EXPORT_BUSY`). 같은 종류가 연속 `BUSY_ESCALATION_STREAK`회면 실패로 올린다.
    `context`가 없으면(Dagster 밖) 로그만 남긴다.
    """
    from app.services.reference_export_preparation import escalate_persistent_busy

    log = context.log if context is not None else logging.getLogger(__name__)
    busy_kinds = [row["kind"] for row in result.get("kinds") or [] if row.get("status") == "busy"]
    if busy_kinds and context is not None:
        persistent = _persistent_busy_kinds(context, busy_kinds)
        if persistent:
            escalate_persistent_busy(result, persistent)
            log.warning(f"기준정보 파생 본문({', '.join(sorted(persistent))})이 연속 {BUSY_ESCALATION_STREAK}회 경합으로 "
                        "준비되지 않았습니다. 잠금을 쥔 세션(idle in transaction 등)을 확인하세요.")
    metadata = _reference_prepare_metadata(result)
    status = result.get("status")
    failed = metadata.get("failed_kinds", "").replace(",", ", ")
    if status == "failed" and dedicated:
        raise Failure(description="기준정보 파생 본문을 한 종류도 준비하지 못했습니다. 마지막 정상 본문은 유지되고, "
                                  "첫 조회가 같은 본문을 직접 구성합니다.",
                      metadata={**metadata, "error_code": "REFERENCE_EXPORT_FAILED", "previous_data_preserved": True},
                      allow_retries=False)
    outcome = error_code = None
    if status in {"partial_success", "failed"}:
        outcome, error_code = "partial", ("REFERENCE_EXPORT_PARTIAL" if status == "partial_success" else "REFERENCE_EXPORT_FAILED")
        log.warning(f"기준정보 파생 본문({failed})을 준비하지 못했습니다. 수집 결과와 마지막 정상 본문은 유지되고, "
                    "실패한 종류는 다음 준비나 첫 export 요청이 다시 구성합니다.")
    elif status == "not_ready":
        outcome, error_code = "deferred", "REFERENCE_EXPORT_DEFERRED"
        log.warning("완결된 기준정보가 아직 없어 파생 본문 준비를 미룹니다. 마지막 정상 본문을 유지합니다.")
    elif metadata.get("deferred_kinds"):
        outcome, error_code = "deferred", "REFERENCE_EXPORT_DEFERRED"
        log.warning(f"기준정보 파생 본문({metadata['deferred_kinds'].replace(',', ', ')})은 준비 시간 예산을 다 써 "
                    "다음 준비로 미뤘습니다.")
    elif metadata.get("busy_kinds"):
        outcome, error_code = "deferred", "REFERENCE_EXPORT_BUSY"
        log.warning(f"기준정보 파생 본문({metadata['busy_kinds'].replace(',', ', ')})은 다른 준비가 만드는 중이라 "
                    "이번에는 건너뜁니다.")
    if outcome is not None:
        metadata.update({"collection_outcome": outcome, "error_code": error_code, "previous_data_preserved": True})
    if context is None:
        return metadata
    context.add_output_metadata(metadata)
    if outcome is not None:
        _record_collection_outcome(context, outcome)
    if metadata.get("busy_kinds"):
        with contextlib.suppress(Exception):
            call_with_deadline(lambda: context.instance.add_run_tags(
                context.run_id, {REFERENCE_BUSY_TAG: metadata["busy_kinds"]}), timeout_seconds=10)
    return metadata


@job(tags=_job_tags("reference", "reference_export_prepare_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def reference_export_prepare_job() -> None:
    prepare_reference_exports()


@job(tags=_job_tags("parking", "airport_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def airport_collection_job() -> None:
    prepare_reference_exports(collect_airport_parking())


#: 주차 통계 보관 적재의 정기 실행(소유자 결정 2026-11-24: **적재만** 주 1회 자동, 정리·원본 삭제는 수동 유지 —
#: `prune_parking_raw`는 계속 항상 거부). 매주 월요일 05:10 KST: 유가 브라우저 수집(00:00 시작, 보통 1~2시간·최대 3.5시간)과
#: 새벽 기준정보 job(02:30~04:45)이 끝난 뒤다. 늘 도는 것은 5분 공항·고속도로와 매시 정각 KRIC 시간표뿐이다.
PARKING_ARCHIVE_SCHEDULE_CRON = "10 5 * * 1"
#: 수동 실행 기본값(예전 동작: 배치 1개, 공항 버킷 144, busy면 바로 끝냄).
PARKING_ARCHIVE_DEFAULT_BUCKETS = 144
#: 정기 실행 설정. 하루 공항 수집은 2,016 버킷(공항 14곳 x 10분 144)이라 기본값(144)으로는 한 주 분량의 1/14도 못 한다.
#: 배치 하나에 하루 범위를 끝내고(`max_buckets=2016` — 같은 하루를 144씩 나누면 배치마다 그날 기존 버킷을 다시 검산한다)
#: 시간 예산 안에서 배치를 잇는다. busy(같은 lease를 HTTP 수동 수집 등이 쥠)는 짧게 몇 번만 다시 본다.
PARKING_ARCHIVE_SCHEDULED_CONFIG = {"max_batches": 50, "max_buckets": 2016, "busy_retries": 3, "time_budget_seconds": 240}
#: 정기 실행의 시간 예산(`time_budget_seconds`): 이 시간이 지나면 새 배치를 시작하지 않는다. 보관 job은 공항 수집과 같은
#: run group(`parking`, 상한 1)이라 보관 run 동안 공항 run은 Dagster 대기열에서 기다린다 — 보통 5분 수집 한 주기 안에서 끝내
#: 공항 run은 늦어지기만 한다. 예산은 배치의 **시작**만 막으므로, 배치 하나가 길면 run이 5분을 넘고 그 사이 공항 tick 하나가
#: coalescing에 합쳐질 수 있다(주 1회 1~2 tick, 첫 run의 `max_batch_seconds`로 확인한다).
#: 수동 실행 기본값 0 = 예산 없음(실행 상한 `dagster/max_runtime`까지).
PARKING_ARCHIVE_SCHEDULED_TIME_BUDGET_SECONDS = PARKING_ARCHIVE_SCHEDULED_CONFIG["time_budget_seconds"]
#: lease 경합(`busy`) 뒤 다시 시도하는 간격(초).
PARKING_ARCHIVE_BUSY_WAIT_SECONDS = 10
#: 결과 metadata에 싣는 서비스 결과 필드(마지막 배치 기준). 원문·비밀값은 없다.
PARKING_ARCHIVE_METADATA_FIELDS = frozenset({
    "status", "coverage_status", "archived_buckets", "deferred_buckets", "pruned_snapshots",
    "checked_at", "raw_cutoff_at", "complete_before", "max_buckets",
    "selection_start_at", "selection_end_exclusive", "selected_observed_min_at", "selected_observed_max_at",
    "selected_snapshots", "selected_buckets", "verified_buckets", "verification_scope",
    "verified_min_bucket_at", "verified_max_bucket_at", "archived_min_bucket_at", "archived_max_bucket_at",
    "verification_domain", "airport_status", "airport_coverage_status", "global_status", "global_coverage_status",
    "latest_seeded", "oldest_pending_at", "deferred_count_scope", "blocked_scope", "blocked_reason", "blocked_bucket_at",
    "global_buckets", "global_max_buckets", "global_deferred_buckets", "global_deferred_count_scope", "global_oldest_pending_at",
    "global_selection_start_at", "global_selection_end_exclusive", "global_selected_observed_min_at",
    "global_selected_observed_max_at", "global_selected_snapshots", "global_selected_buckets", "global_verified_buckets",
    "global_verification_scope", "global_verified_min_bucket_at", "global_verified_max_bucket_at",
    "global_archived_min_bucket_at", "global_archived_max_bucket_at",
})
#: 따라잡지 못하고 멈춘 사유. 실패는 아니지만(적재한 배치는 commit했다) run을 부분 완료로 표시한다.
PARKING_ARCHIVE_BACKLOG_STOPS = frozenset({"max_batches", "time_budget", "busy"})


def _archive_clock() -> float:
    """보관 실행의 시간 예산·배치 시간 측정(시험이 바꿔 낀다)."""
    return time.monotonic()


def _archive_sleep(seconds: float) -> None:
    """보관 실행의 busy 재시도 대기(시험이 바꿔 낀다)."""
    time.sleep(seconds)


def _archive_remaining_runtime(context, fallback: float) -> float:
    """이 run에 남은 실행 상한(초). run 기록의 `dagster/max_runtime` 태그와 시작 시각으로 잰다 — 운영자가 태그를 바꾼 수동 run도
    그 상한을 쓰고, step 기동 지연도 셈에 든다. 읽지 못하면 op 시작 기준 `fallback`."""
    try:
        record = call_with_deadline(lambda: context.instance.get_run_record_by_id(context.run_id), timeout_seconds=10)
        if record is None or record.start_time is None:
            return fallback
        limit = int((record.dagster_run.tags or {}).get(
            "dagster/max_runtime", job_max_runtime_seconds("parking_statistics_archive_job")))
        return limit - (time.time() - record.start_time)
    except Exception:  # noqa: BLE001 — 예산 계산 실패로 보관을 막지 않는다.
        return fallback


def _log_archive_batch(context, result: dict[str, Any], batch_seconds: float) -> None:
    context.log.info(
        "주차 통계 결과: status=%s coverage_status=%s selected_snapshots=%s verified_buckets=%s "
        "archived_buckets=%s deferred_buckets=%s pruned_snapshots=%s raw_cutoff_at=%s selection=[%s,%s) "
        "global_status=%s global_verified_buckets=%s global_buckets=%s global_deferred_buckets=%s blocked_reason=%s "
        "batch_seconds=%.1f",
        result.get("status"), result.get("coverage_status"), result.get("selected_snapshots", 0),
        result.get("verified_buckets", 0), result.get("archived_buckets", 0), result.get("deferred_buckets", 0),
        result.get("pruned_snapshots", 0), result.get("raw_cutoff_at"),
        result.get("selection_start_at"), result.get("selection_end_exclusive"),
        result.get("global_status"), result.get("global_verified_buckets", 0), result.get("global_buckets", 0),
        result.get("global_deferred_buckets", 0), result.get("blocked_reason"), batch_seconds,
    )


@op(config_schema={
    "max_batches": Field(int, default_value=1, is_required=False,
                         description="이어 할 배치 수 상한(1~500). 기본 1 = 예전 수동 동작."),
    "max_buckets": Field(int, default_value=PARKING_ARCHIVE_DEFAULT_BUCKETS, is_required=False,
                         description="배치 하나의 공항 통계 버킷 상한(1~2016, 2016 = 하루 범위 전체)."),
    "busy_retries": Field(int, default_value=0, is_required=False,
                          description="DB lease 경합(busy) 뒤 다시 시도하는 횟수(0~100)."),
    "time_budget_seconds": Field(int, default_value=0, is_required=False,
                                 description="이 시간이 지나면 새 배치를 시작하지 않는다(0 = 예산 없음, 실행 상한까지)."),
})
@_redact_op_errors
def archive_airport_parking_statistics(context) -> dict[str, Any]:
    # 원본 수집/provider와 별개인 DB 전용 작업. 적재·검산만 하고 원본 정리(삭제)는 없다.
    config = context.op_config
    max_batches, max_buckets, busy_retries = config["max_batches"], config["max_buckets"], config["busy_retries"]
    budget = config["time_budget_seconds"]
    if not (1 <= max_batches <= 500 and 1 <= max_buckets <= 2016 and 0 <= busy_retries <= 100
            and 0 <= budget <= 86_400):
        raise Failure(description="주차 통계 보관 설정이 범위를 벗어났습니다"
                                  "(max_batches 1~500, max_buckets 1~2016, busy_retries 0~100, time_budget_seconds 0~86400).",
                      allow_retries=False)
    settings = _settings()
    runtime = job_max_runtime_seconds("parking_statistics_archive_job")
    started = _archive_clock()
    totals: dict[str, Any] = {"batches": 0, "total_archived_buckets": 0, "total_global_buckets": 0,
                              "busy_retries_used": 0, "max_batch_seconds": 0.0, "stop_reason": ""}
    result: dict[str, Any] = {}

    def elapsed() -> float:
        return _archive_clock() - started

    def out_of_budget() -> bool:
        return bool(budget) and elapsed() >= budget

    while True:
        batch_started = _archive_clock()
        # 배치의 취소 시한은 이 run에 남은 실행 상한(run 기록 기준)으로 잰다(run monitoring보다 먼저 끝내 rollback한다).
        remaining = _archive_remaining_runtime(context, runtime - elapsed())
        result = asyncio.run(_run_with_session(
            settings, archive_parking_with_coverage, max_buckets=max_buckets,
            max_runtime_seconds=max(int(remaining), RUN_DEADLINE_MARGIN_SECONDS + MIN_RUN_DEADLINE_SECONDS),
        ))
        batch_seconds = _archive_clock() - batch_started
        totals["max_batch_seconds"] = round(max(totals["max_batch_seconds"], batch_seconds), 3)
        _log_archive_batch(context, result, batch_seconds)
        status = result["status"]
        if status == "blocked":
            totals["stop_reason"] = "blocked"
            # 보류 상태 commit 뒤 job은 실패시킨다. 녹색 실행으로 coverage 성공을 위장하지 않는다.
            raise Failure(description="주차 영구 통계 검산이 보류되었습니다. parking_archive_issues를 확인하세요.",
                          metadata={**{key: value for key, value in result.items()
                                       if key in PARKING_ARCHIVE_METADATA_FIELDS}, **totals})
        if status == "busy":
            # 다른 보유자(HTTP 수동 수집·수동 보관 실행)가 lease를 쥐고 있다. 변경 0으로 돌아왔다.
            if totals["busy_retries_used"] < busy_retries and not out_of_budget():
                totals["busy_retries_used"] += 1
                _archive_sleep(PARKING_ARCHIVE_BUSY_WAIT_SECONDS)
                continue
            totals["stop_reason"] = "busy"
            break
        totals["batches"] += 1
        totals["total_archived_buckets"] += int(result.get("archived_buckets", 0) or 0)
        totals["total_global_buckets"] += int(result.get("global_buckets", 0) or 0)
        if status != "batch_complete":
            # no_new_rows(새 원본 없음)·deferred(남은 가장 오래된 대상이 아직 늦은 수신 보류) — 더 돌려도 진척이 없다.
            totals["stop_reason"] = status
            break
        if totals["batches"] >= max_batches:
            totals["stop_reason"] = "max_batches"
            break
        if out_of_budget():
            totals["stop_reason"] = "time_budget"
            break
    context.add_output_metadata({**{key: value for key, value in result.items()
                                    if key in PARKING_ARCHIVE_METADATA_FIELDS}, **totals})
    if max_batches > 1 and totals["stop_reason"] in PARKING_ARCHIVE_BACKLOG_STOPS:
        # 실패는 아니다(적재한 배치는 commit했다). 남은 보관분이 있다는 것을 부분 완료 태그와 경고로 보인다 — 매주 이러면
        # 주 1회 예산이 쌓이는 양을 따라가지 못하는 것이다(주기·예산을 다시 정한다, docs/architecture/parking-retention.md).
        context.log.warning(
            f"주차 통계 보관을 {totals['stop_reason']}로 멈췄습니다(배치 {totals['batches']}개, 공항 버킷 "
            f"{totals['total_archived_buckets']}·전국 {totals['total_global_buckets']}, 가장 긴 배치 "
            f"{totals['max_batch_seconds']}초). 남은 가장 오래된 보관 대상: {result.get('oldest_pending_at')}.")
        _record_collection_outcome(context, "partial")
    return {**result, **totals}


# 공항 수집과 같은 run group(`parking`, 상한 1)이다 — Dagster가 둘을 직렬화하고, DB는 같은 advisory lease가 지킨다.
@job(tags=_job_tags("parking", "parking_statistics_archive_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def parking_statistics_archive_job() -> None:
    archive_airport_parking_statistics()


@job(tags=_job_tags("highway", "highway_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def highway_collection_job() -> None:
    collect_highway_transport()


@job(tags=_job_tags("fuel", "fuel_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def fuel_collection_job() -> None:
    collect_fuel_transport()


@job(tags=_job_tags("reference", "rail_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def rail_reference_collection_job() -> None:
    prepare_reference_exports(collect_rail_reference(), collect_general_rail_reference())


@job(tags=_job_tags("reference", "maritime_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def maritime_reference_collection_job() -> None:
    prepare_reference_exports(enrich_new_reference_locations(collect_maritime_reference()))


@job(tags=_job_tags("reference", "ferry_timetable_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def ferry_timetable_collection_job() -> None:
    collect_ferry_timetable()


@op
@_redact_op_errors
def collect_vadahub_reference(context) -> dict[str, Any]:
    with collection_owner(context.run_id, context.instance):
        settings = _settings()
        result = asyncio.run(_run_with_session(settings, VadaHubCollectionService(settings).collect))
        if result["status"] == "partial_success" and not result["counts"]:
            detail = (result.get("failure_details") or [{}])[0]
            raise Failure(description="일부 배편 기준자료 수집에 실패했습니다. 마지막 정상 자료를 유지합니다.",
                          metadata={"failed_datasets": ", ".join(result["failed_datasets"]),
                                    "failed_dataset_count": len(result["failed_datasets"]),
                                    "successful_dataset_count": len(result["counts"]),
                                    "successful_data_preserved": True, **detail}, allow_retries=False)
        if result["status"] == "partial_success":
            detail = (result.get("failure_details") or [{}])[0]
            context.add_output_metadata({"status": result["status"], "collection_outcome": "partial",
                                         "failed_dataset_count": len(result["failed_datasets"]),
                                         "successful_dataset_count": len(result["counts"]),
                                         "previous_data_preserved": True, **detail})
            context.log.warning("배편 기준자료의 정상 원천은 유지했습니다. 미완료 데이터셋만 후속 수집 대상입니다.")
        context.log.info("VadaHub 배편 기준자료: %s", result)
        _record_collection_outcome(
            context, _collection_output_metadata(result, "reference")["collection_outcome"],
        )
        return result


@job(tags=_job_tags("reference", "vadahub_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def vadahub_reference_collection_job() -> None:
    collect_vadahub_reference()


@job(tags=_job_tags("reference", "bus_reference_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def bus_reference_collection_job() -> None:
    prepare_reference_exports(enrich_new_reference_locations(collect_bus_reference()))


@job(tags=_job_tags("reference", "place_location_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def place_location_collection_job() -> None:
    prepare_reference_exports(collect_place_locations())


@job(tags=_job_tags("reference", "kakao_place_location_collection_job"), executor_def=multiprocess_executor.configured({"max_concurrent": 1}))
def kakao_place_location_collection_job() -> None:
    prepare_reference_exports(collect_kakao_place_locations())


#: 회수 keyset 위치. sensor cursor는 common 정체 시계가 소유하므로 code-server 프로세스에 둔다.
_RECOVERY_POSITION = ScanPosition()


#: 5분 수집 trigger → 그 수집을 예약하는 schedule 이름(common `coalescing_schedule`은 `<job>_schedule`).
_TRIGGER_SCHEDULES = {
    recovery.FIVE_MINUTE_TRIGGERS[0]: f"{airport_collection_job.name}_schedule",
    recovery.FIVE_MINUTE_TRIGGERS[1]: f"{highway_collection_job.name}_schedule",
}
_LOCATION_NAME = "kor-travel-transport"
#: 유가 신선도 경보가 보는 원천의 정기 schedule. STOPPED면 그 원천은 경보에서 뺀다(`paused`).
_FUEL_SCHEDULES = {
    OPINET_SOURCE: f"{fuel_collection_job.name}_schedule",
    REST_AREA_FUEL_SOURCE: f"{rest_area_fuel_price_collection_job.name}_schedule",
}


def _fuel_provider_enabled(settings: Settings, source: str) -> bool:
    """그 유가 원천의 수집이 설정상 켜져 있는가(관리 화면 `provider_status`의 `enabled`와 같은 조건)."""
    if source == OPINET_SOURCE:
        return bool(settings.transport_collection_enabled and settings.opinet_browser_enabled)
    return bool(settings.rest_area_collection_enabled and settings.kex_ex_api_key)


def _stopped_schedules(instance, names: set[str] | None = None) -> set[str]:
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
        if location == _LOCATION_NAME and state.instigator_name in (names or set(_TRIGGER_SCHEDULES.values())):
            statuses.setdefault(state.instigator_name, set()).add(state.status)
    return {name for name, seen in statuses.items() if seen == {InstigatorStatus.STOPPED}}


async def _reconcile_workers(
    instance, remaining, paused: list[str] | None = None, fuel_report: FuelFreshnessReport | None = None,
) -> int:
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

    fuel_stopped: list[set[str]] = []

    def fuel_monitored(source: str) -> bool:
        # 경고 이상인 원천에만 불린다. 확인할 예산이 없거나 확인이 실패하면 경보 쪽(감시 중)으로 본다.
        if not _fuel_provider_enabled(_settings(), source):
            return False
        if not fuel_stopped:
            if work_remaining() <= recovery.METADATA_TIMEOUT_SECONDS:
                return True
            try:
                fuel_stopped.append(call_with_deadline(
                    lambda: _stopped_schedules(instance, set(_FUEL_SCHEDULES.values())),
                    timeout_seconds=recovery.METADATA_TIMEOUT_SECONDS))
            except Exception:  # noqa: BLE001
                fuel_stopped.append(set())
        return _FUEL_SCHEDULES[source] not in fuel_stopped[0]

    engine, factory = create_engine_and_session_factory(
        _settings().database_url, collector=True, statement_timeout_seconds=recovery.RECOVERY_STATEMENT_TIMEOUT_SECONDS,
    )
    try:
        # 첫 접속의 dialect 초기화·빈 page 확인까지 포함한 작업 전체를 정리 시간 앞에서 끊는다.
        async with asyncio.timeout(max(0.0, work_remaining())):
            return await run_recovery_tick(
                factory, instance, position=_RECOVERY_POSITION, remaining=work_remaining,
                collection_scheduled=collection_scheduled, paused=paused, fuel_report=fuel_report,
                fuel_monitored=fuel_monitored,
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
    fuel_report = FuelFreshnessReport()
    try:
        recovered = asyncio.run(_reconcile_workers(instance, remaining, paused, fuel_report))
    finally:
        # 정체(예외)로 끝난 tick에서도 이미 판정한 유가 신선도는 남긴다.
        if remaining() > 0:
            _report_fuel_freshness(context, fuel_report)
    if paused and remaining() > 0:
        # 점검으로 멈춘 schedule은 정체가 아니다. traceback 없이 한 줄만 남긴다.
        context.log.warning("5분 수집 schedule이 STOPPED라 신선도 판정에서 제외합니다: " + ", ".join(sorted(paused)))
    if fuel_report.paused and remaining() > 0:
        context.log.warning("유가 수집이 설정에서 꺼졌거나 schedule이 STOPPED라 유가 신선도 경보에서 제외합니다: "
                            + ", ".join(sorted(fuel_report.paused)))
    return recovered


_STALL_LOGGER = logging.getLogger("app.dagster.recovery")


def _alert_stall(context, clock) -> None:
    """정체 경보. 별도 경보 테이블·채널이 없어 고정 event 이름 한 줄로 두 곳에 남긴다.

    sensor tick 로그(Dagster UI)와 code-server 프로세스 stderr(컨테이너 로그, `docker logs`·로그 수집기).
    """
    line = format_stall_alert(clock, now=time.time())
    context.log.error(line)
    _STALL_LOGGER.error(line)


#: 유가 신선도 경보의 마지막 단계·시각. sensor cursor는 정체 시계가 소유하므로 code-server 프로세스에 둔다.
_FUEL_FRESHNESS_ALERTS = FuelFreshnessAlerts()


def _report_fuel_freshness(context, report: FuelFreshnessReport) -> None:
    """유가 시도 소실·신선도 경보(G1-F5·G1-F6). `_alert_stall`과 같이 고정 event 이름 한 줄을 두 곳에 남긴다.

    경고·위험·만료는 정체가 아니라 정체 시계를 건드리지 않는다. 경보를 남기는 일이 회수 tick을 실패시키지 않게 한다. 경보
    기억은 줄을 두 곳에 다 남긴 뒤에만 반영한다 — 기록이 실패한 줄은 다음 tick에 다시 만든다(`report_failed` 한 줄).
    """
    try:
        for line in _FUEL_FRESHNESS_ALERTS.lines(report, now=time.time()):
            (context.log.error if line.level >= logging.ERROR else context.log.warning)(line.text)
            _STALL_LOGGER.log(line.level, line.text)
            _FUEL_FRESHNESS_ALERTS.commit(line)
    except Exception:  # noqa: BLE001
        with contextlib.suppress(Exception):
            _STALL_LOGGER.warning("transport_fuel_freshness.report_failed")


worker_recovery = reconciliation_sensor(
    name="transport_worker_recovery", reconcile=_reconcile_tick, required_resource_keys=set(),
    budget_seconds=RECOVERY_BUDGET_SECONDS, on_stall=_alert_stall,
)


definitions = Definitions(
    sensors=[address_refresh_sensor, worker_recovery, *[
        infrastructure_retry_sensor(
            name=f"transport_infra_retry_{retry_job.name}",
            project="transport", location_name="kor-travel-transport", job=retry_job,
            # 재시도 run의 태그는 이 정책이 덮는다(common `infrastructure_retry_sensor`). job과 같은 상한을 쓴다.
            policy=_recovery_policy(retry_job.name),
        )
        for retry_job in (airport_collection_job, highway_collection_job, rest_area_reference_collection_job,
                          rest_area_food_collection_job)
    ]],
    jobs=[
        public_parking_reference_job,
        address_refresh_job,
        airport_collection_job,
        parking_statistics_archive_job,
        highway_collection_job,
        fuel_collection_job,
        rail_reference_collection_job,
        reference_export_prepare_job,
        maritime_reference_collection_job,
        vadahub_reference_collection_job,
        ferry_timetable_collection_job,
        bus_reference_collection_job,
        place_location_collection_job,
        kakao_place_location_collection_job,
        kric_timetable_collection_job,
        general_rail_timetable_collection_job,
        rest_area_reference_collection_job,
        rest_area_fuel_price_collection_job,
        rest_area_food_collection_job,
    ],
    schedules=[
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=public_parking_reference_job, cron_schedule="45 4 4 * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=airport_collection_job, cron_schedule=staggered_cron(interval_minutes=5, phase_minutes=1), execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=highway_collection_job, cron_schedule=staggered_cron(interval_minutes=5, phase_minutes=3), execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=fuel_collection_job, cron_schedule="0 */8 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 주차 통계 보관 적재만 주 1회(정리·원본 삭제는 수동). 설정·시각 근거는 `PARKING_ARCHIVE_*` 주석.
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=parking_statistics_archive_job,
                            cron_schedule=PARKING_ARCHIVE_SCHEDULE_CRON, execution_timezone="Asia/Seoul",
                            default_status=DefaultScheduleStatus.RUNNING,
                            run_config={"ops": {"archive_airport_parking_statistics": {
                                "config": dict(PARKING_ARCHIVE_SCHEDULED_CONFIG)}}}),
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
        # 시간별로 미수집분을 이어가되 같은 역·운행 기준은 24시간 호출 원장으로 보호한다.
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=kric_timetable_collection_job, cron_schedule="0 * * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=general_rail_timetable_collection_job, cron_schedule="30 2 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 휴게소 기준정보는 저변동(약 200행·1회 호출)이라 하루 한 번, 유가는 4시간마다 갱신한다(ADR-013).
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=rest_area_reference_collection_job, cron_schedule="40 3 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=rest_area_fuel_price_collection_job, cron_schedule="25 */4 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
        # 휴게소 먹거리(0615 코드 1회 + 0502 메뉴 약 74페이지)는 천천히 바뀐다. 하루 한 번이면 충분하다.
        coalescing_schedule(project="transport", location_name="kor-travel-transport", job=rest_area_food_collection_job, cron_schedule="50 3 * * *", execution_timezone="Asia/Seoul", default_status=DefaultScheduleStatus.RUNNING),
    ],
)
