"""운영 PostgreSQL의 기존 전체 주차 이력 계약을 읽기 전용으로 계측한다."""

from __future__ import annotations

import asyncio
import gzip
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from pydantic_core import to_json

from app.core.config import get_settings
from app.db.session import create_engine_and_session_factory


QUERY = """
SELECT h.observed_at, h.parking_lot_id, a.code,
       h.occupied_spaces, h.total_spaces, h.available_spaces
FROM (
    SELECT DISTINCT ON (p.observed_at, p.parking_lot_id)
           p.observed_at, p.parking_lot_id, p.airport_id,
           p.occupied_spaces, p.total_spaces, p.available_spaces
    FROM parking_snapshots p
    WHERE p.observed_at >= :cutoff
    ORDER BY p.observed_at, p.parking_lot_id,
             CASE WHEN left(p.source, 10) = 'migration_' THEN 1 ELSE 0 END,
             p.collected_at DESC, p.id DESC
) h
JOIN airports a ON a.id = h.airport_id
ORDER BY h.observed_at, h.parking_lot_id
"""

async def main() -> None:
    engine, _ = create_engine_and_session_factory(get_settings().database_url)
    cutoff = datetime.now(UTC) - timedelta(days=30)
    try:
        for trial in range(1):
            started = time.perf_counter()
            async with engine.connect() as connection:
                async with connection.begin():
                    await connection.execute(text("SET TRANSACTION READ ONLY"))
                    rows = (await connection.execute(text(QUERY), {"cutoff": cutoff})).all()
            fetched = time.perf_counter()
            items = [{
                "airport_code": row.code,
                "parking_lot_id": row.parking_lot_id,
                "observed_at": row.observed_at,
                "occupied_spaces": row.occupied_spaces,
                "total_spaces": row.total_spaces,
                "available_spaces": row.available_spaces,
            } for row in rows]
            encoded = to_json({"items": items, "next_cursor": None})
            finished = time.perf_counter()
            compressed = gzip.compress(encoded, compresslevel=1, mtime=0)
            zipped = time.perf_counter()
            fragments = [to_json(item) for item in items]
            cache_built = time.perf_counter()
            cached_body = b'{"items":[' + b','.join(fragments) + b'],"next_cursor":null}'
            cache_joined = time.perf_counter()
            assert cached_body == encoded
            cached_compressed = gzip.compress(cached_body, compresslevel=1, mtime=0)
            cache_zipped = time.perf_counter()
            print({"trial": trial + 1, "rows": len(rows), "bytes": len(encoded),
                   "db_fetch_s": round(fetched - started, 3),
                   "serialize_s": round(finished - fetched, 3),
                   "total_s": round(finished - started, 3),
                   "gzip_bytes": len(compressed),
                   "gzip_s": round(zipped - finished, 3),
                   "cache_fragment_build_s": round(cache_built - zipped, 3),
                   "cache_join_s": round(cache_joined - cache_built, 3),
                   "cache_gzip_s": round(cache_zipped - cache_joined, 3),
                   "cache_gzip_bytes": len(cached_compressed)}, flush=True)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
