"""Map 교통 current의 source 단위 원자적 갱신. commit/외부 호출은 소유하지 않는다."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, case, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time_utils import serialize_utc
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
    carry_forward_limit: int = 0,
    carry_forward_max_age: timedelta | None = None,
) -> bool:
    """호출자는 provider 완결 guard를 통과한 한 source 저장 transaction을 전달한다.

    `carry_forward_limit`은 이번 완결 응답에서 SDK가 격리한 무효 행 수다. 무효 행의 identity는 알 수 없으므로
    직전 세대에 있었는데 이번 집합에 없는 구간이 그 수 이하일 때만, 관측이 `carry_forward_max_age` 안인 구간을
    새 세대로 넘긴다(값·관측시각은 그대로). 빠진 구간이 무효 행 수보다 많으면 실제 소멸이 섞인 것이라 넘기지
    않는다 — 완결 집합 교체(지금 동작)와 같다.

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
    previous_generation = state["generation"]
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
    carried = 0
    if carry_forward_limit > 0 and carry_forward_max_age is not None and previous_generation != generation:
        carried = await _carry_forward_missing(
            session, source=source, scope_key=scope_key, previous_generation=previous_generation,
            generation=generation, present=set(latest), limit=carry_forward_limit,
            observed_after=confirmed_at - carry_forward_max_age,
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
            member_count=len(keys) + carried,
        )
    )
    return True


async def _carry_forward_missing(
    session: AsyncSession, *, source: str, scope_key: str, previous_generation: str, generation: str,
    present: set[str], limit: int, observed_after: datetime,
) -> int:
    """직전 세대에서 빠진 구간이 `limit` 이하면 최근 관측만 새 세대로 넘긴다. 넘긴 수를 돌려준다."""
    table = HighwayTrafficCurrent.__table__
    previous = (await session.execute(
        select(table.c.identity_key, table.c.observed_at).where(
            table.c.source == source, table.c.scope_key == scope_key,
            table.c.generation == previous_generation,
        )
    )).all()
    missing = [row for row in previous if row.identity_key not in present]
    if not missing or len(missing) > limit:
        return 0
    cutoff = serialize_utc(observed_after)
    keep = [row.identity_key for row in missing if serialize_utc(row.observed_at) >= cutoff]
    if keep:
        await session.execute(
            table.update()
            .where(
                table.c.source == source, table.c.scope_key == scope_key,
                table.c.generation == previous_generation, table.c.identity_key.in_(keep),
            )
            .values(generation=generation)
        )
    return len(keep)
