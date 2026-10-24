from datetime import UTC, datetime

import pytest

from app.db.session import create_engine_and_session_factory, init_database
from app.models import Airport, ParkingLot, ParkingSnapshot
from app.services.parking_outlook import parking_outlook


@pytest.mark.asyncio
async def test_arrival_cohort_uses_dates_equally_and_deduplicates_before_aggregation(test_settings, monkeypatch):
    now = datetime(2026, 10, 24, 1, tzinfo=UTC)
    monkeypatch.setattr("app.services.parking_outlook.now_utc", lambda: now)
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    await init_database(engine)
    async with factory() as session:
        airport = Airport(code="TST", name_ko="시험 공항", source="test", created_at=now, updated_at=now)
        session.add(airport)
        await session.flush()
        lot = ParkingLot(airport_id=airport.id, source_lot_id="A", name="주차장 A", is_active=True, created_at=now, updated_at=now)
        session.add(lot)
        await session.flush()
        def row(day, hour, minute, available, *, source="kac", capacity=200):
            return ParkingSnapshot(airport_id=airport.id, parking_lot_id=lot.id, source=source,
                observed_at=datetime(2026, 10, day, hour, minute, tzinfo=UTC), collected_at=now,
                occupied_spaces=capacity-available, available_spaces=available, total_spaces=capacity)
        session.add_all([
            row(17, 1, 0, 100), row(17, 1, 0, 199, source="migration_old"), row(17, 1, 30, 0),
            row(10, 1, 0, 40, capacity=100), row(17, 2, 0, 199), row(16, 1, 0, 199),
            row(24, 1, 0, 0), row(3, 1, 0, 0, capacity=0),
        ])
        await session.commit()
        result = await parking_outlook(session, airport, now, 28)
        assert result.hour == 10 and result.weekday == 5
        assert len(result.items) == 1
        item = result.items[0]
        assert item.sample_days == 2 and item.observations == 3
        assert item.average_available_spaces == 45
        assert item.minimum_available_spaces == 0 and item.maximum_available_spaces == 100
        assert item.full_days == 1 and item.full_day_ratio == 50
        assert (item.minimum_capacity, item.maximum_capacity) == (100, 200)
    await engine.dispose()


def test_outlook_api_rejects_ambiguous_time_and_unknown_airport(client):
    response = client.get("/v1/parking/outlook", params={"airport_code": "GMP", "arrival_at": "2026-10-24T10:00"})
    assert response.status_code == 422
    assert client.get("/v1/parking/outlook", params={"airport_code": "ZZZ"}).status_code == 404
    response = client.get("/v1/parking/outlook", params={"airport_code": "GMP", "arrival_at": "2026-10-24T10:00:00+09:00"})
    assert response.status_code == 200
    assert response.json()["hour"] == 10
    assert response.json()["airport_code"] == "GMP"
