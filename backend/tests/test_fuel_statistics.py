"""원본 이력을 다시 읽지 않는 수집 완료 통계와 지도 전체 범위 집계 계약."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import func, select, update

from app.models import (
    FuelLatestPrice, FuelPriceSnapshot, FuelStation, FuelStatisticsDaily, RestAreaFuelPrice,
    TransportCollectionState,
)
from app.services.fuel_statistics import (
    HIGHWAY, OPINET, fuel_statistics_page, publish_fuel_statistics, try_publish_fuel_statistics,
)
from app.services.transport_collection import upsert_latest_fuel_prices


async def seed(session, stamp):
    for index, (price, longitude) in enumerate(((1600, 127), (1800, 127.01), (1600, 128))):
        station = FuelStation(id=(2, 3, 10)[index], source=OPINET, identity_key=str(index), name=f"주유소{index}",
            address=f"서울 도로{index}", query_level="sigungu", source_kinds=[],
            sido_value="11", sido_name="서울", sigungu_value="110", sigungu_name="종로",
            longitude=longitude, latitude=37.5, first_seen_at=stamp, last_seen_at=stamp)
        session.add(station)
        await session.flush()
        session.add(FuelPriceSnapshot(fuel_station_id=station.id, source=OPINET,
            product_code="B027", price=price, observed_at=stamp, collected_at=stamp))
    await session.flush()
    await upsert_latest_fuel_prices(session, collected_at=stamp)


def test_summary_and_viewport_ignore_marker_limit(client):
    stamp = datetime.now(timezone.utc)
    async def setup():
        async with client.app.state.session_factory() as session:
            await seed(session, stamp)
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
    asyncio.run(setup())
    response = client.get("/v1/transport/fuel/statistics")
    assert response.status_code == 200
    summary = response.json()["items"][0]
    assert summary["station_count"] == 3
    assert summary["average_price"] == 1666.67
    assert summary["minimum_price"] == 1600
    assert summary["price_spread"] == 200
    assert summary["saving_50l"] == 3333.33
    assert summary["cheapest_station_count"] == 2
    # 전국 집계와 지도 SQL은 같은 문자열 station_key 순서로 동률 대표를 고른다.
    assert summary["cheapest_station"]["name"] == "주유소2"
    for zoom in (7, 15):
        response = client.get("/v1/transport/features/places", params={
            "kind": "fuel_station", "limit": 1, "zoom": zoom, "include_fuel_statistics": True,
            "min_longitude": 126.9, "max_longitude": 127.1, "min_latitude": 37, "max_latitude": 38,
        })
        assert response.status_code == 200
        viewport = response.json()["fuel_statistics"][0]
        assert viewport["station_count"] == 2
        assert viewport["average_price"] == 1700
        assert viewport["saving_50l"] == 5000
        assert viewport["cheapest_station"]["name"] == "주유소0"
    assert client.get("/v1/transport/fuel/statistics", params={"scope": "bad"}).status_code == 422
    absent = client.get("/v1/transport/fuel/statistics", params={"scope_key": "removed"}).json()
    assert absent["history_scope_key"] == "all"
    filtered = client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "include_fuel_statistics": True, "query": "주유소1",
        "min_longitude": 124, "max_longitude": 132, "min_latitude": 32, "max_latitude": 39,
    }).json()
    assert filtered["fuel_statistics"][0]["station_count"] == 1
    assert filtered["fuel_statistics"][0]["average_price"] == 1800


def test_kst_retention_same_day_replace_and_atomic_failure(client):
    async def exercise():
        async with client.app.state.session_factory() as session:
            stamp = datetime(2026, 10, 12, 16, tzinfo=timezone.utc)
            await seed(session, stamp)
            for offset in range(8):
                await session.execute(update(FuelLatestPrice).values(collected_at=stamp + timedelta(days=offset)))
                await publish_fuel_statistics(session, OPINET, stamp + timedelta(days=offset))
            latest = stamp + timedelta(days=7, hours=1)
            await session.execute(update(FuelLatestPrice).values(collected_at=latest))
            await publish_fuel_statistics(session, OPINET, latest)
            await session.commit()
            page = await fuel_statistics_page(session, "nationwide", "B027")
            assert len(page["history"]) == 8
            assert str(page["history"][0]["day"]) == "2026-10-13"
            assert str(page["history"][-1]["day"]) == "2026-10-20"
            assert await session.scalar(select(func.count()).select_from(FuelStatisticsDaily)) == 24
            # 통계 도중 실패해도 기존 세대가 보이고 원본 트랜잭션은 계속 사용 가능하다.
            raw_price = await session.get(FuelLatestPrice, (2, "B027"))
            raw_price.price = 1900
            await session.execute(update(FuelLatestPrice).values(collected_at=latest + timedelta(hours=1)))
            session.add(TransportCollectionState(source=OPINET, last_success_at=latest + timedelta(hours=1),
                updated_at=latest + timedelta(hours=1)))
            with patch("app.services.fuel_statistics._Accumulator.metrics", side_effect=RuntimeError("failed")):
                await try_publish_fuel_statistics(session, OPINET, latest + timedelta(hours=1))
            await session.commit()
            after = await fuel_statistics_page(session, "nationwide", "B027")
            assert after["items"] == page["items"]
            assert after["update_pending"] is True
            assert float((await session.get(FuelLatestPrice, (2, "B027"))).price) == 1900
    asyncio.run(exercise())

    response = client.get("/v1/transport/features/places", params={
        "kind": "fuel_station", "include_fuel_statistics": True,
        "min_longitude": 124, "max_longitude": 132, "min_latitude": 32, "max_latitude": 39,
    })
    assert response.status_code == 200
    assert response.json()["fuel_statistics"][0]["update_pending"] is True


def test_highway_direction_and_old_station_exclusion(client):
    async def exercise():
        async with client.app.state.session_factory() as session:
            stamp = datetime.now(timezone.utc)
            for key, direction, price, seen in (("A", "상행", 1700, stamp), ("B", "하행", 1800, stamp), ("C", "상행", 1000, stamp-timedelta(days=1))):
                session.add(RestAreaFuelPrice(source=HIGHWAY, service_area_code=key,
                    service_area_name=key, route_code="0010", route_name="경부선", direction=direction,
                    gasoline_price=price, first_seen_at=seen, last_seen_at=seen))
            await publish_fuel_statistics(session, HIGHWAY, stamp)
            await session.commit()
            total = await fuel_statistics_page(session, "highways", "B027")
            assert total["items"][0]["average_price"] == 1750
            assert total["items"][0]["station_count"] == 2
            directions = await fuel_statistics_page(session, "highway_direction", "B027")
            assert {row["label"] for row in directions["items"]} == {"경부선 · 상행", "경부선 · 하행"}
    asyncio.run(exercise())


def test_publication_between_reads_keeps_current_day_history(client):
    async def exercise():
        async with client.app.state.session_factory() as session:
            stamp = datetime.now(timezone.utc)
            await seed(session, stamp)
            await session.execute(update(FuelLatestPrice).values(collected_at=stamp - timedelta(days=1)))
            await publish_fuel_statistics(session, OPINET, stamp - timedelta(days=1))
            await session.execute(update(FuelLatestPrice).values(collected_at=stamp))
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
            execute = session.execute
            changed = False

            async def interleaved(statement, *args, **kwargs):
                nonlocal changed
                result = await execute(statement, *args, **kwargs)
                if not changed and statement.is_select and "fuel_statistics_daily" in str(statement):
                    changed = True
                    await execute(update(FuelLatestPrice).values(price=2100, collected_at=stamp + timedelta(hours=1)))
                    await publish_fuel_statistics(session, OPINET, stamp + timedelta(hours=1))
                    await session.commit()
                return result

            with patch.object(session, "execute", side_effect=interleaved):
                page = await fuel_statistics_page(session, "nationwide", "B027")
            assert changed
            assert len(page["history"]) == 2
            assert page["history"][-1]["average_price"] == page["items"][0]["average_price"] == 1666.67
    asyncio.run(exercise())


def test_deferred_publication_returns_false_and_logs_a_redacted_one_line_cause(caplog, monkeypatch):
    """발행 실패는 원본 성공을 취소하지 않되, 유형만이 아니라 가린 한 줄 원인을 남긴다(op metadata·event log용)."""
    import logging
    from contextlib import asynccontextmanager

    from app.services import fuel_statistics as module

    class Session:
        @asynccontextmanager
        async def begin_nested(self):
            yield

    async def timeout(*_args):
        raise TimeoutError("command timeout\n  while calling https://example.invalid/api?serviceKey=owned-secret-key&pageNo=1")

    monkeypatch.setattr(module, "publish_fuel_statistics", timeout)
    with caplog.at_level(logging.WARNING, logger="app.services.fuel_statistics"):
        assert asyncio.run(module.try_publish_fuel_statistics(Session(), OPINET, datetime.now(timezone.utc))) is False
    message = caplog.records[-1].getMessage()
    assert "cause=TimeoutError: command timeout while calling" in message
    assert "\n" not in message and "owned-secret-key" not in message


def test_all_products_30day_extremes_and_legacy_missing_values(client):
    async def setup():
        async with client.app.state.session_factory() as session:
            stamp = datetime(2026, 10, 1, 16, tzinfo=timezone.utc)
            await seed(session, stamp)
            session.add(FuelPriceSnapshot(fuel_station_id=2, source=OPINET, product_code="D047",
                price=1500, observed_at=stamp, collected_at=stamp))
            await session.flush()
            await upsert_latest_fuel_prices(session, collected_at=stamp)
            for offset in (0, 1, 30):
                current = stamp + timedelta(days=offset)
                await session.execute(update(FuelLatestPrice).values(collected_at=current))
                await publish_fuel_statistics(session, OPINET, current)
            # 과거 스키마에 실제 없던 극값은 채우지 않는다.
            legacy = await session.scalar(select(FuelStatisticsDaily).where(
                FuelStatisticsDaily.scope == "nationwide", FuelStatisticsDaily.product_code == "D047",
                FuelStatisticsDaily.day == (stamp + timedelta(days=1, hours=9)).date()))
            legacy.metrics_json = {key: value for key, value in legacy.metrics_json.items()
                                   if key not in {"minimum_price", "maximum_price", "cheapest_station"}}
            await session.commit()
    asyncio.run(setup())
    response = client.get("/v1/transport/fuel/statistics", params={"product_code": "ALL", "scope_key": "all"})
    assert response.status_code == 200
    body = response.json()
    assert {row["product_code"] for row in body["items"]} == {"B027", "D047"}
    assert len(body["history"]) == 4  # D-29와 D, 각 두 유종. D-30 제외.
    assert {row["day"] for row in body["history"]} == {"2026-10-03", "2026-11-01"}
    old = next(row for row in body["history"] if row["day"] == "2026-10-03" and row["product_code"] == "D047")
    assert old["minimum_price"] is old["maximum_price"] is old["cheapest_station"] is None
    latest = next(row for row in body["history"] if row["day"] == "2026-11-01" and row["product_code"] == "B027")
    assert (latest["minimum_price"], latest["maximum_price"]) == (1600, 1800)


def test_ranked_cheapest_ten_are_published_cohort_snapshot(client):
    async def setup():
        async with client.app.state.session_factory() as session:
            stamp = datetime(2026, 11, 13, 1, tzinfo=timezone.utc)
            for index in range(13):
                station = FuelStation(source=OPINET, identity_key=f"rank{index}", name=f"순위{index}",
                    address=f"주소{index}", query_level="sigungu", source_kinds=[],
                    sido_value="11", sido_name="서울", sigungu_value="110", sigungu_name="종로",
                    longitude=127 + index / 100, latitude=37.5, first_seen_at=stamp, last_seen_at=stamp)
                session.add(station)
                await session.flush()
                session.add(FuelPriceSnapshot(fuel_station_id=station.id, source=OPINET, product_code="B027",
                    price=100 if index == 12 else 1600 + index // 2, observed_at=stamp,
                    collected_at=stamp - timedelta(days=1) if index == 12 else stamp))
            await session.flush()
            await upsert_latest_fuel_prices(session)
            await publish_fuel_statistics(session, OPINET, stamp)
            # 이후 기준정보 변경으로 이미 공개된 주소/지역/순위를 바꾸지 않는다.
            await session.execute(update(FuelStation).values(address="이후 주소", sigungu_value="999"))
            await session.commit()
    asyncio.run(setup())
    response = client.get("/v1/transport/fuel/statistics", params={"product_code": "ALL"})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["station_count"] == 12
    assert item["ranking_complete"] is True
    ranks = item["cheapest_stations"]
    assert len(ranks) == 10
    assert [(row["price"], row["station_key"]) for row in ranks] == sorted((row["price"], row["station_key"]) for row in ranks)
    assert all(row["price"] >= 1600 and row["address"].startswith("주소") for row in ranks)
    assert ranks[0]["longitude"] is not None
