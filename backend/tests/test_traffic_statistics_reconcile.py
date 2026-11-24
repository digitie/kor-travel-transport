"""소통 5분 통계 차이 기반 재대조와 장기 어긋남 복구 시험(WLH-06 후속).

- 재대조 뒤 범위의 통계는 원본 전체 재계산과 같고, 두 번째 재대조는 0행을 바꾼다(멱등). 값이 같은 행은 다시 쓰지
  않는다(같은 tuple·transaction id 미할당). 범위 밖은 건드리지 않는다. 정본에 없는 행만 지운다.
- 장기 복구는 최근 창보다 오래된 구간을 과거로 구간마다 commit하며 걸어가고, 예산·잠금·실패에서 멈춘 뒤 이어 한다.
  원본이 시작하기 전 구간은 지우지 않는다.
- 운영자 수동 재대조(확인 전용·적용·잠금 양보·예산 이어 하기)와 Dagster metadata·경고(어긋남은 실패가 아닌 경고).
"""
from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from app.core.time_utils import now_utc
from app.dagster.definitions import _collection_output_metadata
from app.db.session import create_engine_and_session_factory
from app.models import TransportCollectionState
from app.services.traffic_statistics import (
    TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY,
    TRAFFIC_STATISTICS_REPAIR_STATE,
    ReconcileResult,
    RepairOutcome,
    five_minute_bucket,
    next_bucket_boundary,
    reconcile_traffic_statistics,
    reconcile_traffic_statistics_range,
    repair_traffic_statistics,
)
from app.services.transport_collection import TransportCollectionService, _traffic_statistics_window_start
from sqlalchemy import select, text
from test_traffic_current import _execute, _flow, replace
from test_traffic_statistics_split import (
    RECOMPUTE_SQL,
    STATISTICS_COLUMNS,
    ScriptedTrafficProvider,
    _iso,
    _make_due,
    _recomputed_statistics,
    _require_postgres,
    _stored_statistics,
)

FIVE = timedelta(minutes=5)
#: 시험 원본의 기준(5분 경계, UTC).
BASE = datetime(2026, 11, 20, 0, 0, tzinfo=UTC)

#: 원본 전체 재계산으로 통계 표를 채운다(어긋남 없는 출발점).
REBUILD_ALL = text(f"""
    INSERT INTO highway_traffic_five_minute_statistics ({STATISTICS_COLUMNS})
    {RECOMPUTE_SQL.text}
""")


async def _seed_raw(session, start: datetime, hours: float, *, prefix: str = "seed") -> None:
    """`start`부터 `hours` 동안 2분 30초마다 노선 2개 + NULL 노선 × 방향 2개 + NULL 방향 관측을 넣는다."""
    await session.execute(text("""
        INSERT INTO highway_traffic_snapshots (source, identity_key, observed_at, collected_at, route_no, direction,
                                               speed, free_flow_speed)
        SELECT 'krex_traffic_flow', CAST(:prefix AS text) || '-' || coalesce(route, 'x') || '-' || coalesce(dir, 'x') || '-' || slot,
               CAST(:start AS timestamptz) + slot * INTERVAL '150 seconds',
               CAST(:start AS timestamptz) + slot * INTERVAL '150 seconds',
               route, dir,
               CASE WHEN slot % 7 = 0 THEN NULL ELSE 40 + (slot * 13 + length(coalesce(route, '')) * 5) % 70 END,
               CASE WHEN slot % 5 = 0 THEN NULL ELSE 100 END
        FROM generate_series(0, CAST(:slots AS integer) - 1) AS slot
        CROSS JOIN (VALUES ('001'), ('002'), (NULL)) AS routes(route)
        CROSS JOIN (VALUES ('S'), ('E'), (NULL)) AS dirs(dir)
    """), {"prefix": prefix, "start": start, "slots": int(hours * 3600 / 150)})


async def _rebuild_all(session) -> None:
    await session.execute(text("DELETE FROM highway_traffic_five_minute_statistics"))
    await session.execute(REBUILD_ALL)


async def _row_versions(session) -> dict[tuple, tuple[str, str]]:
    """통계 행별 (xmin, ctid). 다시 쓰인 행은 새 tuple이라 둘 다 바뀐다."""
    rows = await session.execute(text(
        "SELECT bucket_start, route_no_key, direction_key, xmin::text, ctid::text "
        "FROM highway_traffic_five_minute_statistics"))
    return {(row[0], row[1], row[2]): (row[3], row[4]) for row in rows}


def _in(rows: set[tuple], start: datetime, end: datetime | None) -> set[tuple]:
    return {row for row in rows if row[0] >= start and (end is None or row[0] < end)}


async def _corrupt(session, *, stale_bucket: datetime, orphan_bucket: datetime, missing_bucket: datetime) -> None:
    """범위 안에 값이 틀린 행 1·원본 없는 행 1·빠진 행 1을 만든다."""
    await session.execute(text(
        "UPDATE highway_traffic_five_minute_statistics SET speed_sum = speed_sum + 1000, maximum_speed = 999 "
        "WHERE bucket_start = :bucket AND route_no_key = '001' AND direction_key = 'S'"), {"bucket": stale_bucket})
    await session.execute(text(
        "INSERT INTO highway_traffic_five_minute_statistics (bucket_start, route_no_key, direction_key, observations, "
        "speed_observations, speed_sum, minimum_speed, maximum_speed, free_flow_speed_observations, "
        "free_flow_speed_sum, latest_observed_at) VALUES (:bucket, 'ghost', '', 3, 3, 30, 10, 10, 0, NULL, :bucket)"),
        {"bucket": orphan_bucket})
    await session.execute(text(
        "DELETE FROM highway_traffic_five_minute_statistics "
        "WHERE bucket_start = :bucket AND route_no_key = '002' AND direction_key = ''"), {"bucket": missing_bucket})


def test_range_boundaries_must_be_five_minute_aligned() -> None:
    async def check() -> None:
        for start, end in ((BASE + timedelta(minutes=1), None), (BASE, BASE + timedelta(minutes=7)),
                           (BASE, BASE), (BASE.replace(tzinfo=None), None)):
            with pytest.raises(ValueError):
                await reconcile_traffic_statistics(None, start, end)  # type: ignore[arg-type]

    asyncio.run(check())
    assert five_minute_bucket(datetime(2026, 11, 20, 9, 4, 59, tzinfo=UTC)) == datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    assert next_bucket_boundary(datetime(2026, 11, 20, 9, 0, tzinfo=UTC)) == datetime(2026, 11, 20, 9, 0, tzinfo=UTC)
    assert next_bucket_boundary(datetime(2026, 11, 20, 9, 0, 1, tzinfo=UTC)) == datetime(2026, 11, 20, 9, 5, tzinfo=UTC)


def test_diff_reconcile_equals_full_recompute_touches_only_drift_and_is_idempotent(test_settings) -> None:
    """범위 재대조는 원본 전체 재계산과 같아지고(어긋난 3행만 추가·수정·삭제), 같은 행은 다시 쓰지 않으며(같은 tuple),
    범위 밖의 틀린 행은 그대로 두고, 두 번째 재대조는 0행을 바꾼다(transaction id도 할당되지 않는다)."""

    async def check(factory, engine):
        _require_postgres(engine)
        start, end = BASE + timedelta(hours=2), BASE + timedelta(hours=4)
        async with factory() as session:
            await _seed_raw(session, BASE, 6)
            await _rebuild_all(session)
            await _corrupt(session, stale_bucket=start + FIVE * 3, orphan_bucket=start + FIVE * 7,
                           missing_bucket=end - FIVE)
            # 범위 밖(앞뒤)의 틀린 행: 이 범위의 재대조는 건드리지 않는다.
            await _corrupt(session, stale_bucket=start - FIVE, orphan_bucket=end, missing_bucket=start - FIVE * 2)
            await session.commit()
            before_versions = await _row_versions(session)
            outside_before = (await _stored_statistics(session)) - _in(await _stored_statistics(session), start, end)
            await session.commit()

        async with factory() as session:
            result = await reconcile_traffic_statistics(session, start, end, serial=True)
            await session.commit()
        assert (result.inserted, result.updated, result.deleted) == (1, 1, 1)
        assert result.changed == 3 and result.unchanged == result.canonical_rows - 2 > 100

        async with factory() as session:
            stored, recomputed = await _stored_statistics(session), await _recomputed_statistics(session)
            assert _in(stored, start, end) == _in(recomputed, start, end)
            # 범위 밖은 앞의 틀린 상태 그대로다(창 밖 어긋남은 그 구간의 재대조만 고친다).
            assert stored - _in(stored, start, end) == outside_before
            after_versions = await _row_versions(session)
            rewritten = {key for key, version in after_versions.items()
                         if key in before_versions and before_versions[key] != version}
            # 다시 쓴 행은 값이 틀렸던 한 행뿐이다. 나머지는 같은 tuple(xmin·ctid)이다.
            assert rewritten == {(start + FIVE * 3, "001", "S")}
            await session.commit()

        async with factory() as session:
            again = await reconcile_traffic_statistics(session, start, end, serial=True)
            # 어긋남이 없으면 아무것도 쓰지 않는다: 이 transaction에는 transaction id조차 할당되지 않았다.
            assert await session.scalar(text("SELECT pg_current_xact_id_if_assigned()")) is None
            await session.commit()
        assert again.changed == 0 and again.unchanged == result.canonical_rows

    _execute(test_settings, check)


def test_open_ended_window_reconcile_and_dry_run(test_settings) -> None:
    """끝이 없는 창 재대조(원천 commit 뒤 경로)는 그 뒤 전부를 맞추고, 확인 전용은 같은 수를 세되 쓰지 않는다."""

    async def check(factory, engine):
        _require_postgres(engine)
        start = BASE + timedelta(hours=4)
        async with factory() as session:
            await _seed_raw(session, BASE, 6)
            await _rebuild_all(session)
            # 창 끝보다 뒤(미래 관측 시각) bucket의 원본 없는 행도 끝이 없는 창은 지운다.
            await _corrupt(session, stale_bucket=start + FIVE, orphan_bucket=BASE + timedelta(hours=30),
                           missing_bucket=start + FIVE * 2)
            await session.commit()
        async with factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            preview = await reconcile_traffic_statistics(session, start, dry_run=True)
            assert await session.scalar(text("SELECT pg_current_xact_id_if_assigned()")) is None
            await session.rollback()
        async with factory() as session:
            applied = await reconcile_traffic_statistics(session, start)
            await session.commit()
            assert _in(await _stored_statistics(session), start, None) == _in(
                await _recomputed_statistics(session), start, None)
        assert preview.dry_run and not applied.dry_run
        assert (preview.inserted, preview.updated, preview.deleted) == (applied.inserted, applied.updated,
                                                                        applied.deleted) == (1, 1, 1)

    _execute(test_settings, check)


def test_float_sum_noise_is_not_drift_but_a_real_difference_is(test_settings) -> None:
    """배정밀도 합의 마지막 자리 차이(더하는 순서)는 어긋남이 아니다. 실제 값 차이는 고친다."""

    async def check(factory, engine):
        _require_postgres(engine)
        start, end = BASE, BASE + timedelta(hours=1)
        async with factory() as session:
            await _seed_raw(session, BASE, 1)
            await _rebuild_all(session)
            await session.execute(text(
                "UPDATE highway_traffic_five_minute_statistics SET speed_sum = speed_sum * (1 + 1e-13) "
                "WHERE bucket_start = :bucket AND speed_sum IS NOT NULL"), {"bucket": BASE})
            await session.commit()
        async with factory() as session:
            noise = await reconcile_traffic_statistics(session, start, end)
            await session.commit()
            assert noise.changed == 0
            await session.execute(text(
                "UPDATE highway_traffic_five_minute_statistics SET free_flow_speed_sum = free_flow_speed_sum + 0.5 "
                "WHERE bucket_start = :bucket AND route_no_key = '001' AND direction_key = 'E'"), {"bucket": BASE})
            await session.commit()
        async with factory() as session:
            real = await reconcile_traffic_statistics(session, start, end)
            await session.commit()
        assert (real.inserted, real.updated, real.deleted) == (0, 1, 0)

    _execute(test_settings, check)


async def _repair_state(session) -> TransportCollectionState | None:
    return await session.scalar(select(TransportCollectionState).where(
        TransportCollectionState.source == TRAFFIC_STATISTICS_REPAIR_STATE).execution_options(populate_existing=True))


async def _now_away_from_bucket_edge() -> datetime:
    """5분 경계 직전이면 넘긴 뒤의 현재 시각(시험 안에서 최근 창 시작이 바뀌지 않게)."""
    now = now_utc()
    remaining = (five_minute_bucket(now) + FIVE - now).total_seconds()
    if remaining < 20:
        await asyncio.sleep(remaining + 1)
        now = now_utc()
    return now


class FakeClock:
    def __init__(self, step: float) -> None:
        self.value, self.step = 0.0, step

    def __call__(self) -> float:
        self.value += self.step
        return self.value


def test_repair_walks_back_in_committed_chunks_resumes_after_budget_and_sweeps_daily(test_settings) -> None:
    """장기 복구: 최근 창 시작에서 과거로 2시간 구간마다 commit하고, 예산·구간 상한에서 멈춘 뒤 진행 원장의 위치부터
    이어 한다. 하한(지평과 가장 오래된 원본)에 닿으면 한 바퀴를 끝내고, 다음 한 바퀴는 하루 뒤에 시작한다. 창 안은 건드리지
    않는다."""

    async def check(factory, engine):
        _require_postgres(engine)
        window_start = BASE + timedelta(hours=10)
        async with factory() as session:
            # 원본은 BASE+00:01:00부터(첫 bucket은 온전하지 않다) 12시간.
            await _seed_raw(session, BASE + timedelta(minutes=1), 12)
            await _rebuild_all(session)
            # 원본이 시작하기 전 구간의 통계(원본 보존 정책으로 원본만 지워진 경우와 같다): 하한 밖이라 지우지 않는다.
            await _corrupt(session, stale_bucket=BASE, orphan_bucket=BASE - timedelta(hours=1),
                           missing_bucket=BASE - timedelta(hours=2))
            # 구간마다 어긋남: [8,10)·[6,8)·[4,6)·[0:05,2) — 그리고 창 안(10시 이후)의 원본 없는 행.
            for hour in (9, 7, 5, 1):
                await _corrupt(session, stale_bucket=BASE + timedelta(hours=hour),
                               orphan_bucket=BASE + timedelta(hours=hour, minutes=10),
                               missing_bucket=BASE + timedelta(hours=hour, minutes=20))
            await session.execute(text(
                "INSERT INTO highway_traffic_five_minute_statistics (bucket_start, route_no_key, direction_key, "
                "observations, speed_observations, speed_sum, minimum_speed, maximum_speed, "
                "free_flow_speed_observations, free_flow_speed_sum, latest_observed_at) "
                "VALUES (:bucket, 'in-window', '', 1, 1, 1, 1, 1, 0, NULL, :bucket)"),
                {"bucket": window_start + FIVE})
            await session.commit()
            before = await _stored_statistics(session)
            await session.commit()

        clock_now = [BASE + timedelta(hours=12)]
        common: dict[str, Any] = {"window_start": window_start, "horizon": timedelta(days=7),
                                  "now": lambda: clock_now[0]}
        async with factory() as session:
            first = await repair_traffic_statistics(session, max_chunks=2, **common)
        assert first.status == "repaired" and first.chunks == 2 and not first.sweep_complete
        assert (first.range_start, first.range_end) == (window_start - timedelta(hours=4), window_start)
        assert first.cursor == window_start - timedelta(hours=4)
        lower = BASE + FIVE  # 가장 오래된 원본(00:01)이 담긴 bucket은 온전하지 않아 다음 경계부터.
        assert first.horizon_start == lower
        assert (first.totals.inserted, first.totals.updated, first.totals.deleted) == (2, 2, 2)

        # 시간 예산: 첫 구간 뒤 예산이 지나 멈추고(budget_exhausted) 위치를 남긴다.
        async with factory() as session:
            second = await repair_traffic_statistics(session, budget_seconds=0.5, clock=FakeClock(1.0), **common)
        assert second.status == "repaired" and second.chunks == 1 and second.budget_exhausted
        assert (second.range_start, second.range_end) == (window_start - timedelta(hours=6), first.cursor)
        assert second.totals.changed == 3

        async with factory() as session:
            third = await repair_traffic_statistics(session, **common)
            state = await _repair_state(session)
            await session.commit()
        # 남은 [00:05, 04:00)은 2시간 + 1시간 55분 두 구간이고 하한에 닿아 한 바퀴를 끝냈다.
        assert third.status == "repaired" and third.chunks == 2 and third.sweep_complete and third.cursor is None
        assert (third.range_start, third.range_end) == (lower, second.range_start)
        assert third.totals.changed == 3
        assert state.next_due_at is None and state.last_success_at is not None and state.last_error is None

        async with factory() as session:
            stored, recomputed = await _stored_statistics(session), await _recomputed_statistics(session)
            assert _in(stored, lower, window_start) == _in(recomputed, lower, window_start)
            # 하한 앞(원본 없는 구간)과 창 안은 그대로다.
            assert _in(stored, BASE - timedelta(hours=3), lower) == _in(before, BASE - timedelta(hours=3), lower)
            assert _in(stored, window_start, None) == _in(before, window_start, None)

        # 한 바퀴를 막 끝냈으면 다음 한 바퀴는 시작 시각 + 24시간 뒤다.
        async with factory() as session:
            idle = await repair_traffic_statistics(session, **common)
        assert idle.status == "idle" and idle.chunks == 0 and idle.cursor is None
        clock_now[0] += timedelta(hours=24, minutes=1)
        async with factory() as session:
            await _corrupt(session, stale_bucket=BASE + timedelta(hours=9, minutes=30),
                           orphan_bucket=BASE + timedelta(hours=9, minutes=35),
                           missing_bucket=BASE + timedelta(hours=9, minutes=40))
            await session.commit()
            nxt = await repair_traffic_statistics(session, max_chunks=1, **common)
        assert nxt.status == "repaired" and nxt.range_end == window_start and nxt.totals.changed == 3

    _execute(test_settings, check)


def test_repair_yields_when_busy_and_retries_failed_chunk(test_settings) -> None:
    """다른 transaction이 통계 잠금을 쥐면 양보(busy)하고 위치를 그대로 둔다. 구간이 DB 오류로 실패하면 원인 코드를 남기고
    위치를 그대로 두어 다음 실행이 같은 구간부터 한다."""

    async def check(factory, engine):
        _require_postgres(engine)
        window_start = BASE + timedelta(hours=6)
        async with factory() as session:
            await _seed_raw(session, BASE, 6)
            await _rebuild_all(session)
            await _corrupt(session, stale_bucket=BASE + timedelta(hours=5), orphan_bucket=BASE + timedelta(hours=4),
                           missing_bucket=BASE + timedelta(hours=5, minutes=30))
            await session.commit()
        common: dict[str, Any] = {"window_start": window_start, "horizon": timedelta(days=7), "max_chunks": 1}

        async with engine.connect() as holder:
            await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY})
            async with factory() as session:
                busy = await repair_traffic_statistics(session, **common)
            await holder.rollback()
        assert busy.status == "busy" and busy.busy_skips == 1 and busy.chunks == 0 and busy.cursor is None

        async def statement_timeout(session, start, end, **_kwargs):
            await session.execute(text("SET LOCAL statement_timeout = '50ms'"))
            await session.execute(text("SELECT pg_sleep(1)"))
            raise AssertionError("unreachable")

        async with factory() as session:
            failed = await repair_traffic_statistics(session, reconcile=statement_timeout, **common)
            state = await _repair_state(session)
            await session.commit()
        assert (failed.status, failed.reason, failed.chunks) == ("failed", "statement_timeout", 0)
        # 새 한 바퀴의 첫 구간이 실패해도 막힌 위치(창 시작)와 원인·연속 실패 횟수가 원장에 보인다.
        assert state.next_due_at == window_start and state.last_error == "statement_timeout;failures=1"
        assert failed.cursor == window_start

        # 연속 실패는 같은 위치에서 구간 폭을 반씩 줄이고, 세 번째 실패 뒤에는 한 시간 쉰다(매 실행 문장 상한을 쓰지 않게).
        clock_now = [now_utc()]
        widths: list[timedelta] = []

        async def failing_again(session, start, end, **kwargs):
            widths.append(end - start)
            return await statement_timeout(session, start, end, **kwargs)

        for expected in ("statement_timeout;failures=2", "statement_timeout;failures=3"):
            async with factory() as session:
                again = await repair_traffic_statistics(session, reconcile=failing_again, now=lambda: clock_now[0],
                                                        **common)
                state = await _repair_state(session)
                await session.commit()
            assert again.status == "failed" and state.last_error == expected and state.next_due_at == window_start
        assert widths == [timedelta(hours=1), timedelta(minutes=30)]
        async with factory() as session:
            backoff = await repair_traffic_statistics(session, reconcile=failing_again, now=lambda: clock_now[0],
                                                      **common)
        assert (backoff.status, backoff.reason, backoff.chunks) == ("deferred", "failure_backoff", 0)
        assert len(widths) == 2

        # 쉬는 시간이 지나면 가장 좁은 구간(15분)으로 다시 하고, 성공하면 원인·횟수를 지운다.
        clock_now[0] += timedelta(hours=1, minutes=1)
        async with factory() as session:
            healed = await repair_traffic_statistics(session, now=lambda: clock_now[0], **common)
            state = await _repair_state(session)
            await session.commit()
        assert healed.status == "repaired" and healed.range_end == window_start
        assert healed.range_start == window_start - timedelta(minutes=15)
        assert state.last_error is None and healed.cursor == window_start - timedelta(minutes=15)
        async with factory() as session:
            rest = await repair_traffic_statistics(session, now=lambda: clock_now[0], **{**common, "max_chunks": 12})
        assert rest.sweep_complete and healed.totals.changed + rest.totals.changed == 3

    _execute(test_settings, check)


def test_repair_validates_chunk_and_horizon_alignment() -> None:
    async def check() -> None:
        for kwargs in ({"chunk": timedelta(minutes=7)}, {"chunk": timedelta(0)}, {"horizon": timedelta(0)},
                       {"window_start": BASE + timedelta(minutes=2)}):
            arguments = {"window_start": BASE, "horizon": timedelta(days=7), **kwargs}
            with pytest.raises(ValueError):
                await repair_traffic_statistics(None, **arguments)  # type: ignore[arg-type]

    asyncio.run(check())


def test_collect_reports_window_drift_and_runs_repair_slice_without_partial(test_settings) -> None:
    """고속도로 수집: 최근 창 재대조가 어긋남을 고치면 행 수를 싣되 결과는 success(partial 아님)이고, 장기 복구 조각이
    창보다 오래된 어긋남을 고친다. 두 번째 실행의 창 재대조는 0행을 바꾼다. 수집 상태 목록에는 진행 원장이 없다."""
    test_settings.transport_collection_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        provider = ScriptedTrafficProvider()
        service = TransportCollectionService(test_settings, provider)
        base = await _flow()
        now = await _now_away_from_bucket_edge()
        window_start = _traffic_statistics_window_start(now)
        provider.items = (replace(base, conzone_id="live-1", updated_at=_iso(now - timedelta(minutes=1))),)
        async with factory() as session:
            await _seed_raw(session, window_start - timedelta(hours=8), 9)
            await _rebuild_all(session)
            # 창 안(이번 원본이 닿지 않는 bucket)과 창 밖 3시간 전의 어긋남.
            await _corrupt(session, stale_bucket=window_start + FIVE * 2, orphan_bucket=window_start + FIVE * 3,
                           missing_bucket=window_start + FIVE * 4)
            await _corrupt(session, stale_bucket=window_start - timedelta(hours=3),
                           orphan_bucket=window_start - timedelta(hours=3, minutes=5),
                           missing_bucket=window_start - timedelta(hours=1))
            await session.commit()

        async with factory() as session:
            first = await service.collect(session, trigger="test", scope="highway")
        assert first["status"] == "success" and first["traffic_statistics_refreshed"] is True
        assert (first["traffic_statistics_inserted_rows"], first["traffic_statistics_updated_rows"],
                first["traffic_statistics_deleted_rows"], first["traffic_statistics_drift_rows"]) == (1, 1, 1, 3)
        assert first["traffic_touched_statistics_rows"] >= 1  # 이번 원본의 bucket(원천 transaction 안)
        assert first["traffic_statistics_repair_status"] == "repaired"
        assert first["traffic_statistics_repair_drift_rows"] == 3
        assert first["traffic_statistics_repair_range_end"] == _iso(window_start)
        metadata = _collection_output_metadata(first, "highway")
        assert metadata["collection_outcome"] == "success" and "error_code" not in metadata
        assert metadata["traffic_statistics_drift_rows"] == 3
        assert metadata["traffic_statistics_repair_drift_rows"] == 3
        assert metadata["traffic_statistics_repair_status"] == "repaired"
        assert isinstance(metadata["traffic_statistics_repair_seconds"], float)
        assert metadata["traffic_statistics_repair_range_end"] == _iso(window_start)

        async with factory() as session:
            assert await _stored_statistics(session) == await _recomputed_statistics(session)
            status = await service.status(session)
            assert TRAFFIC_STATISTICS_REPAIR_STATE not in {item["source"] for item in status["sources"]}
            await _make_due(session)
        async with factory() as session:
            second = await service.collect(session, trigger="test", scope="highway")
        assert second["traffic_statistics_drift_rows"] == 0 and second["traffic_statistics_unchanged_rows"] > 0
        await service.close()

    _execute(test_settings, check)


def test_collect_defers_repair_when_window_reconcile_failed_or_disabled(test_settings) -> None:
    """최근 창 재대조가 실패한 실행은 장기 복구를 건너뛴다(DB 부하 신호). 지평 0이면 복구 키가 없다."""
    test_settings.transport_collection_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        provider = ScriptedTrafficProvider()
        service = TransportCollectionService(test_settings, provider)
        base = await _flow()
        provider.items = (replace(base, conzone_id="defer-1", updated_at=_iso(now_utc() - timedelta(minutes=1))),)
        original = service._rebuild_traffic_statistics_range

        async def failing_window(session, rebuild_from, rebuild_until=None):
            if rebuild_until is None:
                await session.execute(text("SET LOCAL statement_timeout = '50ms'"))
                await session.execute(text("SELECT pg_sleep(1)"))
            return await original(session, rebuild_from, rebuild_until)

        service._rebuild_traffic_statistics_range = failing_window
        async with factory() as session:
            deferred = await service.collect(session, trigger="test", scope="highway")
        assert deferred["traffic_statistics_refreshed"] is False
        assert (deferred["traffic_statistics_repair_status"], deferred["traffic_statistics_repair_reason"]) == (
            "deferred", "window_deferred")
        metadata = _collection_output_metadata(deferred, "highway")
        assert metadata["traffic_statistics_repair_reason"] == "window_deferred"
        assert metadata["collection_outcome"] == "partial"  # 창 재대조 실패는 예전대로 partial이다.

        service._rebuild_traffic_statistics_range = original
        test_settings.transport_traffic_statistics_repair_horizon_hours = 0
        async with factory() as session:
            await _make_due(session)
            off = await service.collect(session, trigger="test", scope="highway")
        assert off["traffic_statistics_refreshed"] is True
        assert not any(key.startswith("traffic_statistics_repair") for key in off)
        await service.close()

    _execute(test_settings, check)


def test_source_touched_buckets_wait_for_a_concurrent_reconcile_and_both_stay_consistent(test_settings) -> None:
    """다른 transaction의 재대조(장기 복구·수동)가 통계 잠금을 쥔 채 같은 범위를 쓰는 동안 고속도로 원천 transaction은 바뀐
    bucket을 쓰기 전에 기다리고, 그 commit 뒤 자기 bucket을 차이 기반으로 맞춘다 — unique 충돌·rollback 없이 끝나고 결과는
    원본 재계산과 같다."""
    test_settings.transport_collection_enabled = True

    async def check(factory, engine):
        _require_postgres(engine)
        collector_engine, collector_factory = create_engine_and_session_factory(test_settings.database_url,
                                                                                collector=True)
        try:
            provider = ScriptedTrafficProvider()
            service = TransportCollectionService(test_settings, provider)
            base = await _flow()
            now = await _now_away_from_bucket_edge()
            window_start = _traffic_statistics_window_start(now)
            provider.items = (replace(base, conzone_id="race-1", updated_at=_iso(now - timedelta(minutes=1))),)
            async with factory() as session:
                await _seed_raw(session, window_start - timedelta(hours=1), 2)
                await _rebuild_all(session)
                await _corrupt(session, stale_bucket=window_start + FIVE, orphan_bucket=window_start + FIVE * 2,
                               missing_bucket=window_start + FIVE * 3)
                await session.commit()

            holder = factory()
            await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY})
            # 잠금을 쥔 transaction이 원천이 곧 쓸 bucket을 포함한 창 전체를 맞추되 아직 commit하지 않았다.
            held = await reconcile_traffic_statistics(holder, window_start)
            assert held.changed == 3

            async def release_later() -> None:
                await asyncio.sleep(6.5)  # 수집 기본 lock_timeout(5초)보다 길게
                await holder.commit()
                await holder.close()

            release = asyncio.create_task(release_later())
            async with collector_factory() as session:
                result = await service.collect(session, trigger="test", scope="highway")
            await release
            assert result["status"] == "success" and result["traffic_source_committed"] is True
            assert result["traffic_touched_statistics_seconds"] >= 5.5
            assert result["traffic_statistics_refreshed"] is True and result["traffic_statistics_drift_rows"] == 0
            async with factory() as session:
                assert await _stored_statistics(session) == await _recomputed_statistics(session)
            await service.close()
        finally:
            await collector_engine.dispose()

    _execute(test_settings, check)


def _load_script():
    script = next(root / "scripts/reconcile-traffic-statistics.py"
                  for root in (Path(__file__).parents[2], Path(__file__).parents[1])
                  if (root / "scripts/reconcile-traffic-statistics.py").is_file())
    spec = importlib.util.spec_from_file_location("reconcile_traffic_statistics_script", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manual_script_parses_kst_range_to_utc_buckets() -> None:
    module = _load_script()
    start, end = module.parse_range("2026-11-20T09:03", "2026-11-20T11:01+09:00")
    assert (start, end) == (datetime(2026, 11, 20, 0, 0, tzinfo=UTC), datetime(2026, 11, 20, 2, 5, tzinfo=UTC))
    for bad in (("2026-11-20T10:00", "2026-11-20T09:00"), ("2026-01-01T00:00", "2026-11-01T00:00")):
        with pytest.raises(ValueError):
            module.parse_range(*bad)
    # 잘못된 입력은 DB에 닿기 전에 traceback 없이 argparse 오류(종료 코드 2)로 끝난다.
    for argv in (["--start", "2026-11-20T10:00", "--end", "2026-11-20T09:00"],
                 ["--start", "not-a-time", "--end", "2026-11-20T09:00"],
                 ["--start", "2026-11-20T00:00", "--end", "2026-11-20T09:00", "--chunk-hours", "0.1"],
                 ["--start", "2026-11-20T00:00", "--end", "2026-11-20T09:00", "--chunk-hours", "24"],
                 ["--start", "2026-11-20T00:00", "--end", "2026-11-20T09:00", "--chunk-hours", "0"]):
        with pytest.raises(SystemExit) as exited:
            module.main(argv)
        assert exited.value.code == 2
    assert module.chunk_hours("0.25") == 0.25 and module.chunk_hours("6") == 6.0


def test_manual_range_dry_run_apply_busy_and_budget_resume(test_settings, capsys) -> None:
    """수동 재대조: 확인 전용은 쓰지 않고 수만 세며, 적용은 구간마다 commit한다. 잠금을 쥔 동안은 멈추고 이어 할 시작을
    알려 주며, 예산이 지나면 다음 구간을 시작하지 않는다. 스크립트는 같은 구현을 쓴다."""

    async def check(factory, engine):
        _require_postgres(engine)
        start, end = BASE, BASE + timedelta(hours=6)
        async with factory() as session:
            await _seed_raw(session, BASE, 6)
            await _rebuild_all(session)
            for hour in (1, 3, 5):
                await _corrupt(session, stale_bucket=BASE + timedelta(hours=hour),
                               orphan_bucket=BASE + timedelta(hours=hour, minutes=10),
                               missing_bucket=BASE + timedelta(hours=hour, minutes=20))
            await session.commit()
            before = await _stored_statistics(session)
            await session.commit()

        module = _load_script()
        assert await module.run(start, end, chunk_hours=2, dry_run=True, budget_seconds=None,
                                database_url=test_settings.database_url) == 0
        printed = capsys.readouterr().out
        assert "확인(쓰기 없음): 구간 3개, 어긋나 바꿀 행 9" in printed
        async with factory() as session:
            assert await _stored_statistics(session) == before

        async with engine.connect() as holder:
            await holder.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY})
            async with factory() as session:
                busy = await reconcile_traffic_statistics_range(session, start, end, busy_retries=1,
                                                                busy_wait_seconds=0.05)
            await holder.rollback()
        assert busy.stopped == "busy" and busy.resume_from == start and not busy.chunks

        async with factory() as session:
            partial = await reconcile_traffic_statistics_range(session, start, end, budget_seconds=0.5,
                                                               clock=FakeClock(1.0))
        assert partial.stopped == "budget" and len(partial.chunks) == 1 and partial.resume_from == start + timedelta(hours=2)
        assert partial.totals.changed == 3

        assert await module.run(partial.resume_from, end, chunk_hours=2, dry_run=False, budget_seconds=None,
                                database_url=test_settings.database_url) == 0
        assert "적용: 구간 2개, 어긋나 바꾼 행 6" in capsys.readouterr().out
        async with factory() as session:
            assert _in(await _stored_statistics(session), start, end) == _in(
                await _recomputed_statistics(session), start, end)

    _execute(test_settings, check)


def test_manual_range_skips_before_oldest_raw_unless_forced(test_settings) -> None:
    """수동 재대조도 장기 복구와 같이 가장 오래된 원본이 담긴 첫 온전한 bucket보다 앞은 건너뛴다(원본이 지워진 기간의
    통계를 지우지 않게). 명시적으로 포함하면 그 구간의 원본 없는 행을 지운다."""

    async def check(factory, engine):
        _require_postgres(engine)
        raw_start = BASE + timedelta(hours=2, minutes=1)
        async with factory() as session:
            await _seed_raw(session, raw_start, 2)
            await _rebuild_all(session)
            await _corrupt(session, stale_bucket=BASE + timedelta(hours=3), orphan_bucket=BASE + timedelta(hours=1),
                           missing_bucket=BASE + timedelta(hours=3, minutes=30))
            await session.commit()
        async with factory() as session:
            kept = await reconcile_traffic_statistics_range(session, BASE, BASE + timedelta(hours=4))
            assert any(row[1] == "ghost" for row in await _stored_statistics(session))
            await session.commit()
        assert kept.clamped_to == next_bucket_boundary(raw_start) == BASE + timedelta(hours=2, minutes=5)
        assert (kept.totals.inserted, kept.totals.updated, kept.totals.deleted) == (1, 1, 0)
        async with factory() as session:
            forced = await reconcile_traffic_statistics_range(session, BASE, BASE + timedelta(hours=4),
                                                              include_before_oldest_raw=True)
            assert not any(row[1] == "ghost" for row in await _stored_statistics(session))
            await session.commit()
        assert forced.clamped_to is None and (forced.totals.deleted, forced.totals.changed) == (1, 1)

    _execute(test_settings, check)


def test_repair_metadata_is_bounded_and_drift_is_not_a_failure() -> None:
    result = {
        "status": "success", "collection_run_id": 3, "errors": [], "traffic_snapshot_count": 10,
        "traffic_statistics_refreshed": True, "traffic_source_committed": True,
        "traffic_statistics_inserted_rows": 1, "traffic_statistics_updated_rows": 0,
        "traffic_statistics_deleted_rows": 2, "traffic_statistics_unchanged_rows": 400,
        "traffic_statistics_drift_rows": 3, "traffic_touched_statistics_rows": 12,
        **RepairOutcome(status="repaired", chunks=2, range_start=BASE, range_end=BASE + timedelta(hours=4),
                        cursor=BASE, horizon_start=BASE - timedelta(days=7), budget_exhausted=True,
                        seconds=1.25).summary(),
    }
    metadata = _collection_output_metadata(result, "highway")
    assert metadata["collection_outcome"] == "success" and "error_code" not in metadata
    assert metadata["traffic_statistics_drift_rows"] == 3 and metadata["traffic_touched_statistics_rows"] == 12
    assert metadata["traffic_statistics_repair_status"] == "repaired"
    assert metadata["traffic_statistics_repair_range_start"] == "2026-11-20T00:00:00Z"
    assert metadata["traffic_statistics_repair_horizon_start"] == "2026-11-13T00:00:00Z"
    assert metadata["traffic_statistics_repair_budget_exhausted"] is True
    assert metadata["traffic_statistics_repair_seconds"] == 1.25
    for key, value in (("traffic_statistics_repair_status", "exploded"),
                       ("traffic_statistics_repair_reason", "statement timeout; DROP"),
                       ("traffic_statistics_repair_range_start", "2026-11-20 00:00"),
                       ("traffic_statistics_repair_cursor", "private-canary")):
        assert key not in _collection_output_metadata({**result, key: value}, "highway")
    failed = _collection_output_metadata({**result, **RepairOutcome(status="failed", reason="sqlstate_53").summary()},
                                         "highway")
    assert (failed["traffic_statistics_repair_status"], failed["traffic_statistics_repair_reason"]) == (
        "failed", "sqlstate_53")
    assert failed["collection_outcome"] == "success"


def test_repair_keeps_statistics_of_buckets_without_any_raw(test_settings) -> None:
    """원본 한가운데가 비어도(원본 정리·부분 복원) 장기 복구는 원본이 하나도 없는 bucket의 통계를 지우지 않는다. 원본이 있는
    bucket의 원본 없는 행(유령 노선)은 예전대로 지운다. 최근 창 재대조는 예전대로 둘 다 지운다."""

    async def check(factory, engine):
        _require_postgres(engine)
        window_start = BASE + timedelta(hours=6)
        async with factory() as session:
            await _seed_raw(session, BASE, 6)
            await _rebuild_all(session)
            hole = (BASE + timedelta(hours=3), BASE + timedelta(hours=3, minutes=30))
            await session.execute(text(
                "DELETE FROM highway_traffic_snapshots WHERE observed_at >= :start AND observed_at < :end"),
                {"start": hole[0], "end": hole[1]})
            await _corrupt(session, stale_bucket=BASE + timedelta(hours=4), orphan_bucket=BASE + timedelta(hours=4),
                           missing_bucket=BASE + timedelta(hours=5))
            await session.commit()
            kept_before = _in(await _stored_statistics(session), *hole)
            await session.commit()
        assert kept_before
        async with factory() as session:
            repaired = await repair_traffic_statistics(session, window_start=window_start, horizon=timedelta(days=7))
        assert repaired.sweep_complete and (repaired.totals.inserted, repaired.totals.updated,
                                            repaired.totals.deleted) == (1, 1, 1)
        async with factory() as session:
            assert _in(await _stored_statistics(session), *hole) == kept_before
            window = await reconcile_traffic_statistics(session, hole[0], hole[1])
            await session.commit()
        assert window.deleted == len(kept_before)

    _execute(test_settings, check)


def test_highway_output_metadata_stays_under_console_entry_limit() -> None:
    """고속도로 op 결과 metadata는 관리 콘솔이 읽는 상한(64개, `safeMetadata`)보다 여유 있게 적다 — 넘으면 뒤에 붙은
    장기 복구 시각·실패 진단 키가 콘솔에서 말없이 잘린다. 모든 키를 채운 partial 결과로 잰다."""
    from app.dagster.definitions import (
        TRAFFIC_REPAIR_TIME_KEYS,
        TRAFFIC_STORE_BOOL_KEYS,
        TRAFFIC_STORE_COUNT_KEYS,
        TRAFFIC_STORE_REASON_KEYS,
        TRAFFIC_STORE_SECONDS_KEYS,
    )

    result: dict[str, Any] = {
        "status": "partial_success", "collection_run_id": 3, "raw_response_count": 2, "traffic_snapshot_count": 10,
        "incident_snapshot_count": 4, "errors": ["traffic: highway traffic store failed due to statement timeout"],
        "traffic_failed_step": "history", "traffic_statistics_repair_status": "failed",
        "traffic_statistics_repair_reason": "statement_timeout",
        **{key: 1 for key in TRAFFIC_STORE_COUNT_KEYS}, **{key: 1.5 for key in TRAFFIC_STORE_SECONDS_KEYS},
        **{key: "statement_timeout" for key in TRAFFIC_STORE_REASON_KEYS},
        **{key: True for key in TRAFFIC_STORE_BOOL_KEYS}, **{key: "2026-11-20T00:00:00Z" for key in TRAFFIC_REPAIR_TIME_KEYS},
    }
    metadata = _collection_output_metadata(result, "highway")
    assert metadata["collection_outcome"] == "partial" and "error_code" in metadata
    assert "traffic_statistics_repair_cursor" in metadata
    assert len(metadata) <= 60, len(metadata)


def test_highway_op_warns_on_drift_and_repair_failure_without_partial(monkeypatch) -> None:
    """고속도로 op: 어긋남(창·장기 복구)과 장기 복구 실패는 경고 한 줄이고 결과는 success다."""
    from dagster import DagsterEventType, DagsterInstance

    from app.dagster import definitions as dagster_definitions
    from test_dagster_error_redaction import _patch_services

    async def run_with_drift(*_args: Any, **_kwargs: Any):
        return {"status": "success", "collection_run_id": 1, "traffic_snapshot_count": 1,
                "traffic_statistics_refreshed": True, "traffic_statistics_inserted_rows": 0,
                "traffic_statistics_updated_rows": 2, "traffic_statistics_deleted_rows": 1,
                "traffic_statistics_drift_rows": 3,
                **RepairOutcome(status="failed", reason="statement_timeout").summary()}

    _patch_services(monkeypatch)
    monkeypatch.setattr(dagster_definitions, "_run_with_session", run_with_drift)
    with DagsterInstance.local_temp(overrides={"python_logs": {"python_log_level": "WARNING"}}) as instance:
        result = dagster_definitions.highway_collection_job.execute_in_process(raise_on_error=False, instance=instance)
        assert result.success is True
        texts = [entry.user_message for entry in instance.all_logs(result.run_id) if entry.dagster_event is None]
        outputs = [event for event in result.all_events if event.event_type == DagsterEventType.STEP_OUTPUT]
    joined = "\n".join(texts)
    assert "원본과 달라 3행을 바로잡았습니다(추가 0·수정 2·삭제 1)" in joined
    assert "장기 복구 구간이 실패했습니다(reason=statement_timeout)" in joined
    metadata = {key: value.value for key, value in outputs[0].step_output_data.metadata.items()}
    assert metadata["collection_outcome"] == "success" and "error_code" not in metadata
    assert metadata["traffic_statistics_repair_status"] == "failed"


def test_reconcile_result_counts() -> None:
    result = ReconcileResult(range_start=BASE, range_end=None, canonical_rows=10, inserted=2, updated=3, deleted=4,
                             seconds=0.1)
    assert (result.unchanged, result.changed) == (5, 9)
