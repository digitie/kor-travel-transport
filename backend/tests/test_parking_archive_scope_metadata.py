"""공항과 전국의 서로 다른 검산 창을 같은 범위로 위장하지 않는다."""
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import parking_global_archive as module
from test_parking_statistics_archive import AT, NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("airport_status,global_status,expected", [
    ("batch_complete", "batch_complete", "batch_complete"),
    ("batch_complete", "no_new_rows", "batch_complete"),
    ("no_new_rows", "batch_complete", "batch_complete"),
    ("no_new_rows", "deferred", "deferred"),
    ("no_new_rows", "no_new_rows", "no_new_rows"),
])
async def test_combined_outcome_preserves_separate_domains(monkeypatch, airport_status, global_status, expected):
    @asynccontextmanager
    async def nested():
        yield

    session = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
                              scalar=AsyncMock(return_value=None), begin_nested=nested)
    airport_selected = airport_status == "batch_complete"
    global_selected = global_status != "no_new_rows"
    airport = {"status": airport_status, "coverage_status": "partial" if airport_selected else "not_audited",
               "archived_buckets": int(airport_selected), "selection_start_at": AT.isoformat() if airport_selected else None,
               "selected_buckets": 2 if airport_selected else 0, "verified_buckets": int(airport_selected)}
    global_result = {"status": global_status, "coverage_status": "partial" if global_selected else "not_audited",
                     "global_buckets": int(global_status == "batch_complete"),
                     "global_deferred_buckets": int(global_status == "deferred"),
                     "global_selection_start_at": (AT + timedelta(days=2)).isoformat() if global_selected else None,
                     "global_selected_buckets": 3 if global_selected else 0,
                     "global_verified_buckets": int(global_status == "batch_complete")}
    monkeypatch.setattr(module, "seed_latest_states", AsyncMock(return_value=4))
    airport_action = AsyncMock(return_value=airport)
    global_action = AsyncMock(return_value=global_result)
    monkeypatch.setattr(module, "archive_parking_statistics", airport_action)
    monkeypatch.setattr(module, "archive_global_statistics", global_action)
    result = await module.archive_parking_with_coverage(session, checked_at=NOW)
    assert result["status"] == expected
    assert result["airport_status"] == airport_status and result["global_status"] == global_status
    assert result["verification_domain"] == "airport_statistics"
    for key in ["selection_start_at", "selected_buckets", "verified_buckets", "archived_buckets"]:
        assert result[key] == airport[key]
    for key in ["global_selection_start_at", "global_selected_buckets", "global_verified_buckets", "global_buckets"]:
        assert result[key] == global_result[key]
    assert result["latest_seeded"] == 4 and result["pruned_snapshots"] == 0
    airport_action.assert_awaited_once_with(session, checked_at=NOW)
    global_action.assert_awaited_once_with(session, checked_at=NOW)
