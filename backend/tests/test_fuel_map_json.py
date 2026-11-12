"""PG 집합 JSON 경로와 기존 복합 지도 경로의 전체 장소 DTO를 대조한다."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from app.models import FuelPriceSnapshot, FuelStation
from app.services.transport_collection import upsert_latest_fuel_prices
from sqlalchemy import event


def _seed(client):
    async def insert():
        at = datetime(2026, 11, 8, 3, 4, 5, 123456, tzinfo=timezone(timedelta(hours=9)))
        if client.app.state.session_factory.kw["bind"].dialect.name == "sqlite":
            at = at.astimezone(timezone.utc)
        ids = []
        async with client.app.state.session_factory() as session:
            for i, prices in enumerate(
                [
                    [("B027", None), ("B034", 2000.35), ("D047", 0)],
                    [("D047", 1600.35), ("A000", 1000), ("가", 1500)],
                    [],
                    [
                        ("K015", 1000),
                        ("C004", 1010),
                        ("D047", 1600),
                        ("B034", 2001),
                        ("B027", 1700),
                    ],
                ]
            ):
                station = FuelStation(
                    source="opinet",
                    identity_key=f"json-map-{i}",
                    name=f'검산 "주유소" 한글\\{i}',
                    address="주소 · <안내>",
                    brand_code="SK",
                    brand_name="SK에너지",
                    phone="02-000-0000",
                    query_level="sigungu",
                    sido_value="11",
                    sido_name="서울",
                    sigungu_value="110",
                    sigungu_name="검산구",
                    source_kinds=[],
                    longitude=127.1 + i / 100,
                    latitude=137 if i == 2 else 37.5,
                    is_self=True,
                    is_24h=None,
                    has_carwash=False,
                    has_maintenance=True,
                    has_cvs=None,
                    first_seen_at=at,
                    last_seen_at=at,
                )
                session.add(station)
                await session.flush()
                ids.append(station.id)
                for code, price in prices:
                    session.add(
                        FuelPriceSnapshot(
                            fuel_station_id=station.id,
                            source="opinet",
                            product_code=code,
                            price=price,
                            provider_updated_at=None if code == "B027" else at,
                            observed_at=at,
                            collected_at=at,
                        )
                    )
            await session.flush()
            await upsert_latest_fuel_prices(session)
            await session.commit()
        return ids

    return asyncio.run(insert())


def _get(client, **params):
    response = client.get(
        "/v1/transport/features/places",
        params={
            "include_unlocated": "true",
            "include_sources": "false",
            "limit": 20,
            **params,
        },
    )
    assert response.status_code == 200, response.text[:300]
    return response.json()


def test_fuel_json_preserves_full_dto_order_null_prices_and_utc(client):
    ids = _seed(client)
    mixed = _get(client, kinds="fuel_station,rail_station")
    expected = [row for row in mixed["items"] if row["kind"] == "fuel_station"]
    statements = []
    engine = client.app.state.session_factory.kw["bind"].sync_engine

    def sql_seen(_c, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", sql_seen)
    try:
        actual = _get(client, kind="fuel_station")
    finally:
        event.remove(engine, "before_cursor_execute", sql_seen)
    assert actual["items"] == expected
    assert [row["id"] for row in expected] == list(reversed(ids))
    by_id = {row["id"]: row for row in actual["items"]}
    assert by_id[ids[0]]["latest_price"] is None  # B027가 있으면 NULL도 그대로다.
    assert by_id[ids[1]]["price_product_code"] == "A000"
    assert by_id[ids[1]]["latest_price"] == 1000
    assert by_id[ids[2]]["prices"] == []
    assert by_id[ids[2]]["longitude"] is None and by_id[ids[2]]["latitude"] is None
    for row in actual["items"]:
        assert row["facilities"] == ["셀프", "정비"]
        assert row["updated_at"] == "2026-11-07T18:04:05.123456Z"
        for price in row["prices"]:
            assert price["observed_at"] == price["collected_at"] == row["updated_at"]
            assert price["provider_updated_at"] in (None, row["updated_at"])
    limited = _get(client, kind="fuel_station", limit=2)
    assert limited["items"] == expected[:2]
    assert limited["total"] == 4 and limited["kind_totals"] == {"fuel_station": 4}
    assert limited["truncated"] is True
    if engine.dialect.name == "postgresql":
        projected = [
            sql for sql in statements if "selected_fuel_stations AS MATERIALIZED" in sql
        ]
        assert len(projected) == 1 and "json_agg" in projected[0]
        assert "raw_item_json" not in projected[0]


@pytest.mark.parametrize("products", ["B034,D047", "K015"])
def test_fuel_json_keeps_latest_positive_product_and_source_filters(client, products):
    _seed(client)
    params = {"product_codes": products, "source": "opinet"}
    mixed = _get(client, kinds="fuel_station,rail_station", **params)
    actual = _get(client, kind="fuel_station", **params)
    expected = [row for row in mixed["items"] if row["kind"] == "fuel_station"]
    assert actual["items"] == expected
    assert actual["total"] == len(expected) and not actual["truncated"]
    assert all(
        any(
            p["product_code"] in products.split(",")
            and p["price"] is not None
            and p["price"] > 0
            for p in row["prices"]
        )
        for row in actual["items"]
    )


def test_fuel_json_empty_bbox_preserves_counts_and_metadata(client):
    _seed(client)
    payload = _get(
        client,
        kind="fuel_station",
        min_longitude=128,
        max_longitude=129,
        min_latitude=36,
        max_latitude=38,
    )
    assert payload["items"] == [] and payload["total"] == 0
    assert payload["kind_totals"] == {"fuel_station": 0} and not payload["truncated"]
    assert payload["fuel_statistics"] == [] and payload["generated_at"]


def test_fuel_json_codec_wait_does_not_block_health_event_loop(client, monkeypatch):
    import importlib
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    if client.app.state.session_factory.kw["bind"].dialect.name != "postgresql":
        pytest.skip("PG JSON codec의 worker 배선을 검산합니다.")
    _seed(client)
    main = importlib.import_module("app.main")
    original = main.validated_fuel_map_items
    entered, release = Event(), Event()

    def wait_codec(raw):
        entered.set()
        assert release.wait(5)
        return original(raw)

    monkeypatch.setattr(main, "validated_fuel_map_items", wait_codec)
    with ThreadPoolExecutor(1) as pool:
        request = pool.submit(_get, client, kind="fuel_station")
        assert entered.wait(5)
        try:
            started = time.perf_counter()
            assert client.get("/health").status_code == 200
            assert time.perf_counter() - started < 2
        finally:
            release.set()
        assert len(request.result(timeout=10)["items"]) == 4


def test_fuel_json_cached_validation_reflects_new_price_without_ttl(client):
    ids = _seed(client)
    before = _get(client, kind="fuel_station")
    assert (
        next(row for row in before["items"] if row["id"] == ids[0])["latest_price"]
        is None
    )

    async def correct():
        at = datetime(2026, 11, 8, 4, 4, 5, 123456, tzinfo=timezone.utc)
        async with client.app.state.session_factory() as session:
            session.add(
                FuelPriceSnapshot(
                    fuel_station_id=ids[0],
                    source="opinet",
                    product_code="B027",
                    price=1800.99,
                    provider_updated_at=at,
                    observed_at=at,
                    collected_at=at,
                )
            )
            await session.flush()
            await upsert_latest_fuel_prices(session)
            await session.commit()

    asyncio.run(correct())
    after = _get(client, kind="fuel_station")
    corrected = next(row for row in after["items"] if row["id"] == ids[0])
    assert corrected["latest_price"] == 1800.99
    assert (
        next(row for row in corrected["prices"] if row["product_code"] == "B027")[
            "price"
        ]
        == 1800.99
    )
