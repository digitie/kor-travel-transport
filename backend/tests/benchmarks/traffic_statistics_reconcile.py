"""전용 테스트 PostgreSQL에 운영 규모의 합성 소통 이력을 만들고 5분 통계 재대조 비용을 잰다(WLH-06 후속).

예전 창 재구축(같은 범위 DELETE + 원본 INSERT…SELECT)과 차이 기반 재대조(`reconcile_traffic_statistics`)를 같은
범위에서 번갈아 돌려 시간·쓴 행(`pg_stat_xact_user_tables`)·WAL 바이트(`pg_current_wal_insert_lsn` 차)를 비교한다.
일반 pytest 수집 대상이 아니며 외부 제공자·운영 DB에 접근하지 않는다(TEST_DATABASE_URL과
KOR_TRAVEL_TRANSPORT_TEST_DATABASE=1 필수, 실행 전 alembic upgrade head). 소통 이력·통계 표를 비운다.

    uv run python tests/benchmarks/traffic_statistics_reconcile.py --hours 6 --segments 8300 --repeat 5
"""
from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db.session import create_engine_and_session_factory
from app.services.traffic_statistics import five_minute_bucket, reconcile_traffic_statistics

STATS = "highway_traffic_five_minute_statistics"
OLD_DELETE = text(f"DELETE FROM {STATS} WHERE bucket_start >= :start AND bucket_start < :end")
OLD_INSERT = text(f"""
    INSERT INTO {STATS} (bucket_start, route_no_key, direction_key, observations, speed_observations, speed_sum,
                         minimum_speed, maximum_speed, free_flow_speed_observations, free_flow_speed_sum,
                         latest_observed_at)
    SELECT date_bin(INTERVAL '5 minutes', observed_at, TIMESTAMPTZ '2000-01-01 00:00:00+00'),
           COALESCE(route_no, ''), COALESCE(direction, ''), COUNT(*), COUNT(speed), SUM(speed), MIN(speed),
           MAX(speed), COUNT(free_flow_speed), SUM(free_flow_speed), MAX(observed_at)
    FROM highway_traffic_snapshots
    WHERE observed_at >= :start AND observed_at < :end
    GROUP BY 1, 2, 3
""")
FULL_REBUILD = text(OLD_INSERT.text.replace("WHERE observed_at >= :start AND observed_at < :end", ""))
XACT_WRITES = text("SELECT n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_xact_user_tables WHERE relname = :table")


async def seed(engine, factory, start: datetime, hours: int, segments: int) -> None:
    async with factory() as session:
        await session.execute(text(f"TRUNCATE {STATS}, highway_traffic_current, highway_traffic_snapshots "
                                   "RESTART IDENTITY CASCADE"))
        slots = hours * 12
        for first in range(0, slots, 12):
            # 한 시간씩 넣는다(관측 시각은 5분 주기 + 구간마다 다른 지연, 노선 40개·방향 2개, 속도는 정수 km/h).
            await session.execute(text("""
                INSERT INTO highway_traffic_snapshots (source, identity_key, observed_at, collected_at, route_no,
                                                       direction, speed, free_flow_speed, raw_item_json)
                SELECT 'krex_traffic_flow', 'vds:' || seg, observed, observed + INTERVAL '40 seconds',
                       lpad((seg % 40)::text, 4, '0'), CASE WHEN (seg / 40) % 2 = 0 THEN 'S' ELSE 'E' END,
                       CASE WHEN (seg + slot) % 23 = 0 THEN NULL ELSE 30 + (seg * 7 + slot * 3) % 80 END,
                       CASE WHEN seg % 11 = 0 THEN NULL ELSE 100 END, '{}'::jsonb
                FROM generate_series(CAST(:first AS integer), CAST(:last AS integer)) AS slot
                CROSS JOIN generate_series(1, CAST(:segments AS integer)) AS seg
                CROSS JOIN LATERAL (
                    SELECT CAST(:start AS timestamptz) + slot * INTERVAL '5 minutes' + (seg % 240) * INTERVAL '1 second'
                ) AS t(observed)
            """), {"first": first, "last": min(first + 11, slots - 1), "segments": segments, "start": start})
            await session.commit()
        await session.execute(FULL_REBUILD)
        await session.commit()
    await vacuum(engine)


async def vacuum(engine) -> None:
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(text(f"VACUUM (ANALYZE) highway_traffic_snapshots, {STATS}"))


async def measure(factory, label: str, action) -> dict[str, float]:
    async with factory() as session:
        wal_before = await session.scalar(text("SELECT pg_current_wal_insert_lsn()::text"))
        await session.commit()
        started = time.perf_counter()
        await action(session)
        ins, upd, dele = (await session.execute(XACT_WRITES, {"table": STATS})).one()
        await session.commit()
        seconds = time.perf_counter() - started
        wal = await session.scalar(text("SELECT pg_wal_lsn_diff(pg_current_wal_insert_lsn(), CAST(CAST(:lsn AS text) AS pg_lsn))"),
                                   {"lsn": wal_before})
        await session.commit()
    return {"label": label, "seconds": seconds, "inserted": ins, "updated": upd, "deleted": dele, "wal_bytes": float(wal)}


async def main() -> None:
    if os.getenv("KOR_TRAVEL_TRANSPORT_TEST_DATABASE") != "1" or not os.getenv("TEST_DATABASE_URL"):
        raise SystemExit("TEST_DATABASE_URL과 KOR_TRAVEL_TRANSPORT_TEST_DATABASE=1이 필요합니다(운영 DB 금지).")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=int, default=6)
    parser.add_argument("--segments", type=int, default=8300)
    parser.add_argument("--window-hours", type=int, default=2)
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--drift-rows", type=int, default=25)
    args = parser.parse_args()
    engine, factory = create_engine_and_session_factory(os.environ["TEST_DATABASE_URL"])
    start = five_minute_bucket(datetime.now(timezone.utc) - timedelta(hours=args.hours + 1))
    end = start + timedelta(hours=args.hours)
    window_start = end - timedelta(hours=args.window_hours)
    try:
        began = time.perf_counter()
        await seed(engine, factory, start, args.hours, args.segments)
        async with factory() as session:
            raw = await session.scalar(text("SELECT count(*) FROM highway_traffic_snapshots"))
            window_rows = await session.scalar(text(f"SELECT count(*) FROM {STATS} WHERE bucket_start >= :s"),
                                               {"s": window_start})
        print(f"seeded raw={raw} window_statistics_rows={window_rows} in {time.perf_counter() - began:.1f}s")

        async def old(session):
            await session.execute(OLD_DELETE, {"start": window_start, "end": end})
            await session.execute(OLD_INSERT, {"start": window_start, "end": end})

        async def diff(session):
            await session.execute(text("SELECT set_config('max_parallel_workers_per_gather', '0', true)"))
            await reconcile_traffic_statistics(session, window_start, end)

        async def corrupt() -> None:
            # 측정 밖에서 어긋남을 만든다(값이 틀린 행). 재대조는 이 행만 고쳐야 한다.
            async with factory() as session:
                await session.execute(text(
                    f"UPDATE {STATS} SET speed_sum = speed_sum + 1 WHERE id IN (SELECT id FROM {STATS} "
                    "WHERE bucket_start >= :s AND speed_sum IS NOT NULL ORDER BY id LIMIT :n)"),
                    {"s": window_start, "n": args.drift_rows})
                await session.commit()

        results: dict[str, list[dict[str, float]]] = {"old_delete_insert": [], "diff_clean": [], "diff_with_drift": []}
        for _ in range(args.repeat):
            results["old_delete_insert"].append(await measure(factory, "old_delete_insert", old))
            await vacuum(engine)
            results["diff_clean"].append(await measure(factory, "diff_clean", diff))
            await corrupt()
            results["diff_with_drift"].append(await measure(factory, "diff_with_drift", diff))
            await vacuum(engine)
        for label, runs in results.items():
            median = {key: statistics.median(run[key] for run in runs)
                      for key in ("seconds", "inserted", "updated", "deleted", "wal_bytes")}
            print(f"{label:>18}: median {median['seconds'] * 1000:8.1f} ms  rows ins={median['inserted']:.0f} "
                  f"upd={median['updated']:.0f} del={median['deleted']:.0f}  wal={median['wal_bytes'] / 1024:9.1f} KiB "
                  f"(samples {', '.join(f'{run['seconds'] * 1000:.0f}' for run in runs)} ms)")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
