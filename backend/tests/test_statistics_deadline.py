"""느린 집계의 취소·슬롯 반환·동일 키 경합 회귀 검사."""

import asyncio
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.main import cached_transport_statistics


def _request(cache_seconds=60):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        settings=SimpleNamespace(transport_statistics_cache_seconds=cache_seconds,
                                 transport_statistics_timeout_seconds=0.02),
        transport_statistics_cache=OrderedDict(),
        transport_statistics_locks={},
        transport_statistics_miss_semaphore=asyncio.Semaphore(1),
    )))


@pytest.mark.parametrize('cache_seconds', [0, 60])
def test_deadline_cancels_work_rolls_back_and_allows_next_request(cache_seconds):
    async def exercise():
        request = _request(cache_seconds)
        session = SimpleNamespace(rollback=AsyncMock())
        stopped = asyncio.Event()
        slow = True

        async def handler(**kwargs):
            if slow:
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()
            return {'ok': True}

        cached = cached_transport_statistics(handler)
        with pytest.raises(HTTPException) as failure:
            await cached(request=request, session=session)
        assert failure.value.status_code == 504
        assert stopped.is_set()
        session.rollback.assert_awaited_once()
        state = request.app.state
        assert not state.transport_statistics_miss_semaphore.locked()
        assert not state.transport_statistics_locks
        assert not state.transport_statistics_cache
        slow = False
        assert await cached(request=request, session=session) == {'ok': True}

    asyncio.run(exercise())


def test_deadline_cancels_real_postgres_query_and_returns_connection(test_settings):
    if not test_settings.database_url.startswith('postgresql'):
        pytest.skip('실제 PostgreSQL 취소 검증')
    from sqlalchemy import text
    from app.db.session import create_engine_and_session_factory

    async def exercise():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        request = _request()
        request.app.state.settings.transport_statistics_timeout_seconds = 0.2
        async def handler(*, session, **kwargs):
            await session.execute(text('SELECT pg_sleep(5)'))
            return {'ok':True}
        try:
            async with factory() as session:
                with pytest.raises(HTTPException) as failure:
                    await cached_transport_statistics(handler)(request=request, session=session)
                assert failure.value.status_code == 504
                assert await session.scalar(text('SELECT 1')) == 1
            assert not request.app.state.transport_statistics_miss_semaphore.locked()
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_waiters_share_total_request_deadline():
    async def exercise():
        request = _request()
        calls = 0
        async def handler(**kwargs):
            nonlocal calls
            calls += 1
            await asyncio.Event().wait()
        cached = cached_transport_statistics(handler)
        tasks = [cached(request=request) for _ in range(10)]
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=0.5)
        assert all(isinstance(result,HTTPException) and result.status_code==504 for result in results)
        assert calls == 1
        assert not request.app.state.transport_statistics_locks
    asyncio.run(exercise())


def test_cancelled_owner_keeps_waiters_on_one_lock():
    async def exercise():
        request = _request()
        request.app.state.settings.transport_statistics_timeout_seconds = 10
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def handler(**kwargs):
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return {'ok': True}

        cached = cached_transport_statistics(handler)
        owner = asyncio.create_task(cached(request=request))
        await entered.wait()
        waiter = asyncio.create_task(cached(request=request))
        await asyncio.sleep(0)
        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        newcomer = asyncio.create_task(cached(request=request))
        await asyncio.sleep(0)
        release.set()
        assert await waiter == await newcomer == {'ok': True}
        assert calls == 2
        assert not request.app.state.transport_statistics_locks
        assert not request.app.state.transport_statistics_miss_semaphore.locked()

    asyncio.run(exercise())
