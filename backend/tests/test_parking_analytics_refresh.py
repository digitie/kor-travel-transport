from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.time_utils import now_utc, serialize_utc, to_seoul
from app.dagster import definitions as dagster_definitions
from app.main import create_app
from app.models import AnalyticsCache, CollectionRun, ParkingSnapshot
from app.services.analytics_cache import (
    ANALYTICS_REFRESH_WARN_AFTER, DASHBOARD_REFRESH_GRACE, DASHBOARD_STALE_CACHE_MAX_AGE, MAX_ANALYTICS_CACHE_AGE,
    analytics_refresh_health, load_cached_analytics, refresh_default_analytics_cache,
)
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
        assert second.success
        summary = second.output_for_node("collect_airport_parking")
        assert summary["snapshot_count"] == 1
        expected_status = "partial_success" if partial_success else "success"
        assert summary["status"] == expected_status
        output = next(event.step_output_data for event in second.all_events
                      if event.event_type_value == "STEP_OUTPUT" and event.step_key == "collect_airport_parking")
        assert output.metadata["status"].value == expected_status
        assert output.metadata["collection_outcome"].value == ("partial" if partial_success else "success")
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
                source_run = await session.get(CollectionRun, summary["collection_run_id"])
                assert source_run.status == expected_status  # 부가 Dagster 태그가 원천 상태를 바꾸지 않는다.
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

        async def broken_cache_refresh(session, _settings, **_options):
            cached = await session.scalar(select(AnalyticsCache).where(AnalyticsCache.metric == "timeseries"))
            cached.payload_json = {"invalid": "rolled back"}
            await session.flush()
            raise cache_error

        monkeypatch.setattr(dagster_definitions, "refresh_default_analytics_cache", broken_cache_refresh)
        provider.observed_at += timedelta(minutes=10)
        provider.occupied_spaces = 95
        provider.fail_incheon = partial_success
        failed = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False)
        assert failed.success
        assert not any(event.is_step_up_for_retry for event in failed.all_events)
        output = next(event.step_output_data for event in failed.all_events
                      if event.event_type_value == "STEP_OUTPUT" and event.step_key == "collect_airport_parking")
        assert output.metadata["status"].value == ("partial_success" if partial_success else "success")
        assert output.metadata["collection_outcome"].value == "partial"
        assert output.metadata["cache_refresh_failed"].value is True
        assert "analytics_cache_error" not in output.metadata
        assert "secret-refresh-key" not in str(output.metadata)
        response = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
        assert response.status_code == 200
        # 새 적재가 갱신 유예 안이면 갱신 대기로 보고 직전 사전집계를 낸다(원본 계산으로 떨어지지 않는다).
        assert response.json()["time_series"]["items"][-1]["available_spaces"] == 80
        assert response.headers["x-analytics-source"] == "cache-grace"
        # 갱신이 실패한 채 유예가 지나면 원본에서 계산한다 — 실패한 갱신이 오래된 값을 계속 내게 하지 않는다.
        asyncio.run(_age_pending_refresh_past_grace(client))
        response = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
        assert response.json()["time_series"]["items"][-1]["available_spaces"] == 5
        assert response.headers["x-analytics-source"] == "source"

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
        repaired_bundle = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
        assert repaired_bundle.json()["time_series"]["items"][-1]["available_spaces"] == 5
        assert repaired_bundle.headers["x-analytics-source"] == "cache"


async def _age_pending_refresh_past_grace(client) -> None:
    """사전집계 생성 뒤 새 적재가 갱신 유예보다 오래된 상태로 시각을 옮긴다(사전집계는 최대 나이 안)."""
    async with client.app.state.session_factory() as session:
        caches = (await session.scalars(select(AnalyticsCache))).all()
        generated_at = min(row.generated_at for row in caches)
        now = now_utc()
        for snapshot in (await session.scalars(select(ParkingSnapshot))).all():
            pending = serialize_utc(snapshot.collected_at) > serialize_utc(generated_at)
            snapshot.collected_at = now - DASHBOARD_REFRESH_GRACE - timedelta(minutes=1 if pending else 3)
        for row in caches:
            row.generated_at = now - DASHBOARD_REFRESH_GRACE - timedelta(minutes=2)
        await session.commit()


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
            # 늦은 관측이 갱신 유예 안이면 직전 사전집계, 유예가 지나도 갱신이 없으면 원본 계산이다.
            assert min(row["min_available_spaces"] for row in bundle.json()["weekday_hour_patterns"]) == 80
            asyncio.run(_age_pending_refresh_past_grace(client))
            bundle = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
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


def test_refresh_grace_serves_only_a_pending_refresh_within_the_max_age(test_settings, monkeypatch):
    """대시보드 갱신 유예: 갱신 대기 중인 직전 사전집계만 낸다 — 너무 오래됐거나 갱신이 실패한 뒤에는 내지 않는다."""
    from app.services.analytics_cache import DASHBOARD_STALE_CACHE_MAX_AGE

    app, _settings, _provider = parking_app(test_settings, monkeypatch)
    params = _CACHE_PARAMETERS["timeseries"]
    with TestClient(app) as client:
        assert dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False).success

        async def check():
            async with client.app.state.session_factory() as session:
                caches = (await session.scalars(select(AnalyticsCache))).all()
                snapshot = await session.scalar(select(ParkingSnapshot))

                async def load(**options):
                    return await load_cached_analytics(session, metric="timeseries", airport_code="GMP",
                                                       parking_lot_id=None, **params, **options)

                async def move(generated_ago, collected_ago):
                    now = now_utc()
                    for row in caches:
                        row.generated_at = now - generated_ago
                    snapshot.collected_at = now - collected_ago
                    await session.commit()

                # 새 적재 없음, 엄격한 10분은 지났지만 최대 나이 안 → 유예로만 낸다.
                await move(MAX_ANALYTICS_CACHE_AGE + timedelta(minutes=5), MAX_ANALYTICS_CACHE_AGE + timedelta(minutes=6))
                assert await load() is None
                assert await load(refresh_grace=True) is not None
                # 최대 나이를 넘으면 유예로도 내지 않는다.
                await move(DASHBOARD_STALE_CACHE_MAX_AGE + timedelta(seconds=1), DASHBOARD_STALE_CACHE_MAX_AGE + timedelta(minutes=1))
                assert await load(refresh_grace=True) is None
                # 사전집계 뒤 새 적재가 유예 안이면 갱신 대기 → 직전 사전집계.
                await move(DASHBOARD_REFRESH_GRACE - timedelta(minutes=5), timedelta(minutes=1))
                assert await load(refresh_grace=True) is not None
                # 사전집계 뒤 새 적재가 유예보다 오래됐으면 갱신이 실패·중단된 것 → 내지 않는다.
                await move(DASHBOARD_REFRESH_GRACE + timedelta(minutes=5), DASHBOARD_REFRESH_GRACE + timedelta(minutes=1))
                assert await load(refresh_grace=True) is None

        asyncio.run(check())


def test_dashboard_reports_the_analytics_basis_time(test_settings, monkeypatch):
    """대시보드 묶음은 낸 분석의 기준 시각(가장 오래된 생성 시각)을 함께 낸다 — 유예로 낸 늦은 사전집계도 보인다."""
    app, _settings, provider = parking_app(test_settings, monkeypatch)
    with TestClient(app) as client:
        assert dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False).success

        def basis():
            response = client.get("/v1/dashboard/analytics", params={"airport_code": "GMP"})
            assert response.status_code == 200
            body = response.json()
            value = body["analytics_generated_at"]
            assert value is not None and value.endswith("Z")
            when = datetime.fromisoformat(value.replace("Z", "+00:00"))
            # 서버 시계로 잰 나이를 함께 낸다(화면이 브라우저 시계에 기대지 않게).
            assert abs(body["analytics_age_seconds"] - (now_utc() - when).total_seconds()) <= 5
            return when, response.headers["x-analytics-source"]

        async def caches():
            async with client.app.state.session_factory() as session:
                return {serialize_utc(row.generated_at) for row in (await session.scalars(select(AnalyticsCache))).all()}

        # 갱신 직후: 사전집계 생성 시각 그대로.
        generated = asyncio.run(caches())
        assert len(generated) == 1
        when, source = basis()
        assert source == "cache" and when == next(iter(generated))

        async def age_caches(delta):
            async with client.app.state.session_factory() as session:
                for row in (await session.scalars(select(AnalyticsCache))).all():
                    row.generated_at = row.generated_at - delta
                await session.commit()

        # 새 적재 뒤 갱신 대기(유예): 늦은 사전집계를 내고 그 시각을 그대로 알린다.
        asyncio.run(age_caches(timedelta(minutes=25)))
        provider.observed_at += timedelta(minutes=5)
        asyncio.run(_collect_without_refresh(client, provider))
        when, source = basis()
        assert source == "cache-grace"
        assert now_utc() - when >= timedelta(minutes=25)

        # 유예를 넘긴 갱신 실패: 원본 계산 → 기준 시각은 계산 시각(지금).
        asyncio.run(age_caches(DASHBOARD_REFRESH_GRACE))
        async def age_snapshots():
            async with client.app.state.session_factory() as session:
                for row in (await session.scalars(select(ParkingSnapshot))).all():
                    row.collected_at = row.collected_at - DASHBOARD_REFRESH_GRACE - timedelta(minutes=1)
                await session.commit()
        asyncio.run(age_snapshots())
        before = now_utc()
        when, source = basis()
        assert source == "source"
        assert before - timedelta(seconds=5) <= when <= now_utc()


async def _collect_without_refresh(client, provider) -> None:
    service = CollectionService(client.app.state.settings, client=provider)
    async with client.app.state.session_factory() as session:
        await service.collect(session, trigger="test")
        await session.commit()

def test_analytics_refresh_health_follows_the_dashboard_grace_rules(test_settings, monkeypatch):
    """ANALYTICS-REFRESH-ALERT: 미반영 적재 나이로 정상·지연(경보)·원본 계산(경보)·새 적재 없음을 가른다."""
    app, settings, _provider = parking_app(test_settings, monkeypatch)
    with TestClient(app) as client:
        async def empty():
            async with client.app.state.session_factory() as session:
                return await analytics_refresh_health(session, settings)

        assert asyncio.run(empty()).status == "empty"
        assert dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False).success

        async def check():
            async with client.app.state.session_factory() as session:
                caches = (await session.scalars(select(AnalyticsCache))).all()
                snapshot = await session.scalar(select(ParkingSnapshot))

                async def at(generated_ago, collected_ago):
                    now = now_utc()
                    for row in caches:
                        row.generated_at = now - generated_ago
                    snapshot.collected_at = now - collected_ago
                    await session.commit()
                    return await analytics_refresh_health(session, settings, now=now)

                health = await at(timedelta(minutes=1), timedelta(minutes=2))
                assert (health.status, health.alerting, health.pending_since) == ("ok", False, None)
                health = await at(timedelta(minutes=30), timedelta(minutes=10))
                assert (health.status, health.alerting) == ("ok", False)
                assert health.pending_seconds == 600
                health = await at(timedelta(minutes=30), ANALYTICS_REFRESH_WARN_AFTER)
                assert (health.status, health.alerting) == ("delayed", True)
                health = await at(timedelta(minutes=50), DASHBOARD_REFRESH_GRACE)
                assert (health.status, health.alerting) == ("stale", True)
                # 새 적재가 없어도 사전집계가 2시간을 넘기면 대시보드는 원본 계산이다(공항 job은 정상 tick마다 갱신한다).
                health = await at(DASHBOARD_STALE_CACHE_MAX_AGE + timedelta(minutes=1), timedelta(hours=3))
                assert (health.status, health.alerting, health.pending_since) == ("stale", True, None)
                assert health.generated_age_seconds == int((DASHBOARD_STALE_CACHE_MAX_AGE + timedelta(minutes=1)).total_seconds())
                assert health.as_dict()["generated_at"].endswith("+00:00")
                for row in caches:
                    await session.delete(row)
                await session.commit()
                # 첫 갱신 전(관측이 아직 경보 기준 안)은 경보가 아니다.
                snapshot.collected_at = now_utc() - timedelta(minutes=3)
                await session.commit()
                health = await analytics_refresh_health(session, settings)
                assert (health.status, health.alerting) == ("ok", False)
                snapshot.collected_at = now_utc() - ANALYTICS_REFRESH_WARN_AFTER
                await session.commit()
                health = await analytics_refresh_health(session, settings)
                assert (health.status, health.alerting) == ("missing", True)

        asyncio.run(check())


def test_airport_run_stays_success_and_is_tagged_when_refresh_falls_behind(test_settings, monkeypatch):
    """갱신 실패가 이어져 미반영 적재가 15분을 넘으면 run은 SUCCESS 그대로 두고 태그·metadata·로그로 알린다.

    수집은 성공했다 — 파생 캐시 상태로 run을 FAILURE로 만들지 않는다(감사 2026-11-23 §2.5의 부분 성공 FAILURE 소음).
    """
    from dagster import DagsterInstance

    app, _settings, provider = parking_app(test_settings, monkeypatch)
    with TestClient(app) as client, DagsterInstance.ephemeral() as instance:
        def run():
            result = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False, instance=instance)
            output = next(event.step_output_data for event in result.all_events
                          if event.event_type_value == "STEP_OUTPUT" and event.step_key == "collect_airport_parking")
            return result, output.metadata, instance.get_run_by_id(result.run_id).tags

        healthy, metadata, tags = run()
        assert healthy.success
        assert metadata["analytics_refresh_status"].value == "ok"
        assert "kortravel/analytics-refresh" not in tags

        async def broken_cache_refresh(_session, _settings, **_options):
            raise RuntimeError("refresh down")

        monkeypatch.setattr(dagster_definitions, "refresh_default_analytics_cache", broken_cache_refresh)
        provider.observed_at += timedelta(minutes=5)
        first_failure, metadata, tags = run()
        # 한 번의 실패(미반영 적재가 방금 것)는 경보가 아니다.
        assert first_failure.success and metadata["analytics_refresh_status"].value == "ok"
        assert "kortravel/analytics-refresh" not in tags

        async def age_pending(minutes):
            async with client.app.state.session_factory() as session:
                caches = (await session.scalars(select(AnalyticsCache))).all()
                generated_at = min(serialize_utc(row.generated_at) for row in caches)
                for snapshot in (await session.scalars(select(ParkingSnapshot))).all():
                    if serialize_utc(snapshot.collected_at) > generated_at:
                        snapshot.collected_at = now_utc() - timedelta(minutes=minutes)
                for row in caches:
                    row.generated_at = now_utc() - timedelta(minutes=minutes + 1)
                await session.commit()

        asyncio.run(age_pending(16))
        provider.observed_at += timedelta(minutes=5)
        behind, metadata, tags = run()
        assert behind.success
        assert behind.output_for_node("collect_airport_parking")["snapshot_count"] == 1
        assert metadata["analytics_refresh_status"].value == "delayed"
        assert metadata["analytics_pending_seconds"].value >= 16 * 60
        assert metadata["collection_outcome"].value == "partial"
        assert metadata["error_code"].value == "DERIVED_CACHE_DEFERRED"
        assert tags["kortravel/analytics-refresh"] == "delayed"
        alert = [entry.user_message for entry in instance.all_logs(behind.run_id)
                 if "analytics_refresh_alert" in (entry.user_message or "")]
        assert alert and '"status":"delayed"' in alert[0] and "refresh down" not in alert[0]

        # 갱신이 돌아오면 다음 run에서 바로 풀린다(새 run에는 태그가 없다).
        monkeypatch.setattr(dagster_definitions, "refresh_default_analytics_cache", refresh_default_analytics_cache)
        recovered, metadata, tags = run()
        assert recovered.success and metadata["analytics_refresh_status"].value == "ok"
        assert "kortravel/analytics-refresh" not in tags


def test_airport_run_survives_a_failing_health_check(test_settings, monkeypatch):
    """판정 질의가 실패해도 수집 결과와 run 상태를 바꾸지 않는다."""
    app, _settings, _provider = parking_app(test_settings, monkeypatch)

    async def broken_health(*_args, **_kwargs):
        raise RuntimeError("health down")

    monkeypatch.setattr(dagster_definitions, "analytics_refresh_health", broken_health)
    with TestClient(app):
        result = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False)
        assert result.success
        summary = result.output_for_node("collect_airport_parking")
        assert summary["analytics_refresh_check_error"] == "RuntimeError" and "analytics_refresh" not in summary
        assert summary["snapshot_count"] == 1


def test_lock_busy_refresh_is_reported_as_skipped(test_settings, monkeypatch):
    app, settings, _provider = parking_app(test_settings, monkeypatch)
    with TestClient(app) as client:
        if client.app.state.engine.dialect.name != "postgresql":
            pytest.skip("advisory lock 경합은 PostgreSQL에서만")

        async def check():
            factory = client.app.state.session_factory
            async with factory() as holder, factory() as session:
                assert await holder.scalar(text(
                    "SELECT pg_try_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"
                ))
                outcome = {}
                assert await refresh_default_analytics_cache(session, settings, outcome=outcome) == 0
                assert outcome == {"skipped": "lock_busy"}
                await holder.rollback()

        asyncio.run(check())


def test_provider_status_exposes_analytics_refresh_health(test_settings, monkeypatch):
    app, _settings, _provider = parking_app(test_settings, monkeypatch)
    with TestClient(app) as client:
        assert dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False).success
        body = client.get("/v1/transport/providers").json()["airport_analytics_cache"]
        assert body["status"] == "ok" and body["alerting"] is False
        assert body["generated_at"] and body["pending_since"] is None
        assert body["generated_age_seconds"] >= 0
        assert (body["warn_after_seconds"], body["fallback_after_seconds"]) == (900, 2400)

        async def broken_health(*_args, **_kwargs):
            raise RuntimeError("health down")

        from app.services import provider_status
        monkeypatch.setattr(provider_status, "analytics_refresh_health", broken_health)
        # 부가 판정 실패로 수집 상태 목록 전체가 500이 되지 않는다.
        response = client.get("/v1/transport/providers")
        assert response.status_code == 200 and response.json()["airport_analytics_cache"] is None


def test_slow_health_check_times_out_without_touching_the_collection(test_settings, monkeypatch):
    """판정이 상한을 넘겨도 수집 run은 SUCCESS이고, 판정 실패가 metadata에 남는다."""
    app, _settings, _provider = parking_app(test_settings, monkeypatch)

    async def slow_health(*_args, **_kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(dagster_definitions, "ANALYTICS_HEALTH_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(dagster_definitions, "analytics_refresh_health", slow_health)
    with TestClient(app):
        result = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False)
        assert result.success
        assert result.output_for_node("collect_airport_parking")["snapshot_count"] == 1
        output = next(event.step_output_data for event in result.all_events
                      if event.event_type_value == "STEP_OUTPUT" and event.step_key == "collect_airport_parking")
        assert output.metadata["analytics_refresh_check_error"].value == "TimeoutError"
        assert "analytics_refresh_status" not in output.metadata


def test_lock_busy_skip_reaches_run_metadata(test_settings, monkeypatch):
    app, _settings, _provider = parking_app(test_settings, monkeypatch)

    async def skipped_refresh(_session, _settings, *, outcome=None, **_options):
        outcome["skipped"] = "lock_busy"
        return 0

    monkeypatch.setattr(dagster_definitions, "refresh_default_analytics_cache", skipped_refresh)
    with TestClient(app):
        result = dagster_definitions.airport_collection_job.execute_in_process(raise_on_error=False)
        assert result.success
        output = next(event.step_output_data for event in result.all_events
                      if event.event_type_value == "STEP_OUTPUT" and event.step_key == "collect_airport_parking")
        assert output.metadata["cache_refresh_skipped"].value is True
        assert result.output_for_node("collect_airport_parking")["analytics_cache_skipped"] == "lock_busy"
