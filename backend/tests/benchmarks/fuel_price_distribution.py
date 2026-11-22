"""전용 테스트 PostgreSQL에 운영 규모의 합성 오피넷 세대를 만들고 가격 분포 읽기 비용을 잰다.

일반 pytest 수집 대상이 아니며 외부 제공자·운영 DB에 접근하지 않는다(TEST_DATABASE_URL과
KOR_TRAVEL_TRANSPORT_TEST_DATABASE=1 필수, 실행 전 alembic upgrade head).

    uv run python tests/benchmarks/fuel_price_distribution.py --stations 11500 --repeat 30
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import time
from datetime import datetime, timezone

from sqlalchemy import insert, text

from app.db.session import create_engine_and_session_factory
from app.models import FuelLatestPrice, FuelPriceSnapshot, FuelStation, TransportCollectionState
from app.services import fuel_center_sigungu as center_module
from app.services import fuel_price_distribution as distribution_module
from app.services.fuel_center_sigungu import center_sigungu
from app.services.fuel_price_distribution import price_distribution, viewport_sigungu
from app.services.fuel_statistics import OPINET, publish_fuel_statistics

PRODUCTS = {"B027": 1850, "D047": 1750, "B034": 2100, "K015": 1100}


async def seed(session, stations: int, stamp: datetime) -> None:
    await session.execute(text("TRUNCATE fuel_region_summaries, fuel_statistics_states, fuel_statistics_points, "
                               "fuel_statistics_daily, fuel_latest_prices, fuel_price_snapshots, fuel_stations, "
                               "transport_collection_states RESTART IDENTITY CASCADE"))
    rng = random.Random(20261122)
    station_rows, snapshot_rows = [], []
    for index in range(1, stations + 1):
        sido = index % 17
        sigungu = (index // 17) % 15  # 시도당 15곳, 시군구당 약 45곳(운영 평균과 비슷)
        station_rows.append({"id": index, "source": OPINET, "identity_key": str(index), "name": f"주유소{index}",
            "address": f"시도{sido} 시군구{sigungu}", "query_level": "sigungu", "source_kinds": [],
            "sido_value": f"{sido:02d}", "sido_name": f"시도{sido}", "sigungu_value": f"{sido:02d}{sigungu:03d}",
            "sigungu_name": f"시군구{sigungu}", "longitude": 126 + rng.random() * 3.5, "latitude": 34 + rng.random() * 4,
            "first_seen_at": stamp, "last_seen_at": stamp})
        for product, base in PRODUCTS.items():
            if product in {"B034", "K015"} and rng.random() < .6:
                continue
            snapshot_rows.append({"fuel_station_id": index, "source": OPINET, "product_code": product,
                                  "price": round(base + rng.gauss(0, 60)), "observed_at": stamp, "collected_at": stamp})
    for offset in range(0, len(station_rows), 1000):
        await session.execute(insert(FuelStation), station_rows[offset:offset + 1000])
    for offset in range(0, len(snapshot_rows), 2000):
        await session.execute(insert(FuelPriceSnapshot), snapshot_rows[offset:offset + 2000])
    await session.execute(text("INSERT INTO fuel_latest_prices (fuel_station_id, product_code, snapshot_id, price, observed_at, collected_at) "
                               "SELECT fuel_station_id, product_code, id, price, observed_at, collected_at FROM fuel_price_snapshots"))
    session.add(TransportCollectionState(source=OPINET, last_success_at=stamp, updated_at=stamp))
    await session.flush()
    started = time.perf_counter()
    await publish_fuel_statistics(session, OPINET, stamp)
    await session.commit()
    print(f"seed: stations={stations} prices={len(snapshot_rows)} publish={time.perf_counter() - started:.2f}s")
    await session.execute(text("ANALYZE"))
    await session.commit()


async def timed(label: str, repeat: int, call) -> None:
    samples = []
    for _ in range(repeat):
        started = time.perf_counter()
        await call()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    print(f"{label}: median={statistics.median(samples):.1f}ms p95={samples[int(len(samples) * .95) - 1]:.1f}ms max={samples[-1]:.1f}ms")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stations", type=int, default=11500)
    parser.add_argument("--repeat", type=int, default=30)
    args = parser.parse_args()
    url = os.environ["TEST_DATABASE_URL"]
    if os.environ.get("KOR_TRAVEL_TRANSPORT_TEST_DATABASE") != "1" or not url.startswith("postgresql"):
        raise SystemExit("전용 테스트 PostgreSQL만 사용합니다.")
    engine, factory = create_engine_and_session_factory(url)
    stamp = datetime.now(timezone.utc).replace(microsecond=0)
    async with factory() as session:
        await seed(session, args.stations, stamp)
    async with factory() as session:
        await timed("region B027", args.repeat, lambda: price_distribution(
            session, product_code="B027", sido_value="05", sigungu_value="05010", station_id=None))
        await timed("station B027", args.repeat, lambda: price_distribution(
            session, product_code="B027", sido_value=None, sigungu_value=None, station_id=4255))
        # 10초 결과 캐시를 매번 비워 실제 SQL 비용을 잰다.
        async def uncached(bounds, products):
            distribution_module._sigungu_cache.clear()
            return await viewport_sigungu(session, bounds, [], products, None)
        await timed("viewport national", args.repeat, lambda: uncached((124.0, 33.0, 132.0, 39.0), []))
        await timed("viewport city", args.repeat, lambda: uncached((126.9, 37.4, 127.1, 37.6), ["B027"]))
        await timed("viewport national (cached)", args.repeat, lambda: viewport_sigungu(
            session, (124.0, 33.0, 132.0, 39.0), [], [], None))
        # 지도 중심 시군구(가까운 주유소 근사). 매 호출 다른 중심·캐시 비움으로 실제 SQL 비용을 잰다.
        rng = random.Random(7)

        async def center(longitude, latitude):
            center_module._cache.clear()
            return await center_sigungu(session, longitude, latitude)
        await timed("center land (random)", args.repeat, lambda: center(126.2 + rng.random() * 3.1, 34.2 + rng.random() * 3.6))
        await timed("center sea (3 boxes, null)", args.repeat, lambda: center(124.5, 33.0))
        await timed("center cached", args.repeat, lambda: center_sigungu(session, 127.0, 36.0))
        plan = (await session.execute(text(
            "EXPLAIN (ANALYZE, BUFFERS) SELECT sido_value, sigungu_value FROM fuel_stations WHERE source = 'opinet_browser' "
            "AND sido_value <> '' AND sigungu_value <> '' AND longitude BETWEEN 126.97 AND 127.03 "
            "AND latitude BETWEEN 37.48 AND 37.52 ORDER BY (longitude - 127.0) * (longitude - 127.0) "
            "+ (latitude - 37.5) * (latitude - 37.5) LIMIT 1"))).scalars().all()
        print("center plan:", " | ".join(line.strip() for line in plan))
        body = await price_distribution(session, product_code="B027", sido_value=None, sigungu_value=None, station_id=4255)
        print("station sample:", body["sigungu"]["station_count"], body["station"]["comparisons"][0]["grade"])
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
