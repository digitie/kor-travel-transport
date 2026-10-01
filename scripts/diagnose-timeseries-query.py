"""n150에서 90일·10분 주차 시계열의 단일 스캔 대안을 읽기 전용 계측한다."""

from __future__ import annotations

import asyncio
import argparse
import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.config import get_settings
from app.core.time_utils import align_to_interval
from app.db.session import create_engine_and_session_factory


QUERY = """
WITH scoped AS MATERIALIZED (
    SELECT p.*,
           date_bin(:interval_minutes * interval '1 minute',
                    p.observed_at - interval '1 microsecond',
                    :bucket_start) + :interval_minutes * interval '1 minute' AS bucket_at
    FROM parking_snapshots p
    WHERE p.airport_id = (SELECT id FROM airports WHERE code = 'GMP')
      AND p.observed_at >= :start_at AND p.observed_at < :end_at
), chosen AS MATERIALIZED (
    SELECT DISTINCT ON (p.parking_lot_id, assigned.bucket_at)
           p.parking_lot_id, assigned.bucket_at,
           p.available_spaces, p.occupied_spaces, p.total_spaces
    FROM scoped p
    CROSS JOIN LATERAL (VALUES
        (p.bucket_at),
        (CASE WHEN p.observed_at = p.bucket_at
              THEN p.bucket_at + :interval_minutes * interval '1 minute'
              ELSE NULL END)
    ) assigned(bucket_at)
    WHERE assigned.bucket_at IS NOT NULL
    ORDER BY p.parking_lot_id, assigned.bucket_at, p.observed_at DESC,
             CASE WHEN left(p.source, 10) = 'migration_' THEN 1 ELSE 0 END,
             p.collected_at DESC, p.id DESC
)
SELECT b.bucket_at,
       COALESCE(SUM(c.available_spaces), 0)::integer AS available_spaces,
       COALESCE(SUM(c.occupied_spaces), 0)::integer AS occupied_spaces,
       COALESCE(SUM(c.total_spaces), 0)::integer AS total_spaces,
       COUNT(c.parking_lot_id)::integer AS lot_observations
FROM generate_series(:bucket_start, :bucket_end, :interval_minutes * interval '1 minute') b(bucket_at)
LEFT JOIN chosen c ON c.bucket_at = b.bucket_at
GROUP BY b.bucket_at ORDER BY b.bucket_at
"""

OLD_QUERY = """
SELECT b.bucket_at,
       COALESCE(SUM(s.available_spaces), 0)::integer AS available_spaces,
       COALESCE(SUM(s.occupied_spaces), 0)::integer AS occupied_spaces,
       COALESCE(SUM(s.total_spaces), 0)::integer AS total_spaces,
       COUNT(s.id)::integer AS lot_observations
FROM generate_series(:bucket_start, :bucket_end, :interval_minutes * interval '1 minute') b(bucket_at)
CROSS JOIN parking_lots l
LEFT JOIN LATERAL (
    SELECT p.id, p.available_spaces, p.occupied_spaces, p.total_spaces
    FROM parking_snapshots p
    WHERE p.parking_lot_id = l.id
      AND p.observed_at >= :start_at AND p.observed_at < :end_at
      AND p.observed_at <= b.bucket_at
      AND p.observed_at >= b.bucket_at - :interval_minutes * interval '1 minute'
    ORDER BY p.observed_at DESC,
             CASE WHEN left(p.source, 10) = 'migration_' THEN 1 ELSE 0 END,
             p.collected_at DESC, p.id DESC
    LIMIT 1
) s ON true
WHERE l.airport_id = (SELECT id FROM airports WHERE code = 'GMP')
GROUP BY b.bucket_at ORDER BY b.bucket_at
"""


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=10, choices=range(10, 61))
    args = parser.parse_args()
    tz = ZoneInfo("Asia/Seoul")
    start_at = datetime.combine(date(2026, 7, 4), time.min, tzinfo=tz).astimezone(UTC)
    end_at = datetime.combine(date(2026, 10, 2), time.min, tzinfo=tz).astimezone(UTC)
    anchor_at = end_at - timedelta(minutes=args.interval)
    bucket_count = 90 * 24 * 60 // args.interval
    bucket_end = align_to_interval(anchor_at, args.interval, "Asia/Seoul")
    bucket_start = bucket_end - timedelta(minutes=args.interval * (bucket_count - 1))
    engine, _ = create_engine_and_session_factory(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(text("""
                SELECT count(*) FROM parking_snapshots WHERE airport_id =
                    (SELECT id FROM airports WHERE code='GMP')
                    AND observed_at >= :start_at AND observed_at < :end_at
            """), {"start_at": start_at, "end_at": end_at})
            print("source_rows", count, flush=True)
            raw = await connection.scalar(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + QUERY),
                                          {"start_at": start_at, "end_at": end_at,
                                           "bucket_start": bucket_start, "bucket_end": bucket_end,
                                           "interval_minutes": args.interval})
            plan = raw[0] if isinstance(raw, list) else json.loads(raw)[0]
            print("execution_ms", plan["Execution Time"], "result_rows", plan["Plan"]["Actual Rows"], flush=True)
            params = {"start_at": start_at, "end_at": end_at,
                      "bucket_start": bucket_start, "bucket_end": bucket_end,
                      "interval_minutes": args.interval}
            expected = (await connection.execute(text(OLD_QUERY), params)).all()
            actual = (await connection.execute(text(QUERY), params)).all()
            mismatches = [(old, new) for old, new in zip(expected, actual) if old != new]
            print("old_rows", len(expected), "new_rows", len(actual),
                  "mismatches", len(mismatches), flush=True)
            if mismatches:
                print("first_mismatch", mismatches[0], flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
