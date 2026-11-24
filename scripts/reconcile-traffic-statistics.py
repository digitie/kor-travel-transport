"""고속도로 소통 5분 통계를 지정한 기간의 원본과 차이 기반으로 재대조한다(운영자 수동 정정).

정기 수집의 최근 2시간 창 재대조·장기 복구와 같은 구현(`reconcile_traffic_statistics`)을 구간마다 한 transaction으로
돌린다. 원본에 없는 통계 행만 지우고, 없는 행만 넣고, 값이 다른 행만 고친다(같은 행은 쓰지 않는다). 공급자를 부르지 않는다.
backend 또는 code-server 컨테이너 안에서 실행한다. 먼저 `--dry-run`으로 어긋남 크기를 본다.

    python scripts/reconcile-traffic-statistics.py --start 2026-11-20T00:00+09:00 --end 2026-11-21T00:00+09:00 --dry-run
    python scripts/reconcile-traffic-statistics.py --start 2026-11-20T00:00+09:00 --end 2026-11-21T00:00+09:00

시각에 시간대가 없으면 Asia/Seoul로 본다. 시작은 5분 경계로 내리고 끝은 5분 경계로 올린다. 가장 오래된 원본보다 앞
구간은 건너뛴다(원본이 지워진 기간의 통계를 지우지 않게, `--include-before-oldest-raw`로만 포함). 쓰기는 구간마다 통계 잠금
(advisory lock 420042)을 try-lock으로 잡고, 정기 수집이 쥐고 있으면 잠시 뒤 다시 해 본 뒤 멈춘다. 멈추면(잠금·예산)
마지막 줄의 `--start`로 다시 실행하면 이어진다. 장기 복구 진행 위치는 바꾸지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.time_utils import to_utc  # noqa: E402
from app.db.session import create_engine_and_session_factory  # noqa: E402
from app.services.traffic_statistics import (  # noqa: E402
    TRAFFIC_STATISTICS_REPAIR_CHUNK,
    ReconcileResult,
    five_minute_bucket,
    next_bucket_boundary,
    reconcile_traffic_statistics_range,
)

#: 한 번에 다룰 수 있는 최대 기간(실수로 수년치를 돌리지 않게). 더 길면 나눠 실행한다.
MAX_RANGE = timedelta(days=90)


def parse_range(start: str, end: str) -> tuple[datetime, datetime]:
    """입력 시각을 UTC 5분 경계로 맞춘 `[start, end)`. 시간대가 없으면 Asia/Seoul이다."""
    range_start = five_minute_bucket(to_utc(datetime.fromisoformat(start)))
    range_end = next_bucket_boundary(to_utc(datetime.fromisoformat(end)))
    if range_end <= range_start:
        raise ValueError("--end는 --start보다 뒤여야 합니다")
    if range_end - range_start > MAX_RANGE:
        raise ValueError(f"한 번에 {MAX_RANGE.days}일까지만 재대조합니다. 기간을 나눠 실행하세요")
    return range_start, range_end


def _line(result: ReconcileResult) -> str:
    return (f"{result.range_start.isoformat()} ~ {result.range_end.isoformat() if result.range_end else '-'}: "
            f"추가 {result.inserted} 수정 {result.updated} 삭제 {result.deleted} 그대로 {result.unchanged} "
            f"({result.seconds:.2f}s)")


async def run(range_start: datetime, range_end: datetime, *, chunk_hours: float, dry_run: bool,
              budget_seconds: float | None, include_before_oldest_raw: bool = False,
              database_url: str | None = None) -> int:
    engine, factory = create_engine_and_session_factory(database_url or get_settings().database_url, collector=True)
    try:
        async with factory() as session:
            outcome = await reconcile_traffic_statistics_range(
                session, range_start, range_end, chunk=timedelta(hours=chunk_hours), dry_run=dry_run,
                budget_seconds=budget_seconds, on_chunk=lambda result: print(_line(result), flush=True),
                include_before_oldest_raw=include_before_oldest_raw,
            )
    finally:
        await engine.dispose()
    if outcome.clamped_to is not None:
        print(f"가장 오래된 원본보다 앞이라 건너뜀: {range_start.isoformat()} ~ {outcome.clamped_to.isoformat()} "
              "(원본이 지워진 기간의 통계는 지우지 않는다)")
    totals = outcome.totals
    verb = "바꿀" if dry_run else "바꾼"
    print(f"{'확인(쓰기 없음)' if dry_run else '적용'}: 구간 {len(outcome.chunks)}개, 어긋나 {verb} 행 {totals.changed}"
          f"(추가 {totals.inserted}·수정 {totals.updated}·삭제 {totals.deleted}), 그대로 {totals.unchanged}, "
          f"{totals.seconds:.2f}s")
    if outcome.stopped is not None:
        reason = "다른 통계 쓰기가 잠금을 쥐고 있음" if outcome.stopped == "busy" else "시간 예산 소진"
        print(f"멈춤({reason}): --start {outcome.resume_from.isoformat()} --end {range_end.isoformat()} 로 이어 하세요.")
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", required=True, help="시작 시각(ISO 8601, 시간대 없으면 KST)")
    parser.add_argument("--end", required=True, help="끝 시각(배타, ISO 8601, 시간대 없으면 KST)")
    parser.add_argument("--chunk-hours", type=float, default=TRAFFIC_STATISTICS_REPAIR_CHUNK.total_seconds() / 3600,
                        help="한 transaction이 맡는 구간 폭(시간, 5분의 배수). 기본 2")
    parser.add_argument("--budget-seconds", type=float, default=1800.0, help="이 시간이 지나면 다음 구간을 시작하지 않는다")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 어긋난 행 수만 센다")
    parser.add_argument("--include-before-oldest-raw", action="store_true",
                        help="가장 오래된 원본보다 앞 구간도 재대조한다(그 구간의 통계 행은 정본에 없으므로 지워진다)")
    args = parser.parse_args(argv)
    range_start, range_end = parse_range(args.start, args.end)
    return asyncio.run(run(range_start, range_end, chunk_hours=args.chunk_hours, dry_run=args.dry_run,
                           budget_seconds=args.budget_seconds,
                           include_before_oldest_raw=args.include_before_oldest_raw))


if __name__ == "__main__":
    raise SystemExit(main())
