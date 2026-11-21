"""오피넷 지역별 검색 화면을 사용하는 제한된 수동 가격 갱신."""
import asyncio
import hmac
from collections import defaultdict
from contextlib import AsyncExitStack
from datetime import timedelta
from decimal import Decimal
from ipaddress import ip_address
from typing import Annotated, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from opinet import OpinetAuthError, OpinetError, OpinetRateLimitError
from opinet.experimental.browser import BrowserRegion, OpinetBrowserCollector, OpinetBrowserThrottle
from playwright.async_api import Error as PlaywrightError
from sqlalchemy import and_, case, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from app.core.time_utils import now_utc, serialize_utc
from app.models import FuelLatestPrice, FuelRefreshBudget, FuelRefreshPrice, FuelRefreshStationGate, FuelStation
from app.schemas import FuelRefreshRequest, FuelRefreshResponse, FuelRefreshResult
from app.services.fuel_refresh_prices import fuel_viewport_conditions, has_visible_fuel_product
from app.services.transport_collection import OPINET_SOURCE

SEOUL = ZoneInfo("Asia/Seoul")
MAX_STATIONS = 9
REQUEST_SECONDS = 24
OVERLAY_TTL = timedelta(hours=24)
STATION_COOLDOWN = timedelta(minutes=5)
LEASE_TTL = timedelta(seconds=35)
PROVIDER_BACKOFF = timedelta(minutes=5)


def build_fuel_manual_refresh_router(settings, get_session_factory):
    router = APIRouter()
    token = (settings.fuel_refresh_internal_token or "").strip()
    daily_limit = settings.fuel_refresh_daily_limit
    other_tokens = (settings.transport_admin_write_token, settings.transport_service_export_token)
    enabled = bool(settings.opinet_browser_enabled and len(token) >= 32 and daily_limit and token not in other_tokens)

    def require_private_access(request: Request, authorization: Annotated[str | None, Header()] = None):
        peer = request.client
        try:
            is_loopback = peer is not None and ip_address(peer.host).is_loopback
        except ValueError:
            is_loopback = False
        # Uvicorn can rewrite the ASGI peer from X-Forwarded-For. The direct BFF sends neither header.
        if not enabled or not is_loopback or {"forwarded", "x-forwarded-for"}.intersection(request.headers):
            raise HTTPException(404, "주유소 수동 갱신을 사용할 수 없습니다.")
        if not hmac.compare_digest((authorization or "").encode(), f"Bearer {token}".encode()):
            raise HTTPException(401, "주유소 수동 갱신 인증이 필요합니다.",
                                headers={"WWW-Authenticate": "Bearer"})

    @router.post("/internal/fuel/refresh", response_model=FuelRefreshResponse,
                 include_in_schema=False, dependencies=[Depends(require_private_access)])
    async def refresh_fuel(body: FuelRefreshRequest, response: Response,
                           session_factory=Depends(get_session_factory)) -> FuelRefreshResponse:
        response.headers["Cache-Control"] = "no-store"
        results, targets = {}, []
        lease = uuid4().hex
        claimed = backoff = False
        unfinished_reason = "request_timeout"
        async with session_factory() as session:
            try:
                async with asyncio.timeout(REQUEST_SECONDS):
                    async with session.begin():
                        targets = await _targets(session, body)
                    for target in targets:
                        if target.source != OPINET_SOURCE or not (target.source_station_id and target.sido_value and target.sigungu_value):
                            results[target.id] = FuelRefreshResult(
                                station_id=target.id, status="unsupported", reason="unsupported_station",
                            )
                    eligible = [target for target in targets if target.id not in results]
                    if eligible:
                        claimed = await _claim_lease(session, lease)
                        if claimed:
                            backoff = await _refresh_regions(session, settings, eligible, lease, daily_limit, results)
                        else:
                            for target in eligible:
                                results[target.id] = _rate_limited(target.id, "refresh_busy")
            except TimeoutError:
                if not targets:
                    raise HTTPException(503, "주유소 갱신 대상을 확인하지 못했습니다.") from None
            except SQLAlchemyError:
                if not targets:
                    raise HTTPException(503, "주유소 갱신 대상을 확인하지 못했습니다.") from None
                unfinished_reason = "storage_unavailable"
            finally:
                if claimed:
                    try:
                        async with asyncio.timeout(2), session.begin():
                            await session.execute(update(FuelRefreshBudget).where(
                                FuelRefreshBudget.id == 1, FuelRefreshBudget.lease_id == lease,
                            ).values(lease_id=None, lease_until=now_utc() + PROVIDER_BACKOFF if backoff else None))
                    except (TimeoutError, SQLAlchemyError):
                        # The lease has a fixed expiry even if releasing it times out.
                        pass

        ordered = [results.get(target.id) or FuelRefreshResult(
            station_id=target.id, status="error", reason=unfinished_reason,
        ) for target in targets]
        successful = sum(result.status in {"updated", "unchanged"} for result in ordered)
        status = "completed" if successful == len(ordered) else "partial" if successful else "failed"
        return FuelRefreshResponse(status=status, results=ordered)

    return router


async def _targets(session, request):
    stmt = select(
        FuelStation.id, FuelStation.source, FuelStation.source_station_id,
        FuelStation.sido_value, FuelStation.sido_name, FuelStation.sigungu_value, FuelStation.sigungu_name,
        FuelStation.source_kinds, FuelStation.station_type,
    )
    if request.station_id is not None:
        rows = (await session.execute(stmt.where(FuelStation.id == request.station_id))).all()
        if not rows:
            raise HTTPException(404, "주유소를 찾을 수 없습니다.")
        return rows
    viewport = request.viewport
    bounds = viewport.min_longitude, viewport.min_latitude, viewport.max_longitude, viewport.max_latitude
    stmt = stmt.where(*fuel_viewport_conditions(bounds))
    if viewport.product_codes:
        stmt = stmt.where(has_visible_fuel_product(viewport.product_codes, now_utc()))
    rows = (await session.execute(stmt.order_by(FuelStation.id).limit(MAX_STATIONS + 1))).all()
    if len(rows) > MAX_STATIONS:
        raise HTTPException(422, "화면에 주유소가 10개 미만일 때 갱신할 수 있습니다.")
    return rows


def _insert(session, model):
    return pg_insert(model) if session.get_bind().dialect.name == "postgresql" else sqlite_insert(model)


async def _claim_lease(session, lease: str) -> bool:
    at = now_utc()
    table = FuelRefreshBudget.__table__
    async with session.begin():
        stmt = _insert(session, table).values(id=1, day=at.astimezone(SEOUL).date(), used=0, lease_id=lease,
                                              lease_until=at + LEASE_TTL)
        stmt = stmt.on_conflict_do_update(
            index_elements=[table.c.id],
            set_={"lease_id": lease, "lease_until": at + LEASE_TTL},
            where=or_(table.c.lease_until.is_(None), table.c.lease_until <= at),
        ).returning(table.c.id)
        return await session.scalar(stmt) is not None


async def _reserve_call(session, station_id, lease, daily_limit):
    at = now_utc()
    today = at.astimezone(SEOUL).date()
    async with session.begin():
        allowed_at = await session.scalar(select(FuelRefreshStationGate.allowed_at).where(
            FuelRefreshStationGate.fuel_station_id == station_id,
        ))
        if allowed_at and serialize_utc(allowed_at) > at:
            return FuelRefreshResult(station_id=station_id, status="cooldown", reason="station_cooldown")
        budget = FuelRefreshBudget.__table__.c
        used = case((budget.day < today, 0), else_=budget.used)
        charged = await session.scalar(update(FuelRefreshBudget).where(
            budget.id == 1, budget.lease_id == lease, budget.lease_until > at, used < daily_limit,
        ).values(day=case((budget.day < today, today), else_=budget.day), used=used + 1).returning(budget.id))
        if charged is None:
            return _rate_limited(station_id, "call_budget_exhausted")
        stmt = _insert(session, FuelRefreshStationGate).values(
            fuel_station_id=station_id, allowed_at=at + STATION_COOLDOWN,
        )
        await session.execute(stmt.on_conflict_do_update(
            index_elements=[FuelRefreshStationGate.fuel_station_id],
            set_={"allowed_at": stmt.excluded.allowed_at},
        ))
    return None


def _rate_limited(station_id, reason):
    return FuelRefreshResult(station_id=station_id, status="rate_limited", reason=reason)


def _station_tabs(target):
    kinds = set(target.source_kinds or ())
    if target.station_type == "Y":
        return {"lpg"}
    if target.station_type == "C":
        return {"station", "lpg"}
    return kinds.intersection({"station", "lpg"}) or {"station"}


async def _refresh_regions(session, settings, eligible, lease, daily_limit, results):
    groups = defaultdict(list)
    for target in eligible:
        key = target.sido_value, target.sigungu_value
        groups[key].append(target)

    backoff = False
    async with AsyncExitStack() as browser:
        search = None
        for targets in groups.values():
            if backoff:
                for target in targets:
                    results[target.id] = _rate_limited(target.id, "provider_backoff")
                continue
            reserved = []
            for target in targets:
                limited = await _reserve_call(session, target.id, lease, daily_limit)
                if limited:
                    results[target.id] = limited
                else:
                    reserved.append(target)
            if not reserved:
                continue
            first = reserved[0]
            region = BrowserRegion(first.sido_value, first.sido_name, first.sigungu_value, first.sigungu_name)
            try:
                if search is None:
                    collector = OpinetBrowserCollector(
                        browser_channel=settings.opinet_browser_channel or None,
                        timeout_ms=min(settings.opinet_browser_timeout_ms, 8_000),
                        throttle=OpinetBrowserThrottle(max_search_requests=MAX_STATIONS * 2),
                    )
                    search = await browser.enter_async_context(collector.open_region_search())
                rows = {}
                tabs = set().union(*(_station_tabs(target) for target in reserved))
                for kind in ("station", "lpg"):
                    if kind in tabs:
                        rows[kind] = await search(region, kind)
            except (OpinetError, PlaywrightError) as exc:
                backoff = search is None or isinstance(exc, (OpinetRateLimitError, OpinetAuthError))
                for target in reserved:
                    results[target.id] = (
                        _rate_limited(target.id, "provider_rate_limited") if isinstance(exc, OpinetRateLimitError)
                        else FuelRefreshResult(station_id=target.id, status="error", reason="provider_unavailable")
                    )
                continue
            checked_at = now_utc()
            for target in reserved:
                stations = [station for kind in _station_tabs(target) for station in rows[kind]
                            if station.station_id == target.source_station_id]
                prices = _observations(stations, checked_at)
                if not prices:
                    results[target.id] = FuelRefreshResult(
                        station_id=target.id, status="error", reason="no_valid_observation",
                    )
                    continue
                try:
                    results[target.id] = await _store_observations(session, target, prices, checked_at)
                except SQLAlchemyError:
                    results[target.id] = FuelRefreshResult(
                        station_id=target.id, status="error", reason="storage_unavailable",
                    )
    return backoff


def _observations(stations, checked_at):
    observations = {}
    for station in stations:
        for item in station.prices:
            if item.price is None or not 0 < item.price < 100_000_000 or item.updated_at is None:
                continue
            observed_at = serialize_utc(item.updated_at)
            if observed_at > checked_at:
                continue
            code = item.product_code.value
            price = Decimal(str(item.price)).quantize(Decimal("0.01"))
            if not 0 < price < 100_000_000:
                continue
            previous = observations.get(code)
            if previous is not None and previous[0] == observed_at and previous[1] != price:
                return {}
            if previous is None or observed_at > previous[0]:
                observations[code] = (observed_at, price)
    return observations


async def _store_observations(session, target, prices, checked_at):
    async with session.begin():
        station = await session.scalar(select(FuelStation.id).where(
            FuelStation.id == target.id, FuelStation.source == OPINET_SOURCE,
            FuelStation.source_station_id == target.source_station_id,
        ))
        if station is None:
            return FuelRefreshResult(station_id=target.id, status="unsupported", reason="unsupported_station")
        baseline = (await session.execute(select(
            FuelLatestPrice.product_code, FuelLatestPrice.provider_updated_at,
            FuelLatestPrice.observed_at, FuelLatestPrice.price,
        ).where(FuelLatestPrice.fuel_station_id == station))).all()
        manual = (await session.execute(select(
            FuelRefreshPrice.product_code, FuelRefreshPrice.observed_at, FuelRefreshPrice.price,
            FuelRefreshPrice.expires_at,
        ).where(FuelRefreshPrice.fuel_station_id == station))).all()
        published = {row.product_code: (serialize_utc(row.provider_updated_at or row.observed_at), row.price)
                     for row in baseline}
        saved = {row.product_code: (serialize_utc(row.observed_at), row.price) for row in manual}
        current = dict(published)
        for row in manual:
            previous = current.get(row.product_code)
            observed, price = saved[row.product_code]
            if serialize_utc(row.expires_at) > checked_at and (previous is None or observed > previous[0]):
                current[row.product_code] = (observed, price)

        rows = []
        changed = False
        for code, (observed, price) in prices.items():
            if any(previous and (observed < previous[0] or (observed == previous[0] and price != previous[1]))
                   for previous in (published.get(code), saved.get(code))):
                continue
            rows.append(dict(fuel_station_id=station, product_code=code, price=price, observed_at=observed,
                             checked_at=checked_at, expires_at=checked_at + OVERLAY_TTL))
            changed |= code not in current or current[code][1] != price
        if not rows:
            return FuelRefreshResult(station_id=station, status="error", reason="stale_or_conflicting_observation")
        stmt = _insert(session, FuelRefreshPrice).values(rows)
        table = FuelRefreshPrice.__table__.c
        await session.execute(stmt.on_conflict_do_update(
            index_elements=[table.fuel_station_id, table.product_code],
            set_={name: stmt.excluded[name] for name in ("price", "observed_at", "checked_at", "expires_at")},
            where=or_(stmt.excluded.observed_at > table.observed_at, and_(
                stmt.excluded.observed_at == table.observed_at, stmt.excluded.price == table.price,
                stmt.excluded.checked_at > table.checked_at,
            )),
        ))
    return FuelRefreshResult(station_id=station, status="updated" if changed else "unchanged", checked_at=checked_at)
