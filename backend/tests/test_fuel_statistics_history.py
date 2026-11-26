"""장기 유가 추이: 공개 transaction 저장·backfill·일/주/월 점·snapshot·ETag·422 계약."""
import asyncio
import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import delete, func, select, update

from app.models import FuelLatestPrice, FuelStatisticsDaily, FuelStatisticsHistory, FuelStatisticsState
from app.models import FuelPriceSnapshot, FuelStation
from app.services.fuel_statistics import OPINET, fuel_statistics_history, fuel_statistics_page, publish_fuel_statistics
from app.services.transport_collection import upsert_latest_fuel_prices


async def seed(session, stamp):
    """test_fuel_statistics.seed와 같은 세 주유소(서울 종로, 휘발유 1600·1800·1600)."""
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

START = datetime(2026, 10, 1, 3, tzinfo=timezone.utc)  # KST 2026-10-01 12:00


def _publish_days(client, days, *, step=1, price_step=10):
    """하루씩 가격을 올리며 공개한다. 반환: 마지막 공개 시각."""
    async def run():
        async with client.app.state.session_factory() as session:
            await seed(session, START)
            stamp = START
            for offset in range(0, days, step):
                stamp = START + timedelta(days=offset)
                await session.execute(update(FuelLatestPrice).values(
                    collected_at=stamp, price=FuelLatestPrice.price + (price_step if offset else 0)))
                await publish_fuel_statistics(session, OPINET, stamp)
            await session.commit()
            return stamp
    return asyncio.run(run())


def _history(client, **params):
    return client.get("/v1/transport/fuel/statistics/history", params=params)


def test_publish_writes_slim_history_equal_to_daily_metrics(client):
    _publish_days(client, 3)

    async def check():
        async with client.app.state.session_factory() as session:
            daily = (await session.scalars(select(FuelStatisticsDaily).order_by(
                FuelStatisticsDaily.scope, FuelStatisticsDaily.scope_key, FuelStatisticsDaily.day))).all()
            slim = (await session.scalars(select(FuelStatisticsHistory).order_by(
                FuelStatisticsHistory.scope, FuelStatisticsHistory.scope_key, FuelStatisticsHistory.day))).all()
            assert len(daily) == len(slim) == 9  # 전국·시도·시군구 × 3일
            for full, short in zip(daily, slim):
                assert (full.scope, full.scope_key, full.product_code, full.day, full.label) == (
                    short.scope, short.scope_key, short.product_code, short.day, short.label)
                assert full.generated_at == short.generated_at
                assert float(short.average_price) == full.metrics_json["average_price"]
                assert float(short.minimum_price) == full.metrics_json["minimum_price"]
                assert float(short.maximum_price) == full.metrics_json["maximum_price"]
                assert short.station_count == full.metrics_json["station_count"]
    asyncio.run(check())


def test_same_day_republish_replaces_history_and_day_points(client):
    last = _publish_days(client, 2)

    async def republish():
        async with client.app.state.session_factory() as session:
            later = last + timedelta(hours=2)
            await session.execute(update(FuelLatestPrice).values(collected_at=later, price=2000))
            await publish_fuel_statistics(session, OPINET, later)
            await session.commit()
            return later
    later = asyncio.run(republish())
    response = _history(client)
    assert response.status_code == 200
    body = response.json()
    assert body["bucket"] == "day" and body["scope_key"] == "all" and body["label"] == "전국"
    assert [point["day"] for point in body["points"]] == ["2026-10-01", "2026-10-02"]
    latest = body["points"][-1]
    assert latest["average_price"] == latest["minimum_price"] == latest["maximum_price"] == 2000
    assert latest["generated_at"].startswith(later.strftime("%Y-%m-%dT%H:%M"))
    assert (latest["first_day"], latest["last_day"], latest["day_count"]) == ("2026-10-02", "2026-10-02", 1)


def test_week_and_month_buckets_average_daily_averages_without_station_weighting(client):
    _publish_days(client, 40)
    days = _history(client, bucket="day").json()["points"]
    assert len(days) == 40
    weeks = _history(client, bucket="week").json()
    assert weeks["bucket"] == "week" and weeks["average_method"] == "mean_of_daily_averages"
    # 2026-10-01은 목요일이다. 첫 주 버킷은 그 주 월요일(09-28)에서 시작하고 기록은 10-01~10-04다.
    first = weeks["points"][0]
    assert (first["day"], first["first_day"], first["last_day"], first["day_count"]) == (
        "2026-09-28", "2026-10-01", "2026-10-04", 4)
    expected = round(sum(point["average_price"] for point in days[:4]) / 4, 2)
    assert first["average_price"] == expected
    assert first["minimum_price"] == min(point["minimum_price"] for point in days[:4])
    assert first["maximum_price"] == max(point["maximum_price"] for point in days[:4])
    assert sum(point["day_count"] for point in weeks["points"]) == 40
    months = _history(client, bucket="month").json()["points"]
    assert [(point["day"], point["day_count"]) for point in months] == [("2026-10-01", 31), ("2026-11-01", 9)]
    assert months[1]["average_price"] == round(sum(point["average_price"] for point in days[31:]) / 9, 2)
    assert months[1]["generated_at"] == days[-1]["generated_at"]
    # 기록이 없는 날짜·버킷은 만들지 않는다.
    ranged = _history(client, bucket="day", **{"from": "2026-10-10", "to": "2026-10-12"}).json()
    assert [point["day"] for point in ranged["points"]] == ["2026-10-10", "2026-10-11", "2026-10-12"]
    assert (ranged["from_day"], ranged["to_day"]) == ("2026-10-10", "2026-10-12")


def test_auto_bucket_and_point_bounds(client, monkeypatch):
    from app.services import fuel_statistics as module
    monkeypatch.setattr(module, "HISTORY_MAX_POINTS", 10)
    _publish_days(client, 30)
    assert _history(client).json()["bucket"] == "week"  # 30일 > 10, 5주 ≤ 10
    assert _history(client, **{"from": "2026-10-21"}).json()["bucket"] == "day"
    too_many = _history(client, bucket="day")
    assert too_many.status_code == 422
    assert too_many.headers["content-type"].startswith("application/problem+json")
    assert "bucket=week" in too_many.json()["detail"]
    # 기록이 없는 앞쪽 기간은 점 수에 세지 않는다.
    assert _history(client, bucket="day", **{"from": "2026-01-01", "to": "2026-10-08"}).status_code == 200


def test_snapshot_never_returns_days_after_the_published_state(client):
    last = _publish_days(client, 3)

    async def inject_future():
        async with client.app.state.session_factory() as session:
            # 공개 전환 전의 새 날짜 행(또는 시계가 앞선 행)은 공개 state보다 늦으므로 보이지 않는다.
            session.add(FuelStatisticsHistory(source=OPINET, scope="nationwide", scope_key="all", product_code="B027",
                day=date(2026, 10, 9), generated_at=last + timedelta(days=6), label="전국",
                average_price=1, minimum_price=1, maximum_price=1, station_count=1))
            await session.commit()
    asyncio.run(inject_future())
    body = _history(client, **{"to": "2026-12-31"}).json()
    assert body["to_day"] == "2026-10-03"
    assert [point["day"] for point in body["points"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]


def test_all_products_order_scope_key_requirement_and_validation(client):
    _publish_days(client, 2)
    sido = client.get("/v1/transport/fuel/statistics", params={"scope": "sido"}).json()
    key = sido["history_scope_key"]
    assert _history(client, scope="sido").status_code == 422
    body = _history(client, scope="sido", scope_key=key, product_code="ALL").json()
    assert body["label"] == "서울" and {point["product_code"] for point in body["points"]} == {"B027"}
    assert _history(client, scope="sido", scope_key="[\"없음\"]").json()["points"] == []
    for params in ({"bucket": "year"}, {"from": "2026-13-01"}, {"from": "2026-10-03", "to": "2026-10-01"},
                   {"from": "1990-01-01", "to": "2026-10-01"}, {"scope": "bad"}):
        response = _history(client, **params)
        assert response.status_code == 422, params
        assert response.headers["content-type"].startswith("application/problem+json")
    empty = _history(client, scope="highways").json()
    assert empty["points"] == [] and empty["generated_at"] is None and empty["source"] == "krex_rest_area_fuel"


def test_etag_and_cache_control(client):
    _publish_days(client, 2)
    first = _history(client)
    assert first.headers["cache-control"] == "private, no-cache"
    etag = first.headers["etag"]
    assert etag.startswith('W/"')
    cached = client.get("/v1/transport/fuel/statistics/history", headers={"If-None-Match": etag})
    assert cached.status_code == 304 and cached.content == b"" and cached.headers["etag"] == etag
    assert _history(client, bucket="week").headers["etag"] != etag


def test_first_publish_of_a_day_repairs_previous_day_written_only_to_daily(client):
    """0049 배포 중 옛 이미지가 migration 뒤에 공개한 날(일별 행만 바뀜)을 다음 날 첫 공개가 맞춘다."""
    last = _publish_days(client, 2)

    async def old_image_publish_then_next_day():
        async with client.app.state.session_factory() as session:
            day = (last + timedelta(hours=9)).date()
            await session.execute(update(FuelStatisticsDaily).where(FuelStatisticsDaily.day == day).values(
                generated_at=last + timedelta(hours=1)))
            await session.execute(update(FuelStatisticsState).values(generated_at=last + timedelta(hours=1)))
            # 옛 이미지는 새 표를 모른다: 그날 시군구 행이 없어지고 전국 행은 이전 세대 값이다.
            await session.execute(delete(FuelStatisticsHistory).where(
                FuelStatisticsHistory.day == day, FuelStatisticsHistory.scope == "sigungu"))
            await session.commit()
            following = last + timedelta(days=1)
            await session.execute(update(FuelLatestPrice).values(collected_at=following))
            await publish_fuel_statistics(session, OPINET, following)
            await session.commit()
            daily = {(row.scope, row.day): row.generated_at for row in await session.scalars(select(FuelStatisticsDaily))}
            slim = {(row.scope, row.day): row.generated_at for row in await session.scalars(select(FuelStatisticsHistory))}
            assert slim == daily
    asyncio.run(old_image_publish_then_next_day())


def test_old_image_publishing_across_midnight_is_repaired_by_the_next_publish(client):
    """옛 이미지가 migration 뒤 D와 D+1을 모두 공개해 state가 이미 D+1이어도, 새 이미지의 D+1 공개가 D를 맞춘다."""
    last = _publish_days(client, 2)

    async def run():
        async with client.app.state.session_factory() as session:
            day = (last + timedelta(hours=9)).date()
            # 옛 이미지: D(어제)를 다시 공개해 일별만 바뀌고, 자정 넘어 D+1을 공개해 state도 D+1이다(새 표는 모른다).
            await session.execute(update(FuelStatisticsDaily).where(FuelStatisticsDaily.day == day).values(
                generated_at=last + timedelta(hours=1)))
            following = last + timedelta(days=1)
            await session.execute(update(FuelLatestPrice).values(collected_at=following))
            await publish_fuel_statistics(session, OPINET, following)
            await session.execute(delete(FuelStatisticsHistory).where(FuelStatisticsHistory.day == following.date()))
            await session.execute(update(FuelStatisticsHistory).where(FuelStatisticsHistory.day == day).values(
                generated_at=last))
            await session.commit()
            later = following + timedelta(hours=3)
            await session.execute(update(FuelLatestPrice).values(collected_at=later))
            await publish_fuel_statistics(session, OPINET, later)
            await session.commit()
            daily = {(row.scope, row.day): row.generated_at for row in await session.scalars(select(FuelStatisticsDaily))}
            slim = {(row.scope, row.day): row.generated_at for row in await session.scalars(select(FuelStatisticsHistory))}
            assert slim == daily
    asyncio.run(run())


def test_thirty_day_page_is_unchanged_by_history_table(client):
    _publish_days(client, 3)

    async def check():
        async with client.app.state.session_factory() as session:
            page = await fuel_statistics_page(session, "nationwide", "B027")
            trend = await fuel_statistics_history(session, "nationwide", None, "B027", None, None, "day")
            assert [(str(row["day"]), row["average_price"], row["station_count"]) for row in page["history"]] == [
                (str(point["day"]), point["average_price"], point["station_count"]) for point in trend["points"]]
    asyncio.run(check())


def _migration(name):
    path = Path(__file__).parents[1] / "alembic/versions" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backfill_migration_copies_daily_metrics_in_windows_and_skips_invalid_rows(client, monkeypatch):
    """0049 upgrade를 실제 DB에서 실행: 창 경계·빠진 극값·잘못된 legacy 행을 다룬다. downgrade는 표만 지운다."""
    _publish_days(client, 5)
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    migration = _migration("0049_fuel_statistics_history.py")
    monkeypatch.setattr(migration, "BACKFILL_DAYS", 2)

    async def run():
        engine = client.app.state.engine
        async with engine.begin() as connection:
            legacy = (await connection.execute(select(FuelStatisticsDaily).where(
                FuelStatisticsDaily.scope == "nationwide", FuelStatisticsDaily.day == date(2026, 10, 2)))).one()
            metrics = {key: value for key, value in legacy.metrics_json.items()
                       if key not in {"minimum_price", "maximum_price"}}
            await connection.execute(update(FuelStatisticsDaily).where(
                FuelStatisticsDaily.scope == "nationwide", FuelStatisticsDaily.day == date(2026, 10, 2)).values(
                metrics_json=metrics))
            await connection.execute(update(FuelStatisticsDaily).where(
                FuelStatisticsDaily.scope == "sido", FuelStatisticsDaily.day == date(2026, 10, 3)).values(
                metrics_json={"station_count": 0, "average_price": 0}))
            expected = (await connection.execute(select(func.count()).select_from(FuelStatisticsDaily))).scalar() - 1
            await connection.execute(sa.text("DROP TABLE fuel_statistics_history"))

            def upgrade(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.upgrade()
            await connection.run_sync(upgrade)
            rows = (await connection.execute(select(FuelStatisticsHistory))).all()
            assert len(rows) == expected
            old = next(row for row in rows if row.scope == "nationwide" and row.day == date(2026, 10, 2))
            assert old.minimum_price is None and old.maximum_price is None
            assert float(old.average_price) == metrics["average_price"]
            assert not any(row.scope == "sido" and row.day == date(2026, 10, 3) for row in rows)

            def downgrade(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.downgrade()
                    migration.upgrade()  # 다시 올려도 같은 결과(멱등)
            await connection.run_sync(downgrade)
            assert (await connection.execute(select(func.count()).select_from(FuelStatisticsHistory))).scalar() == expected
    asyncio.run(run())


@pytest.mark.parametrize("bucket", ["day", "auto"])
def test_service_reads_one_snapshot_statement(client, bucket):
    """state와 추이 행을 한 SELECT로 읽는다(공개 전환과 섞이지 않는다)."""
    _publish_days(client, 2)
    from sqlalchemy import event
    statements = []

    async def run():
        engine = client.app.state.engine
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(engine.sync_engine, "before_cursor_execute", listener)
        try:
            async with client.app.state.session_factory() as session:
                await fuel_statistics_history(session, "nationwide", None, "B027", None, None, bucket)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", listener)
    asyncio.run(run())
    reads = [statement for statement in statements if "fuel_statistics_history" in statement]
    assert len(reads) == 1 and "fuel_statistics_states" in reads[0]


def test_postgres_page_reads_only_the_published_day_for_many_categories(client):
    """시군구처럼 범주가 많은 scope의 현재 범주 읽기가 모든 날짜·유종의 색인 항목을 훑지 않는다(0050).

    예전 계획은 기본키 `(source, scope, scope_key, product_code, day)`의 시군구 앞부분을 범주마다 다시 찾았다
    (PostgreSQL 18 skip scan, 400일 합성 데이터에서 Index Searches 461·공유 버퍼 3,494). 새 인덱스는 한 번 찾는다.
    """
    engine = client.app.state.engine
    if engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL 계획을 본다")
    from sqlalchemy import event, insert

    published = date(2026, 11, 26)
    stamp = datetime(2026, 11, 26, 0, 17, tzinfo=timezone.utc)

    async def run():
        async with client.app.state.session_factory() as session:
            rows = [{"source": OPINET, "scope": "sigungu", "scope_key": f'["시도{key // 20:02d}","시군구{key:03d}"]',
                     "product_code": product, "day": published - timedelta(days=offset),
                     "generated_at": stamp - timedelta(days=offset), "label": f"시군구{key}",
                     "metrics_json": {"station_count": 3, "average_price": 1800.5, "minimum_price": 1700,
                                      "maximum_price": 1900, "cheapest_station": None, "cheapest_station_count": 1}}
                    for key in range(230) for product in ("B027", "D047") for offset in range(60)]
            for start in range(0, len(rows), 2000):
                await session.execute(insert(FuelStatisticsDaily), rows[start:start + 2000])
            session.add(FuelStatisticsState(source=OPINET, generated_at=stamp, day=published))
            await session.commit()
        async with engine.connect() as connection:
            await connection.execute(sa.text("ANALYZE fuel_statistics_daily"))
            await connection.commit()
        captured = []
        listener = lambda conn, cursor, statement, parameters, context, many: captured.append((statement, parameters))  # noqa: E731
        event.listen(engine.sync_engine, "before_cursor_execute", listener)
        try:
            async with client.app.state.session_factory() as session:
                page = await fuel_statistics_page(session, "sigungu", "B027")
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", listener)
        assert len(page["items"]) == 230 and len(page["history"]) == 30
        statement, parameters = next(item for item in captured if "fuel_current_keys" in item[0])
        async with engine.connect() as connection:
            raw = (await connection.get_raw_connection()).driver_connection
            plan = "\n".join(row[0] for row in await raw.fetch("EXPLAIN (ANALYZE, BUFFERS) " + statement, *parameters))
            version = int(await raw.fetchval("SHOW server_version_num"))
        assert "ix_fuel_statistics_daily_current" in plan, plan
        searches = [int(line.split(":")[1]) for line in plan.splitlines() if "Index Searches:" in line]
        if version >= 180000:  # "Index Searches"는 PostgreSQL 18 EXPLAIN부터 나온다.
            assert searches and all(count <= 2 for count in searches), plan
    asyncio.run(run())


def test_far_future_or_out_of_range_to_and_from_after_published_day(client, monkeypatch):
    _publish_days(client, 3)
    far = _history(client, to="9999-12-31").json()
    assert [point["day"] for point in far["points"]] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert far["to_day"] == "2026-10-03"
    for params in ({"to": "0030-01-01"}, {"from": "1999-12-31"}, {"product_code": "all"}):
        response = _history(client, **params)
        assert response.status_code == 422, params
        assert response.headers["content-type"].startswith("application/problem+json")
    later = _history(client, **{"from": "2026-12-01", "to": "2026-12-31"}).json()
    assert later["points"] == [] and later["from_day"] is None and later["to_day"] == "2026-10-03"
    # to 없이 from만 줘도 개월 상한을 지킨다(상한을 줄여 확인).
    from app.services import fuel_statistics as module
    monkeypatch.setattr(module, "HISTORY_MAX_POINTS", 3)
    assert _history(client, **{"from": "2026-07-01"}).status_code == 422
    assert _history(client, **{"from": "2026-08-01"}).status_code == 200


def test_bucket_average_is_not_station_weighted(client):
    """하루는 주유소 3곳, 다음 날은 1곳이어도 두 날의 평균을 같은 비중으로 평균한다."""
    async def run():
        async with client.app.state.session_factory() as session:
            for offset, (average, count) in enumerate(((1000, 3), (2000, 1))):
                stamp = datetime(2026, 10, 5 + offset, 3, tzinfo=timezone.utc)  # 월·화
                session.add(FuelStatisticsHistory(source=OPINET, scope="nationwide", scope_key="all", product_code="B027",
                    day=stamp.date(), generated_at=stamp, label="전국", average_price=average, minimum_price=average,
                    maximum_price=average, station_count=count))
            session.add(FuelStatisticsState(source=OPINET, generated_at=datetime(2026, 10, 6, 3, tzinfo=timezone.utc),
                                            day=date(2026, 10, 6)))
            await session.commit()
    asyncio.run(run())
    point = _history(client, bucket="week").json()["points"][0]
    assert point["average_price"] == 1500  # 가중이면 1250
    assert point["station_count"] == 2 and point["day_count"] == 2
