"""Effective prices for the public map and station list only."""
from sqlalchemy import and_, func, or_, select

from app.models import FuelLatestPrice, FuelRefreshPrice, FuelStation


def _active_overlay(at):
    overlay = FuelRefreshPrice.__table__
    published = FuelLatestPrice.__table__.alias("refresh_baseline")
    observed = func.coalesce(published.c.provider_updated_at, published.c.observed_at)
    newer_or_conflicting = select(1).where(
        published.c.fuel_station_id == overlay.c.fuel_station_id,
        published.c.product_code == overlay.c.product_code,
        or_(observed > overlay.c.observed_at, and_(
            observed == overlay.c.observed_at, published.c.price.is_distinct_from(overlay.c.price),
        )),
    ).correlate(overlay).exists()
    return overlay, (overlay.c.expires_at > at, ~newer_or_conflicting)


def effective_fuel_prices(station_ids, at):
    published = FuelLatestPrice.__table__.c
    overlay, active = _active_overlay(at)
    manual = select(
        overlay.c.fuel_station_id, overlay.c.product_code, overlay.c.price,
        overlay.c.observed_at.label("provider_updated_at"), overlay.c.observed_at,
        overlay.c.checked_at.label("collected_at"),
    ).where(overlay.c.fuel_station_id.in_(station_ids), *active).cte("active_manual_fuel_prices")
    replaced = select(1).where(
        manual.c.fuel_station_id == published.fuel_station_id, manual.c.product_code == published.product_code,
    ).correlate(FuelLatestPrice.__table__).exists()
    baseline = select(
        published.fuel_station_id, published.product_code, published.price,
        published.provider_updated_at, published.observed_at, published.collected_at,
    ).where(published.fuel_station_id.in_(station_ids), ~replaced)
    return baseline.union_all(select(manual)).subquery("effective_fuel_prices")


def has_visible_fuel_product(product_codes, at):
    overlay, active = _active_overlay(at)
    manual = select(1).where(
        overlay.c.fuel_station_id == FuelStation.id, overlay.c.product_code.in_(product_codes), *active,
    ).correlate(FuelStation).exists()
    published = select(1).where(
        FuelLatestPrice.fuel_station_id == FuelStation.id,
        FuelLatestPrice.product_code.in_(product_codes), FuelLatestPrice.price > 0,
    ).correlate(FuelStation).exists()
    # Every stored overlay has a strictly positive price.
    return or_(published, manual)


def fuel_viewport_conditions(bounds):
    min_lon, min_lat, max_lon, max_lat = bounds
    return FuelStation.longitude.between(min_lon, max_lon), FuelStation.latitude.between(min_lat, max_lat)
