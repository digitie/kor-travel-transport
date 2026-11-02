"""조회된 일반철도 경로의 예정 시간표를 하루 한 번 갱신한다."""
import json
from datetime import date, timedelta

from datagokr import DataGoKrClient
from sqlalchemy import select, text

from app.core.time_utils import now_utc, serialize_utc, to_seoul
from app.models import CollectionRun, GeneralRailQuerySnapshot
from app.schemas import GeneralRailTimetableResponse, GeneralRailTrip
from app.services.general_rail_storage import save_general_rail

TRIGGER = "dagster_general_rail_timetable"


class GeneralRailCollectionService:
    def __init__(self, settings, *, client_factory=DataGoKrClient):
        self.settings, self.client_factory = settings, client_factory

    async def collect(self, session):
        if not self.settings.data_go_kr_service_key:
            return {"status": "skipped", "reason": "TAGO is unconfigured"}
        engine = session.bind
        async with engine.connect() as connection:
            pg = engine.dialect.name == "postgresql"
            acquired = not pg or await connection.scalar(text("SELECT pg_try_advisory_lock(hashtext('transport:general_rail_daily'))"))
            if not acquired:
                return {"status": "skipped", "reason": "another rail refresh is active"}
            try:
                return await self._collect(session)
            finally:
                if pg:
                    await connection.execute(text("SELECT pg_advisory_unlock(hashtext('transport:general_rail_daily'))"))

    async def _collect(self, session):
        now = now_utc()
        latest = await session.scalar(select(CollectionRun.started_at).where(CollectionRun.trigger == TRIGGER)
                                      .order_by(CollectionRun.started_at.desc()).limit(1))
        if latest and now - serialize_utc(latest) < timedelta(hours=24):
            return {"status": "skipped", "reason": "daily rail refresh is not due"}
        saved = list((await session.scalars(select(GeneralRailQuerySnapshot).where(
            GeneralRailQuerySnapshot.operation == "timetable").order_by(GeneralRailQuerySnapshot.fetched_at))).all())
        today = to_seoul(now).date()
        routes = {}
        for row in saved:
            departure, arrival, day, grade = json.loads(row.request_key)
            day = max(date.fromisoformat(day), today)
            if day > today + timedelta(days=9):
                continue
            key = json.dumps([departure, arrival, day.isoformat(), grade], separators=(",", ":"))
            routes.setdefault(key, (departure, arrival, day, grade))
        run = CollectionRun(trigger=TRIGGER, status="running", started_at=now)
        session.add(run)
        await session.commit()
        run_id = run.id
        due = []
        for key, route in routes.items():
            previous = await session.get(GeneralRailQuerySnapshot, ("timetable", key))
            if previous is None or now - serialize_utc(previous.fetched_at) >= timedelta(hours=24):
                due.append((serialize_utc(previous.fetched_at) if previous else now - timedelta(days=100), key, route))
        due.sort(key=lambda item: (item[0], item[1]))
        count = 0
        try:
            async with self.client_factory(api_key=self.settings.data_go_kr_service_key,
                    timeout=self.settings.api_timeout_seconds, max_rps=1) as client:
                for _, key, (departure, arrival, day, grade) in due[:64]:
                    page = await client.train.timetable_list(departure_station_id=departure,
                        arrival_station_id=arrival, departure_date=day, train_grade_code=grade, num_of_rows=1000)
                    response = GeneralRailTimetableResponse(fetched_at=now_utc(), service_date=day,
                        departure_station_id=departure, arrival_station_id=arrival, total=page.total_count,
                        truncated=page.total_count is None or page.total_count > len(page.items),
                        items=[GeneralRailTrip(train_number=row.train_number, grade_name=row.grade_name,
                            departure_station_name=row.dep_place_name, arrival_station_name=row.arr_place_name,
                            departure_planned_time=row.dep_planned_time, arrival_planned_time=row.arr_planned_time,
                            adult_fare=row.adult_charge) for row in page.items])
                    await save_general_rail(session, "timetable", key, response)
                    count += 1
            run.status = "success"
        except Exception as exc:
            await session.rollback()
            run = await session.get(CollectionRun, run_id)
            run.status, run.error_message = "failed", type(exc).__name__
            # 이미 정상 저장한 시간표는 보존하고 URL·키를 예외에 포함하지 않는다.
        run.finished_at = now_utc()
        await session.commit()
        return {"status": run.status, "stored_route_count": count, "deferred_route_count": max(0, len(due)-64)}
