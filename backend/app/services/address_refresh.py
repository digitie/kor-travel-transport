"""수집 원천·관리자 좌표와 독립적인 최신 주소 갱신."""
from contextlib import contextmanager

from kortravelcommon.address_providers import VworldKakaoAddressResolver
from kortravelcommon.reverse_address import (
    DatabaseAddressSource,
    ReverseAddressStore,
    address_engine,
    refresh_reverse_addresses,
)
from sqlalchemy import String, cast, literal, select, union_all

from app.models import (
    BusTerminalReference,
    FerryPort,
    FuelStation,
    RailStationReference,
    RestAreaReference,
)


@contextmanager
def address_source(settings):
    engine = address_engine(settings.database_url)
    try:
        tables = [
            ("fuel_station", FuelStation, "name"),
            ("bus_terminal", BusTerminalReference, "terminal_name"),
            ("ferry_port", FerryPort, "port_name"),
            ("rail_station", RailStationReference, "station_name"),
            ("rest_area", RestAreaReference, "name"),
        ]
        selects = [
            select(
                (literal(kind + ":") + cast(model.id, String)).label("target_key"),
                model.longitude, model.latitude, getattr(model, name).label("display_name"),
            ).where(model.longitude.between(124, 132), model.latitude.between(33, 43))
            for kind, model, name in tables
        ]
        yield DatabaseAddressSource(
            ReverseAddressStore(engine, VworldKakaoAddressResolver.provider_id), union_all(*selects)
        )
    finally:
        engine.dispose()


def configured(settings):
    return bool(settings.vworld_api_key or settings.kakao_rest_api_key)


def address_summary(settings):
    with address_source(settings) as source:
        return {**source.summary(), "configured": configured(settings),
                "auto_enabled": settings.address_refresh_auto_enabled}


def run_address_refresh(settings, *, force=False, resolver=None):
    if not configured(settings) and resolver is None:
        return {"status": "not_configured"}
    with address_source(settings) as source:
        client = resolver or VworldKakaoAddressResolver(
            vworld_key=settings.vworld_api_key, kakao_key=settings.kakao_rest_api_key,
            timeout=settings.address_refresh_timeout_seconds,
        )
        try:
            return refresh_reverse_addresses(
                source.store, client, source.page, source.lookup,
                batch_size=settings.address_refresh_batch_size, force=force,
            )
        finally:
            if resolver is None:
                client.close()
