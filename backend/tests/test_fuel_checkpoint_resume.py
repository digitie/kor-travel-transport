"""브라우저 재호출 없이 완료 스냅샷 저장을 재개하는 경계를 검증한다."""
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.core.time_utils import now_utc, serialize_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import FuelLatestPrice, TransportCollectionState
from app.services.transport_collection import OPINET_SOURCE, TransportCollectionService, _is_transient_database_error
from test_transport_collection import FakeTransportProvider, build_settings


def test_failed_store_resumes_without_provider_requests_or_extending_reservation(tmp_path):
    async def exercise():
        settings = build_settings(tmp_path)
        provider = FakeTransportProvider()
        snapshot = await provider.collect_fuel()
        provider.collect_fuel = AsyncMock(return_value=snapshot)
        provider.pending_fuel_snapshot = AsyncMock(side_effect=[None, snapshot])
        provider.acknowledge_fuel_snapshot = Mock()
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        try:
            service = TransportCollectionService(settings, provider)
            store = service._store_fuel_snapshot
            service._store_fuel_snapshot = AsyncMock(side_effect=RuntimeError("storage unavailable"))
            async with factory() as session:
                assert (await service.collect(session, scope="fuel"))["status"] == "failed"
                state = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == OPINET_SOURCE))
                due = serialize_utc(state.next_due_at)
                assert due > now_utc()
                assert await session.scalar(select(FuelLatestPrice.fuel_station_id).limit(1)) is None
                provider.acknowledge_fuel_snapshot.assert_not_called()
                service._store_fuel_snapshot = store
                result = await service.collect(session, scope="fuel")
                assert result["status"] == "success"
                assert serialize_utc(state.next_due_at) == due
                assert serialize_utc(state.last_success_at) == serialize_utc(snapshot.collected_at)
                assert await session.scalar(select(FuelLatestPrice.fuel_station_id).limit(1)) is not None
            provider.collect_fuel.assert_awaited_once()
            provider.acknowledge_fuel_snapshot.assert_called_once_with(snapshot)
        finally:
            await engine.dispose()
    asyncio.run(exercise())


@pytest.mark.parametrize("code", ["57014", "55P03", "40001", "40P01", "23505"])
def test_server_timeout_retries_storage_only_by_sqlstate(code):
    class ServerError(Exception):
        sqlstate = code
    assert _is_transient_database_error(DBAPIError("INSERT", {}, ServerError())) is (code != "23505")


def test_empty_provider_result_is_failure_and_unhealthy_skip_stays_visible(tmp_path):
    async def exercise():
        settings = build_settings(tmp_path)
        provider = FakeTransportProvider()
        provider.collect_fuel = AsyncMock(return_value=None)
        engine, factory = create_engine_and_session_factory(settings.database_url)
        await init_database(engine)
        try:
            service = TransportCollectionService(settings, provider)
            async with factory() as session:
                assert (await service.collect(session, scope="fuel"))["status"] == "failed"
                result = await service.collect(session, scope="fuel")
                assert result["status"] == "skipped"
                assert result["fuel_ready"] is False
                assert "no browser snapshot" in result["errors"][0]
        finally:
            await engine.dispose()
    asyncio.run(exercise())
