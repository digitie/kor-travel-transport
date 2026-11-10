"""6개월 주소 갱신과 수동 배치 재개."""
import asyncio
from kortravelcommon.address_dagster import address_refresh_definitions

from app.core.config import get_settings
from app.services.address_refresh import address_source, configured, run_address_refresh


def _run(force):
    settings = get_settings()
    result = run_address_refresh(settings, force=force)
    if settings.transport_map_current_enabled and configured(settings):
        from app.services.reference_export_preparation import prepare_reference_exports_for_settings
        asyncio.run(prepare_reference_exports_for_settings(settings))
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
