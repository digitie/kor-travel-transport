"""저장된 원천별 배편 기준자료만 조회한다."""
from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.models import FerryReferenceSnapshot
from app.schemas import FerryReferenceResponse, FerryReferenceState
from app.services.vadahub_collection import SOURCES


def build_ferry_reference_router(get_db):
    router = APIRouter()

    @router.get("/transport/ferry/reference", response_model=FerryReferenceResponse)
    async def ferry_reference(session=Depends(get_db)):
        rows = {row.dataset: row for row in (await session.scalars(select(FerryReferenceSnapshot))).all()}
        return FerryReferenceResponse(items=[
            FerryReferenceState(dataset=key, title=spec[0],
                last_attempt_at=rows[key].last_attempt_at if key in rows else None,
                last_error=rows[key].last_error if key in rows else None,
                data=rows[key].response_json if key in rows else None)
            for key, spec in SOURCES.items()
        ])

    return router
