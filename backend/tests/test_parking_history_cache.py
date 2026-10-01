from __future__ import annotations

import asyncio
import gzip
import json
from datetime import UTC, datetime, timedelta
from time import monotonic
from types import SimpleNamespace

import pytest
from pydantic_core import to_json
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import Airport, ParkingLot, ParkingSnapshot
from app.services import parking_history_cache as history_cache


def _row(when: datetime, lot_id: int, code: str = "GMP") -> SimpleNamespace:
    return SimpleNamespace(
        observed_at=when, parking_lot_id=lot_id, code=code,
        occupied_spaces=12, total_spaces=100, available_spaces=88,
    )


def test_cached_history_preserves_legacy_json_order_filters_and_cutoff() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    snapshot = history_cache.ParkingHistorySnapshot.from_rows(
        now - timedelta(days=30), 42,
        [_row(now - timedelta(hours=2), 1),
         _row(now - timedelta(hours=1), 2, "CJU"),
         _row(now - timedelta(hours=1), 3)],
    )
    full = json.loads(snapshot.render(now - timedelta(hours=3), None, None))
    assert snapshot.render(now - timedelta(hours=3), None, None) == to_json({
        "items": [{
            "airport_code": row.code,
            "parking_lot_id": row.parking_lot_id,
            "observed_at": row.observed_at,
            "occupied_spaces": row.occupied_spaces,
            "total_spaces": row.total_spaces,
            "available_spaces": row.available_spaces,
        } for row in [_row(now - timedelta(hours=2), 1),
                      _row(now - timedelta(hours=1), 2, "CJU"),
                      _row(now - timedelta(hours=1), 3)]],
        "next_cursor": None,
    })
    assert [(item["airport_code"], item["parking_lot_id"]) for item in full["items"]] == [
        ("GMP", 1), ("CJU", 2), ("GMP", 3),
    ]
    assert full["next_cursor"] is None
    assert [item["parking_lot_id"] for item in json.loads(snapshot.render(
        now - timedelta(hours=1), None, None,
    ))["items"]] == [2, 3]
    assert [item["parking_lot_id"] for item in json.loads(snapshot.render(
        now - timedelta(hours=3), "GMP", None,
    ))["items"]] == [1, 3]
    # 기존 API에서 parking_lot_id가 지정되면 airport_code보다 우선한다.
    assert [item["parking_lot_id"] for item in json.loads(snapshot.render(
        now - timedelta(hours=3), "GMP", 2,
    ))["items"]] == [2]
    assert snapshot.render(now + timedelta(seconds=1), None, None) == b'{"items":[],"next_cursor":null}'


def test_cached_history_gzip_is_negotiated_without_changing_json() -> None:
    body = b'{"items":[],"next_cursor":null}'
    compressed, headers = history_cache.encode_response(body, "br, gzip;q=1")
    assert gzip.decompress(compressed) == body
    assert headers["Content-Encoding"] == "gzip"
    plain, headers = history_cache.encode_response(body, "gzip;q=0, br")
    assert plain == body
    assert "Content-Encoding" not in headers


def test_cache_refreshes_on_new_snapshot_and_expires_when_unchecked(monkeypatch) -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)
    current_id = 10
    updates = 0
    builds: list[int] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalar(self, _statement):
            return current_id

        async def execute(self, _statement):
            return SimpleNamespace(one=lambda: (10, updates, 0))

    async def fake_load(_factory):
        builds.append(current_id)
        return history_cache.ParkingHistorySnapshot.from_rows(now - timedelta(days=30), current_id, [])

    monkeypatch.setattr(history_cache, "load_snapshot", fake_load)
    cache = history_cache.ParkingHistoryReadCache(FakeSession)
    asyncio.run(cache.refresh_once())
    assert builds == [10]
    asyncio.run(cache.refresh_once())
    assert builds == [10]
    current_id = 11
    asyncio.run(cache.refresh_once())
    assert builds == [10, 11]
    updates = 1
    asyncio.run(cache.refresh_once())
    assert builds == [10, 11, 11]
    assert cache.usable_snapshot(now - timedelta(days=1)) is not None
    cache.validated_at = monotonic() - history_cache.MAX_UNCHECKED_SECONDS - 1
    assert cache.usable_snapshot(now - timedelta(days=1)) is None
    assert cache.usable_snapshot(now - timedelta(days=31)) is None


def test_cache_load_query_prefers_live_and_caps_snapshot_id() -> None:
    now = datetime(2026, 10, 1, tzinfo=UTC)

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def scalar(self, _statement):
            return 42

        async def execute(self, statement):
            compiled = str(statement.compile(dialect=postgresql.dialect()))
            assert "DISTINCT ON" in compiled
            assert "parking_snapshots.id <=" in compiled
            assert "left(parking_snapshots.source" in compiled
            return SimpleNamespace(all=lambda: [_row(now, 3)])

    snapshot = asyncio.run(history_cache.load_snapshot(FakeSession, earliest_observed_at=now - timedelta(days=1)))
    assert snapshot.max_snapshot_id == 42
    assert snapshot.items[0].parking_lot_id == 3


def test_postgres_history_route_uses_prepared_gzip_without_database_scan(monkeypatch, test_settings) -> None:
    from app import main as main_module

    now = datetime.now(UTC)
    snapshot = history_cache.ParkingHistorySnapshot.from_rows(
        now - timedelta(days=31), 7, [_row(now - timedelta(hours=1), 3)],
    )

    class FakeCache:
        validated_at_utc = now

        def usable_snapshot(self, _cutoff):
            return snapshot

    class FakeSession:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        async def execute(self, _statement):
            raise AssertionError("cache hit must not scan PostgreSQL")

    fake_engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    monkeypatch.setattr(main_module, "create_engine_and_session_factory", lambda _url: (fake_engine, object()))
    monkeypatch.setattr(main_module, "ParkingHistoryReadCache", lambda _factory: FakeCache())
    app = main_module.create_app(test_settings.model_copy(update={"seed_sample_data": False}))
    included = next(route for route in app.routes if hasattr(route, "original_router"))
    route = next(route for route in included.original_router.routes if route.path == "/parking/history")
    response = asyncio.run(route.endpoint(
        SimpleNamespace(headers={"accept-encoding": "gzip"}),
        None, None, 30, None, None, FakeSession(),
    ))
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["x-parking-history-cache"] == "hit"
    assert response.headers["x-parking-history-checked-at"]
    assert [item["parking_lot_id"] for item in json.loads(gzip.decompress(response.body))["items"]] == [3]


def test_postgres_cache_matches_live_priority_and_detects_new_rows(client) -> None:
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL 통합 검증에서만 실행")
    observed_at = datetime.now(UTC) - timedelta(minutes=5)

    async def seed() -> tuple[int, int]:
        async with client.app.state.session_factory() as session:
            airport = await session.scalar(select(Airport).where(Airport.code == "GMP"))
            lot = await session.scalar(select(ParkingLot).where(ParkingLot.airport_id == airport.id))
            session.add_all([
                ParkingSnapshot(
                    airport_id=airport.id, parking_lot_id=lot.id, source="migration_test",
                    observed_at=observed_at, collected_at=observed_at + timedelta(minutes=2),
                    occupied_spaces=90, total_spaces=100, available_spaces=10,
                ),
                ParkingSnapshot(
                    airport_id=airport.id, parking_lot_id=lot.id, source="kac_test",
                    observed_at=observed_at, collected_at=observed_at + timedelta(minutes=1),
                    occupied_spaces=40, total_spaces=100, available_spaces=60,
                ),
            ])
            await session.commit()
            return airport.id, lot.id

    airport_id, lot_id = asyncio.run(seed())
    cache = history_cache.ParkingHistoryReadCache(client.app.state.session_factory)
    asyncio.run(cache.refresh_once())
    snapshot = cache.usable_snapshot(observed_at - timedelta(seconds=1))
    assert snapshot is not None
    selected = [item for item in json.loads(snapshot.render(
        observed_at - timedelta(seconds=1), None, lot_id,
    ))["items"] if datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00")) == observed_at]
    assert len(selected) == 1
    assert selected[0]["occupied_spaces"] == 40

    async def seed_new() -> None:
        async with client.app.state.session_factory() as session:
            session.add(ParkingSnapshot(
                airport_id=airport_id, parking_lot_id=lot_id, source="kac_test",
                observed_at=observed_at + timedelta(minutes=1), collected_at=datetime.now(UTC),
                occupied_spaces=30, total_spaces=100, available_spaces=70,
            ))
            await session.commit()

    first_max_id = snapshot.max_snapshot_id
    asyncio.run(seed_new())
    asyncio.run(cache.refresh_once())
    assert cache.snapshot.max_snapshot_id > first_max_id
    assert len(json.loads(cache.snapshot.render(
        observed_at - timedelta(seconds=1), None, lot_id,
    ))["items"]) >= len(json.loads(snapshot.render(
        observed_at - timedelta(seconds=1), None, lot_id,
    ))["items"]) + 1
