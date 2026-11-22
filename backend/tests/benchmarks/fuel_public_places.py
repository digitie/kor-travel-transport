"""운영 규모·운영 모양의 공개 유가 데이터로 공개 화면 읽기(places zoom 7·가격 분포)를 HTTP 경로 그대로 잰다.

일반 pytest 수집 대상이 아니며 외부 제공자·운영 DB에 접근하지 않는다(TEST_DATABASE_URL과
KOR_TRAVEL_TRANSPORT_TEST_DATABASE=1 필수, 실행 전 alembic upgrade head).

운영(odroid, 2026-11-23 읽기 전용 측정)과 같게 만드는 것:
- 오피넷 주유소 11,905곳(시도 17·시군구 약 250, 셀프 약 53%, 상표 분포, 일부 행의 시도 이름은 정식 이름),
  유종 행 약 5만 9천, 공개 세대당 가격 point 약 3만 행.
- 지난 공개 세대 53개가 남아 있다(운영 54세대 1.56M 행 — 정리가 수집 속도를 못 따라간다).
- 통계(ANALYZE)는 지난 세대들로 만들어졌고 새 세대는 그 뒤에 공개된다. 운영의 마지막 자동 ANALYZE는
  공개 세대보다 이틀 앞섰다(새 세대의 generated_at이 MCV에 없어 계획이 "1행"으로 추정한다).

    uv run python tests/benchmarks/fuel_public_places.py --repeat 20
    uv run python tests/benchmarks/fuel_public_places.py --current-via copy   # 게시 경로를 거치지 않는 새 세대(통계 낡음 강제)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import insert, text

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory
from app.main import create_app
from app.models import FuelLatestPrice, FuelPriceSnapshot, FuelStation, TransportCollectionState
from app.services.fuel_statistics import OPINET, publish_fuel_statistics

# (시도 코드=정식 이름, 짧은 이름, 운영 주유소 수, 대략 중심 경·위도)
SIDO = (
    ("경기도", "경기", 2525, 127.2, 37.4), ("경상북도", "경북", 1298, 128.7, 36.3), ("전남광주통합특별시", "전남광주", 1206, 126.9, 34.9),
    ("경상남도", "경남", 1119, 128.3, 35.3), ("충청남도", "충남", 1064, 126.8, 36.5), ("전북특별자치도", "전북", 889, 127.1, 35.7),
    ("충청북도", "충북", 746, 127.7, 36.8), ("강원특별자치도", "강원", 702, 128.3, 37.7), ("서울특별시", "서울", 459, 127.0, 37.55),
    ("부산광역시", "부산", 384, 129.05, 35.17), ("대구광역시", "대구", 375, 128.6, 35.87), ("인천광역시", "인천", 356, 126.65, 37.45),
    ("대전광역시", "대전", 244, 127.38, 36.35), ("울산광역시", "울산", 243, 129.3, 35.55), ("제주특별자치도", "제주", 224, 126.55, 33.4),
    ("세종특별자치시", "세종", 71, 127.28, 36.55),
)
# 상표 코드 비율(운영 근사). None은 상표 미제공.
BRANDS = (("SKE", 28), ("GSC", 19), ("HDO", 19), ("SOL", 17), ("RTO", 5), ("RTE", 3), ("NHO", 4), ("RTX", 1), ("NCO", 1),
          ("SKG", 1), ("E1G", 1), (None, 1))
# 유종별 판매 비율과 기준가. 세대당 약 2.5 point/주유소(운영 30,184 / 11,905).
PRODUCTS = (("B027", .95, 1690), ("D047", .95, 1580), ("C004", .32, 1300), ("B034", .22, 1950), ("K015", .11, 1080))
GENERATIONS = 54
BBOX = (126.9, 34.5, 128.7, 37.9)
PROD_PLACES = ("/v1/transport/features/places?kind=fuel_station&zoom=7&min_longitude=126.9&min_latitude=34.5"
               "&max_longitude=128.7&max_latitude=37.9")


async def seed(session, stamp: datetime, generations: int) -> None:
    await session.execute(text("TRUNCATE fuel_region_summaries, fuel_statistics_states, fuel_statistics_points, "
                               "fuel_statistics_daily, fuel_refresh_prices, fuel_latest_prices, fuel_price_snapshots, "
                               "fuel_stations, transport_collection_states RESTART IDENTITY CASCADE"))
    rng = random.Random(20261123)
    brand_codes = [code for code, weight in BRANDS for _ in range(weight)]
    stations, index = [], 0
    for sido_value, short, count, lon, lat in SIDO:
        sigungu_count = max(1, round(count / 48))
        for _ in range(count):
            index += 1
            sigungu = rng.randrange(sigungu_count)
            # 운영처럼 극소수 행만 시도 이름이 정식 이름이다.
            sido_name = sido_value if rng.random() < .004 else short
            stations.append({
                "id": index, "source": OPINET, "identity_key": f"A{index:07d}", "source_station_id": f"A{index:07d}",
                "name": f"주유소{index}", "brand_code": rng.choice(brand_codes), "brand_name": None,
                "address": f"{sido_value} 시군구{sigungu} 길{index}", "query_level": "sigungu", "source_kinds": ["browser"],
                "sido_value": sido_value, "sido_name": sido_name, "sigungu_value": f"{sido_value}:{sigungu:02d}",
                "sigungu_name": f"{short}시군구{sigungu}",
                "longitude": lon + rng.gauss(0, .22), "latitude": lat + rng.gauss(0, .18),
                "is_self": rng.random() < .53, "is_24h": rng.random() < .3, "has_carwash": rng.random() < .5,
                "has_maintenance": rng.random() < .2, "has_cvs": rng.random() < .25, "is_kpetro": rng.random() < .4,
                # 운영 행은 원문 JSON을 함께 저장해 넓다(heap 57 MB / 1.2만 행).
                "raw_item_json": {"pad": "".join(rng.choice("0123456789ABCDEF") for _ in range(1500))},
                "first_seen_at": stamp, "last_seen_at": stamp,
            })
    for offset in range(0, len(stations), 500):
        await session.execute(insert(FuelStation), stations[offset:offset + 500])
    snapshots = []
    for station in stations:
        for product, share, base in PRODUCTS:
            if rng.random() < share:
                snapshots.append({"fuel_station_id": station["id"], "source": OPINET, "product_code": product,
                                  "price": round(base + rng.gauss(0, 55)), "observed_at": stamp, "collected_at": stamp})
    for offset in range(0, len(snapshots), 2000):
        await session.execute(insert(FuelPriceSnapshot), snapshots[offset:offset + 2000])
    await session.execute(text("INSERT INTO fuel_latest_prices (fuel_station_id, product_code, snapshot_id, price, observed_at, collected_at) "
                               "SELECT fuel_station_id, product_code, id, price, observed_at, collected_at FROM fuel_price_snapshots"))
    previous = stamp - timedelta(hours=12)
    await session.execute(text("UPDATE fuel_latest_prices SET collected_at = :at"), {"at": previous})
    session.add(TransportCollectionState(source=OPINET, last_success_at=previous, updated_at=previous))
    await session.flush()
    await publish_fuel_statistics(session, OPINET, previous)
    await session.commit()
    # 지난 세대(운영처럼 수십 개)를 복제한다. 이 세대들로 통계를 만든다.
    for back in range(1, generations - 1):
        await session.execute(text(
            "INSERT INTO fuel_statistics_points (source, station_key, product_code, generated_at, name, address, brand_name, "
            "longitude, latitude, price) SELECT source, station_key, product_code, generated_at - make_interval(hours => :h), "
            "name, address, brand_name, longitude, latitude, price FROM fuel_statistics_points "
            "WHERE source = :source AND generated_at = :at"), {"h": 12 * back, "source": OPINET, "at": previous})
    await session.commit()
    await session.execute(text("ANALYZE"))
    await session.commit()
    print(f"seed: stations={len(stations)} prices={len(snapshots)} generations={generations - 1} (analyzed)")


async def publish_current(session, stamp: datetime, via: str) -> None:
    """새 공개 세대. publish=실제 게시 경로, copy=게시를 거치지 않은 SQL 복제(ANALYZE 없음 — 낡은 통계 강제)."""
    previous = stamp - timedelta(hours=12)
    started = time.perf_counter()
    if via == "publish":
        await session.execute(text("UPDATE fuel_latest_prices SET collected_at = :at"), {"at": stamp})
        await session.execute(text("UPDATE transport_collection_states SET last_success_at = :at WHERE source = :s"),
                              {"at": stamp, "s": OPINET})
        await publish_fuel_statistics(session, OPINET, stamp)
    else:
        for table, columns in (("fuel_statistics_points", "source, station_key, product_code, {g}, name, address, brand_name, "
                                "longitude, latitude, price"),
                               ("fuel_region_summaries", "source, {g}, scope, region_key, product_code, label, longitude, "
                                "latitude, average_price, station_count, metrics_json")):
            await session.execute(text(
                f"INSERT INTO {table} ({columns.format(g='generated_at')}) SELECT {columns.format(g=':at')} FROM {table} "
                "WHERE source = :s AND generated_at = :prev"
            ), {"at": stamp, "s": OPINET, "prev": previous})
        await session.execute(text("UPDATE fuel_statistics_states SET generated_at = :at WHERE source = :s"), {"at": stamp, "s": OPINET})
        await session.execute(text("UPDATE transport_collection_states SET last_success_at = :at WHERE source = :s"),
                              {"at": stamp, "s": OPINET})
    await session.commit()
    print(f"current generation via {via}: {time.perf_counter() - started:.2f}s")


async def describe(session) -> None:
    rows = (await session.execute(text(
        "SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid)) FROM pg_stat_user_tables "
        "WHERE relname IN ('fuel_stations','fuel_statistics_points','fuel_latest_prices') ORDER BY relname"))).all()
    print("tables:", "; ".join(f"{name} rows={rows_} size={size}" for name, rows_, size in rows))
    mcv = await session.scalar(text(
        "SELECT (SELECT generated_at FROM fuel_statistics_states WHERE source = :s)::text = ANY("
        "most_common_vals::text::text[]) FROM pg_stats WHERE tablename = 'fuel_statistics_points' AND attname = 'generated_at'"),
        {"s": OPINET})
    print(f"current generation in pg_stats MCV: {mcv}")


def clear_process_caches() -> None:
    """매 호출 실제 SQL 비용을 잰다(같은 화면 10초 캐시·지도 중심 캐시·세대 캐시를 비운다)."""
    from app.services import fuel_center_sigungu, fuel_price_distribution, fuel_statistics
    fuel_price_distribution._sigungu_cache.clear()
    fuel_statistics._viewport_cache.clear()
    fuel_center_sigungu._cache.clear()
    for name in ("_price_index_cache",):
        cache = getattr(fuel_price_distribution, name, None)
        if cache is not None:
            cache.clear()


def timed(client: TestClient, label: str, path: str, repeat: int, cold: bool = True) -> dict:
    samples, status = [], None
    for _ in range(repeat):
        if cold:
            clear_process_caches()
        started = time.perf_counter()
        response = client.get(path, timeout=120)
        samples.append((time.perf_counter() - started) * 1000)
        status = response.status_code
    samples.sort()
    p95 = samples[max(0, int(len(samples) * .95) - 1)]
    print(f"{label:<44} status={status} median={statistics.median(samples):8.1f}ms p95={p95:8.1f}ms max={samples[-1]:8.1f}ms")
    return {"label": label, "status": status, "median_ms": round(statistics.median(samples), 1), "p95_ms": round(p95, 1),
            "max_ms": round(samples[-1], 1)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--generations", type=int, default=GENERATIONS)
    parser.add_argument("--current-via", choices=("publish", "copy"), default="publish")
    parser.add_argument("--json", default=None, help="결과를 JSON으로 저장할 경로")
    args = parser.parse_args()
    url = os.environ["TEST_DATABASE_URL"]
    if os.environ.get("KOR_TRAVEL_TRANSPORT_TEST_DATABASE") != "1" or not url.startswith("postgresql"):
        raise SystemExit("전용 테스트 PostgreSQL만 사용합니다.")
    stamp = datetime.now(timezone.utc).replace(microsecond=0)

    async def prepare() -> None:
        engine, factory = create_engine_and_session_factory(url)
        async with factory() as session:
            await seed(session, stamp, args.generations)
            await publish_current(session, stamp, args.current_via)
            await describe(session)
        await engine.dispose()
    asyncio.run(prepare())

    settings = Settings(database_url=url, seed_sample_data=False, enable_scheduler=False, manual_collect_enabled=False,
                        data_go_kr_service_key=None, use_sample_client_when_no_key=True, airport_codes_csv="GMP",
                        cors_origins_csv="http://localhost:3000")
    filters = "&brands=SKE,GSC,HDO,ALT,NHO,RTX,NCO,ETC&self_only=true"
    ui = "&include_fuel_statistics=true&include_viewport_sigungu=true&center_longitude=127.8&center_latitude=36.2"
    cases = [
        ("places multi+brands+self (UI, all includes)", f"{PROD_PLACES}&product_codes=B027,D047{filters}{ui}"),
        ("places multi+brands+self (stats=false,sigungu)", f"{PROD_PLACES}&product_codes=B027,D047{filters}"
                                                           "&include_fuel_statistics=false&include_viewport_sigungu=true"),
        ("places multi+brands+self (no includes)", f"{PROD_PLACES}&product_codes=B027,D047{filters}"),
        ("places multi+self (UI)", f"{PROD_PLACES}&product_codes=B027,D047&self_only=true{ui}"),
        ("places multi+brands (UI)", f"{PROD_PLACES}&product_codes=B027,D047&brands=SKE,GSC,HDO,ALT,NHO,RTX,NCO,ETC{ui}"),
        ("places single+brands+self (UI)", f"{PROD_PLACES}&product_codes=B027{filters}{ui}"),
        ("places no filters (UI)", f"{PROD_PLACES}&product_codes=B027,D047{ui}"),
        ("distribution station_id", "/v1/transport/fuel/price-distribution?product_code=B027&station_id=4255"),
        ("distribution station_id + filters", "/v1/transport/fuel/price-distribution?product_code=B027&station_id=4255"
                                              "&self_only=true&brands=SKE,GSC"),
        ("distribution sigungu", "/v1/transport/fuel/price-distribution?product_code=B027&sido_value=%EA%B2%BD%EA%B8%B0%EB%8F%84"
                                 "&sigungu_value=%EA%B2%BD%EA%B8%B0%EB%8F%84:03"),
        ("distribution sigungu D047", "/v1/transport/fuel/price-distribution?product_code=D047"
                                      "&sido_value=%EC%84%9C%EC%9A%B8%ED%8A%B9%EB%B3%84%EC%8B%9C"
                                      "&sigungu_value=%EC%84%9C%EC%9A%B8%ED%8A%B9%EB%B3%84%EC%8B%9C:04"),
    ]
    results = []
    with TestClient(create_app(settings)) as client:
        for label, path in cases:
            results.append(timed(client, label, path, args.repeat))
        # 같은 세대·같은 조건 반복(프로세스 캐시 유지) — 화면에서 지역을 바꿔 가며 보는 경우.
        results.append(timed(client, "distribution station_id (warm)",
                             "/v1/transport/fuel/price-distribution?product_code=B027&station_id=4255", args.repeat, cold=False))
        results.append(timed(client, "distribution sigungu (warm)", cases[9][1], args.repeat, cold=False))
        body = client.get(cases[0][1]).json()
        print("sample: total=", body.get("total"), "regions=", len(body.get("fuel_regions") or []),
              "sigungu=", len(body.get("fuel_viewport_sigungu") or []), "center=", body.get("fuel_center_sigungu"))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"current_via": args.current_via, "repeat": args.repeat, "results": results}, handle, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
