"""Map의 전국주차장 기능을 이식한 Transport 소유 수집·저장 경로."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import unicodedata
from enum import StrEnum
from typing import Any, Callable

from datagokr import DataGoKrClient
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.time_utils import now_utc
from app.models import CollectionRun, PublicParkingLot, RawApiResponse
from app.services.transport_collection import get_or_create_state

SOURCE = "datagokr_parking_lots"
PAGE_SIZE = 1000
MAX_PAGES = 1000
UPSERT_BATCH_SIZE = 200  # 32열×200: asyncpg bind 상한보다 작게 유지한다.
CONFLICT_NOTICE = "원천의 중복 자료가 서로 달라 일부 항목을 확인할 수 없습니다."


class PublicParkingFailureCode(StrEnum):
    MISSING_IDENTITY = "missing_identity"
    PAGE_SEQUENCE = "page_sequence"
    TOTAL_COUNT_CHANGED = "total_count_changed"
    DUPLICATE_IDENTITY = "duplicate_identity"
    EMPTY_CATALOG = "empty_catalog"
    TOTAL_COUNT_MISMATCH = "total_count_mismatch"
    UNKNOWN_TOTAL_PAGE_LIMIT = "unknown_total_page_limit"
    RUN_ALREADY_FINISHED = "run_already_finished"


class IncompletePublicParkingCollection(RuntimeError):
    """누락·중복·0건을 새 완결 집합으로 게시하지 않는다."""

    def __init__(self, code: PublicParkingFailureCode):
        self.code = PublicParkingFailureCode(code)
        super().__init__(self.code.value)


def _label(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(unicodedata.normalize("NFKC", str(value)).split())
    return result or None


def parking_source_key(item: Any) -> str:
    """공식 번호도 전역 고유하지 않으므로 기관·시설명·주소와 함께 결박한다."""
    provider_id = _label(item.prkplce_no)
    name = _label(item.prkplce_nm)
    address = _label(item.rdnmadr) or _label(item.lnmadr)
    if not name or not address:
        raise IncompletePublicParkingCollection(PublicParkingFailureCode.MISSING_IDENTITY)
    parts = [_label(item.instt_code), name, address]
    if provider_id:
        parts.insert(0, provider_id)
    prefix = "id:" if provider_id else "derived:"
    return prefix + hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


def parking_row(item: Any, collected_at: Any) -> dict[str, Any]:
    def nonnegative(value: Any) -> Any:
        return value if value is not None and math.isfinite(value) and value >= 0 else None

    latitude, longitude = item.latitude, item.longitude
    if not (latitude is not None and longitude is not None and math.isfinite(latitude)
            and math.isfinite(longitude) and 32 <= latitude <= 39.5 and 124 <= longitude <= 132):
        latitude = longitude = None
    return {
        "source": SOURCE, "source_key": parking_source_key(item),
        "provider_id": _label(item.prkplce_no), "name": _label(item.prkplce_nm) or "이름 미제공",
        "category": _label(item.prkplce_se), "parking_type": _label(item.prkplce_type),
        "road_address": _label(item.rdnmadr), "land_address": _label(item.lnmadr),
        "latitude": latitude, "longitude": longitude, "capacity": nonnegative(item.prkcmprt),
        "fee_info": _label(item.parkingchrge_info), "basic_minutes": nonnegative(item.basic_time),
        "basic_fee": nonnegative(item.basic_charge), "additional_minutes": nonnegative(item.add_unit_time),
        "additional_fee": nonnegative(item.add_unit_charge), "daily_minutes": nonnegative(item.day_cmmtkt_adj_time),
        "daily_fee": nonnegative(item.day_cmmtkt), "monthly_fee": nonnegative(item.month_cmmtkt),
        "operating_days": _label(item.oper_day), "opening_hours_json": {
            "weekday_open": _label(item.weekday_oper_open_hhmm), "weekday_close": _label(item.weekday_oper_colse_hhmm),
            "saturday_open": _label(item.sat_oper_oper_open_hhmm), "saturday_close": _label(item.sat_oper_close_hhmm),
            "holiday_open": _label(item.holiday_oper_open_hhmm), "holiday_close": _label(item.holiday_close_open_hhmm),
        },
        "payment_methods": _label(item.metpay), "notes": _label(item.spcmnt),
        "phone": _label(item.phone_number), "institution_name": _label(item.institution_nm) or _label(item.instt_nm),
        "institution_code": _label(item.instt_code), "disabled_parking": _label(item.pwdbs_ppk_zone_yn),
        "reference_date": item.reference_date, "raw_json": dict(item.raw),
        "created_at": collected_at, "last_seen_at": collected_at,
    }


def _raw_digest(raw: dict[str, Any]) -> bytes:
    return hashlib.sha256(json.dumps(
        raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode()).digest()


def _merge_common_fields(current: dict[str, Any], incoming: dict[str, Any], conflicts: set[str]) -> None:
    # None도 알려지지 않은 값이다. 값이 한번 달라지면 이후 variant가 들어와도
    # 복구하지 않아 순서·페이지 경계와 무관한 전체 공통값만 남긴다.
    for name, value in incoming.items():
        if name in {"source", "source_key", "raw_json", "created_at", "last_seen_at"}:
            continue
        if name == "opening_hours_json":
            for period, hour in value.items():
                if current[name][period] != hour:
                    current[name][period] = None
                    conflicts.add(f"{name}.{period}")
        elif current[name] != value:
            current[name] = None
            conflicts.add(name)
    if conflicts.intersection({"latitude", "longitude"}):
        current["latitude"] = current["longitude"] = None
        conflicts.update({"latitude", "longitude"})


class _ParkingCatalog:
    """수집과 원문 offline 검산에서 같은 공통값 투영을 사용한다."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.seen_raw: dict[str, set[bytes]] = {}
        self.variants: dict[str, list[dict[str, Any]]] = {}
        self.conflicting_fields: dict[str, set[str]] = {}

    def add(self, item: Any, generation: Any) -> None:
        row = parking_row(item, generation)
        identity, raw = row["source_key"], row["raw_json"]
        digest = _raw_digest(raw)
        if identity not in self.rows:
            self.rows[identity], self.seen_raw[identity] = row, {digest}
            return
        if digest in self.seen_raw[identity]:
            raise IncompletePublicParkingCollection(PublicParkingFailureCode.DUPLICATE_IDENTITY)
        self.seen_raw[identity].add(digest)
        self.variants.setdefault(identity, [self.rows[identity]["raw_json"]]).append(raw)
        _merge_common_fields(self.rows[identity], row, self.conflicting_fields.setdefault(identity, set()))

    def materialize(self) -> list[dict[str, Any]]:
        for identity, records in self.variants.items():
            self.rows[identity]["notes"] = CONFLICT_NOTICE
            self.rows[identity]["raw_json"] = {
                "source_records": sorted(records, key=_raw_digest),
                "conflicting_fields": sorted(self.conflicting_fields[identity]),
            }
        return list(self.rows.values())


class PublicParkingCollectionService:
    def __init__(self, settings: Settings, *, client_factory: Callable[..., Any] = DataGoKrClient):
        self.settings, self.client_factory = settings, client_factory

    async def collect(self, session: AsyncSession, *, trigger: str = "dagster_public_parking") -> dict[str, Any]:
        key = self.settings.public_parking_service_key or self.settings.data_go_kr_service_key
        if not self.settings.public_parking_collection_enabled or not key:
            return {"status": "skipped", "reason": "public parking collection disabled or key unavailable"}
        run = CollectionRun(started_at=now_utc(), status="running", trigger=trigger)
        session.add(run)
        await session.commit()
        run_id, generation = run.id, now_utc()
        received, pages, expected = 0, 0, None
        catalog = _ParkingCatalog()
        try:
            if session.bind.dialect.name == "postgresql":
                locked = await session.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"),
                                              {"name": "kor_travel_transport:public_parking"})
                if not locked:
                    run.status, run.finished_at = "skipped", now_utc()
                    await session.commit()
                    return {"status": "skipped", "reason": "public parking collector busy", "run_id": run_id}
            state = await get_or_create_state(session, SOURCE)
            state.last_started_at = generation
            client = self.client_factory(api_key=key, timeout=self.settings.api_timeout_seconds, max_rps=1.0)
            try:
                async for page in client.parking.iter_pages(num_of_rows=PAGE_SIZE, max_pages=MAX_PAGES):
                    pages += 1
                    if page.page_no != pages:
                        raise IncompletePublicParkingCollection(PublicParkingFailureCode.PAGE_SEQUENCE)
                    if getattr(page, "total_count_known", True):
                        if expected is not None and expected != page.total_count:
                            raise IncompletePublicParkingCollection(PublicParkingFailureCode.TOTAL_COUNT_CHANGED)
                        expected = page.total_count
                    for item in page.items:
                        catalog.add(item, generation)
                    received += len(page.items)
                    session.add(RawApiResponse(
                        collection_run_id=run_id, source=SOURCE, endpoint="datagokr:parking.iter_pages",
                        request_params_json={"page_no": page.page_no, "num_of_rows": PAGE_SIZE},
                        status_code=200, body_text=json.dumps([item.raw for item in page.items], ensure_ascii=False),
                        received_at=now_utc(), parse_status="success", parse_error=None,
                    ))
                    await session.flush()
            finally:
                await client.aclose()
            if not received:
                raise IncompletePublicParkingCollection(PublicParkingFailureCode.EMPTY_CATALOG)
            if expected is not None and received != expected:
                raise IncompletePublicParkingCollection(PublicParkingFailureCode.TOTAL_COUNT_MISMATCH)
            if pages >= MAX_PAGES and expected is None:
                raise IncompletePublicParkingCollection(PublicParkingFailureCode.UNKNOWN_TOTAL_PAGE_LIMIT)
            # 전 페이지의 완결 건수를 검산한 뒤 각 복합키를 한 번만 저장한다.
            rows = catalog.materialize()
            for offset in range(0, len(rows), UPSERT_BATCH_SIZE):
                insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
                statement = insert(PublicParkingLot).values(rows[offset:offset + UPSERT_BATCH_SIZE])
                await session.execute(statement.on_conflict_do_update(
                    index_elements=[PublicParkingLot.source, PublicParkingLot.source_key],
                    set_={name: getattr(statement.excluded, name) for name in rows[0]
                          if name not in {"source", "source_key", "created_at"}},
                ))
            active = await session.scalar(select(CollectionRun).where(CollectionRun.id == run_id)
                                          .with_for_update().execution_options(populate_existing=True))
            if active.status != "running":
                raise IncompletePublicParkingCollection(PublicParkingFailureCode.RUN_ALREADY_FINISHED)
            active.status, active.finished_at = "success", now_utc()
            state.last_success_at, state.last_error, state.updated_at = generation, None, now_utc()
            await session.commit()
            return {"status": "success", "run_id": run_id, "received": received, "stored": len(rows),
                    "pages": pages, "conflicts": len(catalog.variants)}
        except (Exception, asyncio.CancelledError) as error:
            error_type, cancelled = type(error).__name__, isinstance(error, asyncio.CancelledError)
            error_code = error.code.value if isinstance(error, IncompletePublicParkingCollection) else None
            safe_error = error_code or error_type
            await session.rollback()
            stored = await session.get(CollectionRun, run_id, populate_existing=True)
            if stored is not None and stored.status == "running":
                stored.status, stored.finished_at, stored.error_message = "cancelled" if cancelled else "failed", now_utc(), safe_error
            state = await get_or_create_state(session, SOURCE)
            state.last_started_at, state.last_error, state.updated_at = generation, safe_error, now_utc()
            await session.commit()
            if cancelled:
                raise
            result = {"status": "failed", "run_id": run_id, "error_type": error_type, "received": received, "pages": pages}
            if error_code is not None:
                result["error_code"] = error_code
            return result
