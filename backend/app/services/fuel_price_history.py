"""지도 주유소 ID로 읽는 저장 유가 이력. export 인증이나 외부 provider를 사용하지 않는다."""
from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import serialize_utc
from app.models import FuelLatestPrice, FuelPriceSnapshot, FuelStation
from app.schemas import FuelPriceHistoryWindow, FuelPriceItem, FuelStationPriceHistoryResponse
from app.services.export_price_history import (
    CURSOR_TTL, MAX_HISTORY_LIMIT, PriceHistoryUnavailable, _response, read_price_history_page,
)
from app.services.transport_collection import OPINET_SOURCE

MAX_LATEST_PRODUCTS = 64


def _price_item(row) -> FuelPriceItem:
    return FuelPriceItem(
        product_code=row.product_code,
        price=float(row.price) if row.price is not None else None,
        provider_updated_at=serialize_utc(row.provider_updated_at) if row.provider_updated_at else None,
        observed_at=serialize_utc(row.observed_at),
        collected_at=serialize_utc(row.collected_at),
    )


def build_fuel_price_history_router(
    settings: Settings, get_db: Callable[..., AsyncIterator[AsyncSession]],
) -> APIRouter:
    router = APIRouter()
    # namespace와 key를 export와 분리한다. 토큰은 HTTP에 반환하거나 브라우저에서 요구하지 않는다.
    cursor_key = hashlib.sha256(
        ("native-fuel-history:" + (settings.transport_service_export_token or "")).encode(),
    ).digest()

    @router.get(
        "/transport/fuel/stations/{station_id}/price-history",
        response_model=FuelStationPriceHistoryResponse,
        responses={404: {}, 409: {}, 501: {}, 503: {}},
    )
    async def station_price_history(
        request: Request,
        station_id: int = Path(gt=0, le=2_147_483_647),
        source: str = Query(min_length=1, max_length=40),
        days: int = Query(default=7, ge=1, le=7),
        product: str | None = Query(default=None, min_length=1, max_length=20),
        limit: int = Query(default=1000, ge=1, le=MAX_HISTORY_LIMIT),
        cursor: str | None = Query(default=None, min_length=1, max_length=4096),
        session: AsyncSession = Depends(get_db),
    ) -> Response:
        """최근 rolling 최대168시간의 유종별 실제 관측과 별도 현재 가격.

        Feature fuel_station의 양수 id/source를 함께 사용한다. 휴게소 현재 가격에는
        저장 이력이 없으므로501이며, 보간·provider 호출·raw 응답 노출은 하지 않는다.
        cursor는15분 동안 창을 고정하고 수집 revision이 바뀌면409로 재시작한다.
        """
        if source != OPINET_SOURCE:
            raise HTTPException(501, "이 원천의 주유소 가격 이력은 저장하지 않아 지원하지 않습니다.")
        try:
            read = await read_price_history_page(
                request, str(station_id), product, None, None, limit, cursor, session, cursor_key,
                native_station_id=station_id, default_days=days, max_window=timedelta(days=days),
                cursor_scope=f"native:{station_id}:{source}:{days}",
            )
        except PriceHistoryUnavailable as exc:
            return exc.response
        station = (await session.execute(select(
            FuelStation.source, FuelStation.source_station_id, FuelStation.brand_code, FuelStation.brand_name,
        ).where(FuelStation.id == read.station_id))).one()
        query = select(FuelLatestPrice).join(
            FuelPriceSnapshot, FuelPriceSnapshot.id == FuelLatestPrice.snapshot_id,
        ).where(
            FuelLatestPrice.fuel_station_id == read.station_id,
            FuelPriceSnapshot.fuel_station_id == read.station_id,
            FuelPriceSnapshot.source == OPINET_SOURCE,
            FuelPriceSnapshot.product_code == FuelLatestPrice.product_code,
            FuelLatestPrice.observed_at <= read.to_at,
            FuelLatestPrice.collected_at <= read.to_at,
        )
        if product is not None:
            query = query.where(FuelLatestPrice.product_code == product)
        latest = (await session.scalars(query.order_by(FuelLatestPrice.product_code).limit(MAX_LATEST_PRODUCTS + 1))).all()
        if len(latest) > MAX_LATEST_PRODUCTS:
            raise HTTPException(503, "저장 유종 수가 조회 상한을 넘어 가격 이력을 제공할 수 없습니다.")
        result = FuelStationPriceHistoryResponse(
            meta=read.page.meta, station_id=read.station_id, source=station.source,
            provider_id=station.source_station_id, brand_code=station.brand_code, brand_name=station.brand_name,
            window=FuelPriceHistoryWindow(from_at=read.from_at, to_at=read.to_at),
            source_last_success_at=read.source_last_success_at, source_revision=read.revision,
            latest=[_price_item(row) for row in latest], items=[_price_item(row) for row in read.rows],
            has_more=read.page.has_more, next_cursor=read.page.next_cursor,
        )
        await session.rollback()
        return _response(
            result, request,
            cursor_epoch=int(read.issued.timestamp()) // int(CURSOR_TTL.total_seconds()) if read.page.has_more else None,
            cursor_revision=read.revision if read.page.has_more else None,
        )

    return router
