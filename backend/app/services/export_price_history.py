"""Map 요청 프록시용 주유소 이력. 원천 추가 조회·이력 저장 정책 변경은 없다."""

from __future__ import annotations


import base64
import gzip
import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Select, and_, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.export_guard import ExportDeadlineRoute
from app.core.problems import RETRY_AFTER_SECONDS, SERVICE_EXPORT_PATH_PREFIX, CodedHTTPException, ProblemCode
from app.core.time_utils import now_utc, serialize_utc
from app.models import FuelPriceSnapshot, FuelStation, TransportCollectionState
from app.schemas import ExportPriceHistoryItem, FuelPriceHistoryExportPage, FuelStationPriceHistoryResponse, ServiceExportMeta
from app.services.parking_history_cache import accepts_gzip
from app.services.transport_collection import FUEL_STALE_AFTER, OPINET_SOURCE

MAX_HISTORY_LIMIT = 5000
MAX_HISTORY_WINDOW = timedelta(days=366)
CURSOR_TTL = timedelta(minutes=15)
# 이력 조회 transaction의 문장별 서버 상한(밀리초)은 `Settings.fuel_price_history_statement_timeout_ms`다
# (기본 3초). 주목적은 소비자가 이미 포기한 조회가 API 엔진 기본 상한(120초)까지 공용 DB 연결을 잡지 않게
# 하는 것이다. Map T4 read timeout(5초, 감사는 더 낮추기를 권고)이 이 상한보다 길 때만 Map이 503을 본다.
# `SET LOCAL`이라 transaction이 끝나면 연결의 기본값으로 돌아간다. 문장마다 적용되며 연결 풀 대기를 포함한
# 요청 전체 deadline은 아니다.

#: 상한 초과 응답의 `Retry-After`(초). 같은 조회를 곧바로 반복해 같은 부하를 다시 만들지 않게 한다.
HISTORY_TIMEOUT_RETRY_AFTER_SECONDS = 5
#: 상한 초과 응답 본문. export(503)와 native(504)가 같은 문장을 쓴다. 운영자 취소(pg_cancel_backend)도 같은
#: SQLSTATE 57014라 본문은 원인을 단정하지 않는다. 구분은 경고 로그(SQLSTATE·경로)로 한다.
HISTORY_TIMEOUT_DETAIL = "가격 이력 조회가 제시간에 끝나지 않았습니다. 잠시 후 다시 조회하세요."
#: PostgreSQL `query_canceled` — statement_timeout 초과 또는 운영자 취소다.
_QUERY_CANCELED = "57014"
#: OpenAPI에 `Retry-After`를 문서화할 가격 이력 상한 초과 응답(경로, method, status).
_HISTORY_TIMEOUT_RESPONSES = (
    ("/v1/service/exports/fuel-stations/{station_key}/price-history", "get", "503"),
    ("/v1/transport/fuel/stations/{station_id}/price-history", "get", "504"),
)


def document_history_retry_after(schema: dict[str, Any]) -> None:
    """OpenAPI에서 가격 이력 상한 초과 응답(export 503·native 504)의 `Retry-After` 헤더를 문서화한다.

    다른 계약이 이미 같은 헤더를 문서화했으면 덮어쓰지 않는다.
    """
    for path, method, status in _HISTORY_TIMEOUT_RESPONSES:
        response = schema.get("paths", {}).get(path, {}).get(method, {}).get("responses", {}).get(status)
        if response is not None:
            response.setdefault("headers", {}).setdefault("Retry-After", {
                "schema": {"type": "integer", "minimum": 1},
                "description": "DB 문장 시간 상한 초과로 끝난 응답에서 다시 요청하기 전 기다릴 초.",
            })


def opinet_station_identity(station_key: str) -> str:
    """오피넷 안정 ID(UNI_ID) 자연키의 `fuel_stations.identity_key`.

    수집 저장(`transport_collection._station_identity`)이 안정 ID가 있는 주유소에 쓰는 형식과 같아야 한다.
    수집 저장 경로로 만든 fixture에서 두 형식이 같은 행을 고르는지 회귀 테스트로 고정한다.
    """
    return f"station:{station_key}"


def station_lookup_statement(station_key: str, native_station_id: int | None = None) -> Select:
    """이력 대상 주유소 1행(id·source·자연키·상표).

    export 자연키는 수집기가 쓰는 identity_key로 찾는다. `uq_fuel_station_identity`(source, identity_key)
    유니크 인덱스 1행 조회이며, 인덱스 없는 source_station_id 전체 스캔을 피한다. 안정 ID가 있는 행은
    identity_key == 'station:' + source_station_id다(`opinet_station_identity`, 회귀 테스트로 고정).
    native 경로는 기본키로 찾는다.
    """
    return select(
        FuelStation.id, FuelStation.source, FuelStation.source_station_id, FuelStation.brand_code, FuelStation.brand_name,
    ).where(
        FuelStation.source == OPINET_SOURCE,
        (FuelStation.identity_key == opinet_station_identity(station_key) if native_station_id is None
         else FuelStation.id == native_station_id),
    )

logger = logging.getLogger(__name__)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("이력 시각에는 timezone이 필요합니다.")
    return value.astimezone(UTC)


def _revision(state: TransportCollectionState) -> str:
    value = [serialize_utc(state.last_success_at).isoformat(), bool(state.last_error),
             serialize_utc(state.updated_at).isoformat()]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def _encode_cursor(value: dict, key: bytes) -> str:
    body = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
    signed = hmac.new(key, body, hashlib.sha256).hexdigest().encode() + b"." + body
    return base64.urlsafe_b64encode(signed).decode().rstrip("=")


def _decode_cursor(value: str, key: bytes) -> dict:
    try:
        signed = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        signature, body = signed.split(b".", 1)
        expected = hmac.new(key, body, hashlib.sha256).hexdigest().encode()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        result = json.loads(body)
        if not isinstance(result, dict) or result.get("v") != 1:
            raise ValueError("version")
        return result
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "cursor는 이전 응답의 next_cursor를 그대로 사용해야 합니다.") from exc


def _response(
    page: FuelPriceHistoryExportPage | FuelStationPriceHistoryResponse, request: Request, *, cursor_epoch: int | None,
    cursor_revision: str | None, etag_override: str | None = None,
) -> Response:
    payload = page.model_dump(mode="json")
    etag = etag_override
    if etag is None:
        semantic = {**payload, "meta": {k: v for k, v in payload["meta"].items() if k != "generated_at"}}
        # cursor는 같은 집합/페이지의 다른 발급시각이어도 같은 탐색을 제공한다.
        semantic.pop("next_cursor")
        # TTL보다 먼저 바뀌는 고정 bucket을 ETag에 넣어 304가 만료 cursor만
        # 영구 재사용하게 만들지 않는다. 같은 bucket 안의 cursor는 모두 유효하다.
        semantic["cursor_epoch"] = cursor_epoch
        semantic["cursor_revision"] = cursor_revision
        digest = hashlib.sha256(json.dumps(semantic, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        etag = f'W/"{digest}"'
    headers = {"ETag": etag, "Vary": "Accept-Encoding", "Cache-Control": "private, no-cache"}
    candidates = request.headers.get("if-none-match", "").split(",")
    if any(tag.strip() == "*" or tag.strip().removeprefix("W/") == etag[2:] for tag in candidates):
        return Response(status_code=304, headers=headers)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    if len(body) >= 512 and accepts_gzip(request.headers.get("accept-encoding", "")):
        body = gzip.compress(body, compresslevel=1, mtime=0)
        headers["Content-Encoding"] = "gzip"
    return Response(body, media_type="application/json", headers=headers)


@dataclass
class PriceHistoryRead:
    page: FuelPriceHistoryExportPage
    rows: list[Any]
    station_id: int
    from_at: datetime
    to_at: datetime
    source_last_success_at: datetime
    revision: str
    issued: datetime
    #: 같은 snapshot에서 읽은 주유소 행(id, source, source_station_id, brand_code, brand_name).
    #: native 응답이 주유소를 다시 조회하지 않게 한다.
    station: Any


class PriceHistoryUnavailable(Exception):
    def __init__(self, response: Response):
        self.response = response


@asynccontextmanager
async def history_statement_deadline(
    session: AsyncSession, request: Request, *, status_code: int = 503,
) -> AsyncIterator[None]:
    """이력 transaction의 57014(statement_timeout 초과·운영자 취소)를 500이 아닌 `status_code` + Retry-After로 바꾼다.

    T4 export는 503이다(Map은 meta 없는 503을 upstream_unavailable로 강등한다). native 지도 상세 경로는 504다.
    화면이 503을 '성공한 수집 이력 없음'으로 안내하므로, 일시적인 조회 지연을 그 문구와 섞지 않는다.
    다른 DB 오류는 그대로 올린다. 실패한 transaction은 바로 rollback해 연결을 반환한다.
    """
    try:
        yield
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate != _QUERY_CANCELED:
            raise
        # SQL·접속 정보가 담길 수 있는 예외 원문은 남기지 않는다.
        logger.warning("price history query canceled mapped to status=%s sqlstate=%s path=%s",
                       status_code, sqlstate, request.url.path)
        await session.rollback()
        if status_code == 503:
            # export(T4) 503은 다른 export 503처럼 code를 싣는다(ADR-013 개정 2026-11-24). native 504는 그대로다.
            raise CodedHTTPException(
                503, HISTORY_TIMEOUT_DETAIL, code=ProblemCode.EXPORT_QUERY_TIMEOUT,
                retry_after=HISTORY_TIMEOUT_RETRY_AFTER_SECONDS, headers={"Cache-Control": "private, no-cache"},
            ) from exc
        raise HTTPException(
            status_code, HISTORY_TIMEOUT_DETAIL,
            headers={"Retry-After": str(HISTORY_TIMEOUT_RETRY_AFTER_SECONDS), "Cache-Control": "private, no-cache"},
        ) from exc


async def read_price_history_page(
    request: Request, station_key: str, product: str | None,
    from_at: datetime | None, to_at: datetime | None, limit: int, cursor: str | None,
    session: AsyncSession, cursor_key: bytes, *, statement_timeout_ms: int, native_station_id: int | None = None,
    default_days: int = 30, max_window: timedelta = MAX_HISTORY_WINDOW,
    cursor_scope: str | None = None,
) -> PriceHistoryRead:
    """한 주유소의 bounded DB 이력. 호출자가 같은 snapshot의 후속 조회와 rollback을 소유한다.

    PostgreSQL에서는 transaction에 `statement_timeout_ms` 문장 상한을 건다. 호출자는
    `history_statement_deadline` 안에서 불러 상한 초과를 export 503·native 504 problem으로 바꾼다.
    """
    if session.bind.dialect.name == "postgresql":
        await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        await session.execute(text(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}"))
    station = (await session.execute(station_lookup_statement(station_key, native_station_id))).one_or_none()
    if station is None:
        raise HTTPException(404, "주유소 자연키를 찾을 수 없습니다." if native_station_id is None else "저장된 주유소를 찾을 수 없습니다.")
    station_id = station.id
    state = await session.scalar(select(TransportCollectionState).where(
        TransportCollectionState.source == OPINET_SOURCE,
    ))
    if state is None or state.last_success_at is None:
        # export 경로(T4)만 가산 code·Retry-After를 싣는다. `meta`(source_status=failed)는 그대로다. 같은 함수를 쓰는
        # 관리 화면용 native 이력 경로는 본문·헤더가 예전과 같다(ADR-013 개정 2026-11-24).
        coded = {"code": ProblemCode.EXPORT_NO_HISTORY.value} if request.url.path.startswith(
            SERVICE_EXPORT_PATH_PREFIX) else {}
        headers = {"Cache-Control": "private, no-cache"}
        if coded:
            headers["Retry-After"] = str(RETRY_AFTER_SECONDS[ProblemCode.EXPORT_NO_HISTORY])
            # 이 503은 HTTPException handler를 거치지 않으므로 code 응답 로그를 여기서 남긴다(감사 T23-10).
            logger.warning("problem response status=503 code=%s path=%s detail=%s",
                           ProblemCode.EXPORT_NO_HISTORY.value, request.url.path, "성공한 유가 수집 이력이 없습니다.")
        raise PriceHistoryUnavailable(JSONResponse(status_code=503, media_type="application/problem+json", content={
            "type": "about:blank", "title": "Service Unavailable", "status": 503,
            "detail": "성공한 유가 수집 이력이 없습니다.", "instance": request.url.path, **coded,
            "meta": ServiceExportMeta(generated_at=now_utc(), source_collected_at=None,
                                      source_status="failed", item_count=0).model_dump(mode="json"),
        }, headers=headers))
    now = now_utc()
    revision = _revision(state)
    after_at = None
    after_id = None
    try:
        if cursor is not None:
            saved = _decode_cursor(cursor, cursor_key)
            if saved["station"] != station_key or saved["product"] != product or saved.get("scope") != cursor_scope:
                raise ValueError("cursor 필터가 다릅니다.")
            if saved["revision"] != revision:
                raise HTTPException(409, "수집 상태가 바뀌었습니다. 첫 페이지부터 다시 조회하세요.")
            issued = _aware(datetime.fromisoformat(saved["issued"]))
            if now - issued > CURSOR_TTL or issued > now:
                raise HTTPException(409, "cursor가 만료됐습니다. 첫 페이지부터 다시 조회하세요.")
            start, end = (_aware(datetime.fromisoformat(saved[k])) for k in ("from", "to"))
            if (from_at is not None and _aware(from_at) != start
                    or to_at is not None and _aware(to_at) != end):
                raise ValueError("cursor 시각 조건이 다릅니다.")
            after_at = _aware(datetime.fromisoformat(saved["at"]))
            after_id = saved["id"]
            if type(after_id) is not int or after_id < 1:
                raise ValueError("cursor 행 키가 잘못됐습니다.")
        else:
            end = _aware(to_at) if to_at is not None else now
            start = _aware(from_at) if from_at is not None else end - timedelta(days=default_days)
            issued = now
        if end < start or end - start > max_window or end > now:
            raise ValueError("조회 창은 과거366일 이내 길이여야 합니다.")
        if cursor_scope is not None and (end != issued or start != issued - timedelta(days=default_days)):
            raise ValueError("공개 이력 cursor는 최초 요청의 rolling 창만 사용할 수 있습니다.")
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise HTTPException(422, "이력 시각·창·cursor 조건이 올바르지 않습니다.") from exc
    query = select(FuelPriceSnapshot.product_code, FuelPriceSnapshot.observed_at,
                   FuelPriceSnapshot.price, FuelPriceSnapshot.collected_at, FuelPriceSnapshot.id, FuelPriceSnapshot.provider_updated_at).where(
        FuelPriceSnapshot.fuel_station_id == station_id,
        FuelPriceSnapshot.source == OPINET_SOURCE,
        FuelPriceSnapshot.observed_at >= start, FuelPriceSnapshot.observed_at <= end,
    )
    if product is not None:
        query = query.where(FuelPriceSnapshot.product_code == product)
    if after_at is not None:
        query = query.where(or_(FuelPriceSnapshot.observed_at < after_at, and_(
            FuelPriceSnapshot.observed_at == after_at, FuelPriceSnapshot.id < after_id,
        )))
    rows = (await session.execute(query.order_by(
        FuelPriceSnapshot.observed_at.desc(), FuelPriceSnapshot.id.desc(),
    ).limit(limit + 1))).all()
    page, has_more = rows[:limit], len(rows) > limit
    next_cursor = None
    if has_more:
        next_cursor = _encode_cursor({
            **({"scope": cursor_scope} if cursor_scope is not None else {}),
            "v": 1, "station": station_key, "product": product, "revision": revision,
            "from": start.isoformat(), "to": end.isoformat(), "issued": issued.isoformat(),
            "at": serialize_utc(page[-1].observed_at).isoformat(), "id": page[-1].id,
        }, cursor_key)
    source_clock = min(serialize_utc(row.collected_at) for row in page) if page else serialize_utc(state.last_success_at)
    source_status = "stale" if (state.last_error or now - serialize_utc(state.last_success_at) > FUEL_STALE_AFTER) else "ok"
    result = FuelPriceHistoryExportPage(
        meta=ServiceExportMeta(generated_at=now_utc(), source_collected_at=source_clock,
                               source_status=source_status, item_count=len(page)),
        station_key=station_key, items=[ExportPriceHistoryItem(
            product_code=row.product_code, observed_at=serialize_utc(row.observed_at),
            price=float(row.price) if row.price is not None else None,
        ) for row in page], next_cursor=next_cursor, has_more=has_more,
    )
    return PriceHistoryRead(result, page, station_id, start, end, serialize_utc(state.last_success_at), revision, issued,
                            station)


def build_price_history_router(
    settings: Settings, get_db: Callable[..., AsyncIterator[AsyncSession]],
) -> APIRouter:
    # 상위 service router의 기존 token/peer Depends를 그대로 상속한다. handler 전체 상한(25초)은 T4 export에만 둔다.
    router = APIRouter(route_class=ExportDeadlineRoute)
    cursor_key = hashlib.sha256((settings.transport_service_export_token or "").encode()).digest()
    statement_timeout_ms = settings.fuel_price_history_statement_timeout_ms

    @router.get("/fuel-stations/{station_key}/price-history", response_model=FuelPriceHistoryExportPage,
                responses={200: {"headers": {
                    "ETag": {"schema": {"type": "string"}, "description": "데이터·상태·cursor 유효성의 weak ETag"},
                    "Content-Encoding": {"schema": {"type": "string"}, "description": "요청 시 gzip 지원"},
                }}, 304: {"description": "집합·상태·cursor 유효성이 동일함"}, 404: {}, 409: {}, 503: {}})
    async def price_history(
        request: Request,
        station_key: str = Path(min_length=1, max_length=80),
        product: str | None = Query(default=None, min_length=1, max_length=20),
        from_at: datetime | None = Query(default=None, alias="from"),
        to_at: datetime | None = Query(default=None, alias="to"),
        limit: int = Query(default=1000, ge=1, le=MAX_HISTORY_LIMIT),
        cursor: str | None = Query(default=None, min_length=1, max_length=4096),
        session: AsyncSession = Depends(get_db),
    ) -> Response:
        """주유소 자연키의 유종별 과거 가격. 기본 최근30일·최대366일·한 페이지5000건이다.

        cursor는15분 동안 창·필터·성공 수집 revision을 고정한다. 수집 revision이 바뀌면409로
        처음부터 다시 읽는다. 휴게소 가격 이력 표는 만들지 않으며 별도 경로는501이다.
        DB 문장이 서버 상한(기본3초)을 넘으면 meta 없는503 problem과 `Retry-After`를 낸다.
        """
        try:
            async with history_statement_deadline(session, request):
                read = await read_price_history_page(
                    request, station_key, product, from_at, to_at, limit, cursor, session, cursor_key,
                    statement_timeout_ms=statement_timeout_ms,
                )
        except PriceHistoryUnavailable as exc:
            return exc.response
        # gzip/JSON CPU 작업 중에는 DB snapshot을 잡지 않는다.
        await session.rollback()
        return _response(
            read.page, request,
            cursor_epoch=int(read.issued.timestamp()) // int(CURSOR_TTL.total_seconds()) if read.page.has_more else None,
            cursor_revision=read.revision if read.page.has_more else None,
        )

    @router.get("/rest-area-fuel-prices/{station_key}/price-history", status_code=501,
                responses={404: {}, 501: {}})
    async def rest_area_history(station_key: str = Path(min_length=1, max_length=240)) -> Response:
        """휴게소 유가 이력은 저장하지 않아 지원하지 않는다. 현재 가격 export를 사용한다."""
        raise HTTPException(501, "휴게소 유가 이력은 저장하지 않아 지원하지 않습니다.")

    return router
