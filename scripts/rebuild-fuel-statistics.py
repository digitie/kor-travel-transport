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
from app.models import TransportCollectionState  # noqa: E402
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
                await publish_fuel_statistics(session, name, state.last_success_at)
                await session.commit()
                await cleanup_fuel_statistics(session, name)
                print(f"{name}: {state.last_success_at.isoformat()} 기준 통계 발행 완료")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=[OPINET, HIGHWAY])
    asyncio.run(rebuild(parser.parse_args().source))
