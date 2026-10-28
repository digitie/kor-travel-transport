from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from xml.etree import ElementTree

from krairport import KrairportClient
from krairport.models import ParkingFee
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc, serialize_utc
from app.models import Airport, CollectionRun, ParkingFeeRule, ParkingLot, ParkingSnapshot, RawApiResponse, TransportCollectionState
from app.services.flight_status import sanitize_upstream_error
from app.services.parsers import (
    ParsedFeeRule,
    ParsedParkingObservation,
    parse_incheon_fee,
    parse_incheon_parking,
    parse_kac_fee,
    parse_kac_parking,
)


KAC_QUOTA_SOURCE = "airport_kac_quota"
KAC_FEE_REFRESH_CONTRACT = "kac_fee_daily:v1"

KAC_PARKING_ENDPOINT = "http://openapi.airport.co.kr/service/rest/AirportParking/airportparkingRT"
INCHEON_PARKING_ENDPOINT = "http://apis.data.go.kr/B551177/StatusOfParking/getTrackingParking"
KAC_FEE_ENDPOINT = "http://openapi.airport.co.kr/service/rest/AirportParkingFee/parkingfee"
INCHEON_FEE_ENDPOINT = "http://apis.data.go.kr/B551177/ParkingChargeInfo/getParkingChargeInformation"
UPSTREAM_RATE_LIMIT_MARKER = "LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR."
SENSITIVE_REQUEST_KEYS = {"servicekey", "service_key", "apikey", "api_key", "token", "password"}

logger = logging.getLogger(__name__)

SAMPLE_KAC_PARKING_ITEMS = [
    {"aprEng": "GIMPO INTERNATIONAL AIRPORT", "aprKor": "김포국제공항", "parkingAirportCodeName": "국내선 제1주차장", "parkingFullSpace": "2279", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "1813", "parkingIoutcnt": "1507", "parkingIstay": "2046"},
    {"aprEng": "GIMPO INTERNATIONAL AIRPORT", "aprKor": "김포국제공항", "parkingAirportCodeName": "국내선 제2주차장", "parkingFullSpace": "1733", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "914", "parkingIoutcnt": "820", "parkingIstay": "1358"},
    {"aprEng": "GIMPO INTERNATIONAL AIRPORT", "aprKor": "김포국제공항", "parkingAirportCodeName": "국제선 주차빌딩", "parkingFullSpace": "567", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "301", "parkingIoutcnt": "282", "parkingIstay": "434"},
    {"aprEng": "GIMPO INTERNATIONAL AIRPORT", "aprKor": "김포국제공항", "parkingAirportCodeName": "국제선 지하", "parkingFullSpace": "599", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "318", "parkingIoutcnt": "295", "parkingIstay": "485"},
    {"aprEng": "GIMHAE INTERNATIONAL AIRPORT", "aprKor": "김해국제공항", "parkingAirportCodeName": "P1 여객주차장", "parkingFullSpace": "2005", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "1114", "parkingIoutcnt": "970", "parkingIstay": "1782"},
    {"aprEng": "GIMHAE INTERNATIONAL AIRPORT", "aprKor": "김해국제공항", "parkingAirportCodeName": "P2 여객주차장", "parkingFullSpace": "2453", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "1337", "parkingIoutcnt": "1255", "parkingIstay": "2362"},
    {"aprEng": "GIMHAE INTERNATIONAL AIRPORT", "aprKor": "김해국제공항", "parkingAirportCodeName": "P3 여객(화물)", "parkingFullSpace": "878", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "342", "parkingIoutcnt": "349", "parkingIstay": "809"},
    {"aprEng": "JEJU INTERNATIONAL AIRPORT", "aprKor": "제주국제공항", "parkingAirportCodeName": "P1주차장", "parkingFullSpace": "1763", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "3573", "parkingIoutcnt": "3333", "parkingIstay": "1417"},
    {"aprEng": "JEJU INTERNATIONAL AIRPORT", "aprKor": "제주국제공항", "parkingAirportCodeName": "P2장기주차장", "parkingFullSpace": "488", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "124", "parkingIoutcnt": "109", "parkingIstay": "325"},
    {"aprEng": "JEJU INTERNATIONAL AIRPORT", "aprKor": "제주국제공항", "parkingAirportCodeName": "화물주차장", "parkingFullSpace": "732", "parkingGetdate": "2026-04-25", "parkingGettime": "09:20:03", "parkingIincnt": "98", "parkingIoutcnt": "92", "parkingIstay": "418"},
]

SAMPLE_INCHEON_ITEMS = [
    {"floor": "T1 단기주차장", "parking": "575", "parkingarea": "640", "datetm": "2026-04-25 09:20"},
    {"floor": "T2 장기주차장", "parking": "832", "parkingarea": "910", "datetm": "2026-04-25 09:20"},
]

SAMPLE_INCHEON_FEE_ITEMS = [
    {"charid": "FB00000001", "chardesc": "최초 00:30 에 한해 1200원 적용", "datetime": "202605080630"},
    {"charid": "FB00000001", "chardesc": "00:15 초과 시 600원 부과", "datetime": "202605080630"},
    {"charid": "FB00000002", "chardesc": "01:00 초과 시 1000원 부과", "datetime": "202605080630"},
    {"charid": "FB00000003", "chardesc": "00:30 초과 시 1200원 부과", "datetime": "202605080630"},
    {"charid": "NF00000001", "chardesc": "일일 최대 24000원 적용", "datetime": "202605080630"},
    {"charid": "NF00000002", "chardesc": "일일 최대 9000원 적용", "datetime": "202605080630"},
    {"charid": "NF00000003", "chardesc": "일일 최대 12000원 적용", "datetime": "202605080630"},
]

SAMPLE_KAC_FEE_LOT_NAMES = {
    "GMP": ("김포국제공항", ["국내선 제1주차장", "국내선 제2주차장", "국제선 지하주차장", "국제선 주차빌딩"]),
    "PUS": ("김해국제공항", ["P1 여객주차장", "P2 여객주차장", "P3 여객(화물)주차장"]),
    "CJU": ("제주국제공항", ["P1 주차장", "P2 장기주차장", "화물터미널주차장"]),
}


def _kac_fee_sample_items(airport_code: str) -> list[dict[str, str]]:
    """Sample KAC fee items using the live endpoint's real (camelCase) field
    names -- confirmed against `AirportParkingFee/parkingfee` directly (see
    ADR-004 / T-030). Do not revert to `PARKING_BASIC_ACCOUNT`-style names;
    that was never the real API shape."""

    airport_name, lot_names = SAMPLE_KAC_FEE_LOT_NAMES.get(airport_code, SAMPLE_KAC_FEE_LOT_NAMES["GMP"])
    return [
        {
            "siteName": airport_name,
            "parkingParkingName": lot_name,
            "parkingBasicAccount": "1000",
            "parkingBasicM": "30",
            "parkingFreeM": "30",
            "parkingMinuteAccount": "500",
            "parkingMinuteM": "15",
            "parkingMaxAccount": "20000",
            "parkingHoliBasicAccount": "1500",
            "parkingHoliBasicM": "30",
            "parkingHoliFreeM": "30",
            "parkingHoliMinuteAccount": "700",
            "parkingHoliMinuteM": "15",
            "parkingHoliMaxAccount": "25000",
            "parkingBasicAccountd": "1200",
            "parkingBasicMd": "30",
            "parkingFreeMd": "30",
            "parkingMinuteAccountd": "600",
            "parkingMinuteMd": "15",
            "parkingMaxAccountd": "25000",
            "parkingHoliBasicAccountd": "1800",
            "parkingHoliBasicMd": "30",
            "parkingHoliFreeMd": "30",
            "parkingHoliMinuteAccountd": "800",
            "parkingHoliMinuteMd": "15",
            "parkingHoliMaxAccountd": "30000",
        }
        for lot_name in lot_names
    ]


@dataclass(slots=True)
class SourceResponse:
    source: str
    endpoint: str
    request_params: dict[str, Any]
    status_code: int
    body_text: str
    completion: dict[str, Any] | None = None
    fee_rules: list[ParsedFeeRule] | None = None
    raw_response_id: int | None = None


def _kac_fee_domain_rules(items: list[ParkingFee], airport_code: str) -> list[ParsedFeeRule]:
    """SDK의 정규화 요금표를 저장용 도메인으로 옮긴다. 공급자 필드를 재파싱하지 않는다."""
    rules: list[ParsedFeeRule] = []
    observed_at = now_utc()
    for item in items:
        if item.airport_code != airport_code:
            raise ValueError("요금표 공항이 요청 공항과 다릅니다.")
        for vehicle in ("small", "large"):
            for day_type, holiday in (("weekday", ""), ("holiday", "holiday_")):
                values = {name: getattr(item, f"{vehicle}_{holiday}{name}") for name in (
                    "free_minutes", "basic_minutes", "basic_fee", "unit_minutes", "unit_fee", "daily_max_fee",
                )}
                if any(value is None for value in values.values()):
                    continue
                if values["basic_minutes"] <= 0 or values["unit_minutes"] <= 0:
                    raise ValueError("요금표의 기본·추가 단위시간이 올바르지 않습니다.")
                rules.append(ParsedFeeRule(
                    airport_code=airport_code, airport_name=item.airport_name or airport_code,
                    parking_lot_name=item.parking_name, vehicle_size=vehicle, day_type=day_type,
                    source_updated_at=observed_at, raw_item=dict(item.raw), **values,
                ))
    if items and not rules:
        raise ValueError("완전한 주차요금 규칙을 제공받지 못했습니다.")
    return rules


@dataclass(slots=True)
class UpstreamRateLimitState:
    is_blocked: bool
    blocked_until: datetime | None = None
    source: str | None = None
    error_message: str | None = None


class PublicDataClient:
    async def fetch_kac_parking(self) -> SourceResponse:
        raise NotImplementedError

    async def fetch_incheon_parking(self) -> SourceResponse:
        raise NotImplementedError

    async def fetch_incheon_fee(self) -> SourceResponse:
        raise NotImplementedError

    async def fetch_kac_fee(self, airport_code: str) -> SourceResponse:
        raise NotImplementedError


class FixturePublicDataClient(PublicDataClient):
    async def fetch_kac_parking(self) -> SourceResponse:
        return SourceResponse(
            source="kac_parking",
            endpoint=KAC_PARKING_ENDPOINT,
            request_params={"scope": "all"},
            status_code=200,
            body_text=json.dumps(SAMPLE_KAC_PARKING_ITEMS, ensure_ascii=False),
            completion={"complete": True, "item_count": len(SAMPLE_KAC_PARKING_ITEMS), "fixture": True},
        )

    async def fetch_incheon_parking(self) -> SourceResponse:
        return SourceResponse(
            source="incheon_parking",
            endpoint=INCHEON_PARKING_ENDPOINT,
            request_params={"type": "json"},
            status_code=200,
            body_text=json.dumps(SAMPLE_INCHEON_ITEMS, ensure_ascii=False),
            completion={"complete": True, "item_count": len(SAMPLE_INCHEON_ITEMS), "fixture": True},
        )

    async def fetch_incheon_fee(self) -> SourceResponse:
        return SourceResponse(
            source="incheon_fee",
            endpoint=INCHEON_FEE_ENDPOINT,
            request_params={"type": "json"},
            status_code=200,
            body_text=json.dumps(SAMPLE_INCHEON_FEE_ITEMS, ensure_ascii=False),
        )

    async def fetch_kac_fee(self, airport_code: str) -> SourceResponse:
        return SourceResponse(
            source="kac_fee",
            endpoint=KAC_FEE_ENDPOINT,
            request_params={"schAirportCode": airport_code},
            status_code=200,
            body_text=json.dumps(_kac_fee_sample_items(airport_code), ensure_ascii=False),
        )


class KrairportPublicDataClient(PublicDataClient):
    """공급자 조회·요금 필드 정규화는 SDK에 맡기고 원문은 감사용으로 보존한다.

    KAC 요금은 완전한 typed `ParkingFee`를 소비한다. typed 지원이 없는
    인천 요금 등은 기존 SDK 원문 경로를 유지하며 HTTP 우회 구현을 만들지 않는다.
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.data_go_kr_service_key:
            raise ValueError("공공데이터 서비스 키가 필요합니다.")
        self.settings = settings

    async def _raw_items(
        self,
        *,
        provider: str,
        service: str,
        operation: str,
        params: dict[str, Any],
        source: str,
        endpoint: str,
    ) -> SourceResponse:
        async with KrairportClient(
            kac_service_key=self.settings.data_go_kr_service_key,
            iiac_service_key=self.settings.data_go_kr_service_key,
            timeout=self.settings.api_timeout_seconds,
        ) as client:
            completion = None
            if self.settings.transport_map_current_enabled and source in {"kac_parking", "incheon_parking"}:
                receipt = await client.parking_raw_set(provider=provider, page_size=100, max_pages=20)
                items = list(receipt.items)
                completion = {"complete": True, "item_count": receipt.total_count,
                              "page_count": receipt.page_count, "page_size": receipt.page_size,
                              "wire_page_metadata": receipt.wire_page_metadata,
                              "contract": "python-krairport-api:parking_raw_set:v1"}
            elif provider == "kac":
                items = await client.kac_raw_items(service, operation, params)
            else:
                items = await client.iiac_raw_items(service, operation, params)
        return SourceResponse(
            source=source,
            endpoint=endpoint,
            request_params=params,
            status_code=200,
            body_text=json.dumps(items, ensure_ascii=False),
            completion=completion,
        )

    async def fetch_kac_parking(self) -> SourceResponse:
        return await self._raw_items(
            provider="kac",
            service="AirportParking",
            operation="airportparkingRT",
            params={},
            source="kac_parking",
            endpoint=KAC_PARKING_ENDPOINT,
        )

    async def fetch_incheon_parking(self) -> SourceResponse:
        return await self._raw_items(
            provider="iiac",
            service="StatusOfParking",
            operation="getTrackingParking",
            params={"pageNo": 1, "numOfRows": 50},
            source="incheon_parking",
            endpoint=INCHEON_PARKING_ENDPOINT,
        )

    async def fetch_incheon_fee(self) -> SourceResponse:
        return await self._raw_items(
            provider="iiac",
            service="ParkingChargeInfo",
            operation="getParkingChargeInformation",
            params={"pageNo": 1, "numOfRows": 100},
            source="incheon_fee",
            endpoint=INCHEON_FEE_ENDPOINT,
        )

    async def fetch_kac_fee(self, airport_code: str) -> SourceResponse:
        async with KrairportClient(
            kac_service_key=self.settings.data_go_kr_service_key,
            timeout=self.settings.api_timeout_seconds,
            retries=0,
        ) as client:
            items = await client.parking_fees(airport_code=airport_code)
        return SourceResponse(
            source="kac_fee",
            endpoint=KAC_FEE_ENDPOINT,
            request_params={"schAirportCode": airport_code}, status_code=200,
            body_text=json.dumps([dict(item.raw) for item in items], ensure_ascii=False),
            fee_rules=_kac_fee_domain_rules(items, airport_code),
        )


def validate_source_response_body(source: str, body_text: str) -> None:
    if body_text.strip().startswith("["):
        # KrairportPublicDataClient / FixturePublicDataClient already hand us
        # a pre-extracted item list -- krairport validates resultCode itself
        # (raising before returning) for the live path, and the fixture path
        # has nothing to validate.
        return

    if source in {"kac_parking", "kac_congestion", "kac_fee"}:
        root = ElementTree.fromstring(body_text)
        result_code = (root.findtext(".//resultCode") or "").strip()
        result_msg = (root.findtext(".//resultMsg") or "").strip()
        if result_code and result_code not in {"00", "0"}:
            raise ValueError(f"{source} API error {result_code}: {result_msg}")
        return

    if source in {"incheon_parking", "incheon_fee"}:
        document = json.loads(body_text)
        header = document.get("response", {}).get("header", {})
        result_code = str(header.get("resultCode") or "").strip()
        result_msg = str(header.get("resultMsg") or "").strip()
        if result_code and result_code not in {"00", "0"}:
            raise ValueError(f"{source} API error {result_code}: {result_msg}")


def redact_request_params(params: dict[str, Any]) -> dict[str, Any]:
    """Keep request provenance without persisting reusable credentials."""

    return {
        key: "[REDACTED]" if key.lower() in SENSITIVE_REQUEST_KEYS else value
        for key, value in params.items()
    }


def build_public_data_client(settings: Settings) -> PublicDataClient:
    if settings.data_go_kr_service_key:
        return KrairportPublicDataClient(settings)
    if settings.use_sample_client_when_no_key:
        return FixturePublicDataClient()
    raise ValueError("DATA_GO_KR_SERVICE_KEY가 없으면 실데이터 수집을 시작할 수 없습니다.")


def is_upstream_rate_limit_error(message: str | None) -> bool:
    if not message:
        return False
    return UPSTREAM_RATE_LIMIT_MARKER in message.upper()


def normalize_upstream_rate_limit_error(message: str | None) -> str:
    if not is_upstream_rate_limit_error(message):
        return message or UPSTREAM_RATE_LIMIT_MARKER
    if message and "upstream rate limit active until" not in message.lower():
        return message
    return f"kac_parking API error 99: {UPSTREAM_RATE_LIMIT_MARKER}"


def compute_upstream_rate_limit_retry_at(reference_at: datetime, backoff_seconds: int) -> datetime:
    return serialize_utc(reference_at) + timedelta(seconds=max(backoff_seconds, 0))


class CollectionService:
    def __init__(self, settings: Settings, client: PublicDataClient | None = None) -> None:
        self.settings = settings
        self.client = client or build_public_data_client(settings)
        # The deployment runs one backend process. Serialize scheduler/manual
        # collection so a cooldown check cannot launch two upstream writes.
        self.operation_lock = asyncio.Lock()

    @property
    def client_mode(self) -> str:
        return "live" if isinstance(self.client, KrairportPublicDataClient) else "sample"

    @property
    def enabled_sources(self) -> list[str]:
        sources = ["kac_parking"]
        if self.settings.enable_incheon_collection:
            sources.append("incheon_parking")
        if self.settings.enable_fee_collection:
            sources.append("kac_fee")
        if self.settings.enable_incheon_fee_collection:
            sources.append("incheon_fee")
        return sources

    async def get_upstream_rate_limit_state(self, session: AsyncSession) -> UpstreamRateLimitState:
        if self.client_mode != "live":
            return UpstreamRateLimitState(is_blocked=False)

        quota = await session.scalar(select(TransportCollectionState).where(
            TransportCollectionState.source == KAC_QUOTA_SOURCE,
        ))
        if quota is not None:
            # 한 번 명시 deadline을 만든 뒤에는 blocked 관찰 run의 started_at으로 재계산하지 않는다.
            due = serialize_utc(quota.next_due_at) if quota.next_due_at is not None else None
            if due is None or now_utc() >= due:
                # 지난 deadline은 차단이 아니다. legacy 분기와 같이 until·message를 비워 collector-status에
                # `upstream_rate_limited=false`와 과거 until이 함께 나가지 않게 한다.
                return UpstreamRateLimitState(is_blocked=False)
            return UpstreamRateLimitState(
                is_blocked=True, blocked_until=due, source="kac_parking", error_message=quota.last_error,
            )
        latest_run = await session.scalar(
            select(CollectionRun)
            .where(CollectionRun.status != "skipped")
            .order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
            .limit(1)
        )
        if latest_run is None or not is_upstream_rate_limit_error(latest_run.error_message):
            return UpstreamRateLimitState(is_blocked=False)

        blocked_until = compute_upstream_rate_limit_retry_at(
            latest_run.started_at,
            self.settings.upstream_rate_limit_backoff_seconds,
        )
        if now_utc() >= blocked_until:
            return UpstreamRateLimitState(is_blocked=False)

        return UpstreamRateLimitState(
            is_blocked=True,
            blocked_until=blocked_until,
            source="kac_parking",
            error_message=normalize_upstream_rate_limit_error(latest_run.error_message),
        )

    async def _retain_quota_deadline(self, session, state):
        """이전 배포의 native 오류를 한 번만 명시 deadline으로 채택한다."""
        row = await session.scalar(select(TransportCollectionState).where(
            TransportCollectionState.source == KAC_QUOTA_SOURCE,
        ).with_for_update())
        if row is None and state.blocked_until is not None:
            session.add(TransportCollectionState(
                source=KAC_QUOTA_SOURCE, next_due_at=state.blocked_until,
                last_started_at=serialize_utc(state.blocked_until) - timedelta(seconds=max(self.settings.upstream_rate_limit_backoff_seconds, 0)),
                last_error=self._redact(normalize_upstream_rate_limit_error(state.error_message)), updated_at=now_utc(),
            ))

    async def _record_quota_outcome(self, session, *, started_at, was_blocked, messages):
        if self.client_mode != "live" or was_blocked:
            return
        error = next((item for item in messages if is_upstream_rate_limit_error(item)), None)
        row = await session.scalar(select(TransportCollectionState).where(
            TransportCollectionState.source == KAC_QUOTA_SOURCE,
        ).with_for_update())
        if row is not None:
            if row.last_started_at is not None and serialize_utc(row.last_started_at) > started_at:
                return
            if row.next_due_at is not None and serialize_utc(row.next_due_at) > started_at:
                return  # 이미 유효한 원래 quota deadline을 실제 중복 실패도 연장하지 않는다.
        if error is None:
            if row is None:
                row = TransportCollectionState(source=KAC_QUOTA_SOURCE)
                session.add(row)
            # 초기 성공도 원장/fence를 남겨 늦은 옛 quota 실패가 새 대기를 만들지 못하게 한다.
            row.last_started_at = started_at
            row.next_due_at = None
            row.last_error = None
            row.updated_at = now_utc()
            return
        if row is None:
            row = TransportCollectionState(source=KAC_QUOTA_SOURCE)
            session.add(row)
        row.last_started_at = started_at
        row.next_due_at = compute_upstream_rate_limit_retry_at(started_at, self.settings.upstream_rate_limit_backoff_seconds)
        row.last_error = self._redact(normalize_upstream_rate_limit_error(error))
        row.updated_at = now_utc()

    async def collect(self, session: AsyncSession, trigger: str = "manual") -> dict[str, Any]:
        async with self.operation_lock:
            async with self._postgres_collection_lease(session) as acquired:
                if not acquired:
                    logger.warning("collection skipped trigger=%s because another database lease is active", trigger)
                    return {
                        "status": "skipped",
                        "reason": "another airport collection is active",
                        "raw_response_count": 0,
                        "snapshot_count": 0,
                        "fee_rule_count": 0,
                        "errors": [],
                    }
                return await self._collect_unlocked(session, trigger)

    @asynccontextmanager
    async def _postgres_collection_lease(self, session: AsyncSession) -> AsyncIterator[bool]:
        """동일 DB를 쓰는 Dagster/HTTP process 간 주차 수집을 하나로 직렬화한다.

        PostgreSQL session advisory lock은 수집 세션과 분리한 전용 connection에서 잡는다.
        수집 중 ``session.commit()``이 connection pool에 수집 세션 connection을 되돌려도
        lock 소유 connection은 유지되며, 같은 connection에서만 unlock한다. SQLite 단위
        테스트에는 기존 process-local lock만 적용한다.
        """
        engine = session.bind
        if engine is None or engine.dialect.name != "postgresql":
            yield True
            return

        async with engine.connect() as lock_connection:
            acquired = bool(
                await lock_connection.scalar(
                    text("SELECT pg_try_advisory_lock(hashtext('kor_travel_transport:airport_collection'))")
                )
            )
            try:
                yield acquired
            finally:
                if acquired:
                    released = bool(
                        await lock_connection.scalar(
                            text("SELECT pg_advisory_unlock(hashtext('kor_travel_transport:airport_collection'))")
                        )
                    )
                    if not released:
                        raise RuntimeError("airport collection advisory lock was not released by its owner connection")

    async def _collect_unlocked(self, session: AsyncSession, trigger: str = "manual") -> dict[str, Any]:
        rate_limit_state = await self.get_upstream_rate_limit_state(session)
        can_collect_incheon = self.settings.enable_incheon_collection or self.settings.enable_incheon_fee_collection
        if rate_limit_state.is_blocked:
            await self._retain_quota_deadline(session, rate_limit_state)
        if rate_limit_state.is_blocked and rate_limit_state.blocked_until is not None and not can_collect_incheon:
            return await self._store_rate_limit_skip(session, trigger, rate_limit_state)

        started_at = now_utc()
        run = CollectionRun(started_at=started_at, finished_at=None, status="running", trigger=trigger, error_message=None)
        session.add(run)
        await session.flush()

        owner_run_id = run.id if session.info.get("collector_owner") or self.settings.transport_map_current_enabled else None
        if owner_run_id is not None:
            await session.commit()  # worker 강제 종료 전에도 소유권 기록을 남긴다.

        errors: list[str] = []
        raw_count = 0
        snapshot_count = 0
        fee_rule_count = 0

        try:
            if self.settings.transport_map_current_enabled:
                raw_count, snapshot_count = await self._collect_map_parking(session, run.id, rate_limit_state, errors)
                run = await session.get(CollectionRun, owner_run_id)
            else:
                if rate_limit_state.is_blocked:
                    errors.append(
                        normalize_upstream_rate_limit_error(rate_limit_state.error_message)
                        or f"kac_parking API error 99: {UPSTREAM_RATE_LIMIT_MARKER}"
                    )
                else:
                    response = await self._safe_fetch(session, run, self.client.fetch_kac_parking, errors)
                    if response is not None:
                        raw_count += 1
                        parsed = parse_kac_parking(
                            response.body_text,
                            allowed_airport_codes=self.settings.supported_airport_codes,
                        )
                        snapshot_count += await self._store_observations(session, run.id, parsed)

                if self.settings.enable_incheon_collection:
                    response = await self._safe_fetch(session, run, self.client.fetch_incheon_parking, errors)
                    if response is None:
                        pass
                    else:
                        raw_count += 1
                        parsed = parse_incheon_parking(response.body_text)
                        snapshot_count += await self._store_observations(session, run.id, parsed)

            if (self.settings.enable_fee_collection and not rate_limit_state.is_blocked
                    and not any(is_upstream_rate_limit_error(message) for message in errors)):
                for airport_code in self.settings.supported_airport_codes:
                    if airport_code == "ICN":
                        continue
                    if not await self._kac_fee_refresh_due(session, airport_code, started_at):
                        continue
                    response = await self._safe_fetch(
                        session,
                        run,
                        lambda airport_code=airport_code: self.client.fetch_kac_fee(airport_code),
                        errors,
                        kac_fee_airport_code=airport_code,
                    )
                    if response is None:
                        if any(is_upstream_rate_limit_error(message) for message in errors):
                            break
                        continue
                    raw_count += 1
                    assert response.fee_rules is not None
                    error_start = len(errors)
                    fee_rule_count += await self._store_fee_rules(session, response.fee_rules, errors=errors)
                    # 저장 오류는 바깥 transaction을 실패시킨다. 원천/매칭 오류만 공항별 재시도에 남긴다.
                    raw = await session.scalar(select(RawApiResponse).where(
                        RawApiResponse.id == response.raw_response_id,
                        RawApiResponse.collection_run_id == run.id,
                        RawApiResponse.source == "kac_fee",
                        RawApiResponse.endpoint == KAC_FEE_ENDPOINT,
                        RawApiResponse.request_params_json["schAirportCode"].as_string() == airport_code,
                        RawApiResponse.request_params_json["fee_refresh_contract"].as_string() == KAC_FEE_REFRESH_CONTRACT,
                    ))
                    if raw is None:
                        raise RuntimeError("자체 생성한 KAC 요금 원문을 확인하지 못했습니다.")
                    raw.parse_status = "failed" if len(errors) > error_start else "parsed"
                    raw.parse_error = "\n".join(errors[error_start:]) or None

            if self.settings.enable_incheon_fee_collection:
                response = await self._safe_fetch(session, run, self.client.fetch_incheon_fee, errors)
                if response is not None:
                    raw_count += 1
                    assert response.fee_rules is not None
                    fee_rule_count += await self._store_fee_rules(session, response.fee_rules, errors=errors)

            if not errors:
                run.status = "success"
            elif raw_count == 0 and snapshot_count == 0 and fee_rule_count == 0:
                run.status = "failed"
            else:
                run.status = "partial_success"
        except Exception as exc:
            failed_at = now_utc()
            error_message = self._redact(str(exc))
            await session.rollback()
            await self._record_quota_outcome(session, started_at=started_at,
                                             was_blocked=rate_limit_state.is_blocked,
                                             messages=[*errors, error_message])
            if self.settings.transport_map_current_enabled and owner_run_id is not None:
                from app.services.parking_exports import KIND, parking_scope, parking_sources
                from app.services.reference_exports import mark_reference_failure
                for source in parking_sources(self.settings):
                    await mark_reference_failure(session, kind=KIND, scope=parking_scope(self.settings, source),
                                                 run_id=owner_run_id, error=type(exc).__name__)
            if owner_run_id is not None:
                stored_run = await session.get(CollectionRun, owner_run_id)
                if stored_run is not None:
                    stored_run.status = "failed"
                    stored_run.finished_at = failed_at
                    stored_run.error_message = error_message
            else:
                session.add(
                    CollectionRun(
                        started_at=started_at,
                        finished_at=failed_at,
                        status="failed",
                        trigger=trigger,
                        error_message=error_message,
                    )
                )
            await session.commit()
            raise
        else:
            run.finished_at = now_utc()
            run.error_message = "\n".join(errors) if errors else None
            await self._record_quota_outcome(session, started_at=started_at,
                                             was_blocked=rate_limit_state.is_blocked, messages=errors)
            await session.commit()
            if errors:
                # 공개 collector-status는 오류 코드만 낸다. 원문은 서버 로그(키는 가림)와 DB에만 둔다.
                logger.warning("collection run_id=%s errors: %s", run.id, self._redact(" | ".join(errors)))

        logger.info(
            "collection finished run_id=%s trigger=%s status=%s client_mode=%s raw=%s snapshots=%s fee_rules=%s errors=%s",
            run.id,
            trigger,
            run.status,
            self.client_mode,
            raw_count,
            snapshot_count,
            fee_rule_count,
            len(errors),
        )

        return {
            "collection_run_id": run.id,
            "status": run.status,
            "client_mode": self.client_mode,
            "raw_response_count": raw_count,
            "snapshot_count": snapshot_count,
            "fee_rule_count": fee_rule_count,
            "errors": errors,
        }

    async def _store_rate_limit_skip(
        self,
        session: AsyncSession,
        trigger: str,
        rate_limit_state: UpstreamRateLimitState,
    ) -> dict[str, Any]:
        started_at = now_utc()
        blocked_until = rate_limit_state.blocked_until or started_at
        blocked_until_iso = serialize_utc(blocked_until).isoformat().replace("+00:00", "Z")
        error_message = (
            f"{rate_limit_state.source or 'kac_parking'} upstream rate limit active until "
            f"{blocked_until_iso}: {rate_limit_state.error_message or UPSTREAM_RATE_LIMIT_MARKER}"
        )
        run = CollectionRun(
            started_at=started_at,
            finished_at=started_at,
            status="skipped",
            trigger=trigger,
            error_message=error_message,
        )
        session.add(run)
        await session.commit()
        logger.warning(
            "collection skipped trigger=%s client_mode=%s blocked_until=%s reason=%s",
            trigger,
            self.client_mode,
            blocked_until_iso,
            rate_limit_state.error_message,
        )
        return {
            "collection_run_id": run.id,
            "status": run.status,
            "client_mode": self.client_mode,
            "raw_response_count": 0,
            "snapshot_count": 0,
            "fee_rule_count": 0,
            "errors": [error_message],
        }

    def _redact(self, message: str) -> str:
        # flight_status와 같은 sanitizer(원문 키 + URL의 serviceKey= 값 — 인코딩된 키 포함)를 쓴다.
        return sanitize_upstream_error(message, self.settings.data_go_kr_service_key)

    async def _kac_fee_refresh_due(self, session: AsyncSession, airport_code: str, checked_at: datetime) -> bool:
        # 제공기관 보장이 아닌 내부 호출예산 정책이다. 예전 received 원문은 성공으로 추정하지 않는다.
        previous = await session.scalar(select(RawApiResponse).where(
            RawApiResponse.source == "kac_fee",
            RawApiResponse.endpoint == KAC_FEE_ENDPOINT,
            RawApiResponse.request_params_json["schAirportCode"].as_string() == airport_code,
            RawApiResponse.request_params_json["fee_refresh_contract"].as_string() == KAC_FEE_REFRESH_CONTRACT,
            RawApiResponse.parse_status.in_(["parsed", "failed"]),
            RawApiResponse.received_at > checked_at - timedelta(hours=24),
        ).order_by(RawApiResponse.received_at.desc(), RawApiResponse.id.desc()).limit(1))
        if previous is None:
            return True
        due_at = serialize_utc(previous.received_at) + timedelta(hours=24 if previous.parse_status == "parsed" else 4)
        if checked_at >= due_at:
            return True
        logger.info("KAC fee refresh deferred airport=%s status=%s received_at=%s next_due_at=%s",
                    airport_code, previous.parse_status, serialize_utc(previous.received_at).isoformat(), due_at.isoformat())
        return False

    async def _safe_fetch(
        self,
        session: AsyncSession,
        run: CollectionRun,
        fetcher,
        errors: list[str],
        *,
        kac_fee_airport_code: str | None = None,
    ) -> SourceResponse | None:
        try:
            response = await fetcher()
        except Exception as exc:
            if kac_fee_airport_code is not None:
                # SDK 예외에는 인증 query/응답 본문이 들어갈 수 있다. 차단 표지만 보존한다.
                detail = UPSTREAM_RATE_LIMIT_MARKER if is_upstream_rate_limit_error(str(exc)) else type(exc).__name__
                message = f"kac_fee {kac_fee_airport_code}: {detail}"
            else:
                message = self._redact(str(exc))
            errors.append(message)
            session.add(
                RawApiResponse(
                    collection_run_id=run.id,
                    source="kac_fee" if kac_fee_airport_code is not None else "error",
                    endpoint=KAC_FEE_ENDPOINT if kac_fee_airport_code is not None else "unknown",
                    request_params_json={"schAirportCode": kac_fee_airport_code,
                        "fee_refresh_contract": KAC_FEE_REFRESH_CONTRACT} if kac_fee_airport_code is not None else None,
                    status_code=0,
                    body_text="",
                    received_at=now_utc(),
                    parse_status="failed",
                    parse_error=message,
                )
            )
            await session.flush()
            return None
        # DB 오류를 원천 실패로 삼키지 않는다. fetcher가 넘긴 receipt는 신뢰하지 않는다.
        response.raw_response_id = None
        raw = RawApiResponse(
            collection_run_id=run.id,
            source="kac_fee" if kac_fee_airport_code is not None else response.source,
            endpoint=KAC_FEE_ENDPOINT if kac_fee_airport_code is not None else response.endpoint,
            request_params_json={"schAirportCode": kac_fee_airport_code,
                "fee_refresh_contract": KAC_FEE_REFRESH_CONTRACT} if kac_fee_airport_code is not None else redact_request_params(response.request_params),
            status_code=response.status_code, body_text=response.body_text, received_at=now_utc(),
            parse_status="received", parse_error=None,
        )
        session.add(raw)
        await session.flush()
        response.raw_response_id = raw.id
        try:
            if kac_fee_airport_code is not None and (
                response.source != "kac_fee" or response.endpoint != KAC_FEE_ENDPOINT
                or response.request_params.get("schAirportCode") != kac_fee_airport_code
            ):
                raise ValueError("KAC 요금 응답의 공항·원천이 요청과 다릅니다.")
            validate_source_response_body(response.source, response.body_text)
            if response.source == "incheon_fee":
                response.fee_rules = parse_incheon_fee(response.body_text)
            elif kac_fee_airport_code is not None and response.fee_rules is None:
                response.fee_rules = parse_kac_fee(response.body_text, kac_fee_airport_code)
        except Exception as exc:
            message = self._redact(str(exc))
            raw.parse_status = "failed"
            raw.parse_error = message
            errors.append(message)
            await session.flush()
            return None
        return response

    async def _get_or_create_airport(
        self,
        session: AsyncSession,
        airport_code: str,
        name_ko: str,
        name_en: str | None,
        source: str,
        *,
        airports: dict[str, Airport] | None = None,
    ) -> Airport:
        airport = airports.get(airport_code) if airports is not None else None
        if airport is None:
            airport = await session.scalar(select(Airport).where(Airport.code == airport_code))
        timestamp = now_utc()
        if airport is None:
            airport = Airport(
                code=airport_code,
                name_ko=name_ko,
                name_en=name_en,
                source=source,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(airport)
            await session.flush()
        else:
            airport.name_ko = name_ko
            airport.name_en = name_en
            airport.updated_at = timestamp
        if airports is not None:
            airports[airport_code] = airport
        return airport

    async def _get_or_create_lot(
        self,
        session: AsyncSession,
        airport_id: int,
        source_lot_id: str,
        name: str,
        terminal: str | None,
        category: str | None,
        total_spaces: int,
    ) -> ParkingLot:
        lot = await session.scalar(
            select(ParkingLot).where(ParkingLot.airport_id == airport_id, ParkingLot.source_lot_id == source_lot_id)
        )
        if lot is None:
            # A source can expose a different identifier for the same named lot
            # after an import. Reuse the imported reference row so the live
            # collector does not create a second lot and split its history.
            named_lots = (
                await session.scalars(
                    select(ParkingLot)
                    .where(ParkingLot.airport_id == airport_id, ParkingLot.name == name)
                    .order_by(ParkingLot.id)
                )
            ).all()
            if len(named_lots) > 1:
                raise ValueError(f"ambiguous parking lot identity for airport_id={airport_id}, name={name!r}")
            lot = named_lots[0] if named_lots else None
        timestamp = now_utc()
        if lot is None:
            lot = ParkingLot(
                airport_id=airport_id,
                source_lot_id=source_lot_id,
                name=name,
                terminal=terminal,
                category=category,
                total_spaces_hint=total_spaces,
                is_active=total_spaces > 0,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(lot)
            await session.flush()
        else:
            lot.name = name
            lot.terminal = terminal
            lot.category = category
            lot.total_spaces_hint = total_spaces
            lot.is_active = total_spaces > 0
            lot.updated_at = timestamp
        return lot

    async def _collect_map_parking(self, session, run_id, rate_limit_state, errors):
        from app.models import ReferenceExportState
        from app.services.parking_exports import KIND, parking_scope, parking_sources, store_parking_current, validate_parking_payload
        from app.services.reference_exports import mark_reference_failure
        sources = parking_sources(self.settings)
        previous = {}
        for source in sources:
            head = await session.get(ReferenceExportState, (KIND, parking_scope(self.settings, source)))
            previous[source] = len(head.member_ids) if head else 0
        await session.rollback()  # 모든 원천의 network 대기 전에 pool을 반환한다.
        fetched = []
        failures = []
        failed_responses = []
        # current 승격만 거절된 원천의 마지막 수신 응답. 이력은 플래그 OFF와 같은 parser로 계속 남긴다.
        rejected = {}
        for source in sources:
            if source == "kac_parking" and rate_limit_state.is_blocked:
                failures.append((source, normalize_upstream_rate_limit_error(rate_limit_state.error_message)
                                 or f"kac_parking API error 99: {UPSTREAM_RATE_LIMIT_MARKER}"))
                continue
            fetch = self.client.fetch_kac_parking if source == "kac_parking" else self.client.fetch_incheon_parking
            last_error = None
            for attempt in range(2):
                response = None
                try:
                    response = await fetch()
                    history_rows, rows = validate_parking_payload(self.settings, source, response)
                    if not rows or len(rows) * 4 < previous[source]:
                        raise ValueError("주차장 빈/급감 집합은 재확인이 필요합니다")
                    fetched.append((source, response, history_rows, rows))
                    rejected.pop(source, None)
                    break
                except Exception as exc:
                    last_error = self._redact(str(exc))
                    if response is not None:
                        failed_responses.append((response, last_error))
                        rejected[source] = response
                    if attempt or is_upstream_rate_limit_error(last_error):
                        failures.append((source, last_error))
                        break
        raw_count = snapshot_count = 0
        run = await session.get(CollectionRun, run_id)
        for response, error in failed_responses:
            session.add(RawApiResponse(collection_run_id=run_id, source=response.source,
                        endpoint=response.endpoint, request_params_json=redact_request_params(response.request_params),
                        status_code=response.status_code, body_text=response.body_text,
                        received_at=now_utc(), parse_status="failed", parse_error=error))
        for source, response, history_rows, rows in fetched:
            async def already_fetched(value=response):
                return value
            stored = await self._safe_fetch(session, run, already_fetched, errors)
            if stored is None:
                failures.append((source, "source response validation failed"))
                continue
            raw_count += 1
            lot_ids = {}
            snapshot_count += await self._store_observations(session, run_id, history_rows, lot_ids=lot_ids)
            await store_parking_current(session, self.settings, source=source, run_id=run_id,
                                        observations=rows, proof=response.completion, lot_ids=lot_ids)
        for source, response in rejected.items():
            # 엄격 검증·급감 guard는 current 승격에만 건다. 용량0·미매핑 공항 한 행 때문에 그 원천의 이번 이력을
            # 통째로 잃지 않게 플래그 OFF 경로와 같은 parser·인자로 이력만 저장한다(KAC는 현재값만 주므로
            # 빠진 이력은 되살릴 수 없다). 관대한 parser마저 실패하면 지금처럼 이력을 건너뛴다. head는 그대로다.
            try:
                validate_source_response_body(response.source, response.body_text)
                history_rows = (parse_kac_parking(response.body_text,
                                                  allowed_airport_codes=self.settings.supported_airport_codes)
                                if source == "kac_parking" else parse_incheon_parking(response.body_text))
            except Exception:
                continue
            # 한 원천의 이력 저장 실패가 남은 원천과 실패 기록(mark_reference_failure)을 끊지 않게
            # savepoint로 격리하고 기록만 남긴 뒤 다음 원천으로 넘어간다.
            try:
                async with session.begin_nested():
                    snapshot_count += await self._store_observations(session, run_id, history_rows)
            except Exception as exc:
                logger.warning("parking history-only store failed source=%s run_id=%s: %s",
                               source, run_id, self._redact(str(exc)))
        for source, message in failures:
            errors.append(message)
            await mark_reference_failure(session, kind=KIND, scope=parking_scope(self.settings, source),
                                         run_id=run_id, error="source_failed")
        return raw_count, snapshot_count

    async def _store_observations(
        self,
        session: AsyncSession,
        collection_run_id: int,
        observations: list[ParsedParkingObservation],
        *, lot_ids: dict[tuple[str, str], int] | None = None,
    ) -> int:
        stored = 0
        # 같은 저장 호출 안에서만 재사용한다. rollback/다음 수집으로 ORM 객체를 넘기지 않는다.
        airports: dict[str, Airport] = {}
        for observation in observations:
            airport = await self._get_or_create_airport(
                session,
                observation.airport_code,
                observation.airport_name_ko,
                observation.airport_name_en,
                "incheon" if observation.airport_code == "ICN" else "kac",
                airports=airports,
            )
            lot = await self._get_or_create_lot(
                session,
                airport.id,
                observation.lot_id,
                observation.lot_name,
                observation.terminal,
                observation.category,
                observation.total_spaces,
            )

            if lot_ids is not None:
                lot_ids[(observation.airport_code, observation.lot_id)] = lot.id
            existing = await session.scalar(
                select(ParkingSnapshot).where(
                    ParkingSnapshot.parking_lot_id == lot.id,
                    ParkingSnapshot.observed_at == observation.observed_at,
                    ParkingSnapshot.source == observation.source,
                )
            )
            if existing is not None:
                continue

            available_spaces = max(observation.total_spaces - observation.occupied_spaces, 0)
            snapshot = ParkingSnapshot(
                    collection_run_id=collection_run_id,
                    airport_id=airport.id,
                    parking_lot_id=lot.id,
                    source=observation.source,
                    observed_at=observation.observed_at,
                    collected_at=now_utc(),
                    occupied_spaces=observation.occupied_spaces,
                    total_spaces=observation.total_spaces,
                    available_spaces=available_spaces,
                    congestion_label=observation.congestion_label,
                    congestion_ratio=observation.congestion_ratio,
                    raw_item_json=observation.raw_item,
            )
            # Advisory lock으로 정상 경로의 중복을 막고, 이전 process/수동 실행과의 경합은
            # savepoint에서 unique constraint를 소비해 전체 수집 transaction을 망치지 않는다.
            try:
                async with session.begin_nested():
                    session.add(snapshot)
                    await session.flush()
            except IntegrityError:
                continue
            stored += 1
        await session.flush()
        return stored

    async def _store_fee_rules(
        self, session: AsyncSession, rules: list[ParsedFeeRule], *, errors: list[str] | None = None,
    ) -> int:
        stored = 0
        unmatched: dict[str, int] = {}
        for rule in rules:
            airport = await session.scalar(select(Airport).where(Airport.code == rule.airport_code))
            if airport is None:
                airport = await self._get_or_create_airport(
                    session,
                    rule.airport_code,
                    rule.airport_name,
                    None,
                    "incheon" if rule.airport_code == "ICN" else "kac",
                )

            lot_ids = [None]
            if rule.parking_lot_name:
                # KAC 요금 응답의 공식 명칭과 실시간 현황의 canonical lot를 연결한다.
                # 국제선 통합 요금은 공식 표에서 동일한 지하/빌딩 두 곳에만 적용한다.
                lot_names = {
                    ("GMP", "국제선 주차장"): ("국제선 지하주차장", "국제선 주차빌딩"),
                    ("GMP", "화물청사 주차장"): ("화물청사주차장",),
                    ("GMP", "국내선 제2주차장(일반/예약)"): ("국내선 제2주차장",),
                }.get((rule.airport_code, rule.parking_lot_name), (rule.parking_lot_name,))
                exact_lots = list((await session.execute(select(ParkingLot).where(
                    ParkingLot.airport_id == airport.id, ParkingLot.name.in_(lot_names),
                ))).scalars())
                if rule.airport_code == "ICN":
                    # 현황의 'T1 장기 P1 주차장', 'T2 P1 장기주차타워' 등은
                    # 요금표 명칭의 접두어가 아니다. 확인된 터미널·종류로 연결한다.
                    category = {"단기주차장": "short", "장기주차장": "long", "예약주차장": "reserved"}.get(
                        rule.parking_lot_name[3:]
                    )
                    matching_lots = (
                        await session.execute(
                            select(ParkingLot).where(
                                ParkingLot.airport_id == airport.id,
                                ParkingLot.terminal == rule.parking_lot_name[:2],
                                ParkingLot.category == category,
                            )
                        )
                    ).scalars().all() if category is not None else []
                    if matching_lots:
                        lot_ids = [matching_lot.id for matching_lot in matching_lots]
                elif exact_lots:
                    lot_ids = [lot.id for lot in exact_lots]

                # 이름이 있는 규칙은 해당 주차장에만 적용한다. 매칭 실패를
                # 공항 공통(NULL) 규칙으로 저장하면 다른 주차장 요금이 오염된다.
                if lot_ids == [None]:
                    logger.warning("주차장에 연결하지 못한 요금 규칙을 저장하지 않습니다: airport=%s", rule.airport_code)
                    unmatched[rule.airport_code] = unmatched.get(rule.airport_code, 0) + 1
                    continue

            for lot_id in lot_ids:
                existing = await session.scalar(
                    select(ParkingFeeRule).where(
                        ParkingFeeRule.airport_id == airport.id,
                        ParkingFeeRule.parking_lot_id == lot_id,
                        ParkingFeeRule.vehicle_size == rule.vehicle_size,
                        ParkingFeeRule.day_type == rule.day_type,
                    )
                )

                if existing is None:
                    existing = ParkingFeeRule(
                        airport_id=airport.id,
                        parking_lot_id=lot_id,
                        vehicle_size=rule.vehicle_size,
                        day_type=rule.day_type,
                        free_minutes=rule.free_minutes,
                        basic_minutes=rule.basic_minutes,
                        basic_fee=rule.basic_fee,
                        unit_minutes=rule.unit_minutes,
                        unit_fee=rule.unit_fee,
                        daily_max_fee=rule.daily_max_fee,
                        source_updated_at=rule.source_updated_at,
                        raw_item_json=rule.raw_item,
                    )
                    session.add(existing)
                else:
                    existing.free_minutes = rule.free_minutes
                    existing.basic_minutes = rule.basic_minutes
                    existing.basic_fee = rule.basic_fee
                    existing.unit_minutes = rule.unit_minutes
                    existing.unit_fee = rule.unit_fee
                    existing.daily_max_fee = rule.daily_max_fee
                    existing.source_updated_at = rule.source_updated_at
                    existing.raw_item_json = rule.raw_item
                stored += 1

        await session.flush()
        if errors is not None:
            errors.extend(
                f"{airport_code} 주차요금 규칙 {count}개를 주차장에 연결하지 못해 저장하지 않았습니다."
                for airport_code, count in sorted(unmatched.items())
            )
        return stored
