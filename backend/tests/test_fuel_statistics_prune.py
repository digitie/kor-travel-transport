"""이전 통계 세대 정리가 수집을 따라잡는지 검증한다(FUEL-PRUNE-BACKLOG-20261123).

운영에서는 2,000개 키를 `(4열) IN ((...), ...)`로 다시 보내는 문장의 계획만 3.2초라 수집마다
한 배치(2,000행)만 지워 세대가 54개까지 쌓였다. 정리는 매개변수 수가 행 수와 무관한 한 문장이어야 하고,
쌓인 세대는 한 번의 예산 안에서 배치를 이어가며 오래된 것부터 지워야 한다.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, func, insert, select

from app.db.session import create_engine_and_session_factory
from app.models import FuelStatisticsPoint, FuelStatisticsState
from app.services import fuel_statistics as stats

ROWS_PER_GENERATION = 25


async def _seed_generations(session, source: str, base: datetime, generations: int) -> list[datetime]:
    stamps = [base + timedelta(hours=8 * index) for index in range(generations)]
    for stamp in stamps:
        await session.execute(insert(FuelStatisticsPoint), [{
            "source": source, "station_key": str(station), "product_code": "B027", "generated_at": stamp,
            "name": f"주유소{station}", "address": None, "brand_name": None,
            "longitude": 127.0, "latitude": 37.5, "price": 1600 + station,
        } for station in range(ROWS_PER_GENERATION)])
    session.add(FuelStatisticsState(source=source, generated_at=stamps[-1], day=stamps[-1].date()))
    await session.commit()
    return stamps


async def _counts(session, source: str) -> dict[datetime, int]:
    p = FuelStatisticsPoint
    rows = (await session.execute(select(p.generated_at, func.count()).where(p.source == source)
                                  .group_by(p.generated_at))).all()
    await session.rollback()
    return {stamp.replace(tzinfo=stamp.tzinfo or timezone.utc): count for stamp, count in rows}


def test_backlog_is_pruned_in_bounded_statements_and_keeps_public_generation(test_settings, caplog):
    async def exercise():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        base = datetime(2026, 10, 24, tzinfo=timezone.utc)
        delete_parameters: list[int] = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("DELETE FROM FUEL_STATISTICS_POINTS"):
                size = len(parameters) if isinstance(parameters, (tuple, list, dict)) else 0
                delete_parameters.append(size)

        event.listen(engine.sync_engine, "before_cursor_execute", capture)
        try:
            async with factory() as session:
                stamps = await _seed_generations(session, stats.OPINET, base, 6)
                await _seed_generations(session, stats.HIGHWAY, base, 2)
            async with factory() as session:
                with caplog.at_level(logging.INFO, logger=stats.logger.name):
                    cleanup = await stats.cleanup_fuel_statistics(session, stats.OPINET, batch_rows=10)
                assert cleanup.deleted == 5 * ROWS_PER_GENERATION
                assert cleanup.outcome == "done"
                assert cleanup.metadata() == {"fuel_statistics_cleanup": "done",
                                              "fuel_statistics_pruned_rows": 5 * ROWS_PER_GENERATION}
                # 25행 세대 5개를 10행씩: 배치가 이어지고 마지막 짧은 배치(5행)에서 멈춘다.
                assert len(delete_parameters) == 13
                # 매개변수 수가 지우는 행 수(10)에 비례하지 않는다: 원천·한도 정도만 묶는다.
                assert max(delete_parameters) <= 4
                remaining = await _counts(session, stats.OPINET)
                assert remaining == {stamps[-1]: ROWS_PER_GENERATION}
                # 다른 원천의 이전 세대는 그 원천의 정리가 맡는다.
                assert sum((await _counts(session, stats.HIGHWAY)).values()) == 2 * ROWS_PER_GENERATION
                assert "deleted=125" in caplog.text
                # 지울 것이 없으면 한 문장으로 끝난다.
                delete_parameters.clear()
                assert (await stats.cleanup_fuel_statistics(session, stats.OPINET, batch_rows=10)).deleted == 0
                assert len(delete_parameters) == 1
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", capture)
            await engine.dispose()
    asyncio.run(exercise())


def test_budget_is_checked_between_batches_and_oldest_generations_go_first(test_settings, caplog):
    async def exercise():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        base = datetime(2026, 10, 24, tzinfo=timezone.utc)
        ticks = iter([0.0, 0.0, 0.5, 2.0])  # 시작, 1·2번째 배치 전, 3번째 전에 예산(1초) 초과

        try:
            async with factory() as session:
                stamps = await _seed_generations(session, stats.OPINET, base, 4)
            async with factory() as session:
                with caplog.at_level(logging.WARNING, logger=stats.logger.name):
                    cleanup = await stats.cleanup_fuel_statistics(
                        session, stats.OPINET, budget_seconds=1.0, batch_rows=ROWS_PER_GENERATION,
                        clock=lambda: next(ticks),
                    )
                assert cleanup.deleted == 2 * ROWS_PER_GENERATION
                # 예산 소진은 남은 세대가 있다는 뜻이다. 조용히 끝내지 않고 결과·경고로 남긴다.
                assert cleanup.outcome == "budget_exhausted"
                assert "budget exhausted" in caplog.text
                # 예산이 끝나면 남은 세대는 다음 수집이 이어서 지운다. 가장 오래된 두 세대가 먼저 사라진다.
                assert set(await _counts(session, stats.OPINET)) == {stamps[2], stamps[3]}
                assert (await stats.cleanup_fuel_statistics(session, stats.OPINET)).deleted == ROWS_PER_GENERATION
                assert set(await _counts(session, stats.OPINET)) == {stamps[3]}
        finally:
            await engine.dispose()
    asyncio.run(exercise())
