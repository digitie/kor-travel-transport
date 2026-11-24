"""고속도로 소통 저장 transaction 축소(WLH-06·WLH missed) 회귀 시험.

- 값이 같은 반복 관측은 확인 시각·실행만 갱신하고 원본 JSON을 다시 쓰지 않는다. 통계 bucket도 다시 만들지 않는다.
- 이번 저장이 바꾼 bucket의 5분 통계는 원본·성공 상태와 같은 transaction에서 commit된다(원자성 유지).
- 최근 두 시간 창 재대조는 원천 commit 뒤 별도 transaction이다. 실패해도 원본·current·성공 상태를 되돌리지 않고
  run 결과에 `traffic_statistics_refreshed=false`(Dagster partial, `DERIVED_CACHE_DEFERRED`)로 남으며 다음 실행이 고친다.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.core.time_utils import now_utc, serialize_utc
from app.dagster.definitions import _collection_output_metadata
from app.models import CollectionRun, HighwayTrafficSnapshot, TransportCollectionState
from app.services.transport_collection import (
    TRAFFIC_SOURCE,
    HighwayPayload,
    TrafficStoreReport,
    TransportCollectionService,
    _five_minute_bucket,
    _traffic_statistics_window_start,
)
from sqlalchemy import event, func, select, text
from test_traffic_current import _execute, _flow, _run, replace
from test_transport_collection import FakeTransportProvider

STATISTICS_COLUMNS = (
    "bucket_start, route_no_key, direction_key, observations, speed_observations, speed_sum, minimum_speed, "
    "maximum_speed, free_flow_speed_observations, free_flow_speed_sum, latest_observed_at"
)
#: 원본 전체를 5분 집계로 다시 계산한 값. 저장된 통계는 원본에서 언제든 다시 만들 수 있는 파생 자료여야 한다.
RECOMPUTE_SQL = text("""
    SELECT date_bin(INTERVAL '5 minutes', observed_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket_start,
           COALESCE(route_no, ''), COALESCE(direction, ''), COUNT(*), COUNT(speed), SUM(speed), MIN(speed),
           MAX(speed), COUNT(free_flow_speed), SUM(free_flow_speed), MAX(observed_at)
    FROM highway_traffic_snapshots
    GROUP BY 1, 2, 3
""")


def _iso(value: datetime) -> str:
    return serialize_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_postgres(engine) -> None:
    if engine.dialect.name != "postgresql":
        pytest.skip("5분 통계(date_bin)는 PostgreSQL에서만 만든다")


async def _stored_statistics(session) -> set[tuple]:
    rows = await session.execute(text(f"SELECT {STATISTICS_COLUMNS} FROM highway_traffic_five_minute_statistics"))
    return {tuple(row) for row in rows}


async def _recomputed_statistics(session) -> set[tuple]:
    return {tuple(row) for row in await session.execute(RECOMPUTE_SQL)}


class ScriptedTrafficProvider(FakeTransportProvider):
    """소통 원천만 켠 provider. 매 실행 `items`를 완결 응답으로 돌려준다."""

    enabled_sources = (TRAFFIC_SOURCE,)

    def __init__(self) -> None:
        super().__init__()
        self.items: tuple = ()

    async def collect_highway(self, *, sources=(TRAFFIC_SOURCE,)) -> HighwayPayload:
        return HighwayPayload(traffic=self.items, incidents=None, complete_sources=(TRAFFIC_SOURCE,))


async def _make_due(session) -> None:
    state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == TRAFFIC_SOURCE))
    state.next_due_at = now_utc() - timedelta(seconds=1)
    await session.commit()


def test_five_minute_bucket_matches_date_bin_boundaries() -> None:
    assert _five_minute_bucket(datetime(2026, 11, 24, 3, 9, 59, 999, tzinfo=UTC)) == datetime(2026, 11, 24, 3, 5, tzinfo=UTC)
    assert _five_minute_bucket(datetime(2026, 11, 24, 12, 0, tzinfo=UTC)) == datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    # KST 입력도 UTC bucket으로 맞춘다(date_bin 원점 2000-01-01 00:00+00).
    kst = datetime(2026, 11, 24, 12, 7, tzinfo=UTC).astimezone(ZoneInfo("Asia/Seoul"))
    assert _five_minute_bucket(kst) == datetime(2026, 11, 24, 12, 5, tzinfo=UTC)
    assert _traffic_statistics_window_start(datetime(2026, 11, 24, 12, 7, tzinfo=UTC)) == datetime(
        2026, 11, 24, 10, 5, tzinfo=UTC)


def test_repeated_identical_observation_only_refreshes_confirmation(test_settings) -> None:
    """KREX가 멈춘 구간의 같은 관측을 매 주기 돌려줘도 원본 JSON·값 열을 다시 쓰지 않고 bucket도 다시 만들지 않는다.
    값이 바뀐 정정은 예전처럼 원본까지 갱신한다(KREX 정정 반영 계약)."""

    async def check(factory, engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        base = await _flow()
        times = [datetime(2026, 10, 27, 9, minute, tzinfo=UTC) for minute in (0, 10, 20, 30)]
        points = tuple(
            replace(base, conzone_id=f"repeat-{index}", updated_at=_iso(times[index]), raw={"revision": 1})
            for index in range(3)
        )
        async with factory() as session:
            first = await _run(session)
            report = TrafficStoreReport(rebuild_from=datetime(2026, 10, 27, 8, tzinfo=UTC))
            assert await service._store_traffic(session, first, points, report=report) == 3
            await session.commit()
            assert (report.inserted, report.changed, report.unchanged) == (3, 0, 0)
            assert report.affected_buckets == {times[0], times[1], times[2]}
            before = {row.conzone_id: (row.id, row.raw_item_json, row.collected_at)
                      for row in (await session.scalars(select(HighwayTrafficSnapshot))).all()}

            second = await _run(session)
            updates: list[tuple[str, int]] = []

            def capture(_connection, _cursor, statement, parameters, _context, executemany):
                if statement.lstrip().upper().startswith("UPDATE HIGHWAY_TRAFFIC_SNAPSHOTS"):
                    updates.append((statement, len(parameters) if executemany else 1))

            items = (
                points[0],                                            # 같은 관측 그대로
                replace(points[1], raw={"revision": 2}),              # 통계 입력이 아닌 원본만 정정
                replace(points[2], speed=45.0, raw={"revision": 2}),  # 속도 정정
                replace(base, conzone_id="repeat-new", updated_at=_iso(times[3])),  # 새 관측
            )
            report = TrafficStoreReport(rebuild_from=datetime(2026, 10, 27, 8, tzinfo=UTC))
            event.listen(engine.sync_engine, "before_cursor_execute", capture)
            try:
                assert await service._store_traffic(session, second, items, report=report) == 1
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", capture)
            await session.commit()
            assert (report.inserted, report.changed, report.unchanged) == (1, 2, 1)
            # 반복 관측(09:00)과 원본만 바뀐 관측(09:10)의 bucket은 다시 만들 대상이 아니다.
            assert report.affected_buckets == {times[2], times[3]}

            # 반복 관측은 수집 시각·실행만 한 문장으로 갱신한다. 원본 JSON을 쓰는 UPDATE는 정정 두 행뿐이다.
            confirmation = [statement for statement, _ in updates if "raw_item_json" not in statement]
            assert len(confirmation) == 1
            assert "collection_run_id" in confirmation[0] and "collected_at" in confirmation[0]
            assert sum(count for statement, count in updates if "raw_item_json" in statement) == 2

            session.expire_all()
            rows = {row.conzone_id: row for row in (await session.scalars(select(HighwayTrafficSnapshot))).all()}
            assert len(rows) == 4
            assert all(row.collection_run_id == second for row in rows.values())
            assert all(serialize_utc(row.collected_at) >= serialize_utc(before["repeat-0"][2]) for row in rows.values())
            # 같은 행(PK)을 재사용하고, 반복 관측의 원본 JSON은 그대로, 정정은 새 원본이다.
            assert rows["repeat-0"].id == before["repeat-0"][0]
            assert rows["repeat-0"].raw_item_json == before["repeat-0"][1]
            assert rows["repeat-1"].raw_item_json["raw"] == {"revision": 2}
            assert rows["repeat-2"].speed == 45.0 and rows["repeat-2"].raw_item_json["raw"] == {"revision": 2}

    _execute(test_settings, check)


def test_collect_commits_touched_buckets_with_source_and_reconciles_the_window_after_commit(test_settings) -> None:
    """원천 commit에는 이번 저장이 바꾼 bucket의 통계가 함께 들어간다. 최근 창 재대조는 그 commit이 끝난 뒤
    별도 transaction에서 한다(다른 연결에서 원본·성공 상태·바뀐 bucket이 이미 보인다). 결과는 원본 재계산과 같다."""
    test_settings.transport_collection_enabled = True
    test_settings.transport_map_current_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        provider = ScriptedTrafficProvider()
        service = TransportCollectionService(test_settings, provider)
        base = await _flow()
        now = now_utc()
        stale_at = now - timedelta(hours=5)  # 센서가 멈춘 구간: 최근 창 밖의 같은 관측을 매번 돌려준다.
        provider.items = (
            replace(base, conzone_id="live-1", updated_at=_iso(now - timedelta(minutes=2)), speed=80.0),
            replace(base, conzone_id="live-2", route_no="002", updated_at=_iso(now - timedelta(minutes=2)), speed=60.0),
            replace(base, conzone_id="stale-1", updated_at=_iso(stale_at), speed=30.0),
        )
        original = service._rebuild_traffic_statistics_range
        windows: list[datetime] = []

        async def observed(session, rebuild_from, rebuild_until=None):
            if rebuild_until is None:
                windows.append(rebuild_from)
                # 재대조 시작 시점: 다른 연결에서 이번 원본·성공 상태·바뀐 bucket 통계가 이미 commit돼 보여야 한다.
                async with factory() as other:
                    state = await other.scalar(select(TransportCollectionState).where(
                        TransportCollectionState.source == TRAFFIC_SOURCE))
                    assert state is not None and state.last_success_at is not None and state.last_error is None
                    assert await other.scalar(select(func.count()).select_from(HighwayTrafficSnapshot)) == 3
                    assert await _stored_statistics(other) == await _recomputed_statistics(other)
            return await original(session, rebuild_from, rebuild_until)

        service._rebuild_traffic_statistics_range = observed
        async with factory() as session:
            first = await service.collect(session, trigger="test", scope="highway")
        assert first["status"] == "success"
        assert first["traffic_statistics_refreshed"] is True
        assert (first["traffic_inserted_rows"], first["traffic_changed_rows"], first["traffic_unchanged_rows"]) == (3, 0, 0)
        # 처음 보는 멈춘 관측은 새 행이라 그 오래된 bucket을 한 번 만든다(정정 bucket 1).
        assert first["traffic_corrected_buckets"] == 1
        assert first["traffic_touched_buckets"] == 2  # 최근 관측 bucket 하나 + 멈춘 관측 bucket 하나
        assert len(windows) == 1 and windows[0] == _traffic_statistics_window_start(windows[0] + timedelta(hours=2))
        for step in ("raw_response", "history", "current_upsert", "touched_statistics", "commit", "statistics"):
            assert isinstance(first[f"traffic_{step}_seconds"], float)
        metadata = _collection_output_metadata(first, "highway")
        assert metadata["collection_outcome"] == "success" and "error_code" not in metadata
        assert metadata["traffic_touched_buckets"] == first["traffic_touched_buckets"]

        async with factory() as session:
            assert await _stored_statistics(session) == await _recomputed_statistics(session)
            await _make_due(session)

        # 같은 응답의 반복: 원본·통계 입력이 그대로라 원천 transaction은 bucket을 다시 만들지 않는다.
        async with factory() as session:
            repeated = await service.collect(session, trigger="test", scope="highway")
            assert repeated["status"] == "success"
            assert (repeated["traffic_inserted_rows"], repeated["traffic_changed_rows"],
                    repeated["traffic_unchanged_rows"]) == (0, 0, 3)
            assert repeated["traffic_touched_buckets"] == repeated["traffic_corrected_buckets"] == 0
            assert await _stored_statistics(session) == await _recomputed_statistics(session)
            await _make_due(session)

        # 최근 창 밖의 과거 관측 정정은 예전처럼 원천 transaction에서 그 bucket만 다시 만든다.
        provider.items = (provider.items[0], provider.items[1], replace(provider.items[2], speed=35.0))
        async with factory() as session:
            corrected = await service.collect(session, trigger="test", scope="highway")
            assert corrected["status"] == "success"
            assert corrected["traffic_changed_rows"] == 1
            assert corrected["traffic_touched_buckets"] == corrected["traffic_corrected_buckets"] == 1
            assert await _stored_statistics(session) == await _recomputed_statistics(session)
            stale_bucket = _five_minute_bucket(stale_at)
            assert any(row[0] == stale_bucket and row[6] == 35.0 for row in await _stored_statistics(session))
        await service.close()

    _execute(test_settings, check)


def test_reconcile_failure_between_commits_keeps_source_and_heals_on_the_next_run(test_settings) -> None:
    """원천 commit 뒤 재대조 transaction이 실제 PostgreSQL 오류(statement timeout)로 실패하는 경우.

    원본·current·성공 상태·이번 원본의 bucket 통계는 남고, run은 success지만 Dagster 결과는 partial
    (`DERIVED_CACHE_DEFERRED`)이다. 다음 실행의 재대조가 창 전체를 원본 재계산과 같게 되돌린다(멱등·자기 치유).
    """
    test_settings.transport_collection_enabled = True
    test_settings.transport_map_current_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        provider = ScriptedTrafficProvider()
        service = TransportCollectionService(test_settings, provider)
        base = await _flow()
        now = now_utc()
        provider.items = (
            replace(base, conzone_id="heal-1", updated_at=_iso(now - timedelta(minutes=1)), speed=70.0),
            replace(base, conzone_id="heal-2", updated_at=_iso(now - timedelta(minutes=40)), speed=50.0),
        )
        # 창 안의 원본 없는 통계 행: 재대조만 지운다(바뀐 bucket 재구축은 닿지 않는다).
        drift_bucket = _five_minute_bucket(now) - timedelta(minutes=90)
        async with factory() as session:
            await session.execute(text(
                "INSERT INTO highway_traffic_five_minute_statistics (bucket_start, route_no_key, direction_key, "
                "observations, speed_observations, speed_sum, minimum_speed, maximum_speed, "
                "free_flow_speed_observations, free_flow_speed_sum, latest_observed_at) "
                "VALUES (:bucket, 'drift', '', 9, 9, 900, 100, 100, 0, NULL, :bucket)"), {"bucket": drift_bucket})
            await session.commit()

        original = service._rebuild_traffic_statistics_range
        fail_window = True

        async def statement_timeout_in_window(session, rebuild_from, rebuild_until=None):
            if rebuild_until is None and fail_window:
                await session.execute(text("SET LOCAL statement_timeout = '50ms'"))
                await session.execute(text("SELECT pg_sleep(1)"))
            return await original(session, rebuild_from, rebuild_until)

        service._rebuild_traffic_statistics_range = statement_timeout_in_window
        async with factory() as session:
            deferred = await service.collect(session, trigger="test", scope="highway")
        assert deferred["status"] == "success" and deferred["errors"] == []
        assert deferred["traffic_statistics_refreshed"] is False
        assert deferred["traffic_snapshot_count"] == 2
        metadata = _collection_output_metadata(deferred, "highway")
        assert metadata["collection_outcome"] == "partial"
        assert metadata["error_code"] == "DERIVED_CACHE_DEFERRED"
        assert metadata["traffic_statistics_refreshed"] is False

        async with factory() as session:
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == TRAFFIC_SOURCE))
            assert state.last_success_at is not None and state.last_error is None
            assert state.next_due_at is not None
            assert await session.scalar(select(func.count()).select_from(HighwayTrafficSnapshot)) == 2
            run = await session.get(CollectionRun, deferred["collection_run_id"])
            assert run.status == "success"
            stored = await _stored_statistics(session)
            recomputed = await _recomputed_statistics(session)
            # 이번 원본의 bucket은 원천 commit과 함께 맞다. 재대조가 지울 창 안의 drift 행만 남았다.
            assert recomputed <= stored
            assert {row for row in stored - recomputed} == {row for row in stored if row[1] == "drift"}
            await _make_due(session)

        fail_window = False
        async with factory() as session:
            healed = await service.collect(session, trigger="test", scope="highway")
            assert healed["status"] == "success" and healed["traffic_statistics_refreshed"] is True
            assert _collection_output_metadata(healed, "highway")["collection_outcome"] == "success"
            assert await _stored_statistics(session) == await _recomputed_statistics(session)
        await service.close()

    _execute(test_settings, check)


def test_cancellation_between_commits_keeps_source_and_its_buckets(test_settings) -> None:
    """원천 commit 뒤 재대조 중 실행이 끊겨도(취소·프로세스 종료와 같은 경계) 원본과 그 bucket 통계는 이미 확정이다."""
    test_settings.transport_collection_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        provider = ScriptedTrafficProvider()
        service = TransportCollectionService(test_settings, provider)
        base = await _flow()
        provider.items = (replace(base, conzone_id="cancel-1", updated_at=_iso(now_utc() - timedelta(minutes=1))),)
        original = service._rebuild_traffic_statistics_range

        async def cancelled_window(session, rebuild_from, rebuild_until=None):
            if rebuild_until is None:
                raise asyncio.CancelledError
            return await original(session, rebuild_from, rebuild_until)

        service._rebuild_traffic_statistics_range = cancelled_window
        async with factory() as session:
            with pytest.raises(asyncio.CancelledError):
                await service.collect(session, trigger="test", scope="highway")
        async with factory() as session:
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == TRAFFIC_SOURCE))
            # 원천은 이미 commit된 성공이다. 취소는 run 원장만 실패로 닫는다(원천 상태를 오류로 덮지 않는다).
            assert state.last_success_at is not None and state.last_error is None
            assert await session.scalar(select(func.count()).select_from(HighwayTrafficSnapshot)) == 1
            assert await _stored_statistics(session) == await _recomputed_statistics(session) != set()
            run = await session.scalar(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(1))
            assert run.status == "failed" and run.error_message == "collection cancelled"
        await service.close()

    _execute(test_settings, check)


def test_source_failure_rolls_back_its_touched_buckets_with_the_source(test_settings) -> None:
    """바뀐 bucket 통계는 원본과 같은 transaction이다. 원천 commit 전에 실패하면 통계도 함께 되돌아간다."""
    test_settings.transport_collection_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        provider = ScriptedTrafficProvider()
        service = TransportCollectionService(test_settings, provider)
        base = await _flow()
        now = now_utc()
        provider.items = (replace(base, conzone_id="atomic-1", updated_at=_iso(now - timedelta(minutes=30))),)
        async with factory() as session:
            assert (await service.collect(session, trigger="test", scope="highway"))["status"] == "success"
            before = await _stored_statistics(session)
            await _make_due(session)

        provider.items = (
            replace(provider.items[0], speed=10.0),
            replace(base, conzone_id="atomic-2", updated_at=_iso(now - timedelta(minutes=1))),
        )
        mark = service._mark_source_success

        async def failing_mark(session, source, completed_at, **kwargs):
            if source == TRAFFIC_SOURCE:
                raise RuntimeError("state update failed after touched buckets")
            return await mark(session, source, completed_at, **kwargs)

        service._mark_source_success = failing_mark
        async with factory() as session:
            failed = await service.collect(session, trigger="test", scope="highway")
            assert failed["status"] == "failed"
            assert "traffic_statistics_refreshed" not in failed
            assert await _stored_statistics(session) == before == await _recomputed_statistics(session)
            assert await session.scalar(select(func.count()).select_from(HighwayTrafficSnapshot)) == 1
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == TRAFFIC_SOURCE))
            assert state.last_error
        await service.close()

    _execute(test_settings, check)


def test_traffic_store_metadata_is_bounded_and_marks_deferred_reconcile_partial() -> None:
    result = {
        "status": "success", "collection_run_id": 9, "errors": [], "traffic_snapshot_count": 8300,
        "traffic_inserted_rows": 8000, "traffic_changed_rows": 3, "traffic_unchanged_rows": 297,
        "traffic_touched_buckets": 2, "traffic_corrected_buckets": 0, "highway_fetch_seconds": 12.5,
        "traffic_history_seconds": 4.25, "traffic_statistics_seconds": 31.0, "traffic_commit_seconds": -1.0,
        "traffic_statistics_refreshed": True,
    }
    metadata = _collection_output_metadata(result, "highway")
    assert metadata["collection_outcome"] == "success"
    assert metadata["traffic_inserted_rows"] == 8000 and metadata["traffic_touched_buckets"] == 2
    assert metadata["highway_fetch_seconds"] == 12.5 and metadata["traffic_statistics_seconds"] == 31.0
    assert "traffic_commit_seconds" not in metadata  # 범위를 벗어난 값은 싣지 않는다.

    deferred = _collection_output_metadata({**result, "traffic_statistics_refreshed": False}, "highway")
    assert (deferred["collection_outcome"], deferred["error_code"]) == ("partial", "DERIVED_CACHE_DEFERRED")
    # 원천 오류가 함께 있으면 원천 분류를 유지한다(통계 지연이 원천 실패 원인을 덮지 않는다).
    with_errors = _collection_output_metadata({
        **result, "status": "partial_success", "traffic_statistics_refreshed": False,
        "errors": ["KrexQuotaExceededError: EXCEEDED_LIMIT"],
    }, "highway")
    assert with_errors["collection_outcome"] == "partial" and with_errors["error_code"] == "PROVIDER_RATE_LIMIT"
