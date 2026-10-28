"""영구 주차 통계가 있는 DB를 옛 자료 이관이 덮어쓰지 못하게 한다."""
from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ParkingGlobalStatisticsBucket, ParkingLatestState, ParkingStatisticsBucket


async def ensure_legacy_import_allowed(session: AsyncSession) -> None:
    # 조회와 뒤따르는 쓰기를 통계 발행/공항 수집과 같은 transaction lock으로 직렬화한다.
    if session.bind.dialect.name == "postgresql":
        acquired = await session.scalar(text(
            "SELECT pg_try_advisory_xact_lock(hashtext('kor_travel_transport:airport_collection'))"
        ))
        if not acquired:
            raise RuntimeError("주차 수집·통계 작업 중에는 legacy 주차 이관을 실행할 수 없습니다.")
    for model in (ParkingStatisticsBucket, ParkingGlobalStatisticsBucket, ParkingLatestState):
        if await session.scalar(select(exists().select_from(model))):
            raise RuntimeError("영구 주차 통계·현재 요약이 있는 DB에는 legacy 주차 자료를 덮어쓸 수 없습니다.")
