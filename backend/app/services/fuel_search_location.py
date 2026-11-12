"""기존 주소 캐시·provider resolver를 소비한다. 가까운 주유소로 행정구역을 추정하지 않는다."""
from collections import OrderedDict
from time import monotonic

from anyio import CapacityLimiter, to_thread
from kortravelcommon.address_providers import VworldKakaoAddressResolver
from kortravelcommon.reverse_address import AddressTarget, reverse_address_tables
from opinet.codes import bjd_sido_to_opinet
from opinet.exceptions import OpinetInvalidParameterError
from opinet.vworld import OPINET_SIDO_VWORLD_NAMES
from sqlalchemy import String, and_, cast, func, literal, select

from app.core.time_utils import now_utc
from app.models import Base, FuelStation, FuelStatisticsDaily, FuelStatisticsState
from app.schemas import FuelSearchRegion
from app.services.fuel_search import begin_fuel_search
from app.services.fuel_statistics import OPINET, _key


class FuelLocationResolver:
    def __init__(self, settings, session_factory):
        self.settings, self.session_factory = settings, session_factory
        self.cache = OrderedDict()
        self.limiter = CapacityLimiter(2)

    async def address(self, latitude: float, longitude: float):
        target = AddressTarget("fuel-mcp-location", longitude, latitude)
        cached = self.cache.get(target.coordinate_key)
        if cached and cached[0] > monotonic():
            self.cache.move_to_end(target.coordinate_key)
            return cached[1], "memory_cache"
        entries, _ = reverse_address_tables(Base.metadata)
        async with self.session_factory() as session:
            await begin_fuel_search(session)
            payload = await session.scalar(select(entries.c.payload).where(
                entries.c.provider_id == VworldKakaoAddressResolver.provider_id,
                entries.c.coordinate_key == target.coordinate_key, entries.c.status == "ok",
                entries.c.next_refresh_at > now_utc(),
            ).order_by(entries.c.resolved_at.desc()).limit(1))
        method = "stored_address"
        if payload is None:
            if not (self.settings.vworld_api_key or self.settings.kakao_rest_api_key):
                return None, "address_not_configured"
            def lookup():
                resolver = VworldKakaoAddressResolver(vworld_key=self.settings.vworld_api_key,
                    kakao_key=self.settings.kakao_rest_api_key,
                    timeout=min(3, self.settings.address_refresh_timeout_seconds))
                try:
                    return resolver.reverse(target)
                finally:
                    resolver.close()
            try:
                payload = await to_thread.run_sync(lookup, limiter=self.limiter)
            except Exception:
                return None, "address_lookup_failed"
            method = "coordinate_address"
        if not isinstance(payload, dict) or not isinstance(payload.get("region"), dict):
            return None, "address_not_found"
        self.cache[target.coordinate_key] = (monotonic() + 3600, payload)
        self.cache.move_to_end(target.coordinate_key)
        while len(self.cache) > 128:
            self.cache.popitem(last=False)
        return payload, method


async def published_region(session, sido_value, sigungu_value, method, provider=None):
    d, state = FuelStatisticsDaily, FuelStatisticsState
    label = await session.scalar(select(d.label).join(state, and_(d.source == state.source,
        d.generated_at == state.generated_at, d.day == state.day)).where(
            d.source == OPINET, d.scope == "sigungu", d.scope_key == _key(sido_value, sigungu_value)).limit(1))
    return FuelSearchRegion(status="resolved" if label else "unavailable", method=method,
        reason=None if label else "region_not_published", sido_value=sido_value,
        sigungu_value=sigungu_value, label=label, address_provider=provider)


async def region_for_address(session, payload, method):
    if payload is None:
        return FuelSearchRegion(status="unavailable", method="coordinate_address", reason=method)
    address, region = payload.get("address") or {}, payload.get("region") or {}
    legal = address.get("legal_dong_code")
    legal = legal if isinstance(legal, str) and len(legal) == 10 and legal.isascii() and legal.isdigit() else None
    station = FuelStation
    matches = []
    if legal:
        entries, _ = reverse_address_tables(Base.metadata)
        # 캐시의 법정동과 현재 주유소 좌표가 모두 맞는 명시 연결만 사용한다.
        matches = (await session.execute(select(station.sido_value, station.sigungu_value).distinct().join(entries,
            entries.c.target_key == literal("fuel_station:") + cast(station.id, String)).where(
                station.source == OPINET, entries.c.provider_id == VworldKakaoAddressResolver.provider_id,
                entries.c.status == "ok", entries.c.next_refresh_at > now_utc(),
                entries.c.longitude == station.longitude, entries.c.latitude == station.latitude,
                func.substr(entries.c.payload["address"]["legal_dong_code"].as_string(), 1, 5) == legal[:5],
            ).limit(2))).all()
    if not matches:
        try:
            sido = bjd_sido_to_opinet(legal[:2]) if legal else next(
                code for code, names in OPINET_SIDO_VWORLD_NAMES.items() if region.get("sido") in names)
        except (OpinetInvalidParameterError, ValueError, StopIteration):
            return FuelSearchRegion(status="unavailable", method=method, reason="region_not_matched")
        matches = (await session.execute(select(station.sido_value, station.sigungu_value).distinct().where(
            station.source == OPINET, station.sido_value == sido,
            station.sigungu_name == region.get("sigungu"),
        ).limit(2))).all()
    if len(matches) != 1:
        return FuelSearchRegion(status="unavailable", method=method, reason="region_not_uniquely_matched")
    return await published_region(session, *matches[0], method, payload.get("provider"))
