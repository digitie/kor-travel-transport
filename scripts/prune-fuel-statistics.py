"""쌓인 이전 유가 통계 세대를 한 번에 정리한다. 공개 세대·준비 중 세대는 건드리지 않는다.

수집마다 도는 정리(`cleanup_fuel_statistics`)와 같은 배치 문장을 쓰고 배치마다 commit한다.
수집과 동시에 돌아도 된다(행 잠금은 SKIP LOCKED, 공개 세대 쓰기와 행이 겹치지 않는다).
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import create_engine_and_session_factory  # noqa: E402
from app.models import FuelStatisticsPoint  # noqa: E402
from app.services.fuel_statistics import HIGHWAY, OPINET, PRUNE_BATCH_ROWS, cleanup_fuel_statistics  # noqa: E402


async def _generations(session, source: str) -> tuple[int, int]:
    p = FuelStatisticsPoint
    row = (await session.execute(select(func.count(func.distinct(p.generated_at)), func.count()).where(
        p.source == source,
    ))).one()
    await session.rollback()
    return int(row[0]), int(row[1])


async def prune(source: str | None, budget_seconds: float, batch_rows: int) -> None:
    engine, factory = create_engine_and_session_factory(get_settings().database_url, collector=True)
    try:
        for name in [source] if source else [OPINET, HIGHWAY]:
            async with factory() as session:
                before = await _generations(session, name)
                deleted = await cleanup_fuel_statistics(session, name, budget_seconds=budget_seconds,
                                                        batch_rows=batch_rows)
                after = await _generations(session, name)
                print(f"{name}: 세대 {before[0]}→{after[0]}, 행 {before[1]}→{after[1]} (삭제 {deleted})")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=[OPINET, HIGHWAY])
    parser.add_argument("--budget-seconds", type=float, default=1800.0)
    parser.add_argument("--batch-rows", type=int, default=PRUNE_BATCH_ROWS)
    args = parser.parse_args()
    asyncio.run(prune(args.source, args.budget_seconds, args.batch_rows))
