"""유가 시도 소실 기록과 유가 신선도 경보(2026-11-24 감사 G1-F5·G1-F6, 적대적 리뷰 반영).

2026-11-23 08:17Z~11-24 00:17Z T1 주유소 export가 16.6시간 503이었는데 아무 경보가 없었다(회수 sensor의 정체 경보는
5분 수집만 본다). 또 유가 실행이 op 밖에서 죽으면 `_mark_fuel_failure`가 불리지 않아, 직전 성공의 `last_error=None`이
남고 관리자 "재시도"(`retry_failed_fuel=True`)도 호출 유예로 건너뛰었다. 여기서는 다음을 본다.

1. 회수 sensor가 결과 없이 끝난 유가 claim에만 '실행 소실'을 남기는지(성공 시각·예약은 그대로, 경합에 안전한지)
2. 관리자 재시도가 sensor 기록 전이든 뒤든 예약을 옮기지 않고 실행되는지
3. 신선도 단계(진행 중 실행은 실패로 세지 않음, 만료 단계)와 경보 줄(고정 event 이름·cause·기억은 기록 뒤 반영)
4. T1·T4·공개·관리 상태가 소실 기록을 실패 1회와 같게 보는지

자동 추가 유가 run은 만들지 않는다(오피넷 호출 정책은 소유자 결정).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text, update

from app.core.time_utils import now_utc, serialize_utc
from app.dagster import definitions as dagster_definitions
from app.dagster import recovery
from app.dagster.recovery import (
    FIVE_MINUTE_TRIGGERS,
    FUEL_FRESHNESS_CYCLES,
    FUEL_FRESHNESS_EVENT,
    FUEL_FRESHNESS_REALERT_SECONDS,
    FUEL_LEVEL_STEP_SECONDS,
    FUEL_LOST_STEP_SECONDS,
    FUEL_TRIGGER,
    LOST_FUEL_ATTEMPT_ERROR,
    FuelFreshness,
    FuelFreshnessAlerts,
    FuelFreshnessReport,
    LostFuelAttempt,
    check_fuel_freshness,
    evaluate_fuel_freshness,
    fuel_freshness_levels,
    fuel_freshness_snapshot,
    fuel_freshness_thresholds,
    reconcile_collection_runs,
    record_lost_fuel_attempt,
)
from app.db.session import create_engine_and_session_factory
from app.models import Base, CollectionRun, TransportCollectionState
from app.service_exports import REFERENCE_STALE_AFTER
from app.services.rest_area_collection import REST_AREA_FUEL_SOURCE, REST_AREA_FUEL_TRIGGER
from app.services.transport_collection import (
    OPINET_SOURCE,
    TRANSPORT_COLLECTION_ADVISORY_LOCK_KEY,
    TransportCollectionService,
    _fuel_last_attempt_failed,
)
from test_recovery_sensor_stall import T0, TerminalInstance, sensor_env  # noqa: F401 — pytest fixture 재사용
from test_service_exports import HEADERS, _run, _seed_fuel_station, _set_state, export_client  # noqa: F401
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


def _postgres(settings) -> bool:
    return settings.database_url.startswith("postgresql")


def _emit(alerts: FuelFreshnessAlerts, report: FuelFreshnessReport, now: float) -> list[str]:
    """줄을 만들고 모두 남긴 것으로 기억한다(호출자 `_report_fuel_freshness`와 같은 순서)."""
    lines = alerts.lines(report, now=now)
    for line in lines:
        alerts.commit(line)
    return [line.text for line in lines]


# ---------------------------------------------------------------------------
# 신선도 단계


def test_thresholds_are_two_cycles_eighty_percent_and_the_export_stale_threshold():
    for source, cycle in FUEL_FRESHNESS_CYCLES.items():
        export = REFERENCE_STALE_AFTER[source]
        assert fuel_freshness_thresholds(source) == (2 * cycle, 0.8 * export, export)
    # 현재 운영 값(런북 표의 기준). export 기준을 바꾸면 위험·만료가 같이 바뀐다(아래 테스트).
    assert fuel_freshness_thresholds(OPINET_SOURCE)[0] == timedelta(hours=16)
    assert fuel_freshness_thresholds(REST_AREA_FUEL_SOURCE)[:2] == (timedelta(hours=8), timedelta(hours=9, minutes=36))


def test_critical_and_expired_follow_the_export_stale_threshold(monkeypatch):
    # export 기준이 바뀌면(예: 503 틈을 닫으려 늘리면) 위험·만료 기준도 같이 바뀐다 — 경보가 503보다 늦어지지 않게.
    monkeypatch.setitem(REFERENCE_STALE_AFTER, OPINET_SOURCE, timedelta(hours=30))
    assert fuel_freshness_thresholds(OPINET_SOURCE)[1:] == (timedelta(hours=24), timedelta(hours=30))


def test_recovery_module_does_not_import_the_export_routers():
    """Dagster 프로세스는 FastAPI export router 모듈을 불러오지 않는다(위험 기준은 함수 안에서 늦게 읽는다)."""
    import subprocess
    import sys

    code = ("import sys, app.dagster.definitions; "
            "raise SystemExit(1 if 'app.service_exports' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_fuel_freshness_cycles_and_schedules_follow_the_definitions():
    """경고 기준(2주기)은 정기 schedule 주기에서 온다. cron이 바뀌면 `FUEL_FRESHNESS_CYCLES`도 고쳐야 한다."""
    schedules = {schedule.job_name: schedule for schedule in dagster_definitions.definitions.schedules}
    assert schedules["fuel_collection_job"].cron_schedule == "0 */8 * * *"
    assert schedules["rest_area_fuel_price_collection_job"].cron_schedule == "25 */4 * * *"
    assert FUEL_FRESHNESS_CYCLES == {OPINET_SOURCE: timedelta(hours=8), REST_AREA_FUEL_SOURCE: timedelta(hours=4)}
    # STOPPED 판정이 보는 schedule 이름이 실제 이름과 같다(다르면 STOPPED여도 계속 경보한다).
    names = {schedule.name for schedule in dagster_definitions.definitions.schedules}
    assert set(dagster_definitions._FUEL_SCHEDULES.values()) <= names


@pytest.mark.parametrize(("source", "age", "failed", "in_flight", "level", "cause"), [
    (OPINET_SOURCE, timedelta(hours=15), True, False, "ok", "failed"),  # 실패 1회(8h 남짓)는 경보하지 않는다
    (OPINET_SOURCE, timedelta(hours=17), True, False, "warning", "failed"),  # 연속 2회 실패 — 다음 실패면 export 503
    # 실패 1회 뒤 다음 정기 실행이 수집 중: claim은 이전 오류를 지우지 않지만 진행 중이면 실패로 세지 않는다(P2-1).
    (OPINET_SOURCE, timedelta(hours=17), True, True, "ok", "running"),
    (OPINET_SOURCE, timedelta(hours=17), False, False, "ok", "none"),
    # 위험·만료 나이는 export 기준(24h, 503 틈을 닫으려 27.5h로 늘려도)의 80%~100% 사이·바깥에 둔다.
    (OPINET_SOURCE, timedelta(hours=23), False, False, "critical", "none"),  # 수집이 멈춰도(실패 기록 없음) 잡는다
    (OPINET_SOURCE, timedelta(hours=23), True, True, "critical", "running"),  # 위험은 진행 중이어도 남긴다
    (OPINET_SOURCE, timedelta(hours=30), True, False, "expired", "failed"),  # export가 지금 503
    (REST_AREA_FUEL_SOURCE, timedelta(hours=9), True, False, "warning", "failed"),
    (REST_AREA_FUEL_SOURCE, timedelta(hours=9), True, True, "ok", "running"),
    (REST_AREA_FUEL_SOURCE, timedelta(hours=10), False, False, "critical", "none"),
    (REST_AREA_FUEL_SOURCE, timedelta(hours=13), False, False, "expired", "none"),
])
def test_fuel_freshness_levels(source, age, failed, in_flight, level, cause):
    now = now_utc()
    state = _state(
        source, last_success_at=now - age, last_started_at=now - timedelta(minutes=30),
        last_error="x" if failed else None,
    )
    result = evaluate_fuel_freshness(source, state, now=now, in_flight=in_flight)
    assert result is not None
    assert (result.level, result.cause, result.last_attempt_failed) == (level, cause, failed and not in_flight)
    assert result.age_seconds == int(age.total_seconds())


def test_lost_cause_is_reported_as_lost():
    now = now_utc()
    state = _state(last_success_at=now - timedelta(hours=17), last_started_at=now - timedelta(hours=1),
                   last_error=LOST_FUEL_ATTEMPT_ERROR)
    assert evaluate_fuel_freshness(OPINET_SOURCE, state, now=now).cause == "lost"


def test_no_success_history_is_not_judged():
    now = now_utc()
    assert evaluate_fuel_freshness(OPINET_SOURCE, None, now=now) is None
    assert evaluate_fuel_freshness(OPINET_SOURCE, _state(last_error="x", last_started_at=now), now=now) is None


async def test_freshness_levels_read_both_fuel_sources_and_their_running_runs(test_settings):
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        assert await fuel_freshness_levels(factory, now=now) == []  # 새 DB는 판단하지 않는다
        await _add(
            factory,
            _state(OPINET_SOURCE, last_success_at=now - timedelta(hours=17), last_started_at=now - timedelta(hours=1),
                   last_error="Opinet browser resource policy failed"),
            _state(REST_AREA_FUEL_SOURCE, last_success_at=now - timedelta(hours=9),
                   last_started_at=now - timedelta(minutes=5), last_error="TimeoutError"),
            _state("krex_traffic_flow", last_success_at=now - timedelta(days=3)),  # 유가가 아닌 원천은 보지 않는다
        )
        levels = {item.source: item.level for item in await fuel_freshness_levels(factory, now=now)}
        assert levels == {OPINET_SOURCE: "warning", REST_AREA_FUEL_SOURCE: "warning"}
        # 두 원천 모두 다음 실행이 진행 중이면 실패로 세지 않는다. 다른 trigger·24시간 밖의 매달린 행은 세지 않는다.
        await _add(
            factory,
            _fuel_run(now - timedelta(minutes=50)),
            CollectionRun(started_at=now - timedelta(minutes=5), status="running", trigger=REST_AREA_FUEL_TRIGGER),
            CollectionRun(started_at=now - timedelta(minutes=5), status="running", trigger="transport_dagster_highway"),
        )
        causes = {item.source: (item.level, item.cause) for item in await fuel_freshness_levels(factory, now=now)}
        assert causes == {OPINET_SOURCE: ("ok", "running"), REST_AREA_FUEL_SOURCE: ("ok", "running")}
        async with factory() as session:
            await session.execute(update(CollectionRun).where(CollectionRun.trigger == FUEL_TRIGGER)
                                  .values(started_at=now - timedelta(hours=25)))
            await session.commit()
        assert {item.source: item.cause for item in await fuel_freshness_levels(factory, now=now)}[OPINET_SOURCE] == "failed"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 유가 시도 소실 기록


async def test_lost_run_closed_by_recovery_records_a_failed_attempt_without_touching_success_or_reservation(test_settings):
    """op 밖에서 죽은 유가 run: 회수가 run 행을 failed로 닫으면 상태 행에도 실패를 남긴다."""
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
        assert (lost.orchestrator_run_id, lost.last_started_at) == ("dead", serialize_utc(claimed))
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
    "succeeded",            # 마지막 시도가 성공했다
    "already_failed",       # op가 실패를 이미 기록했다(원래 문장을 지키고 덮지 않는다)
    "owner_running",        # 정상 수집 중
    "owner_finished_ok",    # 주인이 정상 종료했다(성공 시각이 claim보다 이른 값이어도 소실이 아니다)
    "resumer_running",      # 주인은 끝났지만 뒤의 체크포인트 저장 재개 실행이 돌고 있다
    "older_run_running",    # 주인보다 먼저 시작한 유가 실행이 아직 running(행 순서와 무관하게 진행 중이면 보류)
    "no_dagster_owner",     # claim 직전에 시작한 Dagster 유가 실행이 없다(in-process·수동 claim)
    "never_claimed",        # 상태 행에 claim이 없다
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
        elif case == "older_run_running":
            runs.insert(0, _fuel_run(claimed - timedelta(hours=3)))
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


async def _service_with_lost_claim(settings, factory, *, owner_status: str):
    """성공 1회 뒤 다음 정기 claim의 실행이 op 밖에서 죽은 상태(시작·예약만 남고 결과가 없다)를 만든다."""
    provider = FakeTransportProvider()
    calls = {"count": 0}
    real_collect = provider.collect_fuel

    async def collect_fuel():
        calls["count"] += 1
        return await real_collect()

    provider.collect_fuel = collect_fuel
    service = TransportCollectionService(settings, provider)
    async with factory() as session:
        first = await service.collect(session, trigger="dagster_fuel", scope="fuel")
    assert first["status"] == "success" and calls["count"] == 1
    claimed = now_utc()
    reservation = claimed + provider.next_fuel_interval()
    async with factory() as session:
        state = await session.scalar(select(TransportCollectionState).where(
            TransportCollectionState.source == OPINET_SOURCE))
        state.last_started_at, state.next_due_at = claimed, reservation
        session.add(_fuel_run(claimed, status=owner_status, orchestrator_run_id="dead"))
        await session.commit()
    provider.observed_at = now_utc()  # 새 브라우저 수집의 수집 시각(대역은 생성 시각에 고정돼 있다)
    return service, calls, reservation


async def test_admin_retry_right_after_the_run_was_closed_runs_before_the_sensor_records(test_settings):
    """G1-F5 회귀(James #1·Popper P2-4): 회수가 run 행을 닫은 직후, sensor가 '실행 소실'을 남기기 전에 누른 재시도.

    예전에는 상태 행에 오류가 없어 호출 유예로 건너뛰었다. 이제 재시도 경로가 같은 규칙(`lost_fuel_claim_owner`)으로
    소실을 직접 보고 실행한다. 정기 예약은 옮기지 않는다.
    """
    settings = test_settings.model_copy(update={"transport_collection_enabled": True})
    engine, factory = await _database(settings)
    service, calls, reservation = await _service_with_lost_claim(settings, factory, owner_status="failed")
    try:
        assert (await _opinet_state(factory)).last_error is None  # sensor 기록 전
        async with factory() as session:
            retried = await service.collect(session, trigger="dagster_fuel", scope="fuel", retry_failed_fuel=True)
        assert retried["status"] == "success" and calls["count"] == 2
        state = await _opinet_state(factory)
        assert state.last_error is None
        assert serialize_utc(state.next_due_at) == serialize_utc(reservation)
        # 성공 뒤에는 다시 소실로 보지 않는다(주인 = 재시도 실행, success).
        assert await record_lost_fuel_attempt(factory) is None
    finally:
        await service.close()
        await engine.dispose()


async def test_admin_retry_after_the_sensor_recorded_the_lost_attempt_runs(test_settings):
    settings = test_settings.model_copy(update={"transport_collection_enabled": True})
    engine, factory = await _database(settings)
    service, calls, reservation = await _service_with_lost_claim(settings, factory, owner_status="failed")
    try:
        assert await record_lost_fuel_attempt(factory) is not None
        async with factory() as session:
            retried = await service.collect(session, trigger="dagster_fuel", scope="fuel", retry_failed_fuel=True)
        assert retried["status"] == "success" and calls["count"] == 2
        assert serialize_utc((await _opinet_state(factory)).next_due_at) == serialize_utc(reservation)
    finally:
        await service.close()
        await engine.dispose()


async def test_admin_retry_while_the_dead_run_is_not_yet_closed_is_still_skipped(test_settings):
    """남은 창(런북 기록): Dagster run은 끝났지만 회수가 아직 run 행을 닫지 않았으면(다음 sensor tick 전, 또는 Dagster 기록이
    없는 run의 5시간 grace) 서비스는 그 실행이 살아 있는지 알 수 없어 재시도를 호출 유예로 건너뛴다."""
    settings = test_settings.model_copy(update={"transport_collection_enabled": True})
    engine, factory = await _database(settings)
    service, calls, _reservation = await _service_with_lost_claim(settings, factory, owner_status="running")
    try:
        async with factory() as session:
            skipped = await service.collect(session, trigger="dagster_fuel", scope="fuel", retry_failed_fuel=True)
        assert skipped["status"] == "skipped" and calls["count"] == 1
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


# ---------------------------------------------------------------------------
# 단계별 예산·실패 분리


class _Broken:
    async def __aenter__(self):
        raise ConnectionError("db down password=secret")

    async def __aexit__(self, *_exc):
        return False


async def test_check_failure_is_reported_without_raising():
    report = FuelFreshnessReport()
    await check_fuel_freshness(_Broken, report)
    assert (report.lost_failure, report.failure) == ("ConnectionError", "ConnectionError")
    assert report.levels == [] and report.lost_attempt is None and report.checked is False


async def test_a_failing_lost_step_does_not_suppress_the_freshness_levels(test_settings, monkeypatch):
    """Popper P2-2: 두 단계는 따로 실패한다 — 소실 기록이 죽어도 위험 단계는 남는다."""
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        await _add(factory, _state(last_success_at=now - timedelta(hours=23), last_started_at=now - timedelta(hours=4),
                                   last_error="x"))

        async def broken(*_args, **_kwargs):
            raise RuntimeError("unexpected password=secret")

        monkeypatch.setattr(recovery, "record_lost_fuel_attempt", broken)
        report = FuelFreshnessReport()
        await check_fuel_freshness(factory, report)
        assert report.lost_failure == "RuntimeError" and report.failure is None and report.checked
        assert [(item.source, item.level) for item in report.levels] == [(OPINET_SOURCE, "critical")]
        texts = _emit(FuelFreshnessAlerts(), report, T0)
        assert texts[0] == f"{FUEL_FRESHNESS_EVENT}.check_failed step=lost_attempt error=RuntimeError"
        assert texts[1].startswith(f"{FUEL_FRESHNESS_EVENT}.critical source={OPINET_SOURCE} ")
    finally:
        await engine.dispose()


async def test_budget_prefers_the_freshness_levels_over_the_lost_step(test_settings, monkeypatch):
    """Popper P2-5: 남은 예산이 두 단계를 다 담지 못하면 소실 기록을 건너뛰고 판정만, 판정도 못 담으면 아무것도 안 한다."""
    engine, factory = await _database(test_settings)
    called = []

    async def recording(*_args, **_kwargs):
        called.append("lost")

    monkeypatch.setattr(recovery, "record_lost_fuel_attempt", recording)
    try:
        report = FuelFreshnessReport()
        await check_fuel_freshness(factory, report, remaining=lambda: FUEL_LEVEL_STEP_SECONDS + 1)
        assert called == [] and report.checked
        report = FuelFreshnessReport()
        await check_fuel_freshness(factory, report, remaining=lambda: FUEL_LEVEL_STEP_SECONDS)
        assert called == [] and not report.checked and report.failure is None
        report = FuelFreshnessReport()
        await check_fuel_freshness(factory, report,
                                   remaining=lambda: FUEL_LOST_STEP_SECONDS + FUEL_LEVEL_STEP_SECONDS + 1)
        assert called == ["lost"] and report.checked
    finally:
        await engine.dispose()


async def test_paused_sources_are_not_alerted(test_settings):
    """Popper P2-6: provider가 꺼졌거나 schedule이 STOPPED면 경보에서 뺀다. 확인이 실패하면 경보 쪽이다."""
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        await _add(factory,
                   _state(OPINET_SOURCE, last_success_at=now - timedelta(hours=30)),
                   _state(REST_AREA_FUEL_SOURCE, last_success_at=now - timedelta(hours=30)))
        alerts = FuelFreshnessAlerts()
        report = FuelFreshnessReport()
        await check_fuel_freshness(factory, report, monitored=lambda source: source != OPINET_SOURCE)
        assert report.paused == [OPINET_SOURCE]
        assert [item.source for item in report.levels] == [REST_AREA_FUEL_SOURCE]
        assert [line.split(" ", 2)[:2] for line in _emit(alerts, report, T0)] == [
            [f"{FUEL_FRESHNESS_EVENT}.expired", f"source={REST_AREA_FUEL_SOURCE}"]]

        def broken(_source):
            raise RuntimeError("metadata down")

        report = FuelFreshnessReport()
        await check_fuel_freshness(factory, report, monitored=broken)
        assert report.paused == [] and len(report.levels) == 2
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 경보 줄


def _level(level: str, source=OPINET_SOURCE, failed=True, cause="failed") -> FuelFreshness:
    now = now_utc()
    warning_after, critical_after, expired_after = fuel_freshness_thresholds(source)
    return FuelFreshness(source=source, level=level, age_seconds=61_200, last_success_at=now - timedelta(hours=17),
                         last_attempt_failed=failed, cause=cause, warning_after=warning_after,
                         critical_after=critical_after, expired_after=expired_after)


def _checked(*levels, **values) -> FuelFreshnessReport:
    return FuelFreshnessReport(checked=True, levels=list(levels), **values)


def test_alert_lines_dedupe_same_level_and_report_changes_immediately():
    alerts = FuelFreshnessAlerts()
    lines = alerts.lines(_checked(_level("warning")), now=T0)
    assert len(lines) == 1
    assert lines[0].level == logging.WARNING
    line = lines[0].text
    assert line.startswith(f"{FUEL_FRESHNESS_EVENT}.warning source={OPINET_SOURCE} age_seconds=61200 ")
    expired = int(REFERENCE_STALE_AFTER[OPINET_SOURCE].total_seconds())
    assert line.endswith(
        f"cause=failed last_attempt_failed=true warning_after_seconds=57600 "
        f"critical_after_seconds={int(0.8 * expired)} expired_after_seconds={expired}")
    alerts.commit(lines[0])
    # 같은 단계는 재경보 간격 전에는 다시 남기지 않는다.
    assert _emit(alerts, _checked(_level("warning")), T0 + 60) == []
    assert len(_emit(alerts, _checked(_level("warning")), T0 + FUEL_FRESHNESS_REALERT_SECONDS)) == 1
    # 단계가 오르면 바로 남긴다(위험·만료는 error 수준).
    [critical] = alerts.lines(_checked(_level("critical")), now=T0 + 3660)
    assert critical.level == logging.ERROR and critical.text.startswith(f"{FUEL_FRESHNESS_EVENT}.critical ")
    alerts.commit(critical)
    [expired_line] = alerts.lines(_checked(_level("expired", cause="lost")), now=T0 + 3670)
    assert expired_line.level == logging.ERROR and " cause=lost " in expired_line.text
    alerts.commit(expired_line)
    # 판정 실패 tick은 단계 기억을 바꾸지 않는다(회복으로 오인하지 않음).
    assert _emit(alerts, FuelFreshnessReport(failure="TimeoutError"), T0 + 3720) == [
        f"{FUEL_FRESHNESS_EVENT}.check_failed step=levels error=TimeoutError"]
    assert _emit(alerts, FuelFreshnessReport(failure="TimeoutError"), T0 + 3780) == []
    assert _emit(alerts, _checked(_level("expired", cause="lost")), T0 + 3840) == []
    # 정상으로 돌아오면 회복 줄을 한 번 남기고, 그 뒤 정상 tick은 조용하다.
    [recovered] = _emit(alerts, _checked(_level("ok", failed=False, cause="none")), T0 + 3900)
    assert recovered.startswith(f"{FUEL_FRESHNESS_EVENT}.recovered source={OPINET_SOURCE} ")
    assert recovered.endswith("previous=expired")
    assert _emit(alerts, _checked(_level("ok", failed=False, cause="none")), T0 + 3960) == []


def test_tick_without_a_fuel_check_keeps_the_alert_memory():
    """점검을 못 한 tick(예산 부족·앞 단계 장애로 tick이 먼저 끝남)의 빈 결과는 "판단 대상 없음"이 아니다."""
    alerts = FuelFreshnessAlerts()
    assert len(_emit(alerts, _checked(_level("warning")), T0)) == 1
    assert _emit(alerts, FuelFreshnessReport(), T0 + 60) == []
    # 기억이 남아 있어 같은 단계를 곧바로 다시 남기지 않고, 이어진 회복도 회복 줄로 남긴다.
    assert _emit(alerts, _checked(_level("warning")), T0 + 120) == []
    [recovered] = _emit(alerts, _checked(_level("ok", failed=False, cause="none")), T0 + 180)
    assert recovered.startswith(f"{FUEL_FRESHNESS_EVENT}.recovered ") and recovered.endswith("previous=warning")
    # 판정까지 마친 tick에서 상태 행이 사라진(또는 경보에서 뺀) 원천은 기억에서 지운다.
    assert _emit(alerts, _checked(_level("critical")), T0 + 240) != []
    assert _emit(alerts, _checked(), T0 + 300) == []
    assert len(_emit(alerts, _checked(_level("critical")), T0 + 360)) == 1


def test_alert_memory_is_committed_only_after_the_line_was_written():
    """Popper P2-7: 로그 기록이 실패한 줄은 기억하지 않는다 — 다음 tick에 다시 만든다."""
    alerts = FuelFreshnessAlerts()
    critical = _level("critical")
    first = alerts.lines(_checked(critical), now=T0)
    assert len(first) == 1  # 남기지 못했다(commit 없음)
    second = alerts.lines(_checked(critical), now=T0 + 60)
    assert [line.text for line in second] == [line.text for line in first]
    alerts.commit(second[0])
    assert alerts.lines(_checked(critical), now=T0 + 120) == []


def test_report_writer_retries_a_line_whose_logging_failed(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="app.dagster.recovery")
    alerts = FuelFreshnessAlerts()
    monkeypatch.setattr(dagster_definitions, "_FUEL_FRESHNESS_ALERTS", alerts)

    def broken(_line):
        raise OSError("log sink down")

    failing = SimpleNamespace(log=SimpleNamespace(warning=broken, error=broken))
    dagster_definitions._report_fuel_freshness(failing, _checked(_level("critical")))
    assert [r.getMessage() for r in caplog.records] == [f"{FUEL_FRESHNESS_EVENT}.report_failed"]
    written: list[str] = []
    working = SimpleNamespace(log=SimpleNamespace(warning=written.append, error=written.append))
    dagster_definitions._report_fuel_freshness(working, _checked(_level("critical")))
    assert len(written) == 1 and written[0].startswith(f"{FUEL_FRESHNESS_EVENT}.critical ")
    dagster_definitions._report_fuel_freshness(working, _checked(_level("critical")))
    assert len(written) == 1


def test_lost_attempt_line_has_fixed_fields_and_is_emitted_once_per_claim():
    started = now_utc()
    lost = LostFuelAttempt(collection_run_id=42, orchestrator_run_id="0f1e2d3c", last_started_at=started)
    alerts = FuelFreshnessAlerts()
    [line] = alerts.lines(_checked(lost_attempt=lost), now=T0)
    assert line.level == logging.WARNING
    assert line.text == (f"{FUEL_FRESHNESS_EVENT}.lost_attempt source={OPINET_SOURCE} collection_run_id=42 "
                         f"orchestrator_run_id=0f1e2d3c last_started_at={started.isoformat()}")
    # 예산 부족 등으로 남기지 못했으면(commit 없음) 다음 tick이 상태에서 다시 만든다(James #3).
    [again] = alerts.lines(_checked(lost_attempt=lost), now=T0 + 60)
    alerts.commit(again)
    assert alerts.lines(_checked(lost_attempt=lost), now=T0 + 120) == []
    assert alerts.lines(_checked(lost_attempt=lost), now=T0 + 10 * FUEL_FRESHNESS_REALERT_SECONDS) == []
    # 판정하지 못한 tick은 기억을 지우지 않고, 소실이 풀린 tick은 지운다.
    assert alerts.lines(FuelFreshnessReport(), now=T0 + 180) == []
    assert alerts.lines(_checked(), now=T0 + 240) == []
    assert len(alerts.lines(_checked(lost_attempt=lost), now=T0 + 300)) == 1


async def test_lost_line_is_rebuilt_from_the_state_row(test_settings):
    """James #3: 기록한 tick에 줄을 남기지 못했어도 상태 행(`실행 소실` + 주인 failed)에서 다시 만든다."""
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        claimed = now - timedelta(hours=1)
        await _add(factory,
                   _state(last_success_at=now - timedelta(hours=9), last_started_at=claimed,
                          last_error=LOST_FUEL_ATTEMPT_ERROR),
                   _fuel_run(claimed - timedelta(seconds=1), status="failed", orchestrator_run_id="gone"))
        levels, lost = await fuel_freshness_snapshot(factory)
        assert lost is not None and (lost.orchestrator_run_id, lost.last_started_at) == ("gone", serialize_utc(claimed))
        assert levels[0].cause == "lost"
        # 그 뒤 재시도 실행이 claim하면(진행 중) 소실 줄을 만들지 않는다(오류 문장은 claim이 지우지 않는다).
        retry_claim = now_utc()
        await _add(factory, _fuel_run(retry_claim))
        async with factory() as session:
            await session.execute(update(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE).values(last_started_at=retry_claim))
            await session.commit()
        levels, lost = await fuel_freshness_snapshot(factory)
        assert lost is None and levels[0].cause == "running"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# 실제 회수 sensor tick


def _enabled(test_settings):
    return test_settings.model_copy(update={"transport_collection_enabled": True, "opinet_browser_enabled": True})


async def test_sensor_records_lost_attempt_in_the_same_tick_and_warns_without_new_runs_or_a_stall(
    test_settings, sensor_env, caplog, monkeypatch,  # noqa: F811
):
    monkeypatch.setattr(dagster_definitions, "_settings", lambda: _enabled(test_settings))
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

        # tick 1: 회수가 실행 행을 닫고, 같은 tick에서 소실을 기록한다. 그 결과 "마지막 시도 실패 + 16시간 초과"라 경고한다.
        result = sensor_env.tick(T0)
        assert result.cursor == "stall:null"
        lines = fuel_lines()
        assert [line.split(" ", 1)[0] for line in lines] == [
            f"{FUEL_FRESHNESS_EVENT}.lost_attempt", f"{FUEL_FRESHNESS_EVENT}.warning"]
        assert "orchestrator_run_id=gone" in lines[0]
        assert " cause=lost " in lines[1]
        assert (await _opinet_state(factory)).last_error == LOST_FUEL_ATTEMPT_ERROR
        # tick 2: 같은 단계·같은 소실은 다시 남기지 않는다. 새 유가 run을 만들지 않는다(실행 행은 그대로 하나).
        sensor_env.tick(T0 + 60)
        assert len(fuel_lines()) == 2
        async with factory() as session:
            fuel_runs = (await session.scalars(select(CollectionRun.status).where(
                CollectionRun.trigger == FUEL_TRIGGER))).all()
        assert fuel_runs == ["failed"]
        assert sensor_env.instance.get_runs() == []
    finally:
        await engine.dispose()


async def test_sensor_does_not_alert_a_disabled_fuel_provider(test_settings, sensor_env, caplog):  # noqa: F811
    """test_settings는 교통 수집이 꺼져 있다(`transport_collection_enabled=False`) — 오래된 상태 행이어도 경보하지 않는다."""
    caplog.set_level(logging.WARNING, logger="app.dagster.recovery")
    engine, factory = await _database(test_settings)
    try:
        now = now_utc()
        await _add(factory,
                   *[CollectionRun(started_at=now, status="success", trigger=trigger) for trigger in FIVE_MINUTE_TRIGGERS],
                   _state(last_success_at=now - timedelta(days=3), last_error="x", last_started_at=now - timedelta(days=1)))
        assert sensor_env.tick(T0).cursor == "stall:null"
        assert [r.getMessage() for r in caplog.records if r.name == "app.dagster.recovery"] == []
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
        assert messages == [f"{FUEL_FRESHNESS_EVENT}.check_failed step=lost_attempt error=RuntimeError"]
    finally:
        await engine.dispose()


def test_report_writer_never_fails_the_tick(monkeypatch):
    class Exploding:
        def lines(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(dagster_definitions, "_FUEL_FRESHNESS_ALERTS", Exploding())
    context = SimpleNamespace(log=SimpleNamespace(warning=lambda *_: None, error=lambda *_: None))
    dagster_definitions._report_fuel_freshness(context, FuelFreshnessReport())


# ---------------------------------------------------------------------------
# 소비 계약: 소실 기록은 실패 1회와 같게 보인다(James #5)


def test_lost_record_reads_as_one_failed_attempt_across_t1_t4_public_and_admin(export_client):  # noqa: F811
    success_at = now_utc() - timedelta(hours=9)
    claimed = now_utc() - timedelta(hours=1)

    async def seed(session) -> None:
        await _seed_fuel_station(session, seen_at=success_at)
        await _set_state(session, OPINET_SOURCE, last_success_at=success_at, last_started_at=claimed, last_error=None,
                         next_due_at=claimed + timedelta(hours=7, minutes=45))
        session.add(_fuel_run(claimed - timedelta(seconds=1), status="failed", orchestrator_run_id="dead"))

    _run(export_client, seed)
    assert asyncio.run(record_lost_fuel_attempt(export_client.app.state.session_factory)) is not None

    # T1: 마지막 성공 집합을 200으로 내고, 마지막 시도 실패만 알린다(503 아님).
    t1 = export_client.get("/v1/service/exports/fuel-stations", headers=HEADERS)
    assert t1.status_code == 200
    assert t1.json()["collection"]["last_attempt_failed"] is True
    assert t1.json()["collection"]["failed"] is False and t1.json()["collection"]["stale"] is False
    # T4: 실패가 있으면 stale(기존 의미 그대로).
    t4 = export_client.get("/v1/service/exports/fuel-stations/A0000001/price-history", headers=HEADERS)
    assert t4.status_code == 200 and t4.json()["meta"]["source_status"] == "stale"
    # 공개 상태: 고정 오류 코드만, 유가 지연 표시.
    public = export_client.get("/v1/transport/collector-status").json()
    assert public["fuel_prices_stale"] is True
    assert public["last_fuel_error"] == "collection_failed"
    assert LOST_FUEL_ATTEMPT_ERROR not in str(public)
    # 관리 상태: 실행 소실을 원인 미상 실패와 구분한다.
    providers = {row["source"]: row for row in export_client.get("/v1/transport/providers").json()["items"]}
    assert providers[OPINET_SOURCE]["error_code"] == "collection_lost"


# ---------------------------------------------------------------------------
# PostgreSQL 경합(Popper P2-3·P2-9)


async def _lost_claim_on(factory):
    now = now_utc()
    claimed = now - timedelta(hours=1)
    await _add(factory,
               _state(last_success_at=now - timedelta(hours=9), last_started_at=claimed),
               _fuel_run(claimed - timedelta(seconds=1), status="failed", orchestrator_run_id="dead"))


async def test_postgres_skips_while_a_fuel_collector_holds_the_fuel_lock(test_settings):
    if not _postgres(test_settings):
        pytest.skip("PostgreSQL 전용")
    engine, factory = await _database(test_settings)
    try:
        await _lost_claim_on(factory)
        async with factory() as collector:
            await collector.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                                    {"key": TRANSPORT_COLLECTION_ADVISORY_LOCK_KEY + 1})
            # 수집기가 claim·저장 중이면 기다리지 않고 건너뛴다.
            assert await asyncio.wait_for(record_lost_fuel_attempt(factory), timeout=3) is None
            await collector.rollback()
        assert (await _opinet_state(factory)).last_error is None
        assert await record_lost_fuel_attempt(factory) is not None
    finally:
        await engine.dispose()


async def test_postgres_cas_loses_to_a_concurrent_failure_write(test_settings):
    """상태 행을 쥔 수집기가 실패를 쓰고 commit하면, 기다리던 소실 기록은 다시 평가돼 0행이다(원래 오류 보존)."""
    if not _postgres(test_settings):
        pytest.skip("PostgreSQL 전용")
    engine, factory = await _database(test_settings)
    try:
        await _lost_claim_on(factory)
        async with factory() as collector:
            await collector.execute(update(TransportCollectionState).where(
                TransportCollectionState.source == OPINET_SOURCE).values(last_error="Opinet browser timeout"))
            pending = asyncio.create_task(record_lost_fuel_attempt(factory))
            await asyncio.sleep(0.3)  # 소실 기록이 행 잠금을 기다리는 중
            await collector.commit()
        assert await pending is None
        assert (await _opinet_state(factory)).last_error == "Opinet browser timeout"
    finally:
        await engine.dispose()


async def test_postgres_lock_timeout_under_contention_is_a_check_failure_not_a_hang(test_settings):
    if not _postgres(test_settings):
        pytest.skip("PostgreSQL 전용")
    engine, factory = await _database(test_settings)
    try:
        await _lost_claim_on(factory)
        async with factory() as holder:
            await holder.execute(text("SELECT 1 FROM transport_collection_states WHERE source = :source FOR UPDATE"),
                                 {"source": OPINET_SOURCE})
            report = FuelFreshnessReport()
            await asyncio.wait_for(check_fuel_freshness(factory, report), timeout=FUEL_LOST_STEP_SECONDS)
            await holder.rollback()
        assert report.lost_failure is not None and report.lost_failure.endswith(":55P03"), report.lost_failure
        assert report.checked  # 판정 단계는 따로 돈다
        assert (await _opinet_state(factory)).last_error is None
    finally:
        await engine.dispose()
