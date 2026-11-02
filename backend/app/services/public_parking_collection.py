"""Map의 전국주차장 기능을 이식한 Transport 소유 수집·저장 경로."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import unicodedata
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


class IncompletePublicParkingCollection(RuntimeError):
    """누락·중복·0건을 새 완결 집합으로 게시하지 않는다."""


def _label(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(unicodedata.normalize("NFKC", str(value)).split())
    return result or None


def parking_source_key(item: Any) -> str:
    """기관 코드는 주차장 식별자가 아니다. 공식 번호가 없으면 여러 단서를 함께 쓴다."""
    provider_id = _label(item.prkplce_no)
    if provider_id:
        return "id:" + provider_id
    name = _label(item.prkplce_nm)
    address = _label(item.rdnmadr) or _label(item.lnmadr)
    if not name or not address:
        raise IncompletePublicParkingCollection("주차장 식별 단서가 없습니다.")
    parts = [_label(item.instt_code), name, address]
    return "derived:" + hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()


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
        received, pages, expected, seen = 0, 0, None, set()
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
                        raise IncompletePublicParkingCollection("페이지 순서가 바뀌었습니다.")
                    if getattr(page, "total_count_known", True):
                        if expected is not None and expected != page.total_count:
                            raise IncompletePublicParkingCollection("전체 건수가 수집 중 바뀌었습니다.")
                        expected = page.total_count
                    rows = [parking_row(item, generation) for item in page.items]
                    for row in rows:
                        if row["source_key"] in seen:
                            raise IncompletePublicParkingCollection("중복 주차장 식별자가 있습니다.")
                        seen.add(row["source_key"])
                    for offset in range(0, len(rows), UPSERT_BATCH_SIZE):
                        insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
                        statement = insert(PublicParkingLot).values(rows[offset:offset + UPSERT_BATCH_SIZE])
                        await session.execute(statement.on_conflict_do_update(
                            index_elements=[PublicParkingLot.source, PublicParkingLot.source_key],
                            set_={name: getattr(statement.excluded, name) for name in rows[0]
                                  if name not in {"source", "source_key", "created_at"}},
                        ))
                    received += len(rows)
                    session.add(RawApiResponse(
                        collection_run_id=run_id, source=SOURCE, endpoint="datagokr:parking.iter_pages",
                        request_params_json={"page_no": page.page_no, "num_of_rows": PAGE_SIZE},
                        status_code=200, body_text=json.dumps([dict(item.raw) for item in page.items], ensure_ascii=False),
                        received_at=now_utc(), parse_status="success", parse_error=None,
                    ))
                    await session.flush()
            finally:
                await client.aclose()
            if not received or (expected is not None and received != expected) or (pages >= MAX_PAGES and expected is None):
                raise IncompletePublicParkingCollection("전체 주차장 집합을 확인하지 못했습니다.")
            active = await session.scalar(select(CollectionRun).where(CollectionRun.id == run_id)
                                          .with_for_update().execution_options(populate_existing=True))
            if active.status != "running":
                raise IncompletePublicParkingCollection("수집 실행이 이미 종료됐습니다.")
            active.status, active.finished_at = "success", now_utc()
            state.last_success_at, state.last_error, state.updated_at = generation, None, now_utc()
            await session.commit()
            return {"status": "success", "run_id": run_id, "received": received, "stored": received, "pages": pages}
        except (Exception, asyncio.CancelledError) as error:
            error_type, cancelled = type(error).__name__, isinstance(error, asyncio.CancelledError)
            await session.rollback()
            stored = await session.get(CollectionRun, run_id, populate_existing=True)
            if stored is not None and stored.status == "running":
                stored.status, stored.finished_at, stored.error_message = "cancelled" if cancelled else "failed", now_utc(), error_type
            state = await get_or_create_state(session, SOURCE)
            state.last_started_at, state.last_error, state.updated_at = generation, error_type, now_utc()
            await session.commit()
            if cancelled:
                raise
            return {"status": "failed", "run_id": run_id, "error_type": error_type, "received": received, "pages": pages}
