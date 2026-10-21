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
                await publish_fuel_statistics(session, OPINET, stamp + timedelta(days=offset))
            latest = stamp + timedelta(days=7, hours=1)
            await publish_fuel_statistics(session, OPINET, latest)
            await session.commit()
            page = await fuel_statistics_page(session, "nationwide", "B027")
            assert len(page["history"]) == 7
            assert str(page["history"][0]["day"]) == "2026-10-14"
            assert str(page["history"][-1]["day"]) == "2026-10-20"
            assert await session.scalar(select(func.count()).select_from(FuelStatisticsDaily)) == 21
            # 통계 도중 실패해도 기존 세대가 보이고 원본 트랜잭션은 계속 사용 가능하다.
            raw_price = await session.get(FuelLatestPrice, (2, "B027"))
            raw_price.price = 1900
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
            await publish_fuel_statistics(session, OPINET, stamp - timedelta(days=1))
            await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
            execute = session.execute
            changed = False

            async def interleaved(statement, *args, **kwargs):
                nonlocal changed
                result = await execute(statement, *args, **kwargs)
                if not changed and statement.is_select and "fuel_statistics_daily" in str(statement):
                    changed = True
                    await execute(update(FuelLatestPrice).values(price=2100))
                    await publish_fuel_statistics(session, OPINET, stamp + timedelta(hours=1))
                    await session.commit()
                return result

            with patch.object(session, "execute", side_effect=interleaved):
                page = await fuel_statistics_page(session, "nationwide", "B027")
            assert changed
            assert len(page["history"]) == 2
            assert page["history"][-1]["average_price"] == page["items"][0]["average_price"] == 1666.67
    asyncio.run(exercise())
