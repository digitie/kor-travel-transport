"""운영 중단으로 종료 기록이 남지 않은 교통 수집 실행을 명시적으로 정리한다.

기본은 읽기 전용이다. 적용 전 scripts/verify-dagster-workers-server14.py로
Dagster 활성 실행과 worker가 없음을 확인하고, 점검한 ID만 --ids로 전달한다.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.time_utils import now_utc
from app.db.session import create_engine_and_session_factory
from app.models import CollectionRun


MINIMUM_AGE = timedelta(hours=4)
TRIGGERS = {"transport_dagster_highway", "transport_dagster_fuel"}
REASON = "운영 점검: Dagster 활성 실행/worker가 없는 오래된 수집 실행을 실패 종료로 정리함"


async def reconcile(ids: list[int], *, apply: bool) -> int:
    engine, session_factory = create_engine_and_session_factory(get_settings().database_url)
    try:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("운영 PostgreSQL에서만 수집 실행을 정리할 수 있습니다")
        async with session_factory() as session:
            rows = (await session.scalars(
                select(CollectionRun).where(CollectionRun.id.in_(ids)).with_for_update()
            )).all()
            if len(rows) != len(ids):
                raise ValueError("요청한 ID 중 존재하지 않는 수집 실행이 있습니다")
            current_time = now_utc()
            for row in rows:
                age = current_time - row.started_at
                if row.trigger not in TRIGGERS or row.status != "running" or age < MINIMUM_AGE:
                    raise ValueError(f"수집 실행 {row.id}은 정리 대상이 아닙니다")
                print(f"{row.id}: {row.trigger}, 시작 {row.started_at.isoformat()}, 경과 {age}")
            if not apply:
                await session.rollback()
                print("읽기 전용 점검 완료. --apply를 지정해야 상태가 변경됩니다.")
                return 0
            for row in rows:
                row.status = "failed"
                row.finished_at = current_time
                row.error_message = REASON
            await session.commit()
            print(f"과거 수집 실행 {len(rows)}건을 실패 종료로 기록했습니다.")
            return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", required=True, help="대조를 마친 수집 실행 ID 쉼표 목록")
    parser.add_argument("--apply", action="store_true", help="검증한 ID의 상태를 실제 변경")
    args = parser.parse_args()
    try:
        ids = [int(item) for item in args.ids.split(",")]
    except ValueError as exc:
        parser.error(f"ID는 정수여야 합니다: {exc}")
    if not ids or len(ids) != len(set(ids)) or any(item <= 0 for item in ids):
        parser.error("중복 없는 양수 ID가 필요합니다")
    return asyncio.run(reconcile(ids, apply=args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
