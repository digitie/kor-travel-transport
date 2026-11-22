"""공개 유가 화면의 세대 조인 계획 회귀(PostgreSQL 전용).

운영(2026-11-23)에서 새 공개 세대는 늘 마지막 ANALYZE보다 늦게 생겨 계획기가 그 세대를 "1행"으로 추정했고,
point→주유소 조인이 `station_key = CAST(fuel_stations.id AS VARCHAR)`라 기본키를 못 써 중첩 루프 안쪽에서
fuel_stations 전체를 point마다 다시 읽었다(places zoom 7 필터 504, 가격 분포 평균 13.8초).

이 시험은 그 상태(지난 세대로 만든 통계 + ANALYZE 없이 공개된 새 세대)를 그대로 만든 뒤 실제 문장의 계획을 본다:
(1) 중첩 루프 안쪽에서 fuel_stations를 기본키 없이 다시 읽지 않는다, (2) 문자열 id 조인이 없다, (3) 새 세대 추정이
통계와 무관하게 실제 행 수에 가깝다(`fixed_generation`). 검출기·전제가 살아 있는지도 확인한다: 예전 문장(문자열 조인·
상수 세대)은 같은 상태에서 반드시 걸려야 한다.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import String, cast, func, insert, select, text

from app.models import FuelLatestPrice, FuelPriceSnapshot, FuelStation, FuelStatisticsPoint, TransportCollectionState
from app.services.fuel_price_distribution import _published_points, viewport_sigungu_statement
from app.services.fuel_station_filters import FuelStationFilters, fixed_generation, published_points_with_station
from app.services.fuel_statistics import HIGHWAY, OPINET, publish_fuel_statistics

STATIONS = 3000
OLD_GENERATIONS = 8
FILTERS = FuelStationFilters(brands=("ALT", "ETC", "GSC", "HDO", "NCO", "NHO", "RTX", "SKE"), self_only=True)
BOUNDS = (126.9, 34.5, 128.7, 37.9)


def _postgres(client) -> bool:
    return client.app.state.engine.dialect.name == "postgresql"


async def _seed_stale(session, stamp: datetime) -> datetime:
    """지난 세대로 통계를 만든 뒤 ANALYZE 없이 새 세대를 공개한다(운영의 낡은 통계 상태). 새 세대 시각을 돌려준다."""
    brands = ("SKE", "GSC", "HDO", "SOL", "RTO", "NHO", None)
    await session.execute(insert(FuelStation), [{
        "id": index, "source": OPINET, "identity_key": str(index), "name": f"주유소{index}", "query_level": "sigungu",
        "source_kinds": [], "sido_value": f"시도{index % 16}", "sido_name": f"시도{index % 16}",
        "sigungu_value": f"시군구{index % 200}", "sigungu_name": f"시군구{index % 200}", "brand_code": brands[index % 7],
        "is_self": index % 2 == 0, "longitude": 126 + (index % 300) / 100, "latitude": 34 + (index % 400) / 100,
        "raw_item_json": {"pad": "x" * 600}, "first_seen_at": stamp, "last_seen_at": stamp,
    } for index in range(1, STATIONS + 1)])
    await session.execute(insert(FuelPriceSnapshot), [{
        "fuel_station_id": index, "source": OPINET, "product_code": product, "price": 1500 + index % 300,
        "observed_at": stamp, "collected_at": stamp,
    } for index in range(1, STATIONS + 1) for product in ("B027", "D047")])
    await session.execute(text(
        "INSERT INTO fuel_latest_prices (fuel_station_id, product_code, snapshot_id, price, observed_at, collected_at) "
        "SELECT fuel_station_id, product_code, id, price, observed_at, collected_at FROM fuel_price_snapshots"))
    session.add(TransportCollectionState(source=OPINET, last_success_at=stamp, updated_at=stamp))
    await session.flush()
    await publish_fuel_statistics(session, OPINET, stamp)
    for back in range(1, OLD_GENERATIONS):
        await session.execute(text(
            "INSERT INTO fuel_statistics_points (source, station_key, product_code, generated_at, name, longitude, latitude, price) "
            "SELECT source, station_key, product_code, generated_at - make_interval(hours => :h), name, longitude, latitude, price "
            "FROM fuel_statistics_points WHERE source = :s AND generated_at = :at"), {"h": back, "s": OPINET, "at": stamp})
    await session.commit()
    await session.execute(text("ANALYZE fuel_statistics_points"))
    await session.execute(text("ANALYZE fuel_stations"))
    current = stamp + timedelta(hours=1)
    # 게시 경로를 거치지 않고(ANALYZE 없음) 새 세대를 복제·공개한다.
    await session.execute(text(
        "INSERT INTO fuel_statistics_points (source, station_key, product_code, generated_at, name, longitude, latitude, price) "
        "SELECT source, station_key, product_code, :now, name, longitude, latitude, price "
        "FROM fuel_statistics_points WHERE source = :s AND generated_at = :at"), {"now": current, "s": OPINET, "at": stamp})
    # 같은 시각의 고속도로 휴게소 point(문자 키). 정수 조인의 CASE가 이 키를 정수로 바꾸려 하면 오류가 난다.
    await session.execute(insert(FuelStatisticsPoint), [{
        "source": HIGHWAY, "station_key": "A00001", "product_code": "B027", "generated_at": current, "name": "휴게소",
        "longitude": 127.5, "latitude": 36.5, "price": 1700}])
    await session.execute(text("UPDATE fuel_statistics_states SET generated_at = :now WHERE source = :s"),
                          {"now": current, "s": OPINET})
    await session.commit()
    return current


async def _plan(session, statement) -> dict:
    compiled = statement.compile(dialect=session.bind.dialect, compile_kwargs={"literal_binds": True})
    rows = (await session.execute(text(f"EXPLAIN (FORMAT JSON) {compiled}"))).scalar_one()
    return (json.loads(rows) if isinstance(rows, str) else rows)[0]["Plan"]


def _nodes(plan: dict):
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


def _rescanned_station_scans(plan: dict) -> list[str]:
    """중첩 루프 안쪽(매 바깥 행마다 다시 도는 쪽)에서 fuel_stations를 기본키가 아닌 방법으로 읽는 곳."""
    found = []
    for node in _nodes(plan):
        if node["Node Type"] != "Nested Loop" or len(node.get("Plans", [])) < 2:
            continue
        for inner in _nodes(node["Plans"][1]):
            if inner.get("Relation Name") == "fuel_stations" and inner["Node Type"] in {"Seq Scan", "Bitmap Heap Scan"}:
                found.append(f"{inner['Node Type']} on fuel_stations inside Nested Loop")
            if inner.get("Relation Name") == "fuel_stations" and "Index Cond" not in inner and "Index" in inner["Node Type"]:
                found.append(f"{inner['Node Type']} on fuel_stations without Index Cond inside Nested Loop")
    return found


def _pkey_skip_scans(plan: dict) -> list[str]:
    """세대 point를 기본키(source, station_key, …)로 훑는 곳. station_key 조건 없이 고르면 PG18 skip scan이다(운영 9.2초)."""
    return [f"{node['Node Type']} {node.get('Index Name')} {node.get('Index Cond')}" for node in _nodes(plan)
            if node.get("Index Name") == "fuel_statistics_points_pkey" and "station_key" not in str(node.get("Index Cond", ""))]


def _text_join(plan: dict) -> list[str]:
    return [str(node.get(key)) for node in _nodes(plan) for key in ("Join Filter", "Hash Cond", "Merge Cond", "Index Cond")
            if "character varying" in str(node.get(key, "")) and "id" in str(node.get(key, ""))]


@pytest.fixture
def stale_generation(client):
    if not _postgres(client):
        pytest.skip("PostgreSQL 실행 계획 회귀")

    async def setup():
        async with client.app.state.session_factory() as session:
            # 시험 중 자동 ANALYZE가 새 세대를 통계에 넣으면 전제가 사라진다.
            await session.execute(text("ALTER TABLE fuel_statistics_points SET (autovacuum_enabled = false)"))
            await session.commit()
            return await _seed_stale(session, datetime(2026, 11, 22, 8, 5, tzinfo=timezone.utc))

    async def teardown():
        async with client.app.state.session_factory() as session:
            await session.execute(text("ALTER TABLE fuel_statistics_points RESET (autovacuum_enabled)"))
            await session.commit()

    try:
        current = asyncio.run(setup())
        yield client, current
    finally:
        asyncio.run(teardown())


def test_stale_statistics_premise_and_legacy_shape_is_detected(stale_generation):
    """전제: 새 세대 추정이 실제보다 크게 작다. 검출기: 예전 문자열 조인은 중첩 루프 안 전체 읽기로 걸린다."""
    client, current = stale_generation
    p = FuelStatisticsPoint

    async def check():
        async with client.app.state.session_factory() as session:
            actual = await session.scalar(select(func.count()).select_from(p).where(p.source == OPINET, p.generated_at == current))
            estimate = (await _plan(session, select(p.station_key).where(p.source == OPINET, p.generated_at == current)))["Plan Rows"]
            assert actual >= STATIONS and estimate * 20 < actual, (estimate, actual)
            legacy = select(p.station_key).join(FuelStation, p.station_key == cast(FuelStation.id, String)).where(
                p.source == OPINET, p.generated_at == current, p.price > 0, p.product_code.in_(["B027", "D047"]),
                *FILTERS.station_conditions())
            plan = await _plan(session, legacy)
            assert _rescanned_station_scans(plan) or _text_join(plan), json.dumps(plan)[:2000]
    asyncio.run(check())


def test_filtered_public_statements_use_station_primary_key_under_stale_statistics(stale_generation):
    client, current = stale_generation

    async def check():
        async with client.app.state.session_factory() as session:
            statements = {
                "viewport_sigungu filtered": viewport_sigungu_statement(current, BOUNDS, ["B027", "D047"], None, 40, FILTERS),
                "viewport_sigungu": viewport_sigungu_statement(current, BOUNDS, ["B027", "D047"], None, 40, None),
                "distribution price index": _published_points(current, "B027", FILTERS).with_only_columns(
                    FuelStation.sido_value, FuelStation.sigungu_value, FuelStatisticsPoint.price),
                # 범위 통계 후보 CTE(fuel_statistics.viewport_fuel_statistics)와 같은 모양: state 조인 + 화면 + 유종 + 필터.
                "viewport statistics candidates": published_points_with_station().with_only_columns(
                    FuelStatisticsPoint.product_code, FuelStatisticsPoint.price).where(
                    FuelStatisticsPoint.longitude.between(BOUNDS[0], BOUNDS[2]),
                    FuelStatisticsPoint.latitude.between(BOUNDS[1], BOUNDS[3]),
                    FuelStatisticsPoint.product_code.in_(["B027", "D047"]), *FILTERS.station_conditions()),
                "regional filtered": published_points_with_station().with_only_columns(
                    FuelStation.sido_value, func.count()).where(*FILTERS.station_conditions()).group_by(FuelStation.sido_value),
            }
            for name, statement in statements.items():
                plan = await _plan(session, statement)
                assert not _rescanned_station_scans(plan), (name, json.dumps(plan)[:2000])
                assert not _pkey_skip_scans(plan), (name, _pkey_skip_scans(plan))
                assert not _text_join(plan), (name, _text_join(plan))
    asyncio.run(check())


def test_generation_estimate_does_not_depend_on_fresh_statistics(stale_generation):
    """새 세대를 InitPlan 매개변수로 넘기면 낡은 통계에서도 추정이 실제 행 수에 가깝다(상수 세대는 1행 근처)."""
    client, current = stale_generation
    p = FuelStatisticsPoint

    async def check():
        async with client.app.state.session_factory() as session:
            actual = await session.scalar(select(func.count()).select_from(p).where(p.source == OPINET, p.generated_at == current))
            opaque = (await _plan(session, select(p.station_key).where(
                p.source == OPINET, p.generated_at == fixed_generation(current))))
            scan = next(node for node in _nodes(opaque) if node.get("Relation Name") == "fuel_statistics_points"
                        and node.get("Parent Relationship") != "InitPlan")
            assert actual / 3 <= scan["Plan Rows"] <= actual * 3, (scan["Plan Rows"], actual)
    asyncio.run(check())


def test_public_statements_run_with_highway_points_in_the_same_generation(stale_generation):
    """CASE 가드: 같은 세대 시각의 고속도로(문자 키) point가 있어도 정수 조인이 실패하지 않는다."""
    client, current = stale_generation

    async def check():
        async with client.app.state.session_factory() as session:
            rows = (await session.execute(viewport_sigungu_statement(current, (124, 33, 132, 39), [], None, 40, None))).all()
            assert rows and sum(row.station_count for row in rows) >= 40
            index_rows = (await session.execute(_published_points(current, "B027", FILTERS).with_only_columns(
                FuelStatisticsPoint.price))).all()
            assert index_rows
    asyncio.run(check())


def test_public_fuel_services_do_not_join_points_on_text_station_ids():
    """모든 호출 지점(범위 통계 후보 CTE 포함)이 정수 조인 하나를 쓴다. 문자열 id 조인을 다시 들이면 실패한다."""
    from pathlib import Path
    services = Path(__file__).resolve().parents[1] / "app" / "services"
    offenders = []
    for path in sorted(services.glob("fuel_*.py")):
        source = path.read_text(encoding="utf-8")
        for needle in ("station_key == cast(", "cast(FuelStation.id, String) ==", "cast(s.id, String) =="):
            if needle in source:
                offenders.append(f"{path.name}: {needle}")
    assert not offenders, offenders
