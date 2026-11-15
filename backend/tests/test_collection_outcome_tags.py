"""수집 결과의 경고 태그는 선택적 관측이며 정상 후속 작업이 지우지 않는다."""

from types import SimpleNamespace

import pytest
from app.dagster.definitions import _record_collection_outcome

TAG = "kortravel/collection-outcome"


@pytest.mark.parametrize("previous,outcome,expected,writes", [
    (None, "success", None, 0), ("partial", "success", "partial", 0),
    ("deferred", "success", "deferred", 0), (None, "deferred", "deferred", 1),
    (None, "partial", "partial", 1), ("deferred", "partial", "partial", 1),
    ("partial", "deferred", "partial", 0), ("partial", "partial", "partial", 0),
    ("success", "deferred", "deferred", 1), (None, "failed", None, 0),
])
def test_optional_warning_tag_never_downgrades_observed_warning(
    previous, outcome, expected, writes,
):
    tags = {TAG: previous} if previous else {}
    calls = []

    def update(run_id, new_tags):
        calls.append((run_id, new_tags))
        tags.update(new_tags)

    context = SimpleNamespace(run_id="own-run", instance=SimpleNamespace(
        get_run_by_id=lambda run_id: SimpleNamespace(tags=tags), add_run_tags=update,
    ))
    _record_collection_outcome(context, outcome)
    assert tags.get(TAG) == expected and len(calls) == writes
    assert all(run_id == "own-run" and set(values) == {TAG} for run_id, values in calls)


@pytest.mark.parametrize("stage", ["read", "write", "missing_instance"])
def test_tag_storage_failure_cannot_fail_collection_or_log_private_error(stage):
    messages = []

    def fail(*args):
        raise RuntimeError("private database connection detail")

    instance = SimpleNamespace(
        get_run_by_id=fail if stage == "read" else lambda _: SimpleNamespace(tags={}),
        add_run_tags=fail,
    )
    context = SimpleNamespace(
        run_id="own-run", instance=None if stage == "missing_instance" else instance,
        log=SimpleNamespace(warning=messages.append),
    )
    _record_collection_outcome(context, "partial")
    assert messages == ([] if stage == "missing_instance" else ["COLLECTION_OUTCOME_TAG_DEFERRED"])
