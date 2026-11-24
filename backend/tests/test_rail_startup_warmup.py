"""기동 때 준비한 철도 지문은 같은 워커의 첫 조회에서 재사용된다. 주차 이력 캐시는 warmup 뒤에 시작한다."""

import asyncio
from threading import Event

import pytest
from fastapi.testclient import TestClient
from kortravelcommon.address_providers import VworldKakaoAddressResolver
from kortravelcommon.reverse_address import AddressTarget, reverse_address_tables
from sqlalchemy import func, select
from test_rail_export import PATH, seed
from test_reference_read_timing import _counts
from test_service_exports import HEADERS, LOOPBACK_CLIENT, TOKEN, _run

from app import main
from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory
from app.models import (
    Base,
    RailStationReference,
    ReferenceExportArtifact,
    ServiceExportSnapshot,
)


def test_rail_startup_warmup_preserves_readiness_and_address_invalidation(test_settings, monkeypatch):
    if not test_settings.database_url.startswith("postgres"):
        pytest.skip("PostgreSQL 기동 지문 통합 검증")
    test_settings.seed_sample_data = False
    test_settings.transport_map_current_enabled = True
    test_settings.release_sha = "rail-startup-warmup-test"
    test_settings.transport_service_export_token = TOKEN
    entries, _ = reverse_address_tables(Base.metadata)

    def payload(road):
        return {"provider": "vworld", "address": {"road_address": road}}

    async def seed_before_startup():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        try:
            async with factory.begin() as session:
                await seed(session)
                row = await session.scalar(select(RailStationReference).where(
                    RailStationReference.identity_key == "rail-0",
                ))
                target = AddressTarget(f"rail_station:{row.id}", row.longitude, row.latitude)
                now = now_utc()
                await session.execute(entries.insert().values(
                    provider_id=VworldKakaoAddressResolver.provider_id, target_key=target.key,
                    coordinate_key=target.coordinate_key, latitude=target.latitude, longitude=target.longitude,
                    status="ok", payload=payload("기존 도로"), checked_at=now, resolved_at=now, failures=0,
                ))
        finally:
            await engine.dispose()

    asyncio.run(seed_before_startup())
    started, finished = Event(), Event()
    resume = asyncio.Event()
    real_warmup = main.warm_reference_revisions
    application = main.create_app(test_settings)
    warmed = []

    async def pause_warmup(factory, *, settings):
        assert factory is application.state.session_factory
        started.set()
        await resume.wait()
        warmed.extend(await real_warmup(factory, settings=settings))
        finished.set()
        return warmed

    monkeypatch.setattr(main, "warm_reference_revisions", pause_warmup)
    with TestClient(application, client=LOOPBACK_CLIENT) as client:
        assert started.wait(3)
        assert client.get("/health").status_code == 200
        assert not finished.is_set()
        # 지문 warmup이 끝나기(또는 30초) 전에는 주차 이력 캐시 전체 구성을 시작하지 않는다(G3-10).
        assert application.state.history_cache_task is None
        assert client.get(PATH).status_code == 404
        assert client.portal is not None
        client.portal.call(resume.set)
        assert finished.wait(5)
        # Map이 읽는 두 종류를 순서대로 데운다. 여객선 원천은 이 시험에 없다.
        assert [(row["kind"], row["status"]) for row in warmed] == [
            ("rail-stations-v1", "warmed"), ("ferry-ports-v1", "source_unavailable"),
        ]
        for _ in range(50):
            if application.state.history_cache_task is not None:
                break
            client.portal.call(asyncio.sleep, 0.05)
        assert application.state.history_cache_task is not None

        async def storage_counts(session):
            return [
                await session.scalar(select(func.count()).select_from(model))
                for model in (ReferenceExportArtifact, ServiceExportSnapshot)
            ]

        assert _run(client, storage_counts) == [0, 0]
        first = client.get(PATH, headers=HEADERS, params={"limit": 1})
        assert first.status_code == 200
        assert _counts(first) == {"page_builds": 1, "fingerprint_calculations": 1}
        assert first.json()["items"][0]["admin"]["road_address"] == "기존 도로"

        async def change_address(session):
            await session.execute(entries.update().values(payload=payload("변경 도로")))

        _run(client, change_address)
        changed = client.get(PATH, headers=HEADERS, params={"limit": 1})
        assert changed.status_code == 200
        assert _counts(changed) == {"page_builds": 1, "fingerprint_calculations": 2}
        assert changed.json()["items"][0]["admin"]["road_address"] == "변경 도로"
        assert changed.headers["etag"] != first.headers["etag"]
        old_page = client.get(PATH, headers=HEADERS, params={
            "limit": 1, "cursor": first.json()["next_cursor"],
        })
        assert old_page.status_code == 200
        assert old_page.json()["snapshot_id"] == first.json()["snapshot_id"]
