"""서로 다른 수집기의 상태 쓰기가 서로를 기다리지 않는다 (COLLECTION-STATE-LOCK-20261124, 0048).

0045의 문장 trigger는 `transport_collection_states` 쓰기마다 `reference_export_input_revisions`의 한 행을 commit까지
잠가, 고속도로·유가처럼 상태를 쓴 뒤 저장을 이어 가는 transaction이 있는 동안 다른 수집기(공항 quota·휴게소 유가 claim)의
상태 UPDATE가 세션 `lock_timeout`(5초)으로 실패했다(운영 odroid 14일 38건). 0048은 이 표를 trigger에서 빼고 장소 캐시는
같은 snapshot의 내용 digest로 상태 변화를 본다.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_engine_and_session_factory


@pytest.fixture
def pg(test_settings: Settings) -> Settings:
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("실제 PostgreSQL 문장 trigger·행 잠금")
    return test_settings


def test_other_collectors_state_write_does_not_wait_for_an_open_state_transaction(pg) -> None:
    async def run():
        engine, factory = create_engine_and_session_factory(pg.database_url, collector=True)
        try:
            async with factory() as setup:
                await setup.execute(text(
                    "INSERT INTO transport_collection_states (source, updated_at) VALUES "
                    "('krex_traffic_flow', now()), ('airport_kac_quota', now())"))
                await setup.commit()
            holder = factory()
            try:
                # 고속도로 저장 transaction: 성공 표시 뒤 수천 행 저장(운영 표본 175초+) 동안 commit하지 않는다.
                await holder.execute(text(
                    "UPDATE transport_collection_states SET last_success_at = now() WHERE source = 'krex_traffic_flow'"))
                async with factory() as other:
                    await other.execute(text("SET LOCAL lock_timeout = '200ms'"))
                    # 공항 quota 결과 기록(매 5분): 다른 source 행이라 기다리지 않는다.
                    await other.execute(text(
                        "UPDATE transport_collection_states SET updated_at = now() WHERE source = 'airport_kac_quota'"))
                    await other.execute(text(
                        "INSERT INTO transport_collection_states (source, updated_at) VALUES ('krex_rest_area_fuel', now())"))
                    await other.commit()
            finally:
                await holder.rollback()
                await holder.close()
            async with factory() as check:
                triggers = await check.scalar(text(
                    "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'public.transport_collection_states'::regclass "
                    "AND tgname LIKE 'kt_places_revision_%'"))
                # 옛 이미지가 배포 중 503을 내지 않게 component 행은 남긴다(아무도 올리지 않는다).
                component = await check.scalar(text(
                    "SELECT count(*) FROM reference_export_input_revisions "
                    "WHERE component = 'places.transport_collection_states'"))
                others = await check.scalar(text(
                    "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND t.tgname LIKE 'kt_places_revision_%'"))
        finally:
            await engine.dispose()
        return triggers, component, others

    triggers, component, others = asyncio.run(run())
    assert (triggers, component) == (0, 1)
    assert others == 40  # 나머지 10개 입력 표의 INSERT·UPDATE·DELETE·TRUNCATE trigger는 그대로다.
