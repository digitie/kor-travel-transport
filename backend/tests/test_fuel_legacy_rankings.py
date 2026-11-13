"""이전 통계의 현재 전국 순위는 동일 공개 point만 읽고 원장을 수정하지 않는다."""
from datetime import datetime, timedelta, timezone
import json

from sqlalchemy import delete, select, update

from app.db.session import create_engine_and_session_factory, init_database
from app.models import FuelLatestPrice, FuelPriceSnapshot, FuelStation, FuelStatisticsDaily, FuelStatisticsPoint
from app.services.fuel_statistics import OPINET, fuel_statistics_page, publish_fuel_statistics
from app.services.transport_collection import upsert_latest_fuel_prices


async def legacy_generation(session):
    stamp = datetime(2026, 11, 13, 0, 30, tzinfo=timezone.utc)
    for index in range(12):
        station = FuelStation(source=OPINET, identity_key=f"legacy-rank-{index}", name=f"동결 주유소{index}",
            address=f"동결 주소{index}", longitude=127, latitude=37.5, query_level="sigungu", source_kinds=[],
            sido_value="11", sido_name="서울", sigungu_value="110", sigungu_name="종로",
            first_seen_at=stamp, last_seen_at=stamp)
        session.add(station)
        await session.flush()
        for product, base in (("B027", 1600), ("D047", 1400)):
            session.add(FuelPriceSnapshot(source=OPINET, fuel_station_id=station.id,
                product_code=product, price=base + index // 2, observed_at=stamp, collected_at=stamp))
    await session.flush()
    await upsert_latest_fuel_prices(session)
    await publish_fuel_statistics(session, OPINET, stamp)
    for daily in (await session.scalars(select(FuelStatisticsDaily))).all():
        daily.metrics_json = {key: value for key, value in daily.metrics_json.items()
                              if key not in {"cheapest_stations", "ranking_complete"}}
    await session.commit()
    return stamp


async def test_legacy_global_rankings_use_frozen_published_points_without_writes(test_settings):
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    try:
        await init_database(engine)
        async with factory() as session:
            stamp = await legacy_generation(session)
            # 현 원천 가격/주소가 달라도 공개된 통계의 보관 가격/주소를 사용한다.
            await session.execute(update(FuelLatestPrice).values(price=1, collected_at=stamp + timedelta(hours=1)))
            await session.execute(update(FuelStation).values(address="이후 주소", sigungu_value="999"))
            session.add(FuelStatisticsPoint(source=OPINET, station_key="not-published", product_code="B027",
                generated_at=stamp + timedelta(hours=1), name="대기 세대", address="대기 주소", price=1))
            await session.commit()
            before = json.dumps([(row.scope, row.scope_key, row.product_code, row.metrics_json) for row in
                (await session.scalars(select(FuelStatisticsDaily))).all()], sort_keys=True)
            page = await fuel_statistics_page(session, "nationwide", "ALL")
            assert len(page["items"]) == 2
            for item in page["items"]:
                assert item["ranking_complete"] is True
                ranks = item["cheapest_stations"]
                assert len(ranks) == 10
                assert [(row["price"], row["station_key"]) for row in ranks] == sorted(
                    (row["price"], row["station_key"]) for row in ranks)
                assert all(row["price"] >= 1400 and row["address"].startswith("동결 주소") for row in ranks)
                assert all(row["station_key"] != "not-published" for row in ranks)
            assert all(row["generated_at"] == page["generated_at"] for row in page["history"])
            after = json.dumps([(row.scope, row.scope_key, row.product_code, row.metrics_json) for row in
                (await session.scalars(select(FuelStatisticsDaily))).all()], sort_keys=True)
            assert before == after
    finally:
        await engine.dispose()


async def test_legacy_region_does_not_rebuild_past_membership_from_current_stations(test_settings):
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    try:
        await init_database(engine)
        async with factory() as session:
            await legacy_generation(session)
            await session.execute(update(FuelStation).values(sigungu_value="999"))
            await session.commit()
            page = await fuel_statistics_page(session, "sigungu", "ALL")
            assert page["items"]
            assert all(not row["ranking_complete"] and row["cheapest_stations"] == [] for row in page["items"])
            assert all(row["cheapest_station"] for row in page["items"])
    finally:
        await engine.dispose()


async def test_legacy_incomplete_generation_keeps_known_cheapest_without_claiming_ten(test_settings):
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    try:
        await init_database(engine)
        async with factory() as session:
            await legacy_generation(session)
            point = await session.scalar(select(FuelStatisticsPoint).where(FuelStatisticsPoint.product_code == "B027"))
            await session.execute(delete(FuelStatisticsPoint).where(
                FuelStatisticsPoint.source == OPINET, FuelStatisticsPoint.station_key == point.station_key,
                FuelStatisticsPoint.product_code == "B027"))
            await session.commit()
            page = await fuel_statistics_page(session, "nationwide", "ALL")
            incomplete = next(row for row in page["items"] if row["product_code"] == "B027")
            assert incomplete["ranking_complete"] is False
            assert incomplete["cheapest_stations"] == [] and incomplete["cheapest_station"]
            assert next(row for row in page["items"] if row["product_code"] == "D047")["ranking_complete"] is True
    finally:
        await engine.dispose()
