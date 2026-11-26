"""전용 테스트 PostgreSQL에 운영 규모의 일별 유가 통계를 만들고 통계 페이지·장기 이력 읽기 비용을 잰다.

일반 pytest 수집 대상이 아니며 외부 제공자·운영 DB에 접근하지 않는다(TEST_DATABASE_URL과
KOR_TRAVEL_TRANSPORT_TEST_DATABASE=1 필수, 실행 전 alembic upgrade head).

운영 모양: 오피넷 약 1.15만 곳·시도 17·시군구 230·유종 4, 하루 한 번 이상 공개(실제 ``publish_fuel_statistics``)를
``--days``일 반복한다. ``--publishes-per-day``로 같은 날 재공개(일별 행 delete/insert)를 늘려 운영의 죽은 행도 흉내 낸다.

    uv run python tests/benchmarks/fuel_statistics_page.py --days 30 --repeat 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import insert, text

from app.db.session import create_engine_and_session_factory
from app.models import FuelLatestPrice, FuelPriceSnapshot, FuelStation, TransportCollectionState
from app.services import fuel_statistics as statistics_module
from app.services.fuel_statistics import OPINET, fuel_statistics_page, publish_fuel_statistics

PRODUCTS = {"B027": 1850, "D047": 1750, "B034": 2100, "K015": 1100}
SIGUNGU_PER_SIDO = (25, 10, 8, 10, 5, 5, 5, 1, 31, 18, 11, 15, 14, 22, 23, 18, 9)  # 합 230


async def seed(session, stations: int, days: int, publishes_per_day: int) -> datetime:
    history = "fuel_statistics_history, " if await session.scalar(text("SELECT to_regclass('fuel_statistics_history')")) else ""
    await session.execute(text("TRUNCATE fuel_region_summaries, fuel_statistics_states, fuel_statistics_points, "
                               f"fuel_statistics_daily, {history}fuel_latest_prices, fuel_price_snapshots, "
                               "fuel_stations, transport_collection_states RESTART IDENTITY CASCADE"))
    rng = random.Random(20261126)
    regions = [(sido, sigungu) for sido, count in enumerate(SIGUNGU_PER_SIDO) for sigungu in range(count)]
    start = datetime(2026, 10, 28, 3, tzinfo=timezone.utc) - timedelta(days=max(0, days - 30))
    station_rows, snapshot_rows = [], []
    for index in range(1, stations + 1):
        sido, sigungu = regions[index % len(regions)]
        station_rows.append({"id": index, "source": OPINET, "identity_key": str(index), "name": f"테스트 주유소 {index}",
            "address": f"테스트특별자치도{sido} 테스트시군구{sigungu} 테스트로 {index}번길 {index % 97}", "query_level": "sigungu",
            "source_kinds": [], "sido_value": f"시도{sido:02d}", "sido_name": f"테스트특별자치도{sido}",
            "sigungu_value": f"테스트시군구{sido:02d}{sigungu:03d}", "sigungu_name": f"테스트시군구{sigungu}",
            "longitude": 126 + rng.random() * 3.5, "latitude": 34 + rng.random() * 4,
            "first_seen_at": start, "last_seen_at": start})
        for product, base in PRODUCTS.items():
            if product in {"B034", "K015"} and rng.random() < .6:
                continue
            snapshot_rows.append({"fuel_station_id": index, "source": OPINET, "product_code": product,
                                  "price": round(base + rng.gauss(0, 60)), "observed_at": start, "collected_at": start})
    for offset in range(0, len(station_rows), 1000):
        await session.execute(insert(FuelStation), station_rows[offset:offset + 1000])
    for offset in range(0, len(snapshot_rows), 2000):
        await session.execute(insert(FuelPriceSnapshot), snapshot_rows[offset:offset + 2000])
    await session.execute(text("INSERT INTO fuel_latest_prices (fuel_station_id, product_code, snapshot_id, price, observed_at, collected_at) "
                               "SELECT fuel_station_id, product_code, id, price, observed_at, collected_at FROM fuel_price_snapshots"))
    session.add(TransportCollectionState(source=OPINET, last_success_at=start, updated_at=start))
    await session.commit()
    started = time.perf_counter()
    stamp = start
    for day in range(days):
        for publish in range(publishes_per_day):
            stamp = start + timedelta(days=day, hours=publish)
            await session.execute(text("UPDATE fuel_latest_prices SET collected_at=:stamp, price=price + (random() * 4 - 2)::int"),
                                  {"stamp": stamp})
            await session.execute(text("UPDATE transport_collection_states SET last_success_at=:stamp WHERE source=:source"),
                                  {"stamp": stamp, "source": OPINET})
            await publish_fuel_statistics(session, OPINET, stamp)
            # 운영처럼 이전 세대 point는 정리한다(일별·지역 요약은 영구 보존).
            await session.execute(text("DELETE FROM fuel_statistics_points WHERE generated_at < :stamp"), {"stamp": stamp})
            await session.commit()
    print(f"seed: stations={stations} prices={len(snapshot_rows)} days={days} publishes={days * publishes_per_day} "
          f"elapsed={time.perf_counter() - started:.1f}s")
    await session.execute(text("ANALYZE"))
    await session.commit()
    sizes = (await session.execute(text(
        "SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_stat_user_tables "
        "WHERE relname IN ('fuel_statistics_daily', 'fuel_statistics_history', 'fuel_region_summaries') ORDER BY relname"))).all()
    for name, rows, size in sizes:
        print(f"table {name}: rows={rows} size={size}")
    return stamp


async def timed(label: str, repeat: int, call) -> None:
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        await call()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    print(f"{label}: median={statistics.median(samples):.1f}ms p95={samples[max(0, int(len(samples) * .95) - 1)]:.1f}ms "
          f"max={samples[-1]:.1f}ms")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", type=int, default=11500)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--publishes-per-day", type=int, default=1)
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--skip-seed", action="store_true")
    parser.add_argument("--hold-snapshot", action="store_true",
                        help="seed 전부터 측정 끝까지 오래된 snapshot을 쥐어 죽은 행 정리·index kill bit를 막는다(운영의 긴 transaction 모양)")
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql") or os.environ.get("KOR_TRAVEL_TRANSPORT_TEST_DATABASE") != "1":
        raise SystemExit("전용 TEST_DATABASE_URL(PostgreSQL)과 KOR_TRAVEL_TRANSPORT_TEST_DATABASE=1이 필요합니다.")
    engine, factory = create_engine_and_session_factory(url)
    holder = None
    try:
        if args.hold_snapshot:
            holder = await engine.connect()
            await holder.execute(text("BEGIN ISOLATION LEVEL REPEATABLE READ"))
            await holder.execute(text("SELECT count(*) FROM alembic_version"))
        if not args.skip_seed:
            async with factory() as session:
                await seed(session, args.stations, args.days, args.publishes_per_day)
        async with factory() as session:
            page = await fuel_statistics_page(session, "sigungu", "B027")
            body = json.dumps(page, default=str, ensure_ascii=False)
            print(f"sigungu B027: items={len(page['items'])} history={len(page['history'])} bytes={len(body)}")
            key = page["history_scope_key"]
        for scope, product in (("nationwide", "ALL"), ("sido", "ALL"), ("sigungu", "B027"), ("sigungu", "ALL"),
                               ("sigungu", "ZZZZ")):
            async def call(scope=scope, product=product):
                async with factory() as session:
                    await fuel_statistics_page(session, scope, product)
            await timed(f"page {scope} {product}", args.repeat, call)
        history = getattr(statistics_module, "fuel_statistics_history", None)
        for bucket, product in () if history is None else (("day", "B027"), ("auto", "ALL"), ("week", "ALL"), ("month", "ALL")):
            async def call(bucket=bucket, product=product):
                async with factory() as session:
                    await history(session, "sigungu", key, product, None, None, bucket)
            await timed(f"history sigungu {product} bucket={bucket}", args.repeat, call)
    finally:
        if holder is not None:
            await holder.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
