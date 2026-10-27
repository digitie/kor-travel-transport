"""자동 연결의 실제 PostgreSQL 잠금·원자성. 전용 TEST_DATABASE_URL만 사용한다."""
import asyncio
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, select, text

from app.db.session import create_engine_and_session_factory
from app.models import KricStationCode, KricStationMappingRegistry, RailStationReference
from app.schemas import KricAutomaticMappingApplyRequest
from app.services import rail_station_mapping as service

NOW = datetime(2026, 10, 27, 9, tzinfo=UTC)


async def seed(factory):
    async with factory() as session:
        refs = [
            RailStationReference(id=823, source="kric_public_file", identity_key="코레일|경의중앙선|1251|서울역",
                rail_operator_name="코레일", operating_line_name="경의중앙선", station_number="1251", station_name="서울역",
                first_seen_at=NOW, last_seen_at=NOW, raw_item_json={"역 번호": "1251", "원문": "보존"}),
            RailStationReference(id=2, source="kric_public_file", identity_key="stable", rail_operator_name="운영사",
                operating_line_name="노선", station_number="002", station_name="보존역", first_seen_at=NOW, last_seen_at=NOW),
            RailStationReference(id=3, source="kric_public_file", identity_key="manual", rail_operator_name="별도 운영사",
                operating_line_name="별도 노선", station_number="999", station_name="수동 기준역", first_seen_at=NOW, last_seen_at=NOW),
        ]
        session.add_all(refs)
        await session.flush()
        codes = [
            KricStationCode(operator_code="KR", line_code="K4", station_code="P313", operator_name="한국철도공사",
                line_name="경의중앙", station_name="서울역", rail_station_id=None, active=True, last_seen_at=NOW),
            KricStationCode(operator_code="OP", line_code="L1", station_code="002", operator_name="운영사",
                line_name="노선", station_name="보존역", rail_station_id=2, active=True, last_seen_at=NOW),
            KricStationCode(operator_code="OP", line_code="L1", station_code="M1", operator_name="운영사",
                line_name="노선", station_name="수동 코드역", rail_station_id=3, active=True, last_seen_at=NOW),
        ]
        session.add_all(codes)
        catalog = service.station_catalog(codes)
        session.add(KricStationMappingRegistry(id=1, catalog_json=catalog, catalog_sha256=service.catalog_digest(catalog),
            automatic_mappings_json=[dict(operator_code="OP", line_code="L1", station_code="002",
                rail_station_identity_key="stable", match_method="exact_identity")],
            manual_mappings_json=[dict(operator_code="OP", line_code="L1", station_code="M1",
                rail_station_identity_key="manual", note="  원문\n보존 🙂  ", legacy_metadata={"보존": [1, 2]})],
            catalog_updated_at=NOW, mappings_updated_at=NOW, updated_at=NOW))
        await session.commit()


async def snapshot(factory):
    async with factory() as session:
        result = {}
        for table in ("kric_station_codes", "kric_station_mapping_registry", "rail_station_references",
                "rail_service_days", "kric_timetable_snapshots", "transport_collection_states", "collection_runs", "raw_api_responses"):
            result[table] = (await session.scalars(text(f"SELECT to_jsonb(t) FROM {table} AS t ORDER BY to_jsonb(t)::text"))).all()
        return result


def request(preview):
    return KricAutomaticMappingApplyRequest(expected_revision=preview.expected_revision, candidate_revision=preview.candidate_revision)


def run_pg(test_settings, exercise):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("실제 advisory lock·RC snapshot 검증은 전용 PostgreSQL에서 실행한다")

    async def run():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        try:
            await seed(factory)
            await exercise(engine, factory)
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_preview_readonly_apply_only_changed_fk_and_preserves_manual_and_sources(test_settings):
    async def exercise(engine, factory):
        before = await snapshot(factory)
        statements = []
        event.listen(engine.sync_engine, "before_cursor_execute", lambda conn, cursor, sql, params, ctx, many: statements.append((sql, params)))
        async with factory() as session:
            preview = await service.preview_automatic_station_mappings(session)
            assert not session.in_transaction()
        assert not [sql for sql, _ in statements if sql.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
        assert any("SET TRANSACTION READ ONLY" in sql for sql, _ in statements)
        assert await snapshot(factory) == before
        assert preview.before.station_count == 3 and preview.after.mapped_count == 3
        statements.clear()
        async with factory() as session:
            result = await service.apply_automatic_station_mappings(session, request(preview))
        assert result.status == "applied" and result.changed_link_count == 1
        after = await snapshot(factory)
        registry_before, registry_after = before["kric_station_mapping_registry"][0], after["kric_station_mapping_registry"][0]
        assert registry_before["manual_mappings_json"] == registry_after["manual_mappings_json"]
        assert registry_before["catalog_json"] == registry_after["catalog_json"]
        assert registry_before["catalog_sha256"] == registry_after["catalog_sha256"]
        for table in before.keys() - {"kric_station_codes", "kric_station_mapping_registry"}:
            assert before[table] == after[table]
        old_codes = {row["station_code"]: row for row in before["kric_station_codes"]}
        for row in after["kric_station_codes"]:
            if row["station_code"] == "P313":
                old = deepcopy(old_codes["P313"])
                old["rail_station_id"] = 823
                assert row == old
            else:
                assert row == old_codes[row["station_code"]]
        code_writes = [(sql, params) for sql, params in statements if sql.startswith("UPDATE kric_station_codes")]
        assert len(code_writes) == 1  # 기존 FK가 NULL이면 clear 단계의 불필요한 UPDATE는 없다.
        assert code_writes[0][1][0] == 823
        assert not [sql for sql, _ in statements if sql.startswith(("INSERT", "DELETE"))]
    run_pg(test_settings, exercise)


def test_noop_does_not_write_or_update_timestamps(test_settings):
    async def exercise(engine, factory):
        async with factory() as session:
            first = await service.preview_automatic_station_mappings(session)
            await service.apply_automatic_station_mappings(session, request(first))
            noop = await service.preview_automatic_station_mappings(session)
        before = await snapshot(factory)
        writes = []
        event.listen(engine.sync_engine, "before_cursor_execute", lambda conn, cursor, sql, params, ctx, many: writes.append(sql) if sql.startswith(("UPDATE", "INSERT", "DELETE")) else None)
        async with factory() as session:
            result = await service.apply_automatic_station_mappings(session, request(noop))
        assert result.status == "unchanged" and result.changed_link_count == 0
        assert not writes and await snapshot(factory) == before
    run_pg(test_settings, exercise)


@pytest.mark.parametrize("writer", ["manual", "reference"])
def test_rc_waits_for_reference_writer_then_reads_committed_revision(test_settings, writer):
    async def exercise(engine, factory):
        async with factory() as session:
            preview = await service.preview_automatic_station_mappings(session)
        reached_lock = asyncio.Event()
        def observe(conn, cursor, sql, params, ctx, many):
            if "SELECT pg_advisory_xact_lock" in sql:
                reached_lock.set()
        async with factory() as holding:
            await service.lock_rail_station_reference_catalog(holding)
            if writer == "manual":
                row = await holding.get(KricStationMappingRegistry, 1)
                raw = deepcopy(row.manual_mappings_json)
                raw[0]["note"] = "다른 관리자의 새 원문"
                row.manual_mappings_json = raw
            else:
                row = await holding.get(RailStationReference, 823)
                row.station_number = "다른 공식 기준 번호"
            await holding.flush()
            event.listen(engine.sync_engine, "before_cursor_execute", observe)
            async with factory() as applying:
                task = asyncio.create_task(service.apply_automatic_station_mappings(applying, request(preview)))
                await asyncio.wait_for(reached_lock.wait(), 2)
                await asyncio.sleep(0.03)
                assert not task.done()
                await holding.commit()
                with pytest.raises(service.AutomaticMappingConflict, match="역 코드나 매핑이 변경"):
                    await asyncio.wait_for(task, 3)
                assert not applying.in_transaction()
        event.remove(engine.sync_engine, "before_cursor_execute", observe)
        async with factory() as session:
            updated = await service.preview_automatic_station_mappings(session)
            assert updated.expected_revision != preview.expected_revision
            assert updated.before.automatic_mapped_count == preview.before.automatic_mapped_count
    run_pg(test_settings, exercise)


def test_kric_session_lease_blocks_apply_and_rollback_releases_xact_lease(test_settings, monkeypatch):
    async def exercise(engine, factory):
        async with factory() as session:
            preview = await service.preview_automatic_station_mappings(session)
        before = await snapshot(factory)
        async with engine.connect() as holder:
            await holder.execute(text("SELECT pg_advisory_lock(hashtext(:name))"), {"name": service.KRIC_TIMETABLE_LEASE_NAME})
            await holder.commit()
            try:
                async with factory() as session:
                    with pytest.raises(service.AutomaticMappingConflict, match="수집이 진행"):
                        await service.apply_automatic_station_mappings(session, request(preview))
            finally:
                assert await holder.scalar(text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": service.KRIC_TIMETABLE_LEASE_NAME})
                await holder.commit()
        assert await snapshot(factory) == before
        entered, release = asyncio.Event(), asyncio.Event()
        original = service._stored_mapping_inputs
        async def pause(session, **kwargs):
            if kwargs.get("lock_registry"):
                entered.set()
                await release.wait()
            return await original(session, **kwargs)
        monkeypatch.setattr(service, "_stored_mapping_inputs", pause)
        async with factory() as session:
            task = asyncio.create_task(service.apply_automatic_station_mappings(session, request(preview)))
            await asyncio.wait_for(entered.wait(), 2)
            async with engine.connect() as probe:
                assert not await probe.scalar(text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": service.KRIC_TIMETABLE_LEASE_NAME})
                await probe.rollback()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not session.in_transaction()
        async with engine.connect() as probe:
            assert await probe.scalar(text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": service.KRIC_TIMETABLE_LEASE_NAME})
            assert await probe.scalar(text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": service.KRIC_TIMETABLE_LEASE_NAME})
        assert await snapshot(factory) == before
    run_pg(test_settings, exercise)


@pytest.mark.parametrize("failure", ["exception", "cancel", "integrity"])
def test_failure_after_fk_flush_rolls_back_every_change(test_settings, monkeypatch, failure):
    async def exercise(engine, factory):
        async with factory() as session:
            preview = await service.preview_automatic_station_mappings(session)
        before = await snapshot(factory)
        async with factory() as session:
            entered = asyncio.Event()
            async def broken_commit():
                await session.flush()
                assert (await session.scalar(select(KricStationCode.rail_station_id).where(KricStationCode.station_code == "P313"))) == 823
                entered.set()
                if failure == "cancel":
                    await asyncio.Future()
                if failure == "integrity":
                    await session.execute(text("""INSERT INTO kric_station_codes
                        (operator_code,line_code,station_code,operator_name,line_name,station_name,rail_station_id,active,last_seen_at)
                        SELECT 'TEST','TX','duplicate','시험','시험','시험',rail_station_id,true,last_seen_at
                        FROM kric_station_codes WHERE station_code='002'"""))
                raise RuntimeError("의도한 commit 직전 실패")
            monkeypatch.setattr(session, "commit", broken_commit)
            task = asyncio.create_task(service.apply_automatic_station_mappings(session, request(preview)))
            await asyncio.wait_for(entered.wait(), 2)
            if failure == "cancel":
                task.cancel()
            error = {"cancel": asyncio.CancelledError, "integrity": service.AutomaticMappingConflict,
                "exception": RuntimeError}[failure]
            with pytest.raises(error):
                await task
            assert not session.in_transaction()
        assert await snapshot(factory) == before
    run_pg(test_settings, exercise)


def test_two_fk_swap_is_atomic_and_never_rewrites_the_unrelated_manual_row(test_settings):
    async def exercise(engine, factory):
        async with factory() as session:
            codes = (await session.scalars(select(KricStationCode).order_by(KricStationCode.id))).all()
            refs = (await session.scalars(select(RailStationReference))).all()
            by_id = {row.id: row for row in refs}
            codes[0].operator_code, codes[0].line_code = "OP", "L1"
            codes[0].operator_name, codes[0].line_name = "운영사", "노선"
            codes[0].station_name, codes[0].rail_station_id = "역B", 823
            codes[1].station_name = "역A"
            by_id[823].rail_operator_name, by_id[823].operating_line_name, by_id[823].station_name = "운영사", "노선", "역A"
            by_id[2].station_name = "역B"
            registry = await session.get(KricStationMappingRegistry, 1)
            registry.catalog_json = service.station_catalog(codes)
            registry.catalog_sha256 = service.catalog_digest(registry.catalog_json)
            registry.automatic_mappings_json = [dict(operator_code="OP", line_code="L1", station_code=row.station_code,
                rail_station_identity_key=identity, match_method="exact_identity") for row, identity in
                ((codes[0], by_id[823].identity_key), (codes[1], by_id[2].identity_key))]
            await session.commit()
        before = await snapshot(factory)
        writes = []
        event.listen(engine.sync_engine, "before_cursor_execute", lambda conn, cursor, sql, params, ctx, many: writes.append((sql, params)) if sql.startswith("UPDATE kric_station_codes") else None)
        async with factory() as session:
            preview = await service.preview_automatic_station_mappings(session)
            assert [row.change_type for row in preview.changes] == ["retargeted", "retargeted"]
            result = await service.apply_automatic_station_mappings(session, request(preview))
            assert result.changed_link_count == 2
        after = await snapshot(factory)
        assert {row["station_code"]: row["rail_station_id"] for row in after["kric_station_codes"]} == {"P313": 2, "002": 823, "M1": 3}
        assert after["kric_station_mapping_registry"][0]["manual_mappings_json"] == before["kric_station_mapping_registry"][0]["manual_mappings_json"]
        manual_id = next(row["id"] for row in before["kric_station_codes"] if row["station_code"] == "M1")
        assert writes
        for _, params in writes:
            batches = params if isinstance(params[0], tuple) else [params]
            assert all(batch[-1] != manual_id for batch in batches)
    run_pg(test_settings, exercise)


def test_lock_timeout_is_a_conflict_and_leaves_no_partial_write(test_settings):
    async def exercise(engine, factory):
        async with factory() as session:
            preview = await service.preview_automatic_station_mappings(session)
        before = await snapshot(factory)
        async with factory() as holding:
            await service.lock_rail_station_reference_catalog(holding)
            async with factory() as session:
                with pytest.raises(service.AutomaticMappingConflict, match="다른 역정보 변경"):
                    await service.apply_automatic_station_mappings(session, request(preview))
                assert not session.in_transaction()
            await holding.rollback()
        assert await snapshot(factory) == before
    run_pg(test_settings, exercise)


def test_method_only_change_updates_registry_without_fk_updates(test_settings):
    async def exercise(engine, factory):
        async with factory() as session:
            preview = await service.preview_automatic_station_mappings(session)
            await service.apply_automatic_station_mappings(session, request(preview))
            registry = await session.get(KricStationMappingRegistry, 1)
            automatic = deepcopy(registry.automatic_mappings_json)
            automatic[0]["match_method"] = "station_number_and_name"
            registry.automatic_mappings_json = automatic
            await session.commit()
        writes = []
        event.listen(engine.sync_engine, "before_cursor_execute", lambda conn, cursor, sql, params, ctx, many: writes.append(sql) if sql.startswith("UPDATE kric_station_codes") else None)
        async with factory() as session:
            preview = await service.preview_automatic_station_mappings(session)
            assert preview.has_changes and preview.changes[0].change_type == "method_changed"
            result = await service.apply_automatic_station_mappings(session, request(preview))
            assert result.status == "applied" and result.changed_link_count == 0
        assert not writes
    run_pg(test_settings, exercise)
