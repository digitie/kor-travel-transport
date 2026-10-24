"""유가 스냅샷 집합 upsert(`_store_fuel_snapshot`)가 옛 행 단위 구현과 같은 DB 상태를 만드는지 본다.

옛 구현은 행마다 select→update/insert로 스냅샷당 왕복 ~7만 번을 써서 n150 디스크 대기에서 14~16분 걸렸고,
수집 엔진의 문장당 `command_timeout`(60초)을 넘겨 스냅샷 전체를 잃었다. 새 구현은 의미를 바꾸지 않아야 하므로
옛 구현을 이 파일에 그대로 옮겨 두고(오라클) 같은 출발 상태에서 두 구현의 결과를 비교한다. 출발 상태는
커밋해 두고 각 구현은 트랜잭션 안에서 돌린 뒤 되돌리므로 두 실행은 정확히 같은 행에서 시작한다.

PostgreSQL 대량 측정은 `KOR_TRAVEL_TRANSPORT_FUEL_STORE_BENCH=1`일 때만 돈다(CI 기본 실행에서 제외).
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from opinet import ProductCode, StationType
from opinet.experimental import BrowserFuelPrice, BrowserRegion, BrowserStation, OpinetBrowserSnapshot
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc, serialize_utc
from app.models import CollectionRun, FuelLatestPrice, FuelPriceSnapshot, FuelStation
from app.services import transport_collection as collection_module
from app.services.transport_collection import (
    OPINET_SOURCE,
    TransportCollectionService,
    _decimal_or_none,
    _enum_value,
    _plain_json,
    _station_identity,
    _station_values,
    upsert_latest_fuel_prices,
)


async def legacy_store_fuel_snapshot(
    service: TransportCollectionService,
    session: AsyncSession,
    collection_run_id: int,
    snapshot: OpinetBrowserSnapshot,
) -> tuple[int, int]:
    """e0545fbc까지의 `_store_fuel_snapshot` 원문(행 단위). 동등성 비교의 기준이다 — 고치지 않는다."""
    station_count = 0
    price_count = 0
    collected_at = serialize_utc(snapshot.collected_at, service.settings.app_timezone)
    for item in snapshot.stations:
        identity_key = _station_identity(item)
        station = await session.scalar(
            select(FuelStation).where(
                FuelStation.source == OPINET_SOURCE,
                FuelStation.identity_key == identity_key,
            )
        )
        values = _station_values(item, collected_at)
        if station is None:
            station = FuelStation(
                source=OPINET_SOURCE,
                identity_key=identity_key,
                first_seen_at=collected_at,
                **values,
            )
            session.add(station)
            station_count += 1
            await session.flush()
        else:
            for key, value in values.items():
                setattr(station, key, value)
            station.last_seen_at = collected_at

        for price in item.prices:
            provider_updated_at = (
                serialize_utc(price.updated_at, service.settings.app_timezone)
                if price.updated_at is not None
                else None
            )
            observed_at = provider_updated_at or collected_at
            product_code = _enum_value(price.product_code) or "unknown"
            existing = await session.scalar(
                select(FuelPriceSnapshot).where(
                    FuelPriceSnapshot.fuel_station_id == station.id,
                    FuelPriceSnapshot.source == OPINET_SOURCE,
                    FuelPriceSnapshot.product_code == product_code,
                    FuelPriceSnapshot.observed_at == observed_at,
                )
            )
            price_value = _decimal_or_none(price.price)
            raw_item = _plain_json(item.raw)
            if existing is None:
                session.add(
                    FuelPriceSnapshot(
                        collection_run_id=collection_run_id,
                        fuel_station_id=station.id,
                        source=OPINET_SOURCE,
                        product_code=product_code,
                        price=price_value,
                        provider_updated_at=provider_updated_at,
                        observed_at=observed_at,
                        collected_at=collected_at,
                        raw_item_json=raw_item,
                    )
                )
                price_count += 1
            else:
                existing.price = price_value
                existing.provider_updated_at = provider_updated_at
                existing.collected_at = collected_at
                existing.raw_item_json = raw_item
    await session.flush()
    await upsert_latest_fuel_prices(session, collected_at=collected_at)
    return station_count, price_count


# --- 스냅샷 생성 -------------------------------------------------------------------------------------------

_PRODUCTS = (
    ProductCode.GASOLINE_PREMIUM, ProductCode.GASOLINE, ProductCode.DIESEL, ProductCode.KEROSENE, ProductCode.LPG,
)


def make_station(
    station_id: str | None,
    *,
    name: str = "테스트주유소",
    sigungu: str = "강남구",
    prices: tuple[BrowserFuelPrice, ...] = (),
    katec: tuple[float, float] = (314000.0, 544000.0),
    phone: str = "02-000-0000",
    raw_extra: dict[str, Any] | None = None,
) -> BrowserStation:
    region = BrowserRegion(sido_value="서울특별시", sido_name="서울", sigungu_value=sigungu, sigungu_name=sigungu)
    raw = {"UNI_ID": station_id or "", "OS_NM": name, "PHN_NO": phone, **(raw_extra or {})}
    return BrowserStation(
        region=region, query_level="sigungu", source_kinds=("station",), station_id=station_id, name=name,
        brand_code="SKE", brand_name="SK에너지", phone=phone, address=f"서울 {sigungu} 1", business_number="1234567890",
        cb_code="CB", station_type=StationType.GAS_STATION, katec_x=katec[0], katec_y=katec[1], lon=127.0, lat=37.5,
        prices=prices, is_illegal=False, is_self=True, is_24h=False, is_kpetro=True, is_electronic=True, is_good=False,
        is_good_strong=False, is_region_franchise=None, has_carwash=True, has_maintenance=False, has_cvs=False,
        cs_yn=False, discount_info=None, save_event_info=None, representative_event_info=None, on_event_info=None,
        other_business_info=None, raw=raw,
    )


def price(product: ProductCode, value: float | None, updated_at: datetime | None) -> BrowserFuelPrice:
    return BrowserFuelPrice(product_code=product, price=value, updated_at=updated_at)


def make_snapshot(collected_at: datetime, stations: list[BrowserStation]) -> OpinetBrowserSnapshot:
    regions = tuple({station.region.sigungu_key: station.region for station in stations}.values())
    return OpinetBrowserSnapshot(
        collected_at=collected_at, source_url="https://www.opinet.co.kr/searRgSelect.do",
        regions=regions, stations=tuple(stations),
    )


def synthetic_snapshot(
    rng: random.Random,
    collected_at: datetime,
    *,
    station_ids: list[str],
    price_change_ratio: float,
    raw_padding: int = 0,
) -> OpinetBrowserSnapshot:
    """운영 모양을 흉내 낸 스냅샷. 주유소당 5유종, 절반가량은 판매 안 함(가격·갱신시각 없음).

    `price_change_ratio` 비율의 판매 유종만 갱신시각이 이번 수집으로 바뀌고(새 행), 나머지는 고정
    갱신시각을 유지한다(기존 행 갱신). 가격 없는 유종은 observed_at이 수집 시각이라 매번 새 행이다.
    """
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    stations = []
    for index, station_id in enumerate(station_ids):
        prices = []
        for product_index, product in enumerate(_PRODUCTS):
            if (index + product_index) % 2:
                prices.append(price(product, None, None))
                continue
            if rng.random() < price_change_ratio:
                updated = collected_at - timedelta(minutes=rng.randint(1, 600))
            else:
                updated = base + timedelta(minutes=(index * 5 + product_index) % 10_000)
            prices.append(price(product, float(rng.randint(1500, 2100)), updated))
        stations.append(make_station(
            station_id, name=f"주유소{index}", sigungu=f"구{index % 230}", prices=tuple(prices),
            phone=f"02-{rng.randint(0, 9999):04d}", raw_extra={"PAD": "x" * raw_padding, "IDX": index},
        ))
    return make_snapshot(collected_at, stations)


# --- DB 비교 ---------------------------------------------------------------------------------------------------

async def dump_fuel_state(session: AsyncSession, run_labels: dict[int, str]) -> dict[str, Any]:
    """id 대신 자연 키로 세 테이블을 읽는다. PostgreSQL 시퀀스는 롤백돼도 되돌아가지 않아 두 실행의
    id(주유소·유가·수집 run)가 다르므로, 수집 run id도 `run_labels`의 이름(seed/run0/...)으로 바꿔 비교한다."""
    stations = (await session.scalars(select(FuelStation).where(FuelStation.source == OPINET_SOURCE))).all()
    identity_by_id = {station.id: station.identity_key for station in stations}
    station_columns = [column.key for column in FuelStation.__table__.columns if column.key != "id"]
    station_state = {
        station.identity_key: {name: getattr(station, name) for name in station_columns} for station in stations
    }
    price_rows = (await session.scalars(select(FuelPriceSnapshot))).all()
    price_key_by_id = {}
    price_state = {}
    for row in price_rows:
        key = (identity_by_id[row.fuel_station_id], row.source, row.product_code, row.observed_at)
        price_key_by_id[row.id] = key
        price_state[key] = {
            "collection_run_id": run_labels.get(row.collection_run_id, row.collection_run_id), "price": row.price,
            "provider_updated_at": row.provider_updated_at, "collected_at": row.collected_at,
            "raw_item_json": row.raw_item_json,
        }
    latest_state = {
        (identity_by_id[row.fuel_station_id], row.product_code): {
            "snapshot": price_key_by_id[row.snapshot_id], "price": row.price,
            "provider_updated_at": row.provider_updated_at, "observed_at": row.observed_at,
            "collected_at": row.collected_at,
        }
        for row in (await session.scalars(select(FuelLatestPrice))).all()
    }
    return {"stations": station_state, "prices": price_state, "latest": latest_state}


def state_differences(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    """두 덤프의 차이를 (테이블, 키, 열, 왼쪽, 오른쪽)으로 풀어 쓴다. 실패 메시지용."""
    differences = []
    for table in sorted(set(left) | set(right)):
        left_rows, right_rows = left.get(table, {}), right.get(table, {})
        for key in sorted(set(left_rows) | set(right_rows), key=repr):
            if key not in left_rows or key not in right_rows:
                differences.append(f"{table} {key!r}: only in {'legacy' if key in left_rows else 'bulk'}")
                continue
            for column in sorted(set(left_rows[key]) | set(right_rows[key])):
                a, b = left_rows[key].get(column), right_rows[key].get(column)
                if a != b:
                    differences.append(f"{table} {key!r} {column}: legacy={a!r} bulk={b!r}")
    return differences


async def new_run(session: AsyncSession) -> int:
    run = CollectionRun(started_at=now_utc(), status="running", trigger="fuel_store_test")
    session.add(run)
    await session.flush()
    return run.id


async def apply_both(
    service: TransportCollectionService,
    factory,
    snapshots: list[OpinetBrowserSnapshot],
    seed_runs: dict[int, str],
) -> tuple[tuple[list[tuple[int, int]], dict], tuple[list[tuple[int, int]], dict]]:
    """같은 커밋 상태에서 옛·새 구현으로 `snapshots`를 차례로 저장하고 (개수, 상태)를 돌려준다."""
    outcomes = []
    for store in (legacy_store_fuel_snapshot, TransportCollectionService._store_fuel_snapshot):
        async with factory() as session:
            counts = []
            run_labels = dict(seed_runs)
            for index, snapshot in enumerate(snapshots):
                run_id = await new_run(session)
                run_labels[run_id] = f"run{index}"
                counts.append(await store(service, session, run_id, snapshot))
                session.expunge_all()
            state = await dump_fuel_state(session, run_labels)
            await session.rollback()
        outcomes.append((counts, state))
    return outcomes[0], outcomes[1]


async def seed(service: TransportCollectionService, factory, snapshot: OpinetBrowserSnapshot) -> dict[int, str]:
    async with factory() as session:
        run_id = await new_run(session)
        await legacy_store_fuel_snapshot(service, session, run_id, snapshot)
        await session.commit()
    return {run_id: "seed"}


# --- 테스트 ---------------------------------------------------------------------------------------------------

T0 = datetime(2026, 10, 11, 23, 35, 10, 717539, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=8)


def _scenario() -> tuple[OpinetBrowserSnapshot, OpinetBrowserSnapshot]:
    t_a = T0 - timedelta(hours=3)
    t_b = T0 - timedelta(hours=2)
    t_c = T0 - timedelta(hours=1)
    t_z = T0 - timedelta(minutes=30)
    first = make_snapshot(T0, [
        make_station("A", name="에이", prices=(price(ProductCode.GASOLINE, 1700, t_a),
                                                price(ProductCode.DIESEL, 1600, None))),
        make_station("B", name="비", prices=(price(ProductCode.GASOLINE, 1800, t_b),)),
        make_station(None, name="코드없음", prices=(price(ProductCode.LPG, 1000, t_c),)),
        make_station("Z", name="사라짐", prices=(price(ProductCode.GASOLINE, 1650, t_z),)),
    ])
    t_b2 = T1 - timedelta(hours=1)
    t_d = T1 - timedelta(minutes=20)
    t_e = T1 - timedelta(minutes=10)
    second = make_snapshot(T1, [
        # 기존 주유소: 속성 변경 + 같은 갱신시각의 가격 변경(기존 유가 행 갱신, run id 유지) + 갱신시각 없는 유종(새 행).
        make_station("A", name="에이-개명", phone="02-999-9999", raw_extra={"NEW": 1},
                     prices=(price(ProductCode.GASOLINE, 1710, t_a), price(ProductCode.DIESEL, 1610, None))),
        # 기존 주유소: 새 갱신시각(새 행) + 처음 보는 유종.
        make_station("B", name="비", prices=(price(ProductCode.GASOLINE, 1790, t_b2),
                                              price(ProductCode.KEROSENE, 1300, t_b2))),
        # 코드 없는 주유소는 지역·이름·좌표 지문으로 같은 행을 찾는다. 판매 안 하는 유종(가격 없음)도 행으로 남는다.
        make_station(None, name="코드없음", prices=(price(ProductCode.LPG, 1010, t_c),
                                                    price(ProductCode.GASOLINE, None, None))),
        make_station("N", name="새주유소", prices=(price(ProductCode.GASOLINE, 1690, t_d),)),
        # 같은 주유소가 두 번: 속성은 마지막 값, 같은 유가 키는 마지막 값, 순서는 처음 위치.
        make_station("DUP", name="첫번째", prices=(price(ProductCode.GASOLINE, 1500, t_d),)),
        make_station("C2", name="사이", prices=(price(ProductCode.DIESEL, 1450, t_e),)),
        make_station("DUP", name="두번째", prices=(price(ProductCode.GASOLINE, 1550, t_d),
                                                   price(ProductCode.DIESEL, 1400, t_e))),
        # "Z"는 이번 스냅샷에 없다 — 옛 구현처럼 손대지 않는다.
    ])
    return first, second


@pytest.mark.parametrize("batch", [None, 1, 2])
def test_bulk_store_matches_row_by_row_store(client, monkeypatch, batch) -> None:
    """기존 행 갱신·새 행·중복 키·사라진 주유소·묶음 경계까지 옛 구현과 같은 상태·개수를 만든다."""
    if batch is not None:
        monkeypatch.setattr(collection_module, "FUEL_STATION_UPSERT_BATCH", batch)
        monkeypatch.setattr(collection_module, "FUEL_PRICE_UPSERT_BATCH", batch)
    service = client.app.state.transport_collection_service
    factory = client.app.state.session_factory
    first, second = _scenario()

    async def run():
        seed_runs = await seed(service, factory, first)
        return await apply_both(service, factory, [second], seed_runs)

    (legacy_counts, legacy_state), (bulk_counts, bulk_state) = asyncio.run(run())

    assert bulk_counts == legacy_counts == [(3, 8)]
    assert state_differences(legacy_state, bulk_state) == []

    stations = bulk_state["stations"]
    assert stations["station:A"]["name"] == "에이-개명"
    assert stations["station:A"]["first_seen_at"] == stations["station:Z"]["first_seen_at"]
    assert stations["station:A"]["last_seen_at"] != stations["station:A"]["first_seen_at"]
    assert stations["station:Z"]["last_seen_at"] == stations["station:Z"]["first_seen_at"]
    assert stations["station:DUP"]["name"] == "두번째"
    updated = next(value for key, value in bulk_state["prices"].items()
                   if key[0] == "station:A" and key[2] == "B027")
    assert float(updated["price"]) == 1710.0
    assert updated["collected_at"] != stations["station:A"]["first_seen_at"]
    # 기존 유가 행을 갱신해도 수집 run은 처음 쓴 run(seed) 그대로다.
    assert updated["collection_run_id"] == "seed"
    dup_gasoline = next(value for key, value in bulk_state["prices"].items()
                        if key[0] == "station:DUP" and key[2] == "B027")
    assert float(dup_gasoline["price"]) == 1550.0
    assert float(bulk_state["latest"][("station:DUP", "D047")]["price"]) == 1400.0


@pytest.mark.parametrize("seed_value", [7, 2026])
def test_bulk_store_matches_row_by_row_store_on_random_snapshots(client, monkeypatch, seed_value) -> None:
    """무작위 스냅샷 세 개를 차례로 저장해도 같은 상태가 된다(일부 주유소는 빠졌다 돌아오고 중복도 섞인다)."""
    monkeypatch.setattr(collection_module, "FUEL_STATION_UPSERT_BATCH", 17)
    monkeypatch.setattr(collection_module, "FUEL_PRICE_UPSERT_BATCH", 29)
    service = client.app.state.transport_collection_service
    factory = client.app.state.session_factory
    rng = random.Random(seed_value)
    pool = [f"R{index:03d}" for index in range(60)]
    seed_snapshot = synthetic_snapshot(rng, T0, station_ids=pool[:40], price_change_ratio=1.0)
    rounds = []
    for round_index in range(3):
        chosen = rng.sample(pool, 45) + rng.sample(pool, 3)
        rounds.append(synthetic_snapshot(rng, T1 + timedelta(hours=8 * round_index), station_ids=chosen,
                                         price_change_ratio=0.3))

    async def run():
        seed_runs = await seed(service, factory, seed_snapshot)
        return await apply_both(service, factory, rounds, seed_runs)

    (legacy_counts, legacy_state), (bulk_counts, bulk_state) = asyncio.run(run())
    assert bulk_counts == legacy_counts
    assert state_differences(legacy_state, bulk_state) == []
    assert sum(prices for _, prices in bulk_counts) > 0


def test_bulk_store_issues_bounded_statements(client, monkeypatch) -> None:
    """왕복 수가 행 수가 아니라 묶음 수에 비례한다(옛 구현은 주유소·유가 행마다 select)."""
    monkeypatch.setattr(collection_module, "FUEL_STATION_UPSERT_BATCH", 50)
    monkeypatch.setattr(collection_module, "FUEL_PRICE_UPSERT_BATCH", 100)
    service = client.app.state.transport_collection_service
    factory = client.app.state.session_factory
    snapshot = synthetic_snapshot(random.Random(1), T0, station_ids=[f"S{index}" for index in range(200)],
                                  price_change_ratio=1.0)
    calls = 0
    original_execute = AsyncSession.execute

    async def counting_execute(self, statement, *args, **kwargs):
        nonlocal calls
        calls += 1
        return await original_execute(self, statement, *args, **kwargs)

    async def run():
        async with factory() as session:
            run_id = await new_run(session)
            monkeypatch.setattr(AsyncSession, "execute", counting_execute)
            try:
                counts = await service._store_fuel_snapshot(session, run_id, snapshot)
            finally:
                monkeypatch.setattr(AsyncSession, "execute", original_execute)
            await session.rollback()
            return counts

    station_count, price_count = asyncio.run(run())
    assert (station_count, price_count) == (200, 1000)
    # 주유소 4묶음 + 유가 10묶음 + 최신 유가 10묶음. 전체 이력 재검색은 없다.
    assert calls == 4 + 10 + 10


@pytest.mark.skipif(os.getenv("KOR_TRAVEL_TRANSPORT_FUEL_STORE_BENCH") != "1",
                    reason="운영 크기 측정은 KOR_TRAVEL_TRANSPORT_FUEL_STORE_BENCH=1에서만")
def test_bench_fuel_store_at_production_size(client) -> None:
    """운영 크기(주유소 11,885 x 5유종 ≈ 59,425 유가 행) 스냅샷의 저장 시간을 옛·새 구현으로 잰다.

    이력 스냅샷을 커밋해 두고 다음 스냅샷을 각 구현으로 저장한 뒤 되돌린다. 같은 출발 상태에서 잰다.
    """
    station_total = int(os.getenv("KOR_TRAVEL_TRANSPORT_FUEL_STORE_BENCH_STATIONS", "11885"))
    history = int(os.getenv("KOR_TRAVEL_TRANSPORT_FUEL_STORE_BENCH_HISTORY", "3"))
    service = client.app.state.transport_collection_service
    factory = client.app.state.session_factory
    rng = random.Random(20261012)
    ids = [f"A{index:07d}" for index in range(station_total)]
    padding = 640  # 운영 raw_item_json 평균 ≈ 877바이트

    async def run():
        for round_index in range(history):
            snapshot = synthetic_snapshot(rng, T0 + timedelta(hours=8 * round_index), station_ids=ids,
                                          price_change_ratio=0.1, raw_padding=padding)
            async with factory() as session:
                await service._store_fuel_snapshot(session, await new_run(session), snapshot)
                await session.commit()
        target = synthetic_snapshot(rng, T0 + timedelta(hours=8 * history), station_ids=ids,
                                    price_change_ratio=0.1, raw_padding=padding)
        results = {}
        for label, store in (("bulk", TransportCollectionService._store_fuel_snapshot),
                             ("legacy", legacy_store_fuel_snapshot),
                             ("bulk-again", TransportCollectionService._store_fuel_snapshot)):
            async with factory() as session:
                run_id = await new_run(session)
                timings: dict[str, list[float]] = {}
                engine = session.bind.sync_engine if hasattr(session.bind, "sync_engine") else session.bind

                def before(_conn, _cursor, statement, _params, context, _executemany):
                    context._bench_started = time.perf_counter()

                def after(_conn, _cursor, statement, _params, context, _executemany):
                    kind = " ".join(statement.split()[:3])[:40]
                    timings.setdefault(kind, []).append(time.perf_counter() - context._bench_started)

                event.listen(engine, "before_cursor_execute", before)
                event.listen(engine, "after_cursor_execute", after)
                try:
                    started = time.perf_counter()
                    counts = await store(service, session, run_id, target)
                    elapsed = time.perf_counter() - started
                finally:
                    event.remove(engine, "before_cursor_execute", before)
                    event.remove(engine, "after_cursor_execute", after)
                await session.rollback()
            results[label] = (elapsed, counts, timings)
        return results

    results = asyncio.run(run())
    for label, (elapsed, counts, timings) in results.items():
        database = sum(sum(values) for values in timings.values())
        calls = sum(len(values) for values in timings.values())
        slowest = max((max(values) for values in timings.values()), default=0.0)
        print(f"FUEL_STORE_BENCH {label}: {elapsed:.1f}s stations_new={counts[0]} prices_new={counts[1]} "
              f"db_calls={calls} db_time={database:.1f}s slowest_call={slowest:.2f}s")
        for kind, values in sorted(timings.items(), key=lambda item: -sum(item[1]))[:6]:
            print(f"FUEL_STORE_BENCH   {label} {kind!r}: calls={len(values)} total={sum(values):.1f}s max={max(values):.2f}s")
    assert results["bulk"][1] == results["legacy"][1] == results["bulk-again"][1]


def test_chunked_consumes_only_requested_batch() -> None:
    consumed = []

    def values():
        for value in range(5):
            consumed.append(value)
            yield value

    chunks = collection_module._chunked(values(), 2)
    assert consumed == []
    assert next(chunks) == [0, 1]
    assert consumed == [0, 1]
    assert next(chunks) == [2, 3]
    assert consumed == [0, 1, 2, 3]
    assert list(chunks) == [[4]]
    assert list(collection_module._chunked({}, 2)) == []


@pytest.mark.parametrize("size", [0, -1])
def test_chunked_rejects_invalid_batch_size(size) -> None:
    with pytest.raises(ValueError, match="chunk size"):
        list(collection_module._chunked([1], size))


def test_chunked_preserves_iterator_failure() -> None:
    def values():
        yield 1
        yield 2
        raise RuntimeError("fixture iterator failure")

    chunks = collection_module._chunked(values(), 2)
    assert next(chunks) == [1, 2]
    with pytest.raises(RuntimeError, match="fixture iterator failure"):
        next(chunks)

def test_empty_fuel_snapshot_keeps_empty_store(client) -> None:
    service = client.app.state.transport_collection_service
    factory = client.app.state.session_factory

    async def run():
        async with factory() as session:
            counts = await service._store_fuel_snapshot(session, await new_run(session), make_snapshot(T0, []))
            state = await dump_fuel_state(session, {})
            await session.rollback()
            return counts, state

    counts, state = asyncio.run(run())
    assert counts == (0, 0)
    assert state == {"stations": {}, "prices": {}, "latest": {}}
