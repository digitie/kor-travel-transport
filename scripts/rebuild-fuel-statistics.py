"""기존 최신 가격에서 통계를 초기화한다. 공급자 호출과 원본 이력 전수 조회는 없다."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import create_engine_and_session_factory  # noqa: E402
from app.models import FuelStatisticsState, TransportCollectionState  # noqa: E402
from app.services.fuel_statistics import HIGHWAY, OPINET, cleanup_fuel_statistics, publish_fuel_statistics  # noqa: E402


async def rebuild(source: str | None) -> None:
    engine, factory = create_engine_and_session_factory(get_settings().database_url, collector=True)
    try:
        for name in [source] if source else [OPINET, HIGHWAY]:
            async with factory() as session:
                state = await session.scalar(select(TransportCollectionState).where(TransportCollectionState.source == name))
                if state is None or state.last_success_at is None:
                    print(f"{name}: 정상 수집 기록 없음")
                    continue
                requested_at = state.last_success_at
                await publish_fuel_statistics(session, name, requested_at)
                await session.commit()
                published_at = await session.scalar(select(FuelStatisticsState.generated_at).where(
                    FuelStatisticsState.source == name,
                ))
                # cleanup rollback은 ORM을 만료시키므로 출력에는 이미 읽은 스칼라만 쓴다.
                await cleanup_fuel_statistics(session, name)
                current = published_at.isoformat() if published_at is not None else "없음(갱신 보류)"
                print(f"{name}: 공개 통계 {current} (요청 원본 {requested_at.isoformat()})")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=[OPINET, HIGHWAY])
    asyncio.run(rebuild(parser.parse_args().source))
