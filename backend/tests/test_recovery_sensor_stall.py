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


def test_step_reserve_keeps_every_step_inside_the_tick_budget():
    # 한 단계(metadata 10초 + 문장 10초)를 시작할 때 예산이 남아 있어야 끊긴 thread가 생기지 않는다.
    assert recovery.STEP_RESERVE_SECONDS == recovery.METADATA_TIMEOUT_SECONDS + recovery.RECOVERY_STATEMENT_TIMEOUT_SECONDS
    assert recovery.STEP_RESERVE_SECONDS < recovery.RECOVERY_BUDGET_SECONDS
    # 문장 상한은 예산보다 짧고, 예산은 Dagster sensor 평가 상한(60초)보다 짧다.
    assert recovery.RECOVERY_STATEMENT_TIMEOUT_SECONDS < recovery.RECOVERY_BUDGET_SECONDS < 60


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

    yield SimpleNamespace(tick=tick, alerts=alerts, state=state)
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


def test_alert_writer_logs_stable_event_without_raw_text():
    errors: list[str] = []
    context = SimpleNamespace(log=SimpleNamespace(error=errors.append))
    clock = StallClock(key="transport_worker_recovery", first_failed_at=T0, last_failure="OperationalError:57P01")
    dagster_definitions._alert_stall(context, clock)
    assert len(errors) == 1
    assert errors[0].startswith(f"{STALL_EVENT} key=transport_worker_recovery first_failed_at=")
    assert errors[0].endswith("last_failure=OperationalError:57P01")
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
