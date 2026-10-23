"""기준정보의 유한 source membership. 호출자의 저장 transaction과 fence를 유지한다."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CollectionRun, ReferenceExportState

MAX_REFERENCE_MEMBERS = 10000


async def promote_reference(
    session: AsyncSession, *, kind: str, scope: str, run_id: int,
    confirmed_at: datetime, member_ids: list[int], proof: dict,
) -> None:
    if (not member_ids or len(member_ids) > MAX_REFERENCE_MEMBERS
            or len(set(member_ids)) != len(member_ids) or not proof.get("complete")):
        raise ValueError("완결된 nonempty reference membership만 승인합니다")
    run = await session.get(CollectionRun, run_id)
    if run is None or run.status != "running":
        raise ValueError("진행 중인 원천 transaction이 아닙니다")
    state = await session.scalar(select(ReferenceExportState).where(
        ReferenceExportState.kind == kind, ReferenceExportState.scope_key == scope,
    ).with_for_update())
    if state is not None and state.attempt_order > run_id:
        raise ValueError("이전 수집 worker는 새 성공집합을 덮을 수 없습니다")
    if state is None:
        state = ReferenceExportState(kind=kind, scope_key=scope)
        session.add(state)
    state.generation = str(uuid4())
    state.attempt_order = run_id
    state.confirmed_at = confirmed_at
    state.last_attempt_at = confirmed_at
    state.last_error = None
    state.member_ids = sorted(member_ids)
    state.proof = proof
