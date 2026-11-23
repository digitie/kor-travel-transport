"""이전 통계 세대 정리의 실패·예산 소진이 조용히 사라지지 않는다(수집 실패 감사 2026-11-23 §2.5 P2).

정리는 원천 성공과 분리한다(실패해도 수집은 성공). 대신 결과 종류·지운 행 수를 수집 결과와 op metadata에,
실패·예산 소진은 가린 한 줄 경고로 남긴다. 유가 op는 이 logger를 Dagster event log로 넘긴다.
"""
import asyncio
import logging
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.dagster.definitions import _collection_output_metadata
from app.models import CollectionRun, RestAreaFuelPrice, TransportCollectionState
from app.services import fuel_statistics as stats
from app.services import rest_area_collection as rest

SECRET = "cleanup-secret-canary"


def test_cleanup_failure_is_reported_with_redacted_cause(client, caplog):
    async def exercise():
        async with client.app.state.session_factory() as session:
            failure = RuntimeError(f"canceling statement due to statement timeout https://x/?serviceKey={SECRET}")
            with patch.object(stats, "prune_fuel_statistics", side_effect=failure), \
                    caplog.at_level(logging.WARNING, logger=stats.logger.name):
                cleanup = await stats.cleanup_fuel_statistics(session, stats.OPINET)
            assert cleanup.outcome == "failed"
            assert cleanup.deleted == 0
            assert cleanup.cause is not None and cleanup.cause.startswith("RuntimeError:")
            assert SECRET not in cleanup.cause
            assert cleanup.metadata() == {"fuel_statistics_cleanup": "failed", "fuel_statistics_pruned_rows": 0}
            # 세션은 rollback돼 다음 문장을 쓸 수 있다.
            assert (await session.execute(select(1))).scalar_one() == 1
    asyncio.run(exercise())
    assert "fuel statistics cleanup failed source=opinet_browser" in caplog.text
    assert "statement timeout" in caplog.text
    assert SECRET not in caplog.text


def test_cleanup_failure_after_some_batches_keeps_committed_count(client):
    async def exercise():
        calls = iter([stats.PRUNE_BATCH_ROWS, RuntimeError("deadlock detected")])

        async def prune(*_args, **_kwargs):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value

        async with client.app.state.session_factory() as session:
            with patch.object(stats, "prune_fuel_statistics", side_effect=prune):
                cleanup = await stats.cleanup_fuel_statistics(session, stats.OPINET)
        assert (cleanup.outcome, cleanup.deleted) == ("failed", stats.PRUNE_BATCH_ROWS)
    asyncio.run(exercise())


def test_zero_budget_reports_remaining_backlog(client):
    async def exercise():
        async with client.app.state.session_factory() as session:
            cleanup = await stats.cleanup_fuel_statistics(session, stats.OPINET, budget_seconds=0)
        assert (cleanup.outcome, cleanup.deleted) == ("budget_exhausted", 0)
    asyncio.run(exercise())


def test_rest_area_fuel_success_carries_cleanup_failure_without_failing_the_source(client, test_settings):
    async def exercise():
        class Client:
            async def aclose(self):
                pass

        async def fetch(_client):
            return (object(),)

        async def store(session, _items, stamp):
            session.add(RestAreaFuelPrice(source=stats.HIGHWAY, service_area_code="A",
                                          service_area_name="합성 주유소", gasoline_price=1700,
                                          first_seen_at=stamp, last_seen_at=stamp))
            await session.flush()
            return 1

        service = rest.RestAreaCollectionService(test_settings, client_factory=lambda **kw: Client())
        async with client.app.state.session_factory() as session:
            with patch.object(stats, "prune_fuel_statistics", side_effect=RuntimeError("statement timeout")):
                result = await service._run(session, rest.REST_AREA_FUEL_TRIGGER, stats.HIGHWAY,
                                            "test:synthetic", fetch, store)
            assert result["status"] == "success"
            assert result["fuel_statistics_cleanup"] == "failed"
            assert result["fuel_statistics_pruned_rows"] == 0
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == stats.HIGHWAY))
            assert state.last_error is None and state.last_success_at is not None
            run = await session.scalar(select(CollectionRun).where(
                CollectionRun.trigger == rest.REST_AREA_FUEL_TRIGGER))
            assert run.status == "success"
    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["done", "budget_exhausted", "failed"])
def test_output_metadata_surfaces_cleanup_without_changing_collection_outcome(outcome):
    result = {"status": "success", "collection_run_id": 3, "fuel_statistics_published": True,
              "fuel_statistics_cleanup": outcome, "fuel_statistics_pruned_rows": 125}
    metadata = _collection_output_metadata(result, "fuel")
    assert metadata["fuel_statistics_cleanup"] == outcome
    assert metadata["fuel_statistics_pruned_rows"] == 125
    # 정리는 원천 신선도와 무관하다. 수집 결과 종류는 그대로다.
    assert metadata["collection_outcome"] == "success"
    assert "error_code" not in metadata


@pytest.mark.parametrize("value", ["oops", None, 3])
def test_output_metadata_ignores_unknown_cleanup_values(value):
    metadata = _collection_output_metadata(
        {"status": "success", "fuel_statistics_cleanup": value, "fuel_statistics_pruned_rows": -1}, "fuel")
    assert "fuel_statistics_cleanup" not in metadata
    assert "fuel_statistics_pruned_rows" not in metadata


def test_pruned_rows_outside_range_is_dropped():
    metadata = _collection_output_metadata(
        {"status": "success", "fuel_statistics_cleanup": "done", "fuel_statistics_pruned_rows": True}, "fuel")
    assert metadata["fuel_statistics_cleanup"] == "done"
    assert "fuel_statistics_pruned_rows" not in metadata

