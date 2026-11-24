"""유가 시도 소실 기록과 유가 신선도 경보(2026-11-24 감사 G1-F5·G1-F6).

2026-11-23 08:17Z~11-24 00:17Z T1 주유소 export가 16.6시간 503이었는데 아무 경보가 없었다(회수 sensor의 정체 경보는
5분 수집만 본다). 또 유가 실행이 op 밖에서 죽으면 `_mark_fuel_failure`가 불리지 않아, 직전 성공의 `last_error=None`이
남고 관리자 "재시도"(`retry_failed_fuel=True`)도 호출 유예로 건너뛰었다. 여기서는 (1) 회수 sensor가 결과 없이 끝난
유가 claim에만 '실행 소실'을 남기는지(성공 시각·예약은 그대로), (2) 그 뒤 관리자 재시도가 예약을 옮기지 않고 실행되는지,
(3) 신선도 단계와 경보 줄(고정 event 이름, 단계 변화 즉시·같은 단계 1시간마다)이 맞는지 본다. 자동 추가 유가 run은
만들지 않는다(오피넷 호출 정책은 소유자 결정).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.time_utils import now_utc, serialize_utc
from app.dagster import definitions as dagster_definitions
from app.dagster import recovery
from app.dagster.recovery import (
    FUEL_FRESHNESS_CYCLES,
    FUEL_FRESHNESS_EVENT,
    FUEL_FRESHNESS_REALERT_SECONDS,
    FUEL_TRIGGER,
    FIVE_MINUTE_TRIGGERS,
    LOST_FUEL_ATTEMPT_ERROR,
    FuelFreshness,
    FuelFreshnessAlerts,
    FuelFreshnessReport,
    LostFuelAttempt,
    check_fuel_freshness,
    evaluate_fuel_freshness,
    fuel_freshness_levels,
    fuel_freshness_thresholds,
    reconcile_collection_runs,
    record_lost_fuel_attempt,
)
from app.db.session import create_engine_and_session_factory
from app.models import Base, CollectionRun, TransportCollectionState
from app.service_exports import REFERENCE_STALE_AFTER
from app.services.rest_area_collection import REST_AREA_FUEL_SOURCE
from app.services.transport_collection import OPINET_SOURCE, TransportCollectionService, _fuel_last_attempt_failed
from test_recovery_sensor_stall import T0, TerminalInstance, sensor_env  # noqa: F401 — pytest fixture 재사용
from test_transport_collection import FakeTransportProvider


async def _database(settings):
    engine, factory = create_engine_and_session_factory(settings.database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, factory


async def _add(factory, *rows):
    async with factory() as session:
        for row in rows:
            session.add(row)
        await session.commit()


async def _opinet_state(factory) -> TransportCollectionState | None:
    async with factory() as session:
        return await session.scalar(select(TransportCollectionState).where(
            TransportCollectionState.source == OPINET_SOURCE))


def _state(source=OPINET_SOURCE, **values) -> TransportCollectionState:
    return TransportCollectionState(source=source, updated_at=now_utc(), **values)


def _fuel_run(started_at, status="running", **values) -> CollectionRun:
    return CollectionRun(started_at=started_at, status=status, trigger=FUEL_TRIGGER, **values)


# ---------------------------------------------------------------------------
# 신선도 단계


def test_thresholds_are_two_cycles_and_eighty_percent_of_the_export_stale_threshold():
    assert fuel_freshness_thresholds(OPINET_SOURCE) == (timedelta(hours=16), timedelta(hours=19, minutes=12))
    assert fuel_freshness_thresholds(REST_AREA_FUEL_SOURCE) == (timedelta(hours=8), timedelta(hours=9, minutes=36))


def test_critical_threshold_follows_the_export_stale_threshold(monkeypatch):
    # export 기준이 바뀌면(예: 503 틈을 닫으려 늘리면) 위험 기준도 같이 바뀐다 — 경보가 503보다 늦어지지 않게.
    monkeypatch.setitem(REFERENCE_STALE_AFTER, OPINET_SOURCE, timedelta(hours=30))
    assert fuel_freshness_thresholds(OPINET_SOURCE)[1] == timedelta(hours=24)


def test_fuel_freshness_cycles_follow_the_schedules():
    """경고 기준(2주기)은 정기 schedule 주기에서 온다. cron이 바뀌면 `FUEL_FRESHNESS_CYCLES`도 고쳐야 한다."""
    crons = {schedule.job_name: schedule.cron_schedule for schedule in dagster_definitions.definitions.schedules}
    assert crons["fuel_collection_job"] == "0 */8 * * *"
    assert crons["rest_area_fuel_price_collection_job"] == "25 */4 * * *"
    assert FUEL_FRESHNESS_CYCLES == {OPINET_SOURCE: timedelta(hours=8), REST_AREA_FUEL_SOURCE: timedelta(hours=4)}


@pytest.mark.parametrize(("source", "age", "failed", "level"), [
    (OPINET_SOURCE, timedelta(hours=15), True, "ok"),  # 실패 1회(8h 남짓)는 경보하지 않는다
    (OPINET_SOURCE, timedelta(hours=17), True, "warning"),  # 연속 2회 실패 — 다음 실패면 export 503
    (OPINET_SOURCE, timedelta(hours=17), False, "ok"),  # 진행 중이거나 막 성공한 시도
    (OPINET_SOURCE, timedelta(hours=20), False, "critical"),  # 수집이 멈춰도(실패 기록 없음) 잡는다
    (OPINET_SOURCE, timedelta(hours=20), True, "critical"),
    (REST_AREA_FUEL_SOURCE, timedelta(hours=9), True, "warning"),
    (REST_AREA_FUEL_SOURCE, timedelta(hours=9), False, "ok"),
    (REST_AREA_FUEL_SOURCE, timedelta(hours=10), False, "critical"),
])
def test_fuel_freshness_levels(source, age, failed, level):
    now = now_utc()
    last_success = now - age
    state = _state(
        source, last_success_at=last_success, last_started_at=now - timedelta(minutes=30),
        last_error="x" if failed else None,
    )
    result = evaluate_fuel_freshness(source, state, now=now)
    assert result is not None
    assert (result.level, result.last_attempt_failed) == (level, failed)
    assert result.age_seconds == int(age.total_seconds())


def test_no_success_history_is_not_judged():
    now = now_utc()
    assert evaluate_fuel_freshness(OPINET_SOURCE, None, now=now) is None
    assert evaluate_fuel_freshness(OPINET_SOURCE, _state(last_error="x", last_started_at=now), now=now) is None


async def test_freshness_levels_read_both_fuel_sources(test_settings):
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        assert await fuel_freshness_levels(factory, now=now) == []  # 새 DB는 판단하지 않는다
        await _add(
            factory,
            _state(OPINET_SOURCE, last_success_at=now - timedelta(hours=17), last_started_at=now - timedelta(hours=1),
                   last_error="Opinet browser resource policy failed"),
            _state(REST_AREA_FUEL_SOURCE, last_success_at=now - timedelta(hours=1), last_started_at=now - timedelta(hours=1)),
            _state("krex_traffic_flow", last_success_at=now - timedelta(days=3)),  # 유가가 아닌 원천은 보지 않는다
        )
        levels = {item.source: item.level for item in await fuel_freshness_levels(factory, now=now)}
        assert levels == {OPINET_SOURCE: "warning", REST_AREA_FUEL_SOURCE: "ok"}
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 유가 시도 소실 기록


async def test_lost_run_closed_by_recovery_records_a_failed_attempt_without_touching_success_or_reservation(test_settings):
    """op 밖에서 죽은 유가 run: 회수가 run 행을 failed로 닫은 다음 tick에 상태 행에도 실패를 남긴다."""
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        claimed = now - timedelta(hours=1)
        last_success = now - timedelta(hours=9)
        next_due = claimed + timedelta(hours=7, minutes=45)
        await _add(
            factory,
            _state(last_success_at=last_success, last_started_at=claimed, next_due_at=next_due),
            _fuel_run(claimed - timedelta(seconds=2), heartbeat_at=claimed, orchestrator_run_id="dead"),
        )
        # 회수 전: 주인 실행이 아직 running이라 건드리지 않는다(정상 수집은 1~2시간 이 상태다).
        assert await record_lost_fuel_attempt(factory) is None
        assert (await _opinet_state(factory)).last_error is None
        assert await reconcile_collection_runs(factory, TerminalInstance()) == 1
        lost = await record_lost_fuel_attempt(factory)
        assert isinstance(lost, LostFuelAttempt)
        assert lost.last_started_at == serialize_utc(claimed)
        state = await _opinet_state(factory)
        assert state.last_error == LOST_FUEL_ATTEMPT_ERROR
        assert serialize_utc(state.last_success_at) == serialize_utc(last_success)
        assert serialize_utc(state.next_due_at) == serialize_utc(next_due)
        assert serialize_utc(state.last_started_at) == serialize_utc(claimed)
        # 관리자 재시도와 신선도 판정이 "마지막 시도 실패"로 본다.
        assert _fuel_last_attempt_failed(state)
        # 한 번만 남긴다(CAS: 오류가 이미 있으면 0행).
        assert await record_lost_fuel_attempt(factory) is None
    finally:
        await engine.dispose()


async def test_failure_record_that_never_committed_is_also_recorded(test_settings):
    """실패 기록 commit 자체가 실패한 경우: 실행 행은 failed인데 상태 행에는 오류가 없다."""
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        claimed = now - timedelta(hours=2)
        await _add(
            factory,
            _state(last_success_at=now - timedelta(hours=10), last_started_at=claimed),
            _fuel_run(claimed - timedelta(seconds=1), status="failed", finished_at=now - timedelta(hours=1),
                      error_message="collection cancelled"),
        )
        assert await record_lost_fuel_attempt(factory) is not None
        assert (await _opinet_state(factory)).last_error == LOST_FUEL_ATTEMPT_ERROR
    finally:
        await engine.dispose()


@pytest.mark.parametrize("case", [
    "succeeded",          # 마지막 시도가 성공했다
    "already_failed",     # op가 실패를 이미 기록했다(원래 문장을 지키고 덮지 않는다)
    "owner_running",      # 정상 수집 중
    "owner_finished_ok",  # 주인이 정상 종료했다(성공 시각이 claim보다 이른 값이어도 소실이 아니다)
    "resumer_running",    # 주인은 끝났지만 뒤의 체크포인트 저장 재개 실행이 돌고 있다
    "no_dagster_owner",   # claim 직전에 시작한 Dagster 유가 실행이 없다(in-process·수동 claim)
    "never_claimed",      # 상태 행에 claim이 없다
])
async def test_lost_attempt_is_not_recorded_when_the_claim_has_an_outcome_or_a_live_run(test_settings, case):
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        claimed = now - timedelta(hours=1)
        state = {"last_success_at": now - timedelta(hours=9), "last_started_at": claimed, "last_error": None}
        runs = [_fuel_run(claimed - timedelta(seconds=1), status="failed")]
        if case == "succeeded":
            state["last_success_at"] = claimed + timedelta(minutes=50)
        elif case == "already_failed":
            state["last_error"] = "Opinet browser resource policy failed"
        elif case == "owner_running":
            runs = [_fuel_run(claimed - timedelta(seconds=1))]
        elif case == "owner_finished_ok":
            runs = [_fuel_run(claimed - timedelta(seconds=1), status="success")]
        elif case == "resumer_running":
            runs.append(_fuel_run(claimed + timedelta(minutes=30)))
        elif case == "no_dagster_owner":
            runs = [_fuel_run(claimed - timedelta(hours=8), status="success"),
                    CollectionRun(started_at=claimed, status="failed", trigger="transport_fuel_scheduler")]
        elif case == "never_claimed":
            state["last_started_at"] = None
        await _add(factory, _state(**state), *runs)
        before = await _opinet_state(factory)
        assert await record_lost_fuel_attempt(factory) is None
        after = await _opinet_state(factory)
        assert after.last_error == before.last_error
        assert after.last_success_at == before.last_success_at
    finally:
        await engine.dispose()


async def test_a_later_claim_moves_ownership_to_the_later_run(test_settings):
    """앞선 실행이 끝났어도 그 뒤 새 claim을 한 실행이 돌고 있으면 그 claim은 살아 있다."""
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        first = now - timedelta(hours=9)
        second = now - timedelta(minutes=20)
        await _add(
            factory,
            _state(last_success_at=now - timedelta(hours=17), last_started_at=second),
            _fuel_run(first - timedelta(seconds=1), status="failed"),
            _fuel_run(second - timedelta(seconds=1)),
        )
        assert await record_lost_fuel_attempt(factory) is None
    finally:
        await engine.dispose()


async def test_admin_retry_runs_after_a_lost_attempt_and_keeps_the_regular_reservation(test_settings):
    """G1-F5 회귀: 잃은 시도 뒤의 관리자 재시도는 예전에는 호출 유예로 건너뛰었다."""
    settings = test_settings.model_copy(update={"transport_collection_enabled": True})
    engine, factory = await _database(settings)
    provider = FakeTransportProvider()
    calls = {"count": 0}
    real_collect = provider.collect_fuel

    async def collect_fuel():
        calls["count"] += 1
        return await real_collect()

    provider.collect_fuel = collect_fuel
    service = TransportCollectionService(settings, provider)
    try:
        async with factory() as session:
            first = await service.collect(session, trigger="dagster_fuel", scope="fuel")
        assert first["status"] == "success" and calls["count"] == 1
        # 다음 정기 claim 뒤 실행이 op 밖에서 죽었다: 시작·예약만 남고 결과가 없다. 회수가 실행 행을 failed로 닫았다.
        claimed = now_utc()
        reservation = claimed + provider.next_fuel_interval()
        async with factory() as session:
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE))
            state.last_started_at, state.next_due_at = claimed, reservation
            session.add(_fuel_run(claimed, status="failed", orchestrator_run_id="dead",
                                  error_message="Dagster 실행 종료 또는 소유권 유실을 확인하여 수집 기록을 회수했습니다."))
            await session.commit()
        async with factory() as session:
            skipped = await service.collect(session, trigger="dagster_fuel", scope="fuel", retry_failed_fuel=True)
        assert skipped["status"] == "skipped" and calls["count"] == 1  # 고치기 전의 동작: 호출 유예로 건너뜀

        assert await record_lost_fuel_attempt(factory) is not None
        provider.observed_at = now_utc()  # 새 브라우저 수집의 수집 시각(대역은 생성 시각에 고정돼 있다)
        async with factory() as session:
            retried = await service.collect(session, trigger="dagster_fuel", scope="fuel", retry_failed_fuel=True)
        assert retried["status"] == "success" and calls["count"] == 2
        state = await _opinet_state(factory)
        assert state.last_error is None
        # 재시도는 정기 예약(다음 tick)을 옮기지 않는다.
        assert serialize_utc(state.next_due_at) == serialize_utc(reservation)
        # 성공 뒤에는 다시 소실로 보지 않는다(대역의 수집 시각은 고정이라 claim보다 이르다 — 주인 상태로 가린다).
        assert serialize_utc(state.last_success_at) < serialize_utc(state.last_started_at)
        assert await record_lost_fuel_attempt(factory) is None
    finally:
        await service.close()
        await engine.dispose()


async def test_fuel_trigger_matches_what_the_op_and_service_store(monkeypatch, test_settings):
    """trigger 이름이 바뀌면 소실 판정은 '주인 없음'으로 조용히 꺼진다. 실제 op 경로와 서비스로 대조한다."""
    engine, factory = await _database(test_settings)
    captured: list[tuple[str, str | None]] = []

    async def fake_run_with_session(_settings, _collect, **kwargs):
        captured.append((kwargs["trigger"], kwargs.get("scope")))
        return {"status": "success", "collection_run_id": 1}

    monkeypatch.setattr(dagster_definitions, "_run_with_session", fake_run_with_session)
    try:
        await dagster_definitions._collect_transport_in_one_loop(test_settings, "fuel")
        [(trigger, scope)] = captured
        assert scope == "fuel"
        disabled = test_settings.model_copy(update={"transport_collection_enabled": False})
        service = TransportCollectionService(disabled)
        try:
            async with factory() as session:
                await service.collect(session, trigger=trigger, scope="fuel")
        finally:
            await service.close()
        async with factory() as session:
            assert set((await session.scalars(select(CollectionRun.trigger))).all()) == {FUEL_TRIGGER}
    finally:
        await engine.dispose()


async def test_check_failure_is_reported_without_raising():
    class Broken:
        async def __aenter__(self):
            raise ConnectionError("db down password=secret")

        async def __aexit__(self, *_exc):
            return False

    report = FuelFreshnessReport()
    await check_fuel_freshness(Broken, report)
    assert report.failure == "ConnectionError"
    assert report.levels == [] and report.lost_attempt is None and report.checked is False


# ---------------------------------------------------------------------------
# 경보 줄


def _level(level: str, source=OPINET_SOURCE, failed=True) -> FuelFreshness:
    now = now_utc()
    warning_after, critical_after = fuel_freshness_thresholds(source)
    return FuelFreshness(source=source, level=level, age_seconds=61_200, last_success_at=now - timedelta(hours=17),
                         last_attempt_failed=failed, warning_after=warning_after, critical_after=critical_after)


def test_alert_lines_dedupe_same_level_and_report_changes_immediately():
    alerts = FuelFreshnessAlerts()
    lines = alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("warning")]), now=T0)
    assert len(lines) == 1
    severity, line = lines[0]
    assert severity == logging.WARNING
    assert line.startswith(f"{FUEL_FRESHNESS_EVENT}.warning source={OPINET_SOURCE} age_seconds=61200 ")
    assert "last_attempt_failed=true warning_after_seconds=57600 critical_after_seconds=69120" in line
    # 같은 단계는 재경보 간격 전에는 다시 남기지 않는다.
    assert alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("warning")]), now=T0 + 60) == []
    realert = T0 + FUEL_FRESHNESS_REALERT_SECONDS
    assert len(alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("warning")]), now=realert)) == 1
    # 단계가 오르면 바로 남긴다(위험은 error 수준).
    [(severity, line)] = alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("critical")]), now=T0 + 3660)
    assert severity == logging.ERROR and line.startswith(f"{FUEL_FRESHNESS_EVENT}.critical ")
    # 판정 실패 tick은 단계 기억을 바꾸지 않는다(회복으로 오인하지 않음).
    [(_, failed)] = alerts.lines(FuelFreshnessReport(failure="TimeoutError"), now=T0 + 3720)
    assert failed == f"{FUEL_FRESHNESS_EVENT}.check_failed error=TimeoutError"
    assert alerts.lines(FuelFreshnessReport(failure="TimeoutError"), now=T0 + 3780) == []
    assert alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("critical")]), now=T0 + 3840) == []
    # 정상으로 돌아오면 회복 줄을 한 번 남기고, 그 뒤 정상 tick은 조용하다.
    [(_, recovered)] = alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("ok", failed=False)]), now=T0 + 3900)
    assert recovered.startswith(f"{FUEL_FRESHNESS_EVENT}.recovered source={OPINET_SOURCE} ")
    assert recovered.endswith("previous=critical")
    assert alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("ok", failed=False)]), now=T0 + 3960) == []


def test_tick_without_a_fuel_check_keeps_the_alert_memory():
    """점검을 못 한 tick(예산 부족·앞 단계 장애로 tick이 먼저 끝남)의 빈 결과는 "판단 대상 없음"이 아니다."""
    alerts = FuelFreshnessAlerts()
    assert len(alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("warning")]), now=T0)) == 1
    assert alerts.lines(FuelFreshnessReport(), now=T0 + 60) == []
    # 기억이 남아 있어 같은 단계를 곧바로 다시 남기지 않고, 이어진 회복도 회복 줄로 남긴다.
    assert alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("warning")]), now=T0 + 120) == []
    [(_, recovered)] = alerts.lines(
        FuelFreshnessReport(checked=True, levels=[_level("ok", failed=False)]), now=T0 + 180)
    assert recovered.startswith(f"{FUEL_FRESHNESS_EVENT}.recovered ") and recovered.endswith("previous=warning")
    # 판정까지 마친 tick에서 상태 행이 사라진 원천은 기억에서 지운다.
    assert alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("critical")]), now=T0 + 240) != []
    assert alerts.lines(FuelFreshnessReport(checked=True), now=T0 + 300) == []
    assert len(alerts.lines(FuelFreshnessReport(checked=True, levels=[_level("critical")]), now=T0 + 360)) == 1


def test_lost_attempt_line_has_fixed_fields_only():
    started = now_utc()
    report = FuelFreshnessReport(lost_attempt=LostFuelAttempt(collection_run_id=42, last_started_at=started))
    [(severity, line)] = FuelFreshnessAlerts().lines(report, now=T0)
    assert severity == logging.WARNING
    assert line == (f"{FUEL_FRESHNESS_EVENT}.lost_attempt source={OPINET_SOURCE} collection_run_id=42 "
                    f"last_started_at={started.isoformat()}")


# ---------------------------------------------------------------------------
# 실제 회수 sensor tick


async def test_sensor_records_lost_attempt_and_warns_without_new_runs_or_a_stall(
    test_settings, sensor_env, caplog,  # noqa: F811
):
    caplog.set_level(logging.WARNING, logger="app.dagster.recovery")
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        claimed = now - timedelta(hours=6)
        await _add(
            factory,
            *[CollectionRun(started_at=now, status="success", trigger=trigger) for trigger in FIVE_MINUTE_TRIGGERS],
            # 연속 실패 1회 뒤의 시도가 run 소실로 끝났다(Dagster run 기록도 없음 → 5시간 grace 뒤 회수).
            _state(last_success_at=now - timedelta(hours=17), last_started_at=claimed),
            _fuel_run(claimed - timedelta(seconds=1), heartbeat_at=claimed, orchestrator_run_id="gone"),
        )

        def fuel_lines():
            return [r.getMessage() for r in caplog.records
                    if r.name == "app.dagster.recovery" and r.getMessage().startswith(FUEL_FRESHNESS_EVENT)]

        # tick 1: 주인 실행이 아직 running이라 소실로 보지 않고, 실패 기록이 없으니 경고도 아니다. 회수가 실행 행을 닫는다.
        result = sensor_env.tick(T0)
        assert result.cursor == "stall:null"
        assert fuel_lines() == []
        # tick 2: 소실을 기록하고, 그 결과 "마지막 시도 실패 + 16시간 초과"라 경고한다. 정체가 아니다.
        result = sensor_env.tick(T0 + 60)
        assert result.cursor == "stall:null"
        lines = fuel_lines()
        assert [line.split(" ", 1)[0] for line in lines] == [
            f"{FUEL_FRESHNESS_EVENT}.lost_attempt", f"{FUEL_FRESHNESS_EVENT}.warning"]
        assert (await _opinet_state(factory)).last_error == LOST_FUEL_ATTEMPT_ERROR
        # tick 3: 같은 단계는 다시 남기지 않는다. 새 유가 run을 만들지 않는다(실행 행은 그대로 하나).
        sensor_env.tick(T0 + 120)
        assert len(fuel_lines()) == 2
        async with factory() as session:
            fuel_runs = (await session.scalars(select(CollectionRun.status).where(
                CollectionRun.trigger == FUEL_TRIGGER))).all()
        assert fuel_runs == ["failed"]
        assert sensor_env.instance.get_runs() == []
    finally:
        await engine.dispose()


async def test_sensor_keeps_recovering_when_the_fuel_check_fails(
    test_settings, monkeypatch, sensor_env, caplog,  # noqa: F811
):
    caplog.set_level(logging.WARNING, logger="app.dagster.recovery")
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        await _add(
            factory,
            *[CollectionRun(started_at=now, status="success", trigger=trigger) for trigger in FIVE_MINUTE_TRIGGERS],
            # Dagster 기록이 없는 실행 — 5시간 grace 뒤 회수 대상이다.
            CollectionRun(started_at=now - timedelta(hours=6), heartbeat_at=now - timedelta(hours=6), status="running",
                          trigger="t", orchestrator_run_id="gone"),
        )

        async def broken(*_args, **_kwargs):
            raise RuntimeError("unexpected password=secret")

        monkeypatch.setattr(recovery, "record_lost_fuel_attempt", broken)
        result = sensor_env.tick(T0)
        # 유가 점검의 실패는 회수·정체 판정을 막지 않는다(정체 시계도 건드리지 않는다).
        assert result.cursor == "stall:null"
        assert getattr(result.skip_reason, "skip_message", result.skip_reason) == "중단된 실행 기록 1건 회수"
        assert sensor_env.alerts == []
        messages = [r.getMessage() for r in caplog.records if r.name == "app.dagster.recovery"]
        assert messages == [f"{FUEL_FRESHNESS_EVENT}.check_failed error=RuntimeError"]
    finally:
        await engine.dispose()


def test_report_writer_never_fails_the_tick(monkeypatch):
    class Exploding:
        def lines(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(dagster_definitions, "_FUEL_FRESHNESS_ALERTS", Exploding())
    context = SimpleNamespace(log=SimpleNamespace(warning=lambda *_: None, error=lambda *_: None))
    dagster_definitions._report_fuel_freshness(context, FuelFreshnessReport())
