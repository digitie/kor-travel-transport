"""Map 교통 current의 source 단위 원자적 갱신. commit/외부 호출은 소유하지 않는다."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import and_, case, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CollectionRun,
    HighwayTrafficCurrent,
    HighwayTrafficCurrentState,
    HighwayTrafficSnapshot,
)

BATCH_SIZE = 400
_FIELDS = (
    "observed_at",
    "collected_at",
    "route_no",
    "route_name",
    "conzone_id",
    "conzone_name",
    "direction",
    "speed",
    "free_flow_speed",
    "congestion_level",
)


async def update_traffic_current(
    session: AsyncSession,
    *,
    source: str,
    scope_key: str,
    collection_run_id: int,
    pairs: set[tuple[str, datetime]],
    confirmed_at: datetime,
) -> bool:
    """호출자는 provider 완결 guard를 통과한 한 source 저장 transaction을 전달한다.

    현재 표는 작은 typed DTO 열도 보존한다. 옛 worker가 mutable history의 같은 PK를
    정정하더라도 승인된 current 값은 별도 성공 원장 없이 바뀌지 않는다.
    """
    run = (
        await session.execute(
            select(CollectionRun.started_at, CollectionRun.status).where(
                CollectionRun.id == collection_run_id,
            )
        )
    ).one()
    if run.status != "running":
        raise ValueError("진행 중인 수집 transaction만 current를 갱신할 수 있습니다")
    insert = (
        pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    )
    generation = str(uuid4())
    states = HighwayTrafficCurrentState.__table__
    await session.execute(
        insert(states)
        .values(
            source=source,
            scope_key=scope_key,
            generation=generation,
            attempt_started_at=run.started_at,
            attempt_order=collection_run_id,
            confirmed_at=confirmed_at,
            member_count=0,
        )
        .on_conflict_do_nothing(index_elements=["source", "scope_key"])
    )
    state = (
        (
            await session.execute(
                select(states)
                .where(
                    states.c.source == source,
                    states.c.scope_key == scope_key,
                )
                .with_for_update()
            )
        )
        .mappings()
        .one()
    )
    # 원천 완결 집합의 소유 순서는 DB run ID로 고정한다. wall clock 역행 때문에
    # 이후의 정상 수집을 영구적으로 막거나 늦은 옛 run을 새 집합으로 승인하지 않는다.
    if collection_run_id < state["attempt_order"]:
        return False
    # 같은 identity가 여러 관측을 포함해도 한 문장이 같은 PK를 두 번 갱신하지 않는다.
    latest: dict[str, datetime] = {}
    for identity, observed_at in pairs:
        if identity not in latest or observed_at > latest[identity]:
            latest[identity] = observed_at
    keys = sorted(latest.items())
    table = HighwayTrafficCurrent.__table__
    for offset in range(0, len(keys), BATCH_SIZE):
        selected = keys[offset : offset + BATCH_SIZE]
        rows = (
            (
                await session.execute(
                    select(
                        HighwayTrafficSnapshot.id.label("snapshot_id"),
                        HighwayTrafficSnapshot.identity_key,
                        *(getattr(HighwayTrafficSnapshot, field) for field in _FIELDS),
                    ).where(
                        HighwayTrafficSnapshot.source == source,
                        tuple_(
                            HighwayTrafficSnapshot.identity_key,
                            HighwayTrafficSnapshot.observed_at,
                        ).in_(selected),
                    )
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != len(selected):
            raise ValueError("이번 수집의 실제 저장 point를 모두 찾을 수 없습니다")
        statement = insert(table).values(
            [
                {
                    **dict(row),
                    "source": source,
                    "scope_key": scope_key,
                    "generation": generation,
                    "snapshot_order": row["snapshot_id"],
                }
                for row in rows
            ]
        )
        excluded = statement.excluded
        newer = or_(
            excluded.observed_at > table.c.observed_at,
            and_(
                excluded.observed_at == table.c.observed_at,
                excluded.collected_at > table.c.collected_at,
            ),
            and_(
                excluded.observed_at == table.c.observed_at,
                excluded.collected_at == table.c.collected_at,
                excluded.snapshot_order >= table.c.snapshot_order,
            ),
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["source", "scope_key", "identity_key"],
                set_={
                    "generation": generation,
                    **{
                        field: case(
                            (newer, getattr(excluded, field)),
                            else_=getattr(table.c, field),
                        )
                        for field in ("snapshot_id", "snapshot_order", *_FIELDS)
                    },
                },
            )
        )
    await session.execute(
        states.update()
        .where(
            states.c.source == source,
            states.c.scope_key == scope_key,
        )
        .values(
            generation=generation,
            attempt_started_at=run.started_at,
            attempt_order=collection_run_id,
            confirmed_at=confirmed_at,
            member_count=len(keys),
        )
    )
    return True
