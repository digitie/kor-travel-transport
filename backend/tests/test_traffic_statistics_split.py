"""고속도로 소통 저장 transaction 축소(WLH-06·WLH missed) 회귀 시험.

- 값이 같은 반복 관측은 행별 UPDATE(executemany) 대신 batch당 한 문장으로 확인 시각·실행만 갱신하고, 통계 bucket을
  다시 만들지 않는다. (예전 코드도 SQLAlchemy가 바뀌지 않은 열을 SET에서 빼므로 원본 JSON을 다시 쓰지는 않았다.)
- 이번 저장이 바꾼 bucket의 5분 통계는 원본·성공 상태와 같은 transaction에서 commit된다(원자성 유지).
- 최근 두 시간 창 재대조는 원천 commit 뒤 별도 transaction이다. 실패해도 원본·current·성공 상태를 되돌리지 않고
  run 결과에 `traffic_statistics_refreshed=false`와 원인 코드(Dagster partial, `DERIVED_CACHE_DEFERRED`)로 남으며
  다음 실행이 고친다. 통계 쓰기는 transaction advisory lock으로 직렬화한다(겹친 실행의 unique 충돌 방지).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.core.time_utils import now_utc, serialize_utc
from app.dagster.definitions import _collection_failure_metadata, _collection_output_metadata
from app.db.session import create_engine_and_session_factory
from app.models import CollectionRun, HighwayTrafficSnapshot, TransportCollectionState
from app.services.transport_collection import (
    TRAFFIC_SOURCE,
    TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY,
    HighwayPayload,
    TrafficStoreReport,
    TransportCollectionService,
    _database_failure_reason,
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
    """KREX가 멈춘 구간의 같은 관측을 매 주기 돌려주면 확인 시각·실행만 batch당 한 문장(IN 목록)으로 갱신하고 bucket을
    다시 만들지 않는다. 예전 코드는 행마다 같은 UPDATE를 executemany로 보냈고(원본 JSON은 SQLAlchemy가 이미 SET에서
    뺐다) 그 과거 bucket을 매 실행 재집계했다. 값이 바뀐 정정은 예전처럼 원본까지 갱신한다(KREX 정정 반영 계약)."""

    async def check(factory, engine):
        service = TransportCollectionService(test_settings, FakeTransportProvider())
        base = await _flow()
        times = [datetime(2026, 10, 27, 9, minute, tzinfo=UTC) for minute in (0, 10, 20, 30, 40)]
        points = tuple(
            replace(base, conzone_id=f"repeat-{index}", updated_at=_iso(times[index]), raw={"revision": 1})
            for index in (0, 1, 2, 4)
        )
        async with factory() as session:
            first = await _run(session)
            report = TrafficStoreReport(rebuild_from=datetime(2026, 10, 27, 8, tzinfo=UTC))
            assert await service._store_traffic(session, first, points, report=report) == 4
            await session.commit()
            assert (report.inserted, report.changed, report.unchanged) == (4, 0, 0)
            assert report.affected_buckets == {times[0], times[1], times[2], times[4]}
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
                points[3],                                            # 같은 관측 그대로
            )
            report = TrafficStoreReport(rebuild_from=datetime(2026, 10, 27, 8, tzinfo=UTC))
            event.listen(engine.sync_engine, "before_cursor_execute", capture)
            try:
                assert await service._store_traffic(session, second, items, report=report) == 1
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", capture)
            await session.commit()
            assert (report.inserted, report.changed, report.unchanged) == (1, 2, 2)
            # 반복 관측(09:00·09:40)과 원본만 바뀐 관측(09:10)의 bucket은 다시 만들 대상이 아니다.
            assert report.affected_buckets == {times[2], times[3]}

            # 반복 관측 두 행은 수집 시각·실행만 IN 목록 한 문장(executemany 아님)으로 갱신한다.
            confirmation = [(statement, count) for statement, count in updates if "raw_item_json" not in statement]
            assert len(confirmation) == 1 and confirmation[0][1] == 1
            assert " IN (" in confirmation[0][0].upper()
            assert "collection_run_id" in confirmation[0][0] and "collected_at" in confirmation[0][0]
            # 값이 바뀐 정정 두 행만 원본 JSON을 쓴다.
            assert sum(count for statement, count in updates if "raw_item_json" in statement) == 2

            session.expire_all()
            rows = {row.conzone_id: row for row in (await session.scalars(select(HighwayTrafficSnapshot))).all()}
            assert len(rows) == 5
            assert all(row.collection_run_id == second for row in rows.values())
            assert all(serialize_utc(row.collected_at) >= serialize_utc(before["repeat-0"][2]) for row in rows.values())
            # 같은 행(PK)을 재사용하고, 반복 관측의 원본 JSON은 그대로, 정정은 새 원본이다.
            assert rows["repeat-0"].id == before["repeat-0"][0]
            assert rows["repeat-0"].raw_item_json == before["repeat-0"][1]
            assert rows["repeat-4"].raw_item_json == before["repeat-4"][1]
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
        # 처음 보는 멈춘 관측은 새 행이라 그 오래된 bucket을 한 번 만든다(창 밖 bucket 1).
        assert first["traffic_out_of_window_buckets"] == 1
        assert first["traffic_touched_buckets"] == 2  # 최근 관측 bucket 하나 + 멈춘 관측 bucket 하나
        assert len(windows) == 1 and windows[0] == _traffic_statistics_window_start(windows[0] + timedelta(hours=2))
        for step in ("raw_response", "history", "current_upsert", "touched_statistics", "commit", "statistics"):
            assert isinstance(first[f"traffic_{step}_seconds"], float)
        assert first["traffic_source_committed"] is True and "traffic_statistics_deferred_reason" not in first
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
            assert repeated["traffic_touched_buckets"] == repeated["traffic_out_of_window_buckets"] == 0
            assert await _stored_statistics(session) == await _recomputed_statistics(session)
            await _make_due(session)

        # 최근 창 밖의 과거 관측 정정은 예전처럼 원천 transaction에서 그 bucket만 다시 만든다.
        provider.items = (provider.items[0], provider.items[1], replace(provider.items[2], speed=35.0))
        async with factory() as session:
            corrected = await service.collect(session, trigger="test", scope="highway")
            assert corrected["status"] == "success"
            assert corrected["traffic_changed_rows"] == 1
            assert corrected["traffic_touched_buckets"] == corrected["traffic_out_of_window_buckets"] == 1
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
        assert deferred["traffic_statistics_deferred_reason"] == "statement_timeout"
        assert deferred["traffic_snapshot_count"] == 2
        metadata = _collection_output_metadata(deferred, "highway")
        assert metadata["collection_outcome"] == "partial"
        assert metadata["error_code"] == "DERIVED_CACHE_DEFERRED"
        assert metadata["traffic_statistics_refreshed"] is False
        assert metadata["traffic_statistics_deferred_reason"] == "statement_timeout"

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


def test_source_statement_timeout_rolls_back_touched_buckets_and_reports_partial_timings(test_settings) -> None:
    """바뀐 bucket 통계는 원본과 같은 transaction이다. 원천 commit 전에 실제 statement timeout으로 실패하면 통계도 함께
    되돌아가고, 실패한 실행에도 어느 단계에서 얼마를 썼는지·원인 코드·행 수가 run 요약과 실패 metadata에 남는다."""
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
        original = service._rebuild_traffic_statistics_range

        async def statement_timeout_in_touched(session, rebuild_from, rebuild_until=None):
            if rebuild_until is not None:
                await session.execute(text("SET LOCAL statement_timeout = '50ms'"))
                await session.execute(text("SELECT pg_sleep(1)"))
            return await original(session, rebuild_from, rebuild_until)

        service._rebuild_traffic_statistics_range = statement_timeout_in_touched
        async with factory() as session:
            failed = await service.collect(session, trigger="test", scope="highway")
            assert failed["status"] == "failed"
            assert failed["traffic_source_committed"] is False
            assert failed["traffic_failed_step"] == "touched_statistics"
            assert failed["traffic_store_failure_reason"] == "statement_timeout"
            assert (failed["traffic_inserted_rows"], failed["traffic_changed_rows"]) == (1, 1)
            assert {"traffic_raw_response_seconds", "traffic_history_seconds",
                    "traffic_touched_statistics_seconds"} <= failed.keys()
            assert "traffic_statistics_refreshed" not in failed and "traffic_commit_seconds" not in failed
            # 원본·통계 모두 앞 실행 그대로다.
            assert await _stored_statistics(session) == before == await _recomputed_statistics(session)
            assert await session.scalar(select(func.count()).select_from(HighwayTrafficSnapshot)) == 1
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == TRAFFIC_SOURCE))
            assert state.last_error
        # Dagster op가 Failure로 올리는 metadata에도 같은 진단이 실린다.
        metadata = _collection_failure_metadata(failed, "highway")
        assert metadata["traffic_store_failure_reason"] == "statement_timeout"
        assert metadata["traffic_failed_step"] == "touched_statistics"
        assert metadata["traffic_source_committed"] is False
        assert isinstance(metadata["traffic_history_seconds"], float)
        await service.close()

    _execute(test_settings, check)


def test_reconcile_defers_as_busy_while_another_transaction_holds_the_statistics_lock(test_settings) -> None:
    """창 재대조는 통계 잠금을 기다리지 않는다. 다른 transaction이 쥐고 있으면 `busy`로 미루고 다음 실행이 고친다."""
    test_settings.transport_collection_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        provider = ScriptedTrafficProvider()
        service = TransportCollectionService(test_settings, provider)
        base = await _flow()
        provider.items = (replace(base, conzone_id="busy-1", updated_at=_iso(now_utc() - timedelta(minutes=1))),)
        original = service._refresh_recent_traffic_statistics

        async def refresh_while_locked(session, rebuild_from):
            async with engine.connect() as holder:
                await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"),
                                     {"key": TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY})
                result = await original(session, rebuild_from)
                await holder.rollback()
            return result

        service._refresh_recent_traffic_statistics = refresh_while_locked
        async with factory() as session:
            busy = await service.collect(session, trigger="test", scope="highway")
        assert busy["status"] == "success" and busy["traffic_source_committed"] is True
        assert (busy["traffic_statistics_refreshed"], busy["traffic_statistics_deferred_reason"]) == (False, "busy")
        metadata = _collection_output_metadata(busy, "highway")
        assert (metadata["collection_outcome"], metadata["error_code"]) == ("partial", "DERIVED_CACHE_DEFERRED")
        assert metadata["traffic_statistics_deferred_reason"] == "busy"

        service._refresh_recent_traffic_statistics = original
        async with factory() as session:
            await _make_due(session)
            healed = await service.collect(session, trigger="test", scope="highway")
            assert healed["traffic_statistics_refreshed"] is True
            assert await _stored_statistics(session) == await _recomputed_statistics(session)
        await service.close()

    _execute(test_settings, check)


def test_reconcile_lock_timeout_on_statistics_rows_is_reported_and_keeps_source(test_settings) -> None:
    """수집 엔진(lock_timeout 5초)에서 창 재대조가 다른 transaction의 통계 행 잠금에 막히면 `lock_timeout`으로 미룬다.
    원천 transaction의 bucket 재구축은 그 행을 건드리지 않으므로 원천은 성공한다."""
    test_settings.transport_collection_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        collector_engine, collector_factory = create_engine_and_session_factory(test_settings.database_url,
                                                                                collector=True)
        try:
            provider = ScriptedTrafficProvider()
            service = TransportCollectionService(test_settings, provider)
            base = await _flow()
            now = now_utc()
            provider.items = (replace(base, conzone_id="lock-1", updated_at=_iso(now - timedelta(minutes=1))),)
            drift_bucket = _five_minute_bucket(now) - timedelta(minutes=90)
            async with factory() as session:
                await session.execute(text(
                    "INSERT INTO highway_traffic_five_minute_statistics (bucket_start, route_no_key, direction_key, "
                    "observations, speed_observations, speed_sum, minimum_speed, maximum_speed, "
                    "free_flow_speed_observations, free_flow_speed_sum, latest_observed_at) "
                    "VALUES (:bucket, 'drift', '', 1, 1, 1, 1, 1, 0, NULL, :bucket)"), {"bucket": drift_bucket})
                await session.commit()
            async with engine.connect() as holder:
                await holder.execute(text(
                    "SELECT 1 FROM highway_traffic_five_minute_statistics WHERE route_no_key = 'drift' FOR UPDATE"))
                async with collector_factory() as session:
                    result = await service.collect(session, trigger="test", scope="highway")
                await holder.rollback()
            assert result["status"] == "success" and result["traffic_source_committed"] is True
            assert result["traffic_statistics_refreshed"] is False
            assert result["traffic_statistics_deferred_reason"] == "lock_timeout"
            async with factory() as session:
                state = await session.scalar(select(TransportCollectionState).where(
                    TransportCollectionState.source == TRAFFIC_SOURCE))
                assert state.last_success_at is not None and state.last_error is None
                stored, recomputed = await _stored_statistics(session), await _recomputed_statistics(session)
                assert recomputed <= stored and {row[1] for row in stored - recomputed} == {"drift"}
            await service.close()
        finally:
            await collector_engine.dispose()

    _execute(test_settings, check)


def test_overlapping_run_waits_for_the_statistics_lock_instead_of_rolling_back_the_source(test_settings) -> None:
    """성공 표시가 창 재대조보다 먼저 commit되므로 다음(수동·관리자) 실행이 앞 실행의 재대조와 겹칠 수 있다. 원천
    transaction은 통계 잠금을 수집 기본 lock_timeout(5초)보다 길게 기다리고, unique 충돌이나 rollback 없이 끝난다."""
    test_settings.transport_collection_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        collector_engine, collector_factory = create_engine_and_session_factory(test_settings.database_url,
                                                                                collector=True)
        try:
            provider = ScriptedTrafficProvider()
            service = TransportCollectionService(test_settings, provider)
            base = await _flow()
            provider.items = (replace(base, conzone_id="overlap-1", updated_at=_iso(now_utc() - timedelta(minutes=1))),)
            holder = await engine.connect()
            # 앞 실행의 창 재대조가 통계 잠금을 쥔 상태를 흉내 낸다(6.5초 > 수집 기본 lock_timeout 5초).
            await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY})

            async def release_later() -> None:
                await asyncio.sleep(6.5)
                await holder.rollback()
                await holder.close()

            release = asyncio.create_task(release_later())
            async with collector_factory() as session:
                result = await service.collect(session, trigger="test", scope="highway")
            await release
            assert result["status"] == "success" and result["traffic_source_committed"] is True
            assert result["traffic_touched_statistics_seconds"] >= 5.5
            assert result["traffic_statistics_refreshed"] is True
            async with factory() as session:
                assert await _stored_statistics(session) == await _recomputed_statistics(session) != set()
                # 잠금 대기 뒤 수집 기본 lock_timeout으로 되돌렸다(같은 transaction 안에서만 늘렸다).
            async with collector_factory() as session:
                assert await session.scalar(text("SELECT current_setting('lock_timeout')")) == "5s"
            await service.close()
        finally:
            await collector_engine.dispose()

    _execute(test_settings, check)


class _FakeDriverError(Exception):
    def __init__(self, sqlstate: str | None) -> None:
        super().__init__("driver error")
        self.sqlstate = sqlstate


def test_database_failure_reason_codes_are_fixed_values() -> None:
    from sqlalchemy.exc import DBAPIError

    def db(sqlstate, invalidated=False):
        return DBAPIError("SELECT 1", {}, _FakeDriverError(sqlstate), connection_invalidated=invalidated)

    assert _database_failure_reason(db("57014")) == "statement_timeout"
    assert _database_failure_reason(db("55P03")) == "lock_timeout"
    assert _database_failure_reason(db("40P01")) == "deadlock"
    assert _database_failure_reason(db("40001")) == "serialization"
    assert _database_failure_reason(db("23505")) == "unique_violation"
    assert _database_failure_reason(db("08006")) == "connection"
    assert _database_failure_reason(db("57P01")) == "connection"
    assert _database_failure_reason(db(None, invalidated=True)) == "connection"
    assert _database_failure_reason(db("22P02")) == "sqlstate_22"
    assert _database_failure_reason(db("not-a-code")) == "database"
    assert _database_failure_reason(TimeoutError()) == "client_timeout"
    assert _database_failure_reason(ConnectionResetError()) == "connection"
    assert _database_failure_reason(asyncio.CancelledError()) == "cancelled"
    assert _database_failure_reason(RuntimeError("x")) == "other"


def test_traffic_store_metadata_is_bounded_and_marks_deferred_reconcile_partial() -> None:
    result = {
        "status": "success", "collection_run_id": 9, "errors": [], "traffic_snapshot_count": 8300,
        "traffic_inserted_rows": 8000, "traffic_changed_rows": 3, "traffic_unchanged_rows": 297,
        "traffic_touched_buckets": 2, "traffic_out_of_window_buckets": 0, "highway_fetch_seconds": 12.5,
        "traffic_history_seconds": 4.25, "traffic_statistics_seconds": 31.0, "traffic_commit_seconds": -1.0,
        "traffic_statistics_refreshed": True, "traffic_source_committed": True,
    }
    metadata = _collection_output_metadata(result, "highway")
    assert metadata["collection_outcome"] == "success"
    assert metadata["traffic_inserted_rows"] == 8000 and metadata["traffic_touched_buckets"] == 2
    assert metadata["highway_fetch_seconds"] == 12.5 and metadata["traffic_statistics_seconds"] == 31.0
    assert "traffic_commit_seconds" not in metadata  # 범위를 벗어난 값은 싣지 않는다.

    deferred = _collection_output_metadata({
        **result, "traffic_statistics_refreshed": False, "traffic_statistics_deferred_reason": "lock_timeout",
    }, "highway")
    assert (deferred["collection_outcome"], deferred["error_code"]) == ("partial", "DERIVED_CACHE_DEFERRED")
    assert deferred["traffic_statistics_deferred_reason"] == "lock_timeout"
    # 원인 코드는 고정 값·SQLSTATE 등급만 싣는다(임의 문자열·원문 금지).
    for value, kept in (("sqlstate_22", True), ("statement timeout; DROP", False), ("sqlstate_2", False)):
        reason = _collection_output_metadata({**result, "traffic_statistics_refreshed": False,
                                              "traffic_statistics_deferred_reason": value}, "highway")
        assert ("traffic_statistics_deferred_reason" in reason) is kept
    assert "traffic_failed_step" not in _collection_output_metadata({**result, "traffic_failed_step": "x"}, "highway")
    # 원천 오류가 함께 있으면 원천 분류를 유지한다(통계 지연이 원천 실패 원인을 덮지 않는다).
    with_errors = _collection_output_metadata({
        **result, "status": "partial_success", "traffic_statistics_refreshed": False,
        "errors": ["KrexQuotaExceededError: EXCEEDED_LIMIT"],
    }, "highway")
    assert with_errors["collection_outcome"] == "partial" and with_errors["error_code"] == "PROVIDER_RATE_LIMIT"
