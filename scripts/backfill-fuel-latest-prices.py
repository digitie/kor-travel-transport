"""`fuel_latest_prices`를 원본 유가 이력 전체에서 다시 맞춘다(0022 배포 뒤 1회).

0022는 migration 안에서 한 번 backfill한다. 그 뒤 옛 Dagster 코드가 아직 돌던 창에서 커밋된
유가 행은 새 테이블에 반영되지 않고 다음 오피넷 수집(최대 약 8시간)까지 빠져 있을 수 있다.
이 스크립트는 그 창을 닫는다. 기본은 읽기 전용으로 어긋난 (주유소, 유종) 수만 센다.
`--apply`는 수집 경로와 같은 `upsert_latest_fuel_prices`를 전 이력으로 실행한다 — 더 새로운
행을 덮지 않는 단조 upsert라 수집과 겹쳐도 안전하고, 몇 번을 다시 실행해도 결과가 같다.

    docker exec kor-travel-transport-backend-1 python scripts/backfill-fuel-latest-prices.py
    docker exec kor-travel-transport-backend-1 python scripts/backfill-fuel-latest-prices.py --apply
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_engine_and_session_factory
from app.services.transport_collection import upsert_latest_fuel_prices

#: 전 이력(수십만 행)을 창 함수로 한 번 훑는다. 앱 기본 statement_timeout(60초)보다 넉넉히 준다.
STATEMENT_TIMEOUT = "15min"

DRIFT_SQL = text(
    """
    SELECT count(*) FROM (
        SELECT DISTINCT ON (fuel_station_id, product_code) fuel_station_id, product_code, id
        FROM fuel_price_snapshots
        ORDER BY fuel_station_id, product_code, collected_at DESC, id DESC
    ) AS latest
    LEFT JOIN fuel_latest_prices AS current
      ON current.fuel_station_id = latest.fuel_station_id
     AND current.product_code = latest.product_code
    WHERE current.snapshot_id IS DISTINCT FROM latest.id
    """
)


async def backfill(*, apply: bool) -> int:
    engine, session_factory = create_engine_and_session_factory(get_settings().database_url)
    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("운영 PostgreSQL에서만 실행한다")
        async with session_factory() as session:
            await session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
            before = int(await session.scalar(DRIFT_SQL) or 0)
            print(f"최신 유가와 어긋난 (주유소, 유종): {before}")
            if not apply:
                await session.rollback()
                print("읽기 전용 점검 완료. --apply를 지정해야 반영한다.")
                return 0
            await upsert_latest_fuel_prices(session)
            after = int(await session.scalar(DRIFT_SQL) or 0)
            await session.commit()
            print(f"반영 완료. 남은 어긋남: {after}")
            return 0 if after == 0 else 1
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="전 이력 upsert를 실제로 반영")
    return asyncio.run(backfill(apply=parser.parse_args().apply))


if __name__ == "__main__":
    raise SystemExit(main())
