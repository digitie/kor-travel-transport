from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.time_utils import now_utc, serialize_utc, to_seoul
from app.dagster import definitions as dagster_definitions
from app.main import create_app
from app.models import AnalyticsCache, CollectionRun, ParkingSnapshot
from app.services.analytics_cache import MAX_ANALYTICS_CACHE_AGE, load_cached_analytics, refresh_default_analytics_cache
from app.services.collection import CollectionService, FixturePublicDataClient


class UpdatingParkingClient(FixturePublicDataClient):
    def __init__(self) -> None:
        self.observed_at = now_utc().replace(second=0, microsecond=0) - timedelta(minutes=20)
        self.occupied_spaces = 20
        self.fail_incheon = False

    async def fetch_kac_parking(self):
        response = await super().fetch_kac_parking()
        local = to_seoul(self.observed_at)
        return replace(response, body_text=json.dumps([{
            "aprEng": "GIMPO INTERNATIONAL AIRPORT", "aprKor": "김포국제공항",
            "parkingAirportCodeName": "국내선 제1주차장", "parkingFullSpace": "100",
            "parkingGetdate": local.strftime("%Y-%m-%d"), "parkingGettime": local.strftime("%H:%M:%S"),
            "parkingIstay": str(self.occupied_spaces),
        }]))

    async def fetch_incheon_parking(self):
        if self.fail_incheon:
            raise RuntimeError("인천 관측 조회 실패")
        return replace(await super().fetch_incheon_parking(), body_text="[]")


def parking_app(test_settings, monkeypatch, *, partial_success=False):
    settings = test_settings.model_copy(update={
        "seed_sample_data": False, "scheduler_mode": "dagster", "airport_codes_csv": "GMP",
        "enable_incheon_collection": partial_success, "enable_fee_collection": False,
        "enable_incheon_fee_collection": False, "transport_map_current_enabled": False,
    })
    provider = UpdatingParkingClient()
    service = CollectionService(settings, client=provider)
    monkeypatch.setattr(dagster_definitions, "_settings", lambda: settings)
    monkeypatch.setattr(dagster_definitions, "get_settings", lambda: settings)
    monkeypatch.setattr(dagster_definitions, "CollectionService", lambda _settings: service)
    return create_app(settings), settings, provider


@pytest.mark.parametrize("partial_success", [False, True])
def test_dagster_new_observation_reaches_existing_analytics_api(test_settings, monkeypatch, partial_success):
    app, settings, provider = parking_app(test_settings, monkeypatch, partial_success=partial_success)

    with TestClient(app) as client:
        first = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False)
        assert first.success

        async def cache_existing_observation():
            async with client.app.state.session_factory() as session:
                assert await refresh_default_analytics_cache(session, settings) == 8
                await session.commit()

        asyncio.run(cache_existing_observation())
        before = client.get("/v1/parking/analytics/timeseries", params={"airport_code": "GMP"}).json()
        assert before["items"][-1]["available_spaces"] == 80

        provider.observed_at += timedelta(minutes=10)
        provider.occupied_spaces = 95
        provider.fail_incheon = partial_success
        second = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False)
        assert second.success is not partial_success
        summary = second.output_for_node("collect_airport_parking") if not partial_success else None
        if summary:
            assert summary["snapshot_count"] == 1
        assert not any(event.is_step_up_for_retry for event in second.all_events)

        current = client.get("/v1/parking/current", params={"airport_code": "GMP"})
        assert current.status_code == 200
        assert current.json()["items"][0]["available_spaces"] == 5
        after = client.get("/v1/parking/analytics/timeseries", params={"airport_code": "GMP"})
        assert after.status_code == 200
        assert after.json()["items"][-1]["available_spaces"] == 5
        bundle = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
        assert bundle.status_code == 200
        assert bundle.json()["time_series"] == after.json()
        for path, field in (("by-weekday-hour", "weekday_hour_patterns"),
                            ("threshold-events", "threshold_events"),
                            ("threshold-insights", "threshold_insights")):
            individual = client.get(f"/v1/parking/analytics/{path}", params={"airport_code": "GMP"})
            assert individual.status_code == 200
            assert bundle.json()[field] == individual.json()
        assert min(row["min_available_spaces"] for row in bundle.json()["weekday_hour_patterns"]) == 5

        async def verify_cache_source():
            async with client.app.state.session_factory() as session:
                caches = (await session.scalars(select(AnalyticsCache))).all()
                latest = await session.scalar(select(ParkingSnapshot.observed_at)
                                              .order_by(ParkingSnapshot.observed_at.desc()).limit(1))
                assert len(caches) == 8
                assert all(row.source_observed_at == latest for row in caches)
                assert all(serialize_utc(row.generated_at) > serialize_utc(latest) for row in caches)

        asyncio.run(verify_cache_source())


@pytest.mark.parametrize("partial_success", [False, True])
@pytest.mark.parametrize("cache_error", [RuntimeError("serviceKey=secret-refresh-key&phase=analytics"), TimeoutError(), RuntimeError("")],
                         ids=["message", "timeout_without_message", "runtime_without_message"])
def test_cache_failure_keeps_committed_source_and_zero_snapshot_tick_repairs_it(test_settings, monkeypatch, partial_success, cache_error):
    app, _settings, provider = parking_app(test_settings, monkeypatch, partial_success=partial_success)
    with TestClient(app) as client:
        assert dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False).success

        async def broken_cache_refresh(session, _settings):
            cached = await session.scalar(select(AnalyticsCache).where(AnalyticsCache.metric == "timeseries"))
            cached.payload_json = {"invalid": "rolled back"}
            await session.flush()
            raise cache_error

        monkeypatch.setattr(dagster_definitions, "refresh_default_analytics_cache", broken_cache_refresh)
        provider.observed_at += timedelta(minutes=10)
        provider.occupied_spaces = 95
        provider.fail_incheon = partial_success
        failed = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False)
        assert not failed.success
        assert not any(event.is_step_up_for_retry for event in failed.all_events)
        failure = failed.failure_data_for_node("collect_airport_parking").user_failure_data
        assert failure.metadata["status"].value == ("partial_success" if partial_success else "success")
        assert failure.description.startswith("공항 수집의 성공분은 저장했지만" if partial_success else "공항 관측은 저장했지만")
        assert "secret-refresh-key" not in failure.metadata["analytics_cache_error"].value
        if not str(cache_error):
            assert type(cache_error).__name__ in failure.metadata["analytics_cache_error"].value
        response = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
        assert response.status_code == 200
        assert response.json()["time_series"]["items"][-1]["available_spaces"] == 5

        async def verify_raw_commit_and_cache_rollback():
            async with client.app.state.session_factory() as session:
                snapshots = (await session.scalars(select(ParkingSnapshot))).all()
                assert len(snapshots) == 2
                cached = await session.scalar(select(AnalyticsCache).where(AnalyticsCache.metric == "timeseries"))
                assert cached.payload_json["items"][-1]["available_spaces"] == 80
                run = await session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
                assert run.status == ("partial_success" if partial_success else "success")

        asyncio.run(verify_raw_commit_and_cache_rollback())
        monkeypatch.setattr(dagster_definitions, "refresh_default_analytics_cache", refresh_default_analytics_cache)
        provider.fail_incheon = False
        repaired = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False)
        assert repaired.success
        assert repaired.output_for_node("collect_airport_parking")["snapshot_count"] == 0
        assert repaired.output_for_node("collect_airport_parking")["analytics_cache_count"] == 8
        assert client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"}).json()["time_series"]["items"][-1]["available_spaces"] == 5


_CACHE_PARAMETERS = {
    "timeseries": {"days": 7, "interval_minutes": 10},
    "weekday_hour": {"days": 14},
    "threshold_events": {"days": 14, "limit": 20},
    "threshold_insights": {"days": 21, "interval_minutes": 10},
}


@pytest.mark.parametrize("cache_state", ["expired", "future", "late_observation"])
def test_all_default_cache_reads_reject_old_or_changed_source(test_settings, monkeypatch, cache_state):
    app, _settings, _provider = parking_app(test_settings, monkeypatch)
    with TestClient(app) as client:
        assert dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False).success

        async def check():
            async with client.app.state.session_factory() as session:
                snapshot = await session.scalar(select(ParkingSnapshot))
                caches = (await session.scalars(select(AnalyticsCache))).all()
                for metric, params in _CACHE_PARAMETERS.items():
                    assert await load_cached_analytics(session, metric=metric, airport_code="GMP", parking_lot_id=None, **params) is not None
                if cache_state == "late_observation":
                    # 최대 observed_at은 그대로 두고 늦게 도착한 과거 관측을 추가한다.
                    session.add(ParkingSnapshot(
                        airport_id=snapshot.airport_id, parking_lot_id=snapshot.parking_lot_id,
                        source=snapshot.source, observed_at=snapshot.observed_at - timedelta(minutes=10),
                        collected_at=now_utc(), occupied_spaces=95, total_spaces=100, available_spaces=5,
                    ))
                else:
                    generated_at = now_utc() + (timedelta(hours=1) if cache_state == "future" else -MAX_ANALYTICS_CACHE_AGE - timedelta(seconds=1))
                    for row in caches:
                        row.generated_at = generated_at
                await session.commit()
                for metric, params in _CACHE_PARAMETERS.items():
                    for lot_id in (None, snapshot.parking_lot_id):
                        assert await load_cached_analytics(session, metric=metric, airport_code="GMP", parking_lot_id=lot_id, **params) is None

        asyncio.run(check())
        bundle = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
        assert bundle.status_code == 200
        assert bundle.json()["time_series"]["items"][-1]["available_spaces"] == 80
        if cache_state == "late_observation":
            assert min(row["min_available_spaces"] for row in bundle.json()["weekday_hour_patterns"]) == 5


def test_postgres_delayed_source_commit_and_concurrent_refresh_share_existing_lease(test_settings, monkeypatch):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("격리 PostgreSQL의 advisory lease 경합 검증")
    app, settings, provider = parking_app(test_settings, monkeypatch)
    with TestClient(app) as client:
        assert dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False).success
        provider.observed_at += timedelta(minutes=10)
        provider.occupied_spaces = 95
        service = CollectionService(settings, client=provider)
        flushed = asyncio.Event()
        resume = asyncio.Event()
        original_store = service._store_observations

        async def hold_before_commit(*args, **kwargs):
            count = await original_store(*args, **kwargs)
            flushed.set()
            await resume.wait()
            return count

        monkeypatch.setattr(service, "_store_observations", hold_before_commit)

        async def check():
            factory = client.app.state.session_factory
            held_after_commit = []
            async with factory() as writer:
                original_commit = writer.commit

                async def commit_with_lease_probe():
                    await original_commit()
                    async with factory() as observer:
                        acquired = await observer.scalar(text(
                            "SELECT pg_try_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"
                        ))
                        held_after_commit.append(acquired is False)
                        await observer.rollback()

                monkeypatch.setattr(writer, "commit", commit_with_lease_probe)
                collection = asyncio.create_task(service.collect(writer, trigger="test_delayed_airport_commit"))
                try:
                    await asyncio.wait_for(flushed.wait(), timeout=10)
                    async with factory() as observer:
                        assert await refresh_default_analytics_cache(observer, settings) == 0
                        cached = await load_cached_analytics(
                            observer, metric="timeseries", airport_code="GMP", parking_lot_id=None,
                            days=7, interval_minutes=10,
                        )
                        # 아직 commit되지 않은 관측 이전의 정상 결과다.
                        assert cached["items"][-1]["available_spaces"] == 80
                        await observer.rollback()
                    resume.set()
                    summary = await asyncio.wait_for(collection, timeout=10)
                    assert summary["snapshot_count"] == 1
                    assert held_after_commit == [True]
                finally:
                    resume.set()
                    if not collection.done():
                        collection.cancel()
                        await asyncio.gather(collection, return_exceptions=True)

            async with factory() as observer:
                assert await load_cached_analytics(
                    observer, metric="timeseries", airport_code="GMP", parking_lot_id=None,
                    days=7, interval_minutes=10,
                ) is None
            # 두 refresh도 같은 잠금에 들어가며, 롤백 뒤 다른 transaction이 재생성한다.
            async with factory() as first, factory() as second:
                assert await refresh_default_analytics_cache(first, settings) == 8
                assert await refresh_default_analytics_cache(second, settings) == 0
                await second.rollback()
                await first.rollback()
                assert await refresh_default_analytics_cache(second, settings) == 8
                await second.commit()

        asyncio.run(check())
        assert client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"}).json()["time_series"]["items"][-1]["available_spaces"] == 5
