"""돌발 전체 이력 출처는 중복 행 수와 무관하게 빠짐없이 읽는다."""
import asyncio
from datetime import timedelta

import pytest
from app.core.time_utils import now_utc
from app.models import Airport, HighwayIncidentSnapshot
from app.services.place_map_reads import _distinct_index_sources, place_sources
from sqlalchemy import Column, MetaData, String, Table, insert, select, union_all


@pytest.mark.parametrize("sources", [[], ["old-only"],
    ["dup", "dup", "", "A", "a", "서울", "부산", "항구🚢", "old-only"],
])
def test_incident_sources_match_all_history_and_new_source_immediately(client, sources):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL source index walk")

    async def verify():
        async with client.app.state.session_factory() as session:
            old = now_utc() - timedelta(days=40)
            if sources:
                await session.execute(insert(HighwayIncidentSnapshot), [
                    {"source": source, "identity_key": f"old-{i}",
                     "observed_at": old, "collected_at": old}
                    for i, source in enumerate(sources)
                ])
                await session.commit()
            models = {"highway_incident": HighwayIncidentSnapshot, "airport": Airport}
            expected = set((await session.scalars(select(HighwayIncidentSnapshot.source).distinct())).all())
            assert await place_sources(session, ["highway_incident"], models) == expected == set(sources)
            previous = union_all(select(HighwayIncidentSnapshot.source), select(Airport.source)).subquery()
            combined = set((await session.scalars(select(previous.c.source).distinct())).all())
            assert await place_sources(session, list(models), models) == combined
            # A committed new source is visible on the next call; no time filter or cache.
            session.add(HighwayIncidentSnapshot(source="새 출처", identity_key="new-source",
                        observed_at=now_utc(), collected_at=now_utc()))
            await session.commit()
            assert await place_sources(session, ["highway_incident"], models) == expected | {"새 출처"}
    asyncio.run(verify())


def test_nullable_walk_matches_distinct_including_null_and_empty_table(client):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL nullable source index walk")

    async def verify():
        async with client.app.state.session_factory() as session:
            table = Table("place_nullable_sources_fixture", MetaData(),
                          Column("source", String, nullable=True), prefixes=["TEMPORARY"],
                          postgresql_on_commit="DROP")
            connection = await session.connection()
            await connection.run_sync(table.create)
            assert list((await session.scalars(_distinct_index_sources(table.c.source))).all()) == []
            for rows in ([{"source": None}, {"source": None}],
                         [{"source": "중복"}, {"source": "중복"}, {"source": ""}, {"source": "A"}]):
                await session.execute(insert(table), rows)
                expected = set((await session.scalars(select(table.c.source).distinct())).all())
                assert set((await session.scalars(_distinct_index_sources(table.c.source))).all()) == expected
            await session.commit()
    asyncio.run(verify())
