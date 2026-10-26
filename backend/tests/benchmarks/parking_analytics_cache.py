"""명시적인 전용 PostgreSQL에서 합성 관측으로 캐시 비용을 비교한다.

일반 pytest 수집 대상이 아니며 외부 제공자·운영 DB에 접근하지 않는다.
실행 조건과 원본/수정 비교 절차는 관련 성능 보고서에 기록한다.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import resource
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import event, func, insert, select, text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.time_utils import ensure_tz
from app.db.session import create_engine_and_session_factory
from app.models import Airport, AnalyticsCache, ParkingLot, ParkingSnapshot
from app.services import analytics, analytics_cache

NOW = datetime(2026, 10, 27, 0, 5, 30, tzinfo=timezone.utc)


async def seed(factory):
    rng = random.Random(20261027)
    count = 0
    digest = hashlib.sha256()
    async with factory() as session:
        assert await session.scalar(select(func.count()).select_from(ParkingSnapshot)) == 0
        for code in ("GMP", "PUS"):
            airport = Airport(code=code, name_ko=f"합성 {code} 공항", source="synthetic",
                              created_at=NOW, updated_at=NOW)
            session.add(airport)
            await session.flush()
            for index in range(4):
                lot = ParkingLot(airport_id=airport.id, source_lot_id=f"{code}-{index}",
                                 name=f"합성 {code} 주차장 {index}", is_active=index != 2,
                                 created_at=NOW, updated_at=NOW)
                session.add(lot)
                await session.flush()
                if index == 3:
                    continue
                batch = []
                for minute in range(21 * 1440 + 10, -1, -5):
                    # 날짜 사이의 긴 공백과, 마지막 관측이 lot별로 다른 경우를 남긴다.
                    if 7000 <= minute <= 7600 or (index == 2 and minute < 20):
                        continue
                    available = (minute // 5 * 17 + index * 31) % 180
                    observed = NOW - timedelta(minutes=minute)
                    raw = {"provider_unused": rng.randbytes(2048).hex()}
                    row = dict(airport_id=airport.id, parking_lot_id=lot.id, source="live",
                               observed_at=observed, collected_at=observed + timedelta(seconds=7),
                               occupied_spaces=200 - available, total_spaces=200,
                               available_spaces=available, raw_item_json=raw)
                    batch.append(row)
                    digest.update(f"{lot.id}:{minute}:{available}:{raw['provider_unused']}".encode())
                    count += 1
                    if minute % 1440 == 0:
                        batch.append({**row, "source": "migration_http",
                                      "collected_at": NOW - timedelta(seconds=1),
                                      "available_spaces": 0, "occupied_spaces": 200})
                        count += 1
                    if len(batch) >= 300:
                        await session.execute(insert(ParkingSnapshot), batch)
                        batch.clear()
                if batch:
                    await session.execute(insert(ParkingSnapshot), batch)
        await session.commit()
        await session.execute(text("ANALYZE parking_snapshots"))
        await session.commit()
        size = await session.scalar(text("SELECT pg_total_relation_size('parking_snapshots')"))
    return {"synthetic": True, "rows": count, "airports": 2, "lots": 8,
            "observed_lots": 6, "active_lots": 6, "scopes": 8,
            "days": 21, "interval_minutes": 5, "unused_json_chars_per_row": 4096,
            "fixture_digest": digest.hexdigest(), "relation_bytes": size}


async def measure(engine, factory):
    statements = []
    def capture(_c, _cursor, statement, _parameters, _context, _many):
        sql = statement.lower()
        if sql.lstrip().startswith("select") and "parking_snapshots" in sql:
            statements.append(sql)
    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    started = time.perf_counter()
    async with factory() as session:
        # 앞선 캐시를 남기지 않고 동일 원본에서 계산한다. 이 전용 DB만 대상으로 한다.
        await session.execute(text("DELETE FROM analytics_caches"))
        await session.commit()
        count = await analytics_cache.refresh_default_analytics_cache(
            session, Settings(seed_sample_data=False, airport_codes_csv="GMP,PUS"),
        )
        await session.commit()
    elapsed = time.perf_counter() - started
    event.remove(engine.sync_engine, "before_cursor_execute", capture)
    async with factory() as session:
        rows = (await session.scalars(select(AnalyticsCache).order_by(
            AnalyticsCache.scope_key, AnalyticsCache.metric))).all()
        payload = [{"scope": row.scope_key, "metric": row.metric,
                    "days": row.days, "interval": row.interval_minutes,
                    "future": row.future_hours, "limit": row.limit,
                    "generated_at": ensure_tz(row.generated_at, "UTC").isoformat(),
                    "source_observed_at": (ensure_tz(row.source_observed_at, "UTC").isoformat()
                                           if row.source_observed_at else None),
                    "payload": row.payload_json} for row in rows]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    data = [sql for sql in statements if "parking_snapshots.available_spaces" in sql]
    return {"synthetic": True, "elapsed_seconds": elapsed, "cache_rows": count,
            "snapshot_selects": len(statements), "raw_value_selects": len(data),
            "raw_json_selects": sum("raw_item_json" in sql for sql in statements),
            "raw_value_sql": sorted(set(data)), "payload_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "payload_bytes": len(canonical.encode()), "payload": payload,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "analytics_cache_source_sha256": hashlib.sha256(
                Path(analytics_cache.__file__).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()}


def benchmark_database_url():
    if os.environ.get("KOR_TRAVEL_TRANSPORT_TEST_DATABASE") != "1":
        raise RuntimeError("명시적인 격리 테스트 표지가 필요합니다.")
    url = os.environ["TEST_DATABASE_URL"]
    parsed = make_url(url)
    if (
        not parsed.drivername.startswith("postgresql")
        or parsed.database != "parking_analytics_benchmark_test"
        or parsed.host not in {"127.0.0.1", "localhost"}
        or parsed.query
    ):
        raise RuntimeError("전용 PostgreSQL 벤치마크 DB만 허용합니다.")
    return url


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["seed", "measure"])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    engine, factory = create_engine_and_session_factory(benchmark_database_url())
    original_cache_clock = analytics_cache.now_utc
    original_analytics_clock = analytics.now_utc
    try:
        analytics_cache.now_utc = lambda: NOW
        analytics.now_utc = lambda: NOW
        result = await seed(factory) if args.phase == "seed" else await measure(engine, factory)
        path = Path(args.out)
        with path.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
        print(json.dumps({key: value for key, value in result.items()
                          if key not in {"payload", "raw_value_sql"}}, ensure_ascii=False))
    finally:
        analytics_cache.now_utc = original_cache_clock
        analytics.now_utc = original_analytics_clock
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
