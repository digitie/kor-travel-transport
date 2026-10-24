import asyncio

from fastapi.testclient import TestClient

from app.core.time_utils import now_utc, to_seoul
from app.main import create_app
from app.models import BusTerminalReference
from app.schemas import BusTimetableItem, BusTimetableResponse
from app.services.bus_timetable_storage import save_bus_timetable


def test_stored_bus_connections_work_in_both_directions_without_inventing_missing_routes(test_settings):
    with TestClient(create_app(test_settings.model_copy(update={"seed_sample_data": False}))) as client:
        today = to_seoul(now_utc()).date()
        async def seed():
            async with client.app.state.session_factory() as session:
                for identifier in ("A", "B", "C"):
                    session.add(BusTerminalReference(source="data_go_kr_tago", service_type="express", terminal_id=identifier,
                        terminal_name=f"터미널 {identifier}", first_seen_at=now_utc(), last_seen_at=now_utc()))
                await session.commit()
                for departure, arrival, items in [("A", "B", [BusTimetableItem(departure_planned_time="1000")]), ("A", "C", [])]:
                    await save_bus_timetable(session, BusTimetableResponse(service_type="express", departure_terminal_id=departure,
                        arrival_terminal_id=arrival, service_date=today, fetched_at=now_utc(), items=items), None)
        asyncio.run(seed())
        params = {"service_type": "express", "terminal_id": "A", "date": today.isoformat(), "direction": "departure"}
        result = client.get("/v1/transport/bus/connections", params=params)
        assert result.status_code == 200
        assert result.json()["coverage"] == "stored_routes"
        assert [row["terminal_id"] for row in result.json()["items"]] == ["B"]
        params.update(terminal_id="B", direction="arrival")
        assert [row["terminal_id"] for row in client.get("/v1/transport/bus/connections", params=params).json()["items"]] == ["A"]
        params["service_type"] = "intercity"
        assert client.get("/v1/transport/bus/connections", params=params).json()["items"] == []
