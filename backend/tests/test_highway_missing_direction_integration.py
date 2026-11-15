import asyncio

import httpx
from app.core.config import Settings
from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory, init_database
from app.models import CollectionRun, HighwayTrafficSnapshot
from app.services.transport_collection import (
    TRAFFIC_SOURCE,
    LiveTransportProvider,
    TransportCollectionService,
)
from sqlalchemy import select


def test_real_sdk_blank_direction_keeps_all_rows_through_storage(tmp_path, monkeypatch):
    raw = {"code": "SUCCESS", "count": 2, "list": [
        {"conzoneId": "6000CZS050", "vdsId": "6000VDS01230", "updownTypeCode": " ",
         "grade": "0", "stdDate": "20261115", "stdHour": "0729", "speed": "-1"},
        {"conzoneId": "0010CZE010", "vdsId": "0010VDE00100", "updownTypeCode": "E",
         "grade": "1", "stdDate": "20261115", "stdHour": "0729", "speed": "90"},
    ]}
    calls = []
    def upstream(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=raw)
    factory = httpx.AsyncClient
    class MockClient(factory):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(upstream), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", MockClient)
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite'}",
                        kex_ex_api_key="fixture", opinet_browser_enabled=False,
                        transport_collection_enabled=True, enable_scheduler=False)

    async def run():
        provider = LiveTransportProvider(settings)
        engine, sessions = create_engine_and_session_factory(settings.database_url)
        try:
            await init_database(engine)
            payload = await provider.collect_highway(sources=(TRAFFIC_SOURCE,))
            assert TRAFFIC_SOURCE in payload.complete_sources
            assert isinstance(payload.traffic, tuple) and len(payload.traffic) == 2
            service = TransportCollectionService(settings, provider)
            async with sessions() as session:
                collection_run = CollectionRun(started_at=now_utc(), status="running", trigger="test")
                session.add(collection_run)
                await session.flush()
                stored = await service._store_traffic(session, collection_run.id, payload.traffic)
                await session.commit()
                rows = (await session.scalars(select(HighwayTrafficSnapshot).order_by(HighwayTrafficSnapshot.id))).all()
                assert stored == len(rows) == 2
                assert rows[0].direction is None and rows[0].speed is None
                assert rows[1].speed == 90
                assert all(row.collection_run_id == collection_run.id for row in rows)
        finally:
            await provider.aclose()
            await engine.dispose()
    asyncio.run(run())
    assert calls == ["/openapi/odtraffic/trafficAmountByRealtime"]
