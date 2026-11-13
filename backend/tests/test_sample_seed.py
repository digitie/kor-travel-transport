from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, event, select

from app.core.time_utils import ensure_tz
from app.db.session import create_engine_and_session_factory, init_database
from app.models import Airport, CollectionRun, ParkingFeeRule, ParkingLot, ParkingSnapshot
from app.services import sample_data


async def sample_fingerprint(session):
    """ID·관측·원문·요금·기준정보 전체를 UTC 정규화해 이전 구현 원장과 대조한다."""
    payload = {}
    for model in (Airport, ParkingLot, ParkingSnapshot, ParkingFeeRule):
        rows = (await session.execute(select(model.__table__).order_by(model.id))).mappings().all()
        payload[model.__tablename__] = [
            {key: ensure_tz(value, "UTC").astimezone(timezone.utc).isoformat()
             if isinstance(value, datetime) else value for key, value in row.items()}
            for row in rows
        ]
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest(), {key: len(value) for key, value in payload.items()}


@pytest.mark.parametrize(("clock", "expected"), [
    ("2026-11-13T03:20:00+00:00", "333a87bc1abed519fac49af2327b455a07c6a0902f94b0ec7816a3f4245e03f0"),
    ("2026-11-13T15:00:00+00:00", "8c1661ff4dffefe451539d5e8f1100c757aced360e8109b11e504f8e34d666cf"),
])
async def test_sample_seed_matches_original_full_rows_and_is_idempotent(test_settings, monkeypatch, clock, expected):
    # 이전842883da 구현에서 고정 시각으로 발급한 전체4테이블 원장이다. 행/필드 생략0.
    fixed = datetime.fromisoformat(clock)
    monkeypatch.setattr(sample_data, "now_utc", lambda: fixed)
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    try:
        await init_database(engine)
        reads = []
        def count_snapshot_reads(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT") and "FROM parking_snapshots" in statement:
                reads.append(1)
        event.listen(engine.sync_engine, "before_cursor_execute", count_snapshot_reads)
        async with factory() as session:
            await sample_data.seed_sample_database(session)
            assert len(reads) == 18
            fingerprint, rows = await sample_fingerprint(session)
            assert fingerprint == expected
            assert rows["airports"] == 4 and rows["parking_lots"] == 18 and rows["parking_fee_rules"] == 72
            reads.clear()
            await sample_data.seed_sample_database(session)
            assert len(reads) == 18
            assert await sample_fingerprint(session) == (fingerprint, rows)
    finally:
        await engine.dispose()


async def test_sample_seed_preserves_existing_sources_runs_and_future_delete_boundary(test_settings, monkeypatch):
    fixed = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)  # KST 자정: recent는 전날이다.
    monkeypatch.setattr(sample_data, "now_utc", lambda: fixed)
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    try:
        await init_database(engine)
        async with factory() as session:
            await sample_data.seed_sample_database(session)
            lot = await session.scalar(select(ParkingLot).where(ParkingLot.source_lot_id == "gmp-domestic-1"))
            run = CollectionRun(started_at=fixed, status="success", trigger="preserved-live")
            session.add(run)
            await session.flush()
            # 기존 동일 source/time의 값·ID·실제run을 수정하지 않고 보존해야 한다.
            existing = await session.scalar(select(ParkingSnapshot).where(
                ParkingSnapshot.parking_lot_id == lot.id, ParkingSnapshot.observed_at == fixed,
                ParkingSnapshot.source == "kac_parking"))
            existing.available_spaces = 0
            existing.collection_run_id = run.id
            existing.raw_item_json = {"live": "보존"}
            existing_id = existing.id
            # 하루 이전 등 같은 시각이어도 다른 source는 새 sample 생성을 막지 않는다.
            missing_at = fixed - timedelta(hours=2)
            await session.execute(delete(ParkingSnapshot).where(
                ParkingSnapshot.parking_lot_id == lot.id, ParkingSnapshot.observed_at == missing_at,
                ParkingSnapshot.source == "kac_parking"))
            def extra(at, source, run_id):
                return ParkingSnapshot(airport_id=lot.airport_id, parking_lot_id=lot.id,
                    source=source, observed_at=at, collected_at=at, total_spaces=10,
                    available_spaces=3, occupied_spaces=7, collection_run_id=run_id,
                    raw_item_json={"preserved": source})
            peer = extra(missing_at, "another-provider", run.id)
            live_future = extra(fixed + timedelta(minutes=30), "live-future", run.id)
            old_future = extra(fixed + timedelta(hours=1), "old-sample-future", None)
            outside = extra(fixed - timedelta(days=20), "kac_parking", None)
            session.add_all([peer, live_future, old_future, outside])
            await session.commit()
            kept_ids = [peer.id, live_future.id, outside.id]
            removed_id = old_future.id
            await sample_data.seed_sample_database(session)
            await session.refresh(existing)
            assert (existing.id, existing.available_spaces, existing.collection_run_id, existing.raw_item_json) == (
                existing_id, 0, run.id, {"live": "보존"})
            for kept_id in kept_ids:
                assert await session.get(ParkingSnapshot, kept_id, populate_existing=True) is not None
            assert await session.get(ParkingSnapshot, removed_id, populate_existing=True) is None
            restored = (await session.scalars(select(ParkingSnapshot).where(
                ParkingSnapshot.parking_lot_id == lot.id, ParkingSnapshot.observed_at == missing_at))).all()
            assert {row.source for row in restored} == {"kac_parking", "another-provider"}
            assert sum(row.source == "kac_parking" for row in restored) == 1
    finally:
        await engine.dispose()
