"""원본 성공 이후의 파생 통계 실패·취소를 원천 장애로 바꾸지 않는다."""
import asyncio
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import CollectionRun, RestAreaFuelPrice, TransportCollectionState
from app.services import fuel_statistics as stats
from app.services import rest_area_collection as rest
from test_fuel_statistics import seed


@pytest.mark.parametrize("error", [asyncio.CancelledError, RuntimeError])
def test_rest_area_derived_interruption_keeps_raw_source_success(client, test_settings, error):
    async def exercise():
        class Client:
            async def aclose(self): pass

        async def fetch(_client):
            return (object(),)

        async def store(session, _items, stamp):
            session.add(RestAreaFuelPrice(source=stats.HIGHWAY, service_area_code="A",
                service_area_name="합성 주유소", gasoline_price=1700,
                first_seen_at=stamp, last_seen_at=stamp))
            await session.flush()
            return 1

        service = rest.RestAreaCollectionService(test_settings, client_factory=lambda **kw: Client())
        async with client.app.state.session_factory() as session:
            with patch.object(rest, "cleanup_fuel_statistics", side_effect=error("interrupted")):
                with pytest.raises(error):
                    await service._run(session, rest.REST_AREA_FUEL_TRIGGER, stats.HIGHWAY,
                                       "test:synthetic", fetch, store)
            state = await session.scalar(select(TransportCollectionState).where(
                TransportCollectionState.source == stats.HIGHWAY))
            assert state.last_success_at is not None
            assert state.last_error is None
            assert await session.get(RestAreaFuelPrice, 1) is not None
            run = await session.scalar(select(CollectionRun).where(
                CollectionRun.trigger == rest.REST_AREA_FUEL_TRIGGER))
            assert run.status == "partial_success"
    asyncio.run(exercise())


def test_rebuild_cleanup_rollback_does_not_expire_print_or_skip_next_source(client, test_settings):
    script = next(root / "scripts/rebuild-fuel-statistics.py"
                  for root in (Path(__file__).parents[2], Path(__file__).parents[1])
                  if (root / "scripts/rebuild-fuel-statistics.py").is_file())
    spec = importlib.util.spec_from_file_location("fuel_rebuild", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stamp = datetime.now(timezone.utc)

    async def exercise():
        async with client.app.state.session_factory() as session:
            await seed(session, stamp)
            for source in [stats.OPINET, stats.HIGHWAY]:
                session.add(TransportCollectionState(source=source,last_success_at=stamp,updated_at=stamp))
            session.add(RestAreaFuelPrice(source=stats.HIGHWAY, service_area_code="A",
                gasoline_price=1700, first_seen_at=stamp,last_seen_at=stamp))
            await session.commit()
        with patch.object(module, "get_settings", return_value=test_settings), patch.object(
            stats, "prune_fuel_statistics", side_effect=RuntimeError("temporary cleanup failure")
        ), patch("builtins.print") as output:
            await module.rebuild(None)
            messages = [call.args[0] for call in output.call_args_list]
            assert len(messages) == 2
            assert messages[0].startswith(stats.OPINET)
            assert messages[1].startswith(stats.HIGHWAY)
    asyncio.run(exercise())
