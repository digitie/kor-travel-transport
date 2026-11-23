"""유가 Dagster op의 일시 오류 자동 재시도와 관리자 재시도 태그(FUEL-RETRY-20261123).

정의의 RetryPolicy는 5분(휴게소 유가 1분) 지연이라, 동작 시험은 같은 op에 지연 0인 정책을 붙인 job으로 한다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from dagster import Backoff, Jitter, RetryPolicy, job
from sqlalchemy.exc import DBAPIError

from app.dagster import definitions as dagster_definitions
from app.services.transport_collection import TransportCollectionService

FAST = RetryPolicy(max_retries=1)


class _SqlState(Exception):
    def __init__(self, message: str, sqlstate: str) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def _lock_timeout() -> DBAPIError:
    return DBAPIError(
        "UPDATE transport_collection_states SET last_started_at=$1", {},
        _SqlState("canceling statement due to lock timeout", "55P03"),
    )


def _summary(status: str, errors: list[str]) -> dict:
    return TransportCollectionService._summary(
        SimpleNamespace(id=4242, status=status), client_mode="live", raw_count=0, traffic_count=0,
        incident_count=0, fuel_station_count=0, fuel_price_count=0, errors=errors,
    )


def _fuel_job():
    @job(name="fuel_retry_fixture_job")
    def fixture_job() -> None:
        dagster_definitions.collect_fuel_transport.with_retry_policy(FAST)()

    return fixture_job


def _patch(monkeypatch, outcomes, calls, *, budget=True):
    class FakeService:
        def __init__(self, settings):
            pass

        async def collect(self, session, **kwargs):
            calls.append(kwargs.get("retry_failed_fuel", False))
            outcome = outcomes[min(len(calls), len(outcomes)) - 1]
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        async def close(self):
            return None

    async def run_with_session(settings, action, *args, **kwargs):
        return await action(None, *args, **kwargs)

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "_secret_forms", lambda: [])
    monkeypatch.setattr(dagster_definitions, "TransportCollectionService", FakeService)
    monkeypatch.setattr(dagster_definitions, "_run_with_session", run_with_session)
    if not budget:
        monkeypatch.setattr(dagster_definitions, "_retry_budget_left", lambda context: False)


def _retries(result) -> int:
    return sum(1 for event in result.all_events if event.is_step_up_for_retry)


def test_definitions_attach_retry_policies_only_to_the_two_fuel_ops() -> None:
    policies = {
        node.name: node.definition.retry_policy if hasattr(node.definition, "retry_policy") else None
        for job_def in dagster_definitions.definitions.get_repository_def().get_all_jobs()
        for node in job_def.graph.nodes
    }
    fuel = dagster_definitions.collect_fuel_transport.retry_policy
    rest = dagster_definitions.collect_rest_area_fuel_prices.retry_policy
    assert (fuel.max_retries, fuel.delay, fuel.backoff, fuel.jitter) == (1, 300, Backoff.EXPONENTIAL, Jitter.PLUS_MINUS)
    assert (rest.max_retries, rest.delay, rest.backoff, rest.jitter) == (2, 60, Backoff.EXPONENTIAL, Jitter.PLUS_MINUS)
    with_policy = {name for name, policy in policies.items() if policy is not None}
    assert with_policy == {"collect_fuel_transport", "collect_rest_area_fuel_prices"}


def test_claim_lock_timeout_is_retried_once_in_the_same_run(monkeypatch) -> None:
    calls: list[bool] = []
    _patch(monkeypatch, [_lock_timeout(), _summary("success", [])], calls)
    result = _fuel_job().execute_in_process(raise_on_error=False)
    assert result.success
    assert _retries(result) == 1
    # 재시도 시도는 "직전 실패의 재시도"로 서비스에 알린다(예약은 서비스가 실패였을 때만 앞당긴다).
    assert calls == [False, True]


@pytest.mark.parametrize("message", [
    "Opinet browser resource policy failed command=Fetch.failRequest cause=Error reason=unclassified",
    "Opinet browser action failed: phase=reload:lpg:region=충청북도/증평군; cause=TimeoutError; events=none",
    "(sqlalchemy.dialects.postgresql.asyncpg.Error) canceling statement due to lock timeout",
])
def test_transient_collection_failures_are_retried(monkeypatch, message) -> None:
    calls: list[bool] = []
    _patch(monkeypatch, [_summary("failed", [message]), _summary("success", [])], calls)
    result = _fuel_job().execute_in_process(raise_on_error=False)
    assert result.success and _retries(result) == 1
    assert calls == [False, True]


@pytest.mark.parametrize("message", [
    "Opinet browser response rate limited: HTTP 429",
    "Opinet browser response appears to be an access-block page",
    "Opinet browser response denied access: HTTP 403",
    "python-opinet-api returned no usable fuel prices",
    "fuel collection exceeded 12600s",
])
def test_quota_block_auth_and_contract_failures_are_not_retried(monkeypatch, message) -> None:
    calls: list[bool] = []
    _patch(monkeypatch, [_summary("failed", [message]), _summary("success", [])], calls)
    result = _fuel_job().execute_in_process(raise_on_error=False)
    assert not result.success and _retries(result) == 0
    assert calls == [False]
    failure = result.failure_data_for_node("collect_fuel_transport").user_failure_data
    assert failure.metadata["auto_retry"].value is False


def test_no_retry_without_run_budget(monkeypatch) -> None:
    calls: list[bool] = []
    _patch(monkeypatch, [_lock_timeout(), _summary("success", [])], calls, budget=False)
    result = _fuel_job().execute_in_process(raise_on_error=False)
    assert not result.success and _retries(result) == 0 and calls == [False]


def test_non_database_exception_is_not_retried(monkeypatch) -> None:
    calls: list[bool] = []
    _patch(monkeypatch, [ConnectionError("provider socket"), _summary("success", [])], calls)
    result = _fuel_job().execute_in_process(raise_on_error=False)
    assert not result.success and _retries(result) == 0 and calls == [False]


def test_admin_retry_tag_marks_the_first_attempt_as_a_retry(monkeypatch) -> None:
    calls: list[bool] = []
    _patch(monkeypatch, [_summary("success", [])], calls)
    result = _fuel_job().execute_in_process(
        raise_on_error=False, tags={dagster_definitions.ADMIN_RETRY_TAG: "0edf4c1f-5269-43f4-afb9-0919f794cbde"})
    assert result.success and calls == [True]


def test_regular_run_is_not_a_retry(monkeypatch) -> None:
    calls: list[bool] = []
    _patch(monkeypatch, [_summary("success", [])], calls)
    assert _fuel_job().execute_in_process(raise_on_error=False).success
    assert calls == [False]


def test_rest_area_fuel_claim_lock_timeout_is_retried(monkeypatch) -> None:
    calls: list[int] = []

    class FakeRestArea:
        def __init__(self, settings):
            pass

        async def collect_fuel_prices(self, session):
            calls.append(1)
            if len(calls) == 1:
                raise _lock_timeout()
            return {"status": "success", "run_id": 7, "received": 1, "stored": 1}

    async def run_with_session(settings, action, *args, **kwargs):
        return await action(None, *args, **kwargs)

    monkeypatch.setattr(dagster_definitions, "_settings", lambda: None)
    monkeypatch.setattr(dagster_definitions, "_secret_forms", lambda: [])
    monkeypatch.setattr(dagster_definitions, "RestAreaCollectionService", FakeRestArea)
    monkeypatch.setattr(dagster_definitions, "_run_with_session", run_with_session)

    @job(name="rest_area_retry_fixture_job")
    def fixture_job() -> None:
        dagster_definitions.collect_rest_area_fuel_prices.with_retry_policy(FAST)()

    result = fixture_job.execute_in_process(raise_on_error=False)
    assert result.success and _retries(result) == 1 and len(calls) == 2
