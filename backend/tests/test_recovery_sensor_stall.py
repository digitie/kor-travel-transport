"""회수 sensor의 tick 예산·keyset 위치·정체 경보와 DB 문장 상한 회귀 검사.

2026-09-27 code-server 정지(journal 2026-09-28 항목)에서 공항·고속도로 5분 수집이 약 8시간 멈췄는데
아무 경보도 없었다. 여기서는 그 신호(5분 수집의 새 `CollectionRun`이 더 생기지 않는데 sensor tick은
돈다)와 그 앞단의 DB 장애가 실제 `transport_worker_recovery` sensor에서 경보로 이어지는지 본다.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from kortravelcommon.stall import StallClock
from sqlalchemy import select

from app.core.time_utils import now_utc
from app.dagster import definitions as dagster_definitions
from app.dagster import recovery
from app.dagster.recovery import (
    COLLECTION_STALE_AFTER,
    FIVE_MINUTE_TRIGGERS,
    STALL_EVENT,
    RecoveryMetadataUnavailable,
    ScanPosition,
    format_stall_alert,
    reconcile_collection_runs,
    stale_five_minute_triggers,
)
from app.db import session as db_session
from app.db.session import create_engine_and_session_factory
from app.models import Base, CollectionRun

T0 = 1_800_000_000.0


async def _database(settings):
    engine, factory = create_engine_and_session_factory(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, factory


async def _add_runs(factory, rows):
    async with factory() as session:
        for row in rows:
            session.add(CollectionRun(**row))
        await session.commit()


def _skip(result) -> str:
    reason = result.skip_reason
    return getattr(reason, "skip_message", reason)


class Budget:
    """`remaining()` 호출 n번까지만 예산이 남은 것처럼 답한다."""

    def __init__(self, steps: int) -> None:
        self.steps = steps
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        return 100.0 if self.calls <= self.steps else 0.0


class TerminalInstance:
    def __init__(self, live=()):
        self.live = set(live)
        self.asked: list[str] = []

    def get_run_by_id(self, owner):
        self.asked.append(owner)
        return SimpleNamespace(is_finished=owner not in self.live)


# ---------------------------------------------------------------------------
# keyset 위치와 예산


async def test_budget_stops_scan_and_next_tick_resumes_without_losing_rows(test_settings):
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        await _add_runs(factory, [
            {"started_at": now, "heartbeat_at": now, "status": "running", "trigger": "t", "orchestrator_run_id": f"r{i}"}
            for i in range(5)
        ])
        position = ScanPosition()
        instance = TerminalInstance()
        # 예산 3단계: page 조회 1 + 행 2개. 그다음 page 조회 전에 멈추고 위치를 저장한다.
        assert await reconcile_collection_runs(
            factory, instance, page_size=2, position=position, remaining=Budget(3)
        ) == 2
        assert instance.asked == ["r0", "r1"]
        stopped_at = position.get()
        assert stopped_at > 0
        # 다음 tick은 처음부터가 아니라 저장한 위치부터 본다.
        assert await reconcile_collection_runs(
            factory, instance, page_size=2, position=position, remaining=Budget(3)
        ) == 2
        assert instance.asked == ["r0", "r1", "r2", "r3"]
        assert await reconcile_collection_runs(
            factory, instance, page_size=2, position=position, remaining=Budget(10)
        ) == 1
        # 끝까지 본 뒤에는 0으로 돌아가 다음 바퀴를 시작한다.
        assert position.get() == 0
        async with factory() as session:
            statuses = (await session.scalars(select(CollectionRun.status).order_by(CollectionRun.id))).all()
        assert statuses == ["failed"] * 5
    finally:
        await engine.dispose()


async def test_live_row_behind_position_is_recovered_on_the_next_lap(test_settings):
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        await _add_runs(factory, [
            {"started_at": now, "heartbeat_at": now, "status": "running", "trigger": "t", "orchestrator_run_id": owner}
            for owner in ("early", "late1", "late2")
        ])
        position = ScanPosition()
        # 첫 tick: early는 아직 살아 있어 지나간다. late1까지 보고 예산이 끝난다.
        assert await reconcile_collection_runs(
            factory, TerminalInstance(live={"early"}), page_size=10, position=position, remaining=Budget(3)
        ) == 1
        assert position.get() > 0
        # early가 끝났다. 이번 tick은 위치 뒤(late2)를 끝내고 0으로 돌아간다.
        instance = TerminalInstance()
        assert await reconcile_collection_runs(factory, instance, page_size=10, position=position) == 1
        assert position.get() == 0
        # 다음 바퀴에서 위치 앞에 있던 early도 회수된다.
        assert await reconcile_collection_runs(factory, instance, page_size=10, position=position) == 1
        async with factory() as session:
            statuses = (await session.scalars(select(CollectionRun.status).order_by(CollectionRun.id))).all()
        assert statuses == ["failed", "failed", "failed"]
    finally:
        await engine.dispose()


async def test_metadata_failure_keeps_position_before_failed_row_and_recovers_nothing(test_settings):
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        await _add_runs(factory, [
            {"started_at": now, "heartbeat_at": now, "status": "running", "trigger": "t", "orchestrator_run_id": owner}
            for owner in ("done", "broken", "after")
        ])

        class HalfBroken:
            def get_run_by_id(self, owner):
                if owner == "broken":
                    raise ConnectionError("metadata storage unavailable")
                return SimpleNamespace(is_finished=True)

        position = ScanPosition()
        with pytest.raises(RecoveryMetadataUnavailable) as raised:
            await reconcile_collection_runs(factory, HalfBroken(), position=position)
        assert isinstance(raised.value.__cause__, ConnectionError)
        async with factory() as session:
            rows = (await session.execute(
                select(CollectionRun.id, CollectionRun.status).order_by(CollectionRun.id))).all()
        assert [row.status for row in rows] == ["failed", "running", "running"]
        # 실패한 행 직전(첫 행)에 멈췄으므로 다음 tick은 broken부터 다시 본다.
        assert position.get() == rows[0].id
    finally:
        await engine.dispose()


class _SlowDb:
    """느린 DB 대역. 모든 문장(신선도 조회·page 조회·UPDATE·COMMIT)과 dispose가 `delay`초 걸린다.

    `hang_on`번째 문장부터는 `hang`초 멈춘다(디스크 대기·잠금 대기 모사).
    """

    def __init__(self, delay: float, *, hang_on: int | None = None, hang: float = 30.0, dispose: float = 0.0):
        self.delay, self.hang_on, self.hang, self.dispose_delay = delay, hang_on, hang, dispose
        self.statements = 0
        self.next_id = 0
        self.disposed = False

    async def _wait(self) -> None:
        import asyncio

        self.statements += 1
        hanging = self.hang_on is not None and self.statements >= self.hang_on
        await asyncio.sleep(self.hang if hanging else self.delay)

    def engine(self):
        db = self

        class Engine:
            async def dispose(self):
                import asyncio

                await asyncio.sleep(db.dispose_delay)
                db.disposed = True

        return Engine()

    def factory(self):
        db = self

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc):
                return False

            async def scalar(self, _statement):
                await db._wait()
                # 5분 수집 행 없음 → 신선도 판정 생략

            async def execute(self, statement):
                await db._wait()
                if getattr(statement, "is_select", False):
                    rows = []
                    for _ in range(3):
                        db.next_id += 1
                        now = now_utc()
                        rows.append(SimpleNamespace(id=db.next_id, orchestrator_run_id=f"r{db.next_id}",
                                                    heartbeat_at=now, started_at=now))
                    return SimpleNamespace(all=lambda: rows)
                return SimpleNamespace(rowcount=1)

            async def commit(self):
                await db._wait()

        return Session


@pytest.fixture
def budget_sensor(monkeypatch):
    """실제 `_reconcile_tick`을 common `reconciliation_sensor`의 짧은 예산(3초)으로 돌린다."""
    import time as real_time

    from dagster import DagsterInstance, build_sensor_context
    from kortravelcommon.dagster import reconciliation_sensor

    # 운영 상수(예산 45, 단계 25, 정리 5, metadata 10)를 같은 비율로 줄인다.
    monkeypatch.setattr(recovery, "METADATA_TIMEOUT_SECONDS", 0.4)
    monkeypatch.setattr(recovery, "STEP_RESERVE_SECONDS", 0.8)
    monkeypatch.setattr(recovery, "CLEANUP_RESERVE_SECONDS", 1.0)
    monkeypatch.setattr(dagster_definitions, "_settings", lambda: SimpleNamespace(database_url="x"))
    monkeypatch.setattr(dagster_definitions, "_RECOVERY_POSITION", ScanPosition())
    sensor = reconciliation_sensor(
        name="transport_worker_recovery_budget_test", reconcile=dagster_definitions._reconcile_tick,
        required_resource_keys=set(), budget_seconds=3, on_stall=lambda *_: None,
    )

    def run(db: _SlowDb):
        monkeypatch.setattr(dagster_definitions, "create_engine_and_session_factory",
                            lambda *_a, **_k: (db.engine(), db.factory()))
        with DagsterInstance.ephemeral() as instance:
            started = real_time.monotonic()
            result = sensor(build_sensor_context(instance=instance))
            return result, real_time.monotonic() - started

    return run


def test_slow_but_working_db_stops_gracefully_inside_budget(budget_sensor):
    db = _SlowDb(0.15, dispose=0.3)
    result, elapsed = budget_sensor(db)
    assert result.cursor == "stall:null"  # 예산 초과·timeout이 아니라 정상 종료
    assert elapsed < 3
    assert db.disposed
    position = dagster_definitions._RECOVERY_POSITION.get()
    assert 0 < position <= db.next_id  # 끝(빈 page)까지 가지 않고 위치를 남겼다(다음 tick이 이어 본다)


def test_hung_statement_and_dispose_end_before_budget_as_timeout_not_deadline(budget_sensor):
    db = _SlowDb(0.05, hang_on=2, dispose=30.0)
    result, elapsed = budget_sensor(db)
    reason = _skip(result)
    # common의 예산 끊김(DeadlineExceeded, thread 누수) 전에 콜백 스스로 끝난다.
    assert reason == "회수 실패 기록: TimeoutError", reason
    assert elapsed < 3
    assert not db.disposed  # dispose는 정리 상한에서 포기했다


# ---------------------------------------------------------------------------
# 5분 수집 신선도


async def test_stale_five_minute_triggers_only_flag_old_last_starts(test_settings):
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        assert await stale_five_minute_triggers(factory, now=now) == []  # 새 DB는 판단하지 않는다.
        airport, highway = FIVE_MINUTE_TRIGGERS
        await _add_runs(factory, [
            {"started_at": now - timedelta(minutes=40), "status": "success", "trigger": airport},
            {"started_at": now - timedelta(minutes=25), "status": "skipped", "trigger": airport},
            {"started_at": now - timedelta(minutes=3), "status": "running", "trigger": highway},
            # 다른 job의 새 행은 5분 수집의 신선도를 대신하지 않는다.
            {"started_at": now, "status": "success", "trigger": "transport_dagster_fuel"},
        ])
        assert await stale_five_minute_triggers(factory, now=now) == [(airport, 25)]
        assert await stale_five_minute_triggers(factory, now=now - timedelta(minutes=10)) == []
        assert COLLECTION_STALE_AFTER == timedelta(minutes=20)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 실제 sensor: 정체 시계와 경보


@pytest.fixture
def sensor_env(monkeypatch, test_settings):
    """실제 `transport_worker_recovery` sensor를 테스트 DB와 가짜 wall clock으로 돌린다."""
    from dagster import DagsterInstance, build_sensor_context
    from kortravelcommon import dagster as common_dagster

    clock = SimpleNamespace(now=T0)
    alerts: list[tuple[StallClock, str]] = []
    original_format = dagster_definitions.format_stall_alert

    def recording_format(stall_clock, *, now):
        line = original_format(stall_clock, now=now)
        alerts.append((stall_clock, line))
        return line

    monkeypatch.setattr(common_dagster, "wall_clock", lambda: clock.now)
    monkeypatch.setattr(dagster_definitions, "time", SimpleNamespace(time=lambda: clock.now))
    monkeypatch.setattr(dagster_definitions, "format_stall_alert", recording_format)
    monkeypatch.setattr(dagster_definitions, "_settings", lambda: test_settings)
    monkeypatch.setattr(dagster_definitions, "_RECOVERY_POSITION", ScanPosition())

    instance_cm = DagsterInstance.ephemeral()
    instance = instance_cm.__enter__()
    state = SimpleNamespace(cursor=None, results=[])

    def tick(at: float):
        clock.now = at
        context = build_sensor_context(instance=instance, cursor=state.cursor)
        result = dagster_definitions.worker_recovery(context)
        state.cursor = result.cursor
        state.results.append(result)
        return result

    yield SimpleNamespace(tick=tick, alerts=alerts, state=state, instance=instance)
    instance_cm.__exit__(None, None, None)


def test_sensor_is_built_with_budget_and_stall_alert():
    sensor = dagster_definitions.worker_recovery
    assert sensor.name == "transport_worker_recovery"
    assert sensor.minimum_interval_seconds == 60
    assert sensor.default_status.name == "RUNNING"


async def test_incident_replay_collection_stop_raises_stall_alert(test_settings, sensor_env):
    """2026-09-27: dequeue된 실행이 `StartRun` 60초 timeout으로 모두 실패해 새 수집 행이 생기지 않았다."""
    engine, factory = await _database(test_settings)
    try:
        last_start = now_utc() - timedelta(minutes=25)
        await _add_runs(factory, [
            {"started_at": last_start, "finished_at": last_start, "status": "success", "trigger": trigger}
            for trigger in FIVE_MINUTE_TRIGGERS
        ])
        # sensor는 1분마다 돈다. 첫 실패 뒤 900초 전에는 경보하지 않는다.
        for minute in range(15):
            result = sensor_env.tick(T0 + 60 * minute)
            assert _skip(result).startswith("회수 실패 기록: CollectionStalled")
        assert sensor_env.alerts == []
        sensor_env.tick(T0 + 900)
        assert len(sensor_env.alerts) == 1
        stall_clock, line = sensor_env.alerts[0]
        assert stall_clock.key == "transport_worker_recovery"
        assert stall_clock.last_failure == "CollectionStalled"
        assert line.startswith(f"{STALL_EVENT} key=transport_worker_recovery ")
        assert "stalled_seconds=900" in line
        # 같은 정체는 realert(3600초) 전까지 다시 알리지 않고, 그 뒤에는 다시 알린다.
        sensor_env.tick(T0 + 960)
        assert len(sensor_env.alerts) == 1
        sensor_env.tick(T0 + 900 + 3600)
        assert len(sensor_env.alerts) == 2
        assert '"alerted_at":' in sensor_env.state.cursor
        # 수집이 다시 시작되면 다음 tick이 정체 시계를 지운다.
        now = now_utc()
        await _add_runs(factory, [
            {"started_at": now, "status": "running", "trigger": trigger} for trigger in FIVE_MINUTE_TRIGGERS
        ])
        result = sensor_env.tick(T0 + 900 + 3660)
        assert result.cursor == "stall:null"
        assert _skip(result) == "중단된 실행 기록 0건 회수"
        assert len(sensor_env.alerts) == 2
    finally:
        await engine.dispose()


async def test_healthy_five_minute_collection_never_alerts(test_settings, sensor_env):
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        await _add_runs(factory, [
            {"started_at": now - timedelta(minutes=3), "status": "success", "trigger": trigger}
            for trigger in FIVE_MINUTE_TRIGGERS
        ])
        for minute in range(20):
            assert sensor_env.tick(T0 + 60 * minute).cursor == "stall:null"
        assert sensor_env.alerts == []
    finally:
        await engine.dispose()


def test_database_outage_alerts_with_sqlstate_only(monkeypatch, sensor_env):
    """incident 앞단(08:32Z 공용 PostgreSQL recovery mode): DB 오류가 계속되면 SQLSTATE로 경보한다."""

    class CannotConnectNow(Exception):
        sqlstate = "57P03"

    class Unavailable:
        async def __aenter__(self):
            raise CannotConnectNow("the database system is in recovery mode password=secret")

        async def __aexit__(self, *_exc):
            return False

    class Engine:
        async def dispose(self):
            pass

    monkeypatch.setattr(
        dagster_definitions, "create_engine_and_session_factory",
        lambda *_args, **_kwargs: (Engine(), Unavailable),
    )
    for minute in range(16):
        sensor_env.tick(T0 + 60 * minute)
    assert len(sensor_env.alerts) == 1
    stall_clock, line = sensor_env.alerts[0]
    assert stall_clock.last_failure == "CannotConnectNow:57P03"
    assert "secret" not in line and "secret" not in sensor_env.state.cursor


def test_metadata_outage_alerts(monkeypatch, sensor_env, test_settings):
    import asyncio

    async def seed():
        engine, factory = await _database(test_settings)
        try:
            now = now_utc()
            await _add_runs(factory, [
                {"started_at": now, "heartbeat_at": now, "status": "running", "trigger": "t", "orchestrator_run_id": "x"},
                *[{"started_at": now, "status": "success", "trigger": t} for t in FIVE_MINUTE_TRIGGERS],
            ])
        finally:
            await engine.dispose()

    asyncio.run(seed())

    class Broken:
        def get_run_by_id(self, _owner):
            raise ConnectionError("event log storage unavailable")

    original = dagster_definitions._reconcile_workers
    monkeypatch.setattr(dagster_definitions, "_reconcile_workers",
                        lambda _instance, remaining: original(Broken(), remaining))
    for minute in range(16):
        sensor_env.tick(T0 + 60 * minute)
    assert [stall.last_failure for stall, _ in sensor_env.alerts] == ["RecoveryMetadataUnavailable"]


def test_alert_writer_logs_stable_event_without_raw_text(caplog):
    errors: list[str] = []
    context = SimpleNamespace(log=SimpleNamespace(error=errors.append))
    clock = StallClock(key="transport_worker_recovery", first_failed_at=T0, last_failure="OperationalError:57P01")
    dagster_definitions._alert_stall(context, clock)
    assert len(errors) == 1
    assert errors[0].startswith(f"{STALL_EVENT} key=transport_worker_recovery first_failed_at=")
    assert errors[0].endswith("last_failure=OperationalError:57P01")
    # Dagster UI tick 로그만이 아니라 프로세스 로그(컨테이너 stderr)에도 같은 줄이 나간다.
    assert [r.getMessage() for r in caplog.records if r.name == "app.dagster.recovery"] == errors
    assert format_stall_alert(clock, now=T0 - 5).count("stalled_seconds=0") == 1


# ---------------------------------------------------------------------------
# 서버 측 statement_timeout


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"collector": True}, {"timeout": 10, "command_timeout": 60,
                               "server_settings": {"lock_timeout": "5s", "statement_timeout": "60s"}}),
        ({"collector": True, "statement_timeout_seconds": 10},
         {"timeout": 10, "command_timeout": 10,
          "server_settings": {"lock_timeout": "5s", "statement_timeout": "10s"}}),
        # 회수 sensor 엔진: 접속 상한도 문장 상한(5초)으로 줄어든다.
        ({"collector": True, "statement_timeout_seconds": recovery.RECOVERY_STATEMENT_TIMEOUT_SECONDS},
         {"timeout": 5, "command_timeout": 5,
          "server_settings": {"lock_timeout": "5s", "statement_timeout": "5s"}}),
        ({}, {"server_settings": {"statement_timeout": "120s"}}),
    ],
)
def test_postgres_engines_set_server_statement_timeout(monkeypatch, kwargs, expected):
    captured = {}

    def fake_engine(url, **options):
        captured.update(options)
        return SimpleNamespace(sync_engine=None)

    monkeypatch.setattr(db_session, "create_async_engine", fake_engine)
    db_session.create_engine_and_session_factory("postgresql://u:p@db/x", **kwargs)
    assert captured["connect_args"] == expected


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_statement_timeout_override_must_be_positive_int(bad):
    with pytest.raises(ValueError):
        db_session.create_engine_and_session_factory("postgresql://u:p@db/x", statement_timeout_seconds=bad)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [({"collector": True}, "1min"), ({"collector": True, "statement_timeout_seconds": 10}, "10s"), ({}, "2min")],
)
async def test_postgres_server_applies_statement_timeout(test_settings, kwargs, expected):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 전용")
    from sqlalchemy import text

    engine, factory = create_engine_and_session_factory(test_settings.database_url, **kwargs)
    try:
        async with factory() as session:
            assert await session.scalar(text("SHOW statement_timeout")) == expected
    finally:
        await engine.dispose()


async def test_postgres_server_cancels_statement_past_timeout(test_settings):
    """서버가 실제로 끊는다(클라이언트 timeout이 아니라 SQLSTATE 57014 query_canceled)."""
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 전용")
    from kortravelcommon.pg_errors import pg_error_info
    from sqlalchemy import text

    # API 엔진은 클라이언트 command_timeout이 없으므로 서버의 취소만 남는다.
    engine, factory = create_engine_and_session_factory(test_settings.database_url, statement_timeout_seconds=1)
    try:
        async with factory() as session:
            with pytest.raises(Exception) as raised:
                await session.execute(text("SELECT pg_sleep(3)"))
        info = pg_error_info(raised.value)
        assert info is not None and info.sqlstate == "57014"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 신선도 판정이 보는 trigger가 실제 op·서비스가 저장하는 값과 같은가


async def test_five_minute_triggers_match_what_ops_and_services_store(monkeypatch, test_settings):
    """trigger 이름이 바뀌면 판정은 '행 없음'으로 조용히 꺼진다. 실제 op와 서비스 경로로 대조한다."""
    import asyncio

    from dagster import DagsterInstance

    from app.services.collection import CollectionService
    from app.services.transport_collection import TransportCollectionService

    engine, factory = await _database(test_settings)
    try:
        captured: list[tuple[str, str | None]] = []

        async def fake_run_with_session(_settings, collect, **kwargs):
            captured.append((kwargs["trigger"], kwargs.get("scope")))
            return {"status": "success", "collection_run_id": 1}

        monkeypatch.setattr(dagster_definitions, "_settings", lambda: test_settings)
        monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run_with_session)

        def run_jobs():
            with DagsterInstance.ephemeral() as instance:
                for job in (dagster_definitions.airport_collection_job, dagster_definitions.highway_collection_job):
                    assert job.execute_in_process(instance=instance).success

        await asyncio.to_thread(run_jobs)
        (airport_trigger, _), (highway_trigger, scope) = captured
        assert scope == "highway"

        disabled = test_settings.model_copy(update={"transport_collection_enabled": False})
        async with factory() as session:
            await CollectionService(test_settings).collect(session, trigger=airport_trigger)
        service = TransportCollectionService(disabled)
        try:
            async with factory() as session:
                await service.collect(session, trigger=highway_trigger, scope="highway")
        finally:
            await service.close()
        async with factory() as session:
            stored = set((await session.scalars(select(CollectionRun.trigger))).all())
        assert stored == set(FIVE_MINUTE_TRIGGERS)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# schedule을 일부러 멈춘 경우(점검)는 정체가 아니다


def _set_schedule_state(instance, schedule_name: str, status_name: str, location: str = "kor-travel-transport"):
    from dagster._core.remote_origin import (
        RegisteredCodeLocationOrigin,
        RemoteInstigatorOrigin,
        RemoteRepositoryOrigin,
    )
    from dagster._core.scheduler.instigation import (
        InstigatorState,
        InstigatorStatus,
        InstigatorType,
    )

    origin = RemoteInstigatorOrigin(
        repository_origin=RemoteRepositoryOrigin(
            code_location_origin=RegisteredCodeLocationOrigin(location), repository_name="__repository__"),
        instigator_name=schedule_name,
    )
    instance.add_instigator_state(
        InstigatorState(origin, InstigatorType.SCHEDULE, InstigatorStatus[status_name]))


def test_stopped_schedules_reads_only_this_location_and_needs_every_state_stopped():
    from dagster import DagsterInstance

    with DagsterInstance.ephemeral() as instance:
        assert dagster_definitions._stopped_schedules(instance) == set()
        _set_schedule_state(instance, "airport_collection_job_schedule", "STOPPED")
        _set_schedule_state(instance, "highway_collection_job_schedule", "STOPPED", location="other-tenant")
        assert dagster_definitions._stopped_schedules(instance) == {"airport_collection_job_schedule"}


@pytest.mark.parametrize(("stopped", "alerts"), [
    (("airport_collection_job_schedule", "highway_collection_job_schedule"), 0),
    (("airport_collection_job_schedule",), 1),  # 고속도로는 여전히 예약 중인데 멈췄다
])
async def test_stopped_schedule_is_not_a_stall_but_running_one_still_alerts(
    test_settings, sensor_env, stopped, alerts,
):
    engine, factory = await _database(test_settings)
    try:
        last_start = now_utc() - timedelta(minutes=25)
        await _add_runs(factory, [
            {"started_at": last_start, "finished_at": last_start, "status": "success", "trigger": trigger}
            for trigger in FIVE_MINUTE_TRIGGERS
        ])
        for name in stopped:
            _set_schedule_state(sensor_env.instance, name, "STOPPED")
        for minute in range(16):
            sensor_env.tick(T0 + 60 * minute)
        assert len(sensor_env.alerts) == alerts
        if not alerts:
            # 회수는 그대로 돌고 시계는 비어 있다(경보도 traceback도 없음).
            assert sensor_env.state.cursor == "stall:null"
            assert all(_skip(r) == "중단된 실행 기록 0건 회수" for r in sensor_env.state.results)
        else:
            assert sensor_env.alerts[0][0].last_failure == "CollectionStalled"
    finally:
        await engine.dispose()
