"""고속도로 소통 5분 통계(`highway_traffic_five_minute_statistics`)의 차이 기반 재대조.

원천 transaction 안의 바뀐 bucket 재구축, 원천 commit 뒤 최근 창 재대조, 최근 창보다 오래된 구간의 장기 어긋남 복구,
운영자 수동 재대조가 모두 이 모듈의 `reconcile_traffic_statistics` 한 구현을 쓴다(WLH-06 후속, 2026-11-24).

재대조는 범위의 원본(`highway_traffic_snapshots`)을 예전과 같은 규칙(UTC `date_bin` 5분, `route_no`·`direction`의 NULL은
빈 문자열)으로 집계한 정본과 저장된 통계 행을 비교해, 없는 행만 넣고 값이 다른 행만 고치고 정본에 없는 행만 지운다. 값이 같은
행은 쓰지 않는다(새 tuple·WAL 없음). 그래서 어긋남이 없는 범위의 재대조는 0행을 바꾸고, 바꾼 행 수가 곧 어긋남의 크기다.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import now_utc, serialize_utc
from app.models import HighwayTrafficSnapshot, TransportCollectionState

#: 소통 5분 통계 쓰기(원천 transaction의 bucket 재구축·commit 뒤 창 재대조·장기 복구·수동 재대조)를 직렬화하는 transaction
#: advisory lock. 성공 표시가 창 재대조보다 먼저 commit되므로 다음(수동·관리자) 고속도로 실행이 앞 실행의 재대조와 겹칠 수
#: 있다. 같은 bucket을 두 transaction이 함께 쓰면 `uq_highway_traffic_five_minute_statistics` 위반으로 한쪽이 실패한다.
TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY = 420042
#: 원천 transaction이 위 잠금을 기다리는 상한. 수집 엔진 기본 `lock_timeout`(5초)보다 길게 두어 앞 실행의 창 재대조
#: (최대 문장 시간)를 기다리게 한다. 수집 `statement_timeout`(60초)보다 짧아 원인이 잠금 대기로 보인다.
TRAFFIC_STATISTICS_LOCK_WAIT = "55s"
#: 통계 bucket 폭. PostgreSQL `date_bin('5 minutes', …, '2000-01-01 00:00+00')`과 같다.
STATISTICS_BUCKET = timedelta(minutes=5)
#: 합(`speed_sum`·`free_flow_speed_sum`) 비교의 상대 허용 오차. 배정밀도 합은 더하는 순서(실행 계획)에 따라 마지막 자리가
#: 달라질 수 있다. 같은 원본의 재집계가 그 차이만으로 "어긋남"이 되어 행을 다시 쓰지 않게 한다. 관측 수·최소·최대·최신
#: 관측 시각은 정확히 비교한다.
SUM_RELATIVE_TOLERANCE = 1e-9

#: 장기 어긋남 복구의 진행 원장. `transport_collection_states`의 전용 행이다(공항 KAC 할당량 원장과 같은 방식, migration 없음).
#: - `next_due_at`: 다음에 재대조할 구간의 **끝**(배타, 5분 경계). 최근 창 시작에서 과거로 걸어간다. NULL이면 진행 중인
#:   한 바퀴(sweep)가 없다.
#: - `last_started_at`: 지금(또는 마지막) 한 바퀴를 시작한 시각. 다음 한 바퀴는 이 시각 + `sweep_interval` 뒤에 시작한다.
#: - `last_success_at`: 마지막으로 한 바퀴를 끝낸 시각.
#: - `last_error`: 마지막 구간 실패의 고정 원인 코드(성공하면 NULL).
TRAFFIC_STATISTICS_REPAIR_STATE = "krex_traffic_statistics_repair"
#: 장기 복구 한 구간(한 transaction·한 commit)의 폭. 최근 창(2시간)과 같아 한 구간의 비용이 창 재대조 한 번과 비슷하다.
TRAFFIC_STATISTICS_REPAIR_CHUNK = timedelta(hours=2)
#: 한 바퀴의 시작 간격 상한. 지평(horizon)이 이보다 짧으면 지평을 쓴다(창에서 빠진 bucket이 빠짐없이 한 바퀴에 들게).
TRAFFIC_STATISTICS_REPAIR_SWEEP_INTERVAL = timedelta(hours=24)
#: 고속도로 실행 한 번이 장기 복구에 쓰는 시간 예산(초). 다음 구간을 시작하기 전에 잰다 — 이미 시작한 구간은 끝낸다.
TRAFFIC_STATISTICS_REPAIR_RUN_BUDGET_SECONDS = 5.0
#: 고속도로 실행 한 번이 처리하는 구간 수 상한(빠른 호스트에서 한 실행이 한 바퀴를 다 돌지 않게).
TRAFFIC_STATISTICS_REPAIR_MAX_CHUNKS_PER_RUN = 12
#: 수집 실행이 이미 이만큼 걸렸으면 장기 복구를 이번 실행에서 건너뛴다(고속도로 job 실행 상한 1,200초의 절반).
TRAFFIC_STATISTICS_REPAIR_SKIP_AFTER = timedelta(minutes=10)

#: 장기 복구 한 실행의 결과(`traffic_statistics_repair_status`).
#: - `idle`: 진행 중인 한 바퀴가 없고 다음 한 바퀴의 시작 시각 전이다(또는 지평 안에 원본이 없다).
#: - `repaired`: 구간을 하나 이상 재대조했다(어긋남이 없었으면 바꾼 행은 0이다).
#: - `busy`: 다른 transaction이 통계 잠금을 쥐고 있어 이번 실행은 양보했다(진행 위치는 그대로).
#: - `deferred`: 이번 실행은 건너뛰었다(`run_budget` 수집이 이미 오래 걸림, `window_deferred` 최근 창 재대조 실패·지연).
#: - `failed`: 구간 재대조가 DB 오류로 실패했다(진행 위치는 그대로라 다음 실행이 같은 구간부터 다시 한다).
REPAIR_STATUSES = ("idle", "repaired", "busy", "deferred", "failed")
REPAIR_DEFER_REASONS = ("run_budget", "window_deferred")
#: 저장·재대조 실패 원인 코드(`database_failure_reason`). SQLSTATE 등급은 `sqlstate_<2자리>`로 남긴다.
DATABASE_FAILURE_REASONS = (
    "statement_timeout", "lock_timeout", "deadlock", "serialization", "unique_violation", "connection",
    "client_timeout", "cancelled", "busy", "database", "other",
)

_STAT_COLUMNS = (
    "observations", "speed_observations", "speed_sum", "minimum_speed", "maximum_speed",
    "free_flow_speed_observations", "free_flow_speed_sum", "latest_observed_at",
)
_ALL_COLUMNS = ("bucket_start", "route_no_key", "direction_key", *_STAT_COLUMNS)


def database_failure_reason(error: BaseException) -> str:
    """저장·재대조 실패의 고정 원인 코드. 예외 원문은 넣지 않는다(`DATABASE_FAILURE_REASONS`, `sqlstate_<등급>`)."""
    if isinstance(error, asyncio.CancelledError):
        return "cancelled"
    if isinstance(error, DBAPIError):
        sqlstate = str(getattr(error.orig, "sqlstate", None) or "")
        known = {"57014": "statement_timeout", "55P03": "lock_timeout", "40P01": "deadlock",
                 "40001": "serialization", "23505": "unique_violation"}
        if sqlstate in known:
            return known[sqlstate]
        if error.connection_invalidated or sqlstate.startswith(("08", "57P")):
            return "connection"
        if re.fullmatch(r"[0-9A-Z]{5}", sqlstate):
            return f"sqlstate_{sqlstate[:2]}"
        return "database"
    if isinstance(error, TimeoutError):
        return "client_timeout"
    if isinstance(error, (ConnectionError, OSError)):
        return "connection"
    return "other"


def five_minute_bucket(value: datetime) -> datetime:
    """PostgreSQL `date_bin('5 minutes', …, '2000-01-01 00:00+00')`과 같은 UTC 5분 bucket 시작."""
    value = serialize_utc(value).replace(second=0, microsecond=0)
    return value - timedelta(minutes=value.minute % 5)


def next_bucket_boundary(value: datetime) -> datetime:
    """`value` 이상인 가장 이른 5분 경계(경계 위면 그대로)."""
    utc = serialize_utc(value)
    bucket = five_minute_bucket(utc)
    return bucket if bucket == utc else bucket + STATISTICS_BUCKET


def _aligned(value: datetime, name: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{name}은 시간대가 있는 시각이어야 합니다")
    utc = serialize_utc(value)
    if five_minute_bucket(utc) != utc:
        raise ValueError(f"{name}은 5분 경계(UTC)여야 합니다: {utc.isoformat()}")
    return utc


def _isoformat(value: datetime | None) -> str | None:
    return serialize_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ") if value is not None else None


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """한 범위 재대조의 결과. `inserted`·`updated`·`deleted`는 정본과 달랐던(바꾼) 행, `unchanged`는 그대로 둔 행이다."""

    range_start: datetime
    range_end: datetime | None
    canonical_rows: int
    inserted: int
    updated: int
    deleted: int
    seconds: float
    dry_run: bool = False

    @property
    def unchanged(self) -> int:
        return max(0, self.canonical_rows - self.inserted - self.updated)

    @property
    def changed(self) -> int:
        return self.inserted + self.updated + self.deleted


@dataclass(slots=True)
class ReconcileTotals:
    """여러 범위(구간) 재대조의 합."""

    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    seconds: float = 0.0

    def add(self, result: ReconcileResult) -> None:
        self.inserted += result.inserted
        self.updated += result.updated
        self.deleted += result.deleted
        self.unchanged += result.unchanged
        self.seconds += result.seconds

    @property
    def changed(self) -> int:
        return self.inserted + self.updated + self.deleted


def _same_statistics(stored: str, canonical: str) -> str:
    """두 통계 행이 같은가(NULL 안전, 합은 상대 허용 오차). 결과는 NULL이 아닌 boolean이다."""
    exact = " AND ".join(
        f"{stored}.{column} IS NOT DISTINCT FROM {canonical}.{column}"
        for column in _STAT_COLUMNS if column not in {"speed_sum", "free_flow_speed_sum"}
    )
    sums = " AND ".join(
        f"COALESCE({stored}.{column} = {canonical}.{column} OR abs({stored}.{column} - {canonical}.{column}) <= "
        f"{SUM_RELATIVE_TOLERANCE!r} * greatest(abs({stored}.{column}), abs({canonical}.{column})), "
        f"{stored}.{column} IS NULL AND {canonical}.{column} IS NULL)"
        for column in ("speed_sum", "free_flow_speed_sum")
    )
    return f"({exact} AND {sums})"


def _statements(has_end: bool) -> tuple[str, str]:
    """(적용 문장, 확인 전용 문장). 정본 CTE는 한 번만 계산한다(두 번 이상 참조하는 CTE는 PostgreSQL이 물질화한다)."""
    source_filter = "observed_at >= :range_start" + (" AND observed_at < :range_end" if has_end else "")
    bucket_filter = "s.bucket_start >= :range_start" + (" AND s.bucket_start < :range_end" if has_end else "")
    canonical = f"""
        canonical AS MATERIALIZED (
            SELECT date_bin(INTERVAL '5 minutes', observed_at, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket_start,
                   COALESCE(route_no, '') AS route_no_key, COALESCE(direction, '') AS direction_key,
                   COUNT(*) AS observations, COUNT(speed) AS speed_observations, SUM(speed) AS speed_sum,
                   MIN(speed) AS minimum_speed, MAX(speed) AS maximum_speed,
                   COUNT(free_flow_speed) AS free_flow_speed_observations,
                   SUM(free_flow_speed) AS free_flow_speed_sum, MAX(observed_at) AS latest_observed_at
            FROM highway_traffic_snapshots
            WHERE {source_filter}
            GROUP BY 1, 2, 3
        ),
        changes AS MATERIALIZED (
            SELECT c.*, s.id IS NULL AS is_new
            FROM canonical c
            LEFT JOIN highway_traffic_five_minute_statistics s
              ON s.bucket_start = c.bucket_start AND s.route_no_key = c.route_no_key
             AND s.direction_key = c.direction_key
            WHERE s.id IS NULL OR NOT {_same_statistics("s", "c")}
        )"""
    orphan_filter = f"""
            {bucket_filter}
            AND NOT EXISTS (
                SELECT 1 FROM canonical c
                WHERE c.bucket_start = s.bucket_start AND c.route_no_key = s.route_no_key
                  AND c.direction_key = s.direction_key
            )"""
    columns = ", ".join(_ALL_COLUMNS)
    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in _STAT_COLUMNS)
    apply = f"""
        WITH {canonical},
        upserted AS (
            INSERT INTO highway_traffic_five_minute_statistics AS s ({columns})
            SELECT {columns} FROM changes
            ON CONFLICT ON CONSTRAINT uq_highway_traffic_five_minute_statistics DO UPDATE SET {assignments}
            WHERE NOT {_same_statistics("s", "EXCLUDED")}
            RETURNING 1
        ),
        orphans AS (
            DELETE FROM highway_traffic_five_minute_statistics s
            WHERE {orphan_filter}
            RETURNING 1
        )
        SELECT (SELECT count(*) FROM canonical) AS canonical_rows,
               (SELECT count(*) FROM changes WHERE is_new) AS inserted,
               (SELECT count(*) FROM changes WHERE NOT is_new) AS updated,
               (SELECT count(*) FROM orphans) AS deleted,
               (SELECT count(*) FROM upserted) AS written
    """
    check = f"""
        WITH {canonical}
        SELECT (SELECT count(*) FROM canonical) AS canonical_rows,
               (SELECT count(*) FROM changes WHERE is_new) AS inserted,
               (SELECT count(*) FROM changes WHERE NOT is_new) AS updated,
               (SELECT count(*) FROM highway_traffic_five_minute_statistics s WHERE {orphan_filter}) AS deleted,
               0 AS written
    """
    return apply, check


_STATEMENTS = {has_end: _statements(has_end) for has_end in (False, True)}


async def reconcile_traffic_statistics(
    session: AsyncSession,
    range_start: datetime,
    range_end: datetime | None = None,
    *,
    dry_run: bool = False,
    serial: bool = False,
) -> ReconcileResult:
    """`[range_start, range_end)`(끝이 없으면 그 뒤 전부)의 5분 통계를 원본 정본과 같게 맞춘다(한 문장).

    호출자가 transaction과 통계 잠금(`TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY`)을 책임진다 — 원천 transaction 안에서 부르면
    원본과 그 통계가 함께 commit·rollback된다. 경계는 5분 bucket 경계여야 한다(원본 범위와 통계 범위가 같은 bucket을
    가리키게). `dry_run`은 아무것도 쓰지 않고 바꿀 행 수만 센다. `serial`은 이 transaction의 병렬 집계를 끈다(독립
    transaction에서만 — 낮은 우선순위 작업이 A55 코어를 더 쓰지 않고, 같은 범위의 합 순서도 실행마다 같게).
    """
    start = _aligned(range_start, "range_start")
    end = _aligned(range_end, "range_end") if range_end is not None else None
    if end is not None and end <= start:
        raise ValueError("range_end는 range_start보다 뒤여야 합니다")
    if serial:
        await session.execute(text("SELECT set_config('max_parallel_workers_per_gather', '0', true)"))
    apply, check = _STATEMENTS[end is not None]
    params: dict[str, Any] = {"range_start": start}
    if end is not None:
        params["range_end"] = end
    started = time.monotonic()
    row = (await session.execute(text(check if dry_run else apply), params)).one()
    return ReconcileResult(
        range_start=start, range_end=end, canonical_rows=int(row.canonical_rows), inserted=int(row.inserted),
        updated=int(row.updated), deleted=int(row.deleted), seconds=time.monotonic() - started, dry_run=dry_run,
    )


async def try_lock_traffic_statistics(session: AsyncSession) -> bool:
    """통계 잠금을 기다리지 않고 잡는다(창 재대조·장기 복구·수동 재대조). 잡으면 이 transaction의 끝까지 쥔다."""
    return bool(await session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"),
                                     {"key": TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY}))


async def wait_for_traffic_statistics_lock(session: AsyncSession) -> None:
    """원천 transaction이 통계 잠금을 기다려 잡는다. 이 대기만 수집 기본 `lock_timeout`보다 길게 둔다."""
    previous = await session.scalar(text("SELECT current_setting('lock_timeout')"))
    await session.execute(text("SELECT set_config('lock_timeout', :wait, true)"), {"wait": TRAFFIC_STATISTICS_LOCK_WAIT})
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": TRAFFIC_STATISTICS_ADVISORY_LOCK_KEY})
    await session.execute(text("SELECT set_config('lock_timeout', :previous, true)"), {"previous": previous})


Reconcile = Callable[..., Awaitable[ReconcileResult]]


@dataclass(slots=True)
class RepairOutcome:
    """장기 어긋남 복구 한 실행의 결과. run 요약·Dagster metadata 키는 `traffic_statistics_repair_*`다."""

    status: str
    reason: str | None = None
    chunks: int = 0
    totals: ReconcileTotals = field(default_factory=ReconcileTotals)
    #: 이번 실행이 재대조한 구간의 합집합 `[range_start, range_end)`.
    range_start: datetime | None = None
    range_end: datetime | None = None
    #: 실행 뒤 다음 구간의 끝(None이면 진행 중인 한 바퀴가 없다)과 이번 한 바퀴의 하한(지평과 가장 오래된 원본 중 늦은 쪽).
    cursor: datetime | None = None
    horizon_start: datetime | None = None
    sweep_complete: bool = False
    budget_exhausted: bool = False
    busy_skips: int = 0
    seconds: float = 0.0

    def summary(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "traffic_statistics_repair_status": self.status,
            "traffic_statistics_repair_chunks": self.chunks,
            "traffic_statistics_repair_seconds": round(self.seconds, 3),
            "traffic_statistics_repair_sweep_complete": self.sweep_complete,
            "traffic_statistics_repair_budget_exhausted": self.budget_exhausted,
            "traffic_statistics_repair_busy_skips": self.busy_skips,
        }
        if self.reason is not None:
            result["traffic_statistics_repair_reason"] = self.reason
        if self.chunks:
            result.update({
                "traffic_statistics_repair_inserted_rows": self.totals.inserted,
                "traffic_statistics_repair_updated_rows": self.totals.updated,
                "traffic_statistics_repair_deleted_rows": self.totals.deleted,
                "traffic_statistics_repair_unchanged_rows": self.totals.unchanged,
                "traffic_statistics_repair_drift_rows": self.totals.changed,
            })
        for key, value in (("range_start", self.range_start), ("range_end", self.range_end),
                           ("cursor", self.cursor), ("horizon_start", self.horizon_start)):
            if value is not None:
                result[f"traffic_statistics_repair_{key}"] = _isoformat(value)
        return result


async def _repair_state(session: AsyncSession) -> TransportCollectionState:
    # 순환 import를 피하려고 여기서 부른다(transport_collection이 이 모듈을 import한다).
    from app.services.transport_collection import get_or_create_state

    state = await get_or_create_state(session, TRAFFIC_STATISTICS_REPAIR_STATE)
    await session.refresh(state)
    return state


async def _horizon_start(session: AsyncSession, window_start: datetime, horizon: timedelta) -> datetime:
    """한 바퀴의 하한: 지평(`window_start - horizon`)과 가장 오래된 원본이 담긴 첫 **온전한** bucket 중 늦은 쪽.

    원본이 없는 구간의 통계는 원본 보존 정책이 생겨 원본만 먼저 지워졌을 수도 있으므로, 원본이 시작하기 전 구간은 재대조
    (정본에 없는 행 삭제)하지 않는다. 원본이 없으면 `window_start`(할 일 없음)다.
    """
    oldest = await session.scalar(select(func.min(HighwayTrafficSnapshot.observed_at)))
    if oldest is None:
        return window_start
    return min(window_start, max(next_bucket_boundary(window_start - horizon), next_bucket_boundary(oldest)))


async def repair_traffic_statistics(
    session: AsyncSession,
    *,
    window_start: datetime,
    horizon: timedelta,
    chunk: timedelta = TRAFFIC_STATISTICS_REPAIR_CHUNK,
    budget_seconds: float = TRAFFIC_STATISTICS_REPAIR_RUN_BUDGET_SECONDS,
    max_chunks: int = TRAFFIC_STATISTICS_REPAIR_MAX_CHUNKS_PER_RUN,
    sweep_interval: timedelta = TRAFFIC_STATISTICS_REPAIR_SWEEP_INTERVAL,
    reconcile: Reconcile = reconcile_traffic_statistics,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = now_utc,
) -> RepairOutcome:
    """최근 창(`window_start` 이후)보다 오래된 구간을 과거로 걸어가며 구간마다 재대조한다(장기 어긋남 자기 치유).

    진행 위치는 `TRAFFIC_STATISTICS_REPAIR_STATE` 행에 남는다. 구간 하나가 한 transaction이고, 그 transaction이 통계 잠금
    (try-lock — 다른 쓰기가 쥐고 있으면 기다리지 않고 양보)·진행 위치 읽기·재대조·진행 위치 전진을 함께 commit한다. 그래서
    끊겨도(실패·취소·예산 소진) 다음 실행은 마지막으로 commit한 구간 다음부터 이어 한다. 한 바퀴는 `window_start`에서 시작해
    하한(`_horizon_start`)에 닿으면 끝나고, 다음 한 바퀴는 이 바퀴를 시작한 뒤 `sweep_interval`(지평보다 길면 지평)이 지나야
    시작한다. 다음 구간은 `budget_seconds`가 남았고 `max_chunks`에 닿지 않았을 때만 시작한다. 호출자 session은 열린
    transaction이 없어야 한다.
    """
    window_start = _aligned(window_start, "window_start")
    if chunk <= timedelta(0) or chunk % STATISTICS_BUCKET:
        raise ValueError("chunk는 5분의 양의 배수여야 합니다")
    if horizon <= timedelta(0):
        raise ValueError("horizon은 양수여야 합니다")
    interval = min(sweep_interval, horizon)
    outcome = RepairOutcome(status="idle")
    started = clock()
    lower: datetime | None = None
    while True:
        if outcome.chunks >= max_chunks:
            break
        if outcome.chunks and clock() - started >= budget_seconds:
            outcome.budget_exhausted = True
            break
        try:
            if not await try_lock_traffic_statistics(session):
                await session.rollback()
                outcome.busy_skips += 1
                if not outcome.chunks:
                    outcome.status = "busy"
                break
            state = await _repair_state(session)
            if lower is None:
                lower = await _horizon_start(session, window_start, horizon)
                outcome.horizon_start = lower
            cursor = serialize_utc(state.next_due_at) if state.next_due_at is not None else None
            if cursor is None:
                started_at = serialize_utc(state.last_started_at) if state.last_started_at is not None else None
                if started_at is not None and now() < started_at + interval:
                    await session.rollback()
                    break
                cursor = window_start
                state.last_started_at = now()
            # 진행 위치는 5분 경계이고 창 시작보다 뒤일 수 없다(창 시작은 시간이 갈수록 뒤로만 간다).
            cursor = min(five_minute_bucket(cursor), window_start)
            if cursor <= lower:
                state.next_due_at = None
                state.last_success_at = now()
                state.last_error = None
                state.updated_at = now()
                await session.commit()
                outcome.sweep_complete = True
                break
            chunk_start = max(cursor - chunk, lower)
            result = await reconcile(session, chunk_start, cursor, serial=True)
            finished = chunk_start <= lower
            state.next_due_at = None if finished else chunk_start
            if finished:
                state.last_success_at = now()
            state.last_error = None
            state.updated_at = now()
            await session.commit()
        except Exception as exc:  # noqa: BLE001 — 실패는 원인 코드로 보고하고 수집 결과를 바꾸지 않는다.
            await session.rollback()
            outcome.status, outcome.reason = "failed", database_failure_reason(exc)
            await _record_repair_failure(session, outcome.reason, now)
            break
        outcome.status = "repaired"
        outcome.chunks += 1
        outcome.totals.add(result)
        outcome.range_start = chunk_start
        outcome.range_end = max(outcome.range_end or cursor, cursor)
        if finished:
            outcome.sweep_complete = True
            break
    outcome.seconds = clock() - started
    outcome.cursor = await _current_cursor(session)
    return outcome


async def _record_repair_failure(session: AsyncSession, reason: str, now: Callable[[], datetime]) -> None:
    """구간 실패의 원인 코드를 진행 원장에 남긴다(진행 위치는 바꾸지 않는다). 기록 실패는 무시한다."""
    try:
        state = await _repair_state(session)
        state.last_error = reason
        state.updated_at = now()
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()


async def _current_cursor(session: AsyncSession) -> datetime | None:
    try:
        value = await session.scalar(select(TransportCollectionState.next_due_at).where(
            TransportCollectionState.source == TRAFFIC_STATISTICS_REPAIR_STATE))
        await session.rollback()
    except Exception:  # noqa: BLE001 — 보고용 값이다.
        await session.rollback()
        return None
    return serialize_utc(value) if value is not None else None


@dataclass(slots=True)
class RangeReconcileOutcome:
    """수동 재대조(`scripts/reconcile-traffic-statistics.py`)의 결과."""

    chunks: list[ReconcileResult] = field(default_factory=list)
    totals: ReconcileTotals = field(default_factory=ReconcileTotals)
    #: 끝까지 하지 못했으면 이어 할 시작 경계와 그 이유(`budget`·`busy`).
    resume_from: datetime | None = None
    stopped: str | None = None
    #: 원본이 시작하기 전이라 건너뛴 앞부분 `[요청 시작, clamped_to)`. None이면 건너뛴 구간이 없다.
    clamped_to: datetime | None = None


async def reconcile_traffic_statistics_range(
    session: AsyncSession,
    range_start: datetime,
    range_end: datetime,
    *,
    chunk: timedelta = TRAFFIC_STATISTICS_REPAIR_CHUNK,
    dry_run: bool = False,
    budget_seconds: float | None = None,
    busy_retries: int = 3,
    busy_wait_seconds: float = 2.0,
    clock: Callable[[], float] = time.monotonic,
    on_chunk: Callable[[ReconcileResult], None] | None = None,
    include_before_oldest_raw: bool = False,
) -> RangeReconcileOutcome:
    """운영자가 지정한 `[range_start, range_end)`를 오래된 쪽부터 구간마다 재대조한다(구간마다 commit).

    `dry_run`은 잠금 없이 읽기 전용으로 바꿀 행 수만 센다. 쓰기는 구간마다 통계 잠금을 try-lock으로 잡고, 다른 쓰기가
    쥐고 있으면 `busy_wait_seconds`씩 `busy_retries`번 다시 해 본 뒤 멈춘다. `budget_seconds`가 지나면 다음 구간을 시작하지
    않는다. 멈춘 경우 `resume_from`부터 다시 실행하면 이어진다. 진행 원장(장기 복구 위치)은 건드리지 않는다. 장기 복구와
    같이 가장 오래된 원본이 담긴 첫 온전한 bucket보다 앞은 건너뛴다(원본이 지워진 기간의 통계를 지우지 않게) —
    `include_before_oldest_raw`로만 끈다. 호출자 session은 열린 transaction이 없어야 한다.
    """
    start = _aligned(range_start, "range_start")
    end = _aligned(range_end, "range_end")
    if end <= start:
        raise ValueError("range_end는 range_start보다 뒤여야 합니다")
    if chunk <= timedelta(0) or chunk % STATISTICS_BUCKET:
        raise ValueError("chunk는 5분의 양의 배수여야 합니다")
    outcome = RangeReconcileOutcome()
    if not include_before_oldest_raw:
        oldest = await session.scalar(select(func.min(HighwayTrafficSnapshot.observed_at)))
        await session.rollback()
        lower = next_bucket_boundary(oldest) if oldest is not None else end
        if lower > start:
            start = min(lower, end)
            outcome.clamped_to = start
    started = clock()
    chunk_start = start
    while chunk_start < end:
        if outcome.chunks and budget_seconds is not None and clock() - started >= budget_seconds:
            outcome.resume_from, outcome.stopped = chunk_start, "budget"
            break
        chunk_end = min(chunk_start + chunk, end)
        try:
            if dry_run:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            else:
                for attempt in range(busy_retries + 1):
                    if await try_lock_traffic_statistics(session):
                        break
                    await session.rollback()
                    if attempt < busy_retries:
                        await asyncio.sleep(busy_wait_seconds)
                else:
                    outcome.resume_from, outcome.stopped = chunk_start, "busy"
                    break
            result = await reconcile_traffic_statistics(session, chunk_start, chunk_end, dry_run=dry_run, serial=True)
            if dry_run:
                await session.rollback()
            else:
                await session.commit()
        except BaseException:
            await session.rollback()
            raise
        outcome.chunks.append(result)
        outcome.totals.add(result)
        if on_chunk is not None:
            on_chunk(result)
        chunk_start = chunk_end
    return outcome
