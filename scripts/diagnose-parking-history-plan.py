"""운영 주차 이력의 페이지 키 조회 계획을 읽기 전용으로 확인한다."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_engine_and_session_factory


QUERIES = {
    "all": """
        SELECT DISTINCT observed_at, parking_lot_id
        FROM parking_snapshots
        WHERE observed_at >= now() - interval '30 days'
        ORDER BY observed_at DESC, parking_lot_id DESC
        LIMIT 1001
    """,
    "gmp": """
        SELECT DISTINCT observed_at, parking_lot_id
        FROM parking_snapshots
        WHERE observed_at >= now() - interval '30 days' AND airport_id =
            (SELECT id FROM airports WHERE code = 'GMP')
        ORDER BY observed_at DESC, parking_lot_id DESC
        LIMIT 1001
    """,
    "page_all": """
        WITH history_keys AS (
            SELECT DISTINCT observed_at, parking_lot_id
            FROM parking_snapshots
            WHERE observed_at >= now() - interval '30 days'
            ORDER BY observed_at DESC, parking_lot_id DESC
            LIMIT 1001
        )
        SELECT k.observed_at, k.parking_lot_id, a.code,
               p.occupied_spaces, p.total_spaces, p.available_spaces
        FROM history_keys k
        JOIN LATERAL (
            SELECT airport_id, occupied_spaces, total_spaces, available_spaces
            FROM parking_snapshots p
            WHERE p.observed_at = k.observed_at AND p.parking_lot_id = k.parking_lot_id
            ORDER BY CASE WHEN left(source, 10) = 'migration_' THEN 1 ELSE 0 END,
                     collected_at DESC, id DESC
            LIMIT 1
        ) p ON true
        JOIN airports a ON a.id = p.airport_id
        ORDER BY k.observed_at DESC, k.parking_lot_id DESC
    """,
}


async def main() -> None:
    engine, _ = create_engine_and_session_factory(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            for name, query in QUERIES.items():
                result = await connection.scalar(text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query
                ))
                plan = result[0] if isinstance(result, list) else json.loads(result)[0]
                def nodes(node: dict) -> list[str]:
                    return [node["Node Type"], *(kind for child in node.get("Plans", []) for kind in nodes(child))]

                print(name, "execution_ms=", plan["Execution Time"],
                      "nodes=", ">".join(nodes(plan["Plan"]))[:300])
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
