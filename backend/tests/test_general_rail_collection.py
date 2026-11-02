import json
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.time_utils import now_utc, to_seoul
from app.db.session import create_engine_and_session_factory, init_database
from app.models import CollectionRun, GeneralRailQuerySnapshot
from app.schemas import GeneralRailTimetableResponse
from app.services.general_rail_collection import GeneralRailCollectionService, TRIGGER
from app.services.general_rail_storage import save_general_rail
from test_general_rail_api import FakeTrain, fake_client


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_daily_refresh_persists_and_keeps_last_good_on_failure(test_settings, failed):
    now = now_utc()
    day = to_seoul(now).date()
    key = json.dumps(["NAT010000", "NAT014445", day.isoformat(), None], separators=(",", ":"))
    train = FakeTrain()
    original = train.timetable_list
    async def fetch(**params):
        if failed:
            raise RuntimeError("private-provider-error")
        return await original(**params)
    train.timetable_list = fetch
    engine, factory = create_engine_and_session_factory(test_settings.database_url)
    await init_database(engine)
    service = GeneralRailCollectionService(test_settings.model_copy(update={"data_go_kr_service_key":"fake"}), client_factory=fake_client(train))
    async with factory() as session:
        previous = now - timedelta(hours=25)
        await save_general_rail(session, "timetable", key, GeneralRailTimetableResponse(fetched_at=previous,
            service_date=day, departure_station_id="NAT010000", arrival_station_id="NAT014445", total=0, items=[]))
        result = await service.collect(session)
        run = await session.scalar(select(CollectionRun).where(CollectionRun.trigger == TRIGGER))
        assert result["status"] == ("failed" if failed else "success"), run.error_message
        stored = await session.get(GeneralRailQuerySnapshot, ("timetable", key), populate_existing=True)
        assert len(stored.response_json["items"]) == (0 if failed else 1)
        assert (await service.collect(session))["status"] == "skipped"
        run = await session.scalar(select(CollectionRun).where(CollectionRun.trigger == TRIGGER))
        assert "private-provider-error" not in (run.error_message or "")
    await engine.dispose()
