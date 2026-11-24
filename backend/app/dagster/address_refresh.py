"""6개월 주소 갱신과 수동 배치 재개."""
import asyncio
import time

from kortravelcommon.address_dagster import address_refresh_definitions

from app.core.config import get_settings
from app.services.address_refresh import address_source, configured, run_address_refresh

#: 주소 갱신 run 상한(공용 `address_refresh_definitions`의 `dagster/max_runtime`)까지 이만큼 남기고 준비를 끝낸다.
_PREPARE_RESERVE_SECONDS = 30


def _current_context():
    """주소 갱신 op 안이면 그 실행 context(공용 op가 `_run`에 넘겨 주지 않는다). 밖이면 None."""
    try:
        from dagster import OpExecutionContext

        return OpExecutionContext.get()
    except Exception:  # noqa: BLE001 — Dagster 밖(시험·수동 호출)이면 로그만 남긴다.
        return None


def _prepare_budget(context, cap: float) -> float:
    """run 시작부터 잰 실행 상한까지 남은 시간 안에서 준비 예산을 정한다(못 읽으면 cap)."""
    if context is None:
        return cap
    try:
        record = context.instance.get_run_record_by_id(context.run_id)
        limit = int((record.dagster_run.tags or {}).get("dagster/max_runtime"))
        remaining = limit - (time.time() - record.start_time) - _PREPARE_RESERVE_SECONDS
        return max(0.0, min(cap, remaining))
    except Exception:  # noqa: BLE001 — 예산 계산 실패가 주소 갱신을 막지 않는다.
        return cap


def _run(force):
    settings = get_settings()
    result = run_address_refresh(settings, force=force)
    if settings.transport_map_current_enabled and configured(settings):
        from app.services.reference_export_preparation import (
            COLLECTION_TAIL_PREPARE_BUDGET_SECONDS,
            prepare_reference_exports_for_settings,
        )
        context = _current_context()
        summary = asyncio.run(prepare_reference_exports_for_settings(
            settings, total_budget_seconds=_prepare_budget(context, COLLECTION_TAIL_PREPARE_BUDGET_SECONDS),
        ))
        # 주소는 이미 commit됐다. 준비 결과는 수집 job 꼬리와 같은 규칙으로 metadata·태그·경고에 남긴다
        # (전부 실패도 부분 완료). 주소 갱신 결과 로그에도 요약을 붙인다.
        from app.dagster.definitions import report_reference_prepare
        metadata = report_reference_prepare(context, summary, dedicated=False)
        if isinstance(result, dict):
            result["reference_export_prepare"] = {key: metadata[key] for key in (
                "reference_status", "prepared", "reused", "busy", "deferred", "failed", "failed_kinds", "error_code",
            ) if key in metadata}
    return result


def _pending():
    settings = get_settings()
    if not configured(settings):
        return False
    with address_source(settings) as source:
        return source.has_work(automatic=settings.address_refresh_auto_enabled)


address_refresh_job, address_refresh_sensor = address_refresh_definitions(
    project="transport", location_name="kor-travel-transport", run=_run, pending=_pending,
)
