"""수집/주소 갱신 뒤 내부 준비를 연결하고, 외부 수집과 예약 수를 늘리지 않는다."""
import copy
import logging
from types import SimpleNamespace

from dagster import DagsterInstance, job, op

from app.dagster import address_refresh
from app.dagster import definitions as d
from app.services import reference_export_preparation


def test_reference_job_waits_for_both_sources_and_has_no_new_schedule():
    graph = d.definitions.get_job_def("rail_reference_collection_job").graph
    assert set(graph.node_names()) == {"collect_rail_reference", "collect_general_rail_reference", "prepare_reference_exports"}
    deps = graph.dependency_structure
    node = graph.node_named("prepare_reference_exports")
    upstream = {handle.node_name for values in deps.input_to_upstream_outputs_for_node(node.name).values() for handle in values}
    assert upstream == {"collect_rail_reference", "collect_general_rail_reference"}
    publisher = d.definitions.get_job_def("reference_export_prepare_job")
    assert publisher.graph.node_names() == ["prepare_reference_exports"]
    assert publisher.tags["dagster/max_runtime"] == "180"
    assert all(v.job_name != publisher.name for v in d.definitions.schedules)


def test_address_refresh_prepares_after_committed_address_action(monkeypatch):
    settings = SimpleNamespace(transport_map_current_enabled=True)
    calls = [];result = {"status": "success"}
    monkeypatch.setattr(address_refresh,"get_settings",lambda:settings)
    monkeypatch.setattr(address_refresh,"configured",lambda _:True)
    def addresses(s,force):
        assert s is settings and force is False
        calls.append("addresses");return result
    async def prepare(s, *, total_budget_seconds):
        assert s is settings
        # Dagster 밖이면 수집 job 꼬리와 같은 짧은 예산이다.
        assert total_budget_seconds == reference_export_preparation.COLLECTION_TAIL_PREPARE_BUDGET_SECONDS
        calls.append("prepare");return {"status":"success","prepared":1}
    monkeypatch.setattr(address_refresh,"run_address_refresh",addresses)
    monkeypatch.setattr(reference_export_preparation,"prepare_reference_exports_for_settings",prepare)
    assert address_refresh._run(False) is result
    assert calls == ["addresses","prepare"]
    # 준비 결과가 사라지지 않는다(주소 갱신 결과 로그에 요약이 붙는다).
    assert result["reference_export_prepare"]["reference_status"] == "success"


def test_address_refresh_job_records_a_partial_prepare_without_failing(monkeypatch):
    """주소는 이미 commit됐다. 준비 실패는 주소 갱신 run의 metadata·태그로 남고 run을 실패시키지 않는다."""
    settings = SimpleNamespace(transport_map_current_enabled=True)
    monkeypatch.setattr(address_refresh, "get_settings", lambda: settings)
    monkeypatch.setattr(address_refresh, "configured", lambda _: True)
    monkeypatch.setattr(address_refresh, "run_address_refresh", lambda _s, force: {"status": "success"})
    budgets = []

    async def prepare(_s, *, total_budget_seconds):
        budgets.append(total_budget_seconds)
        return {"status": "partial_success", "prepared": 0, "reused": 1, "busy": 0, "deferred": 0, "failed": 1,
                "kinds": [{"kind": "rail-stations-v1", "status": "failed", "duration_ms": 4, "error_type": "OSError"},
                          {"kind": "ferry-ports-v1", "status": "reused", "duration_ms": 2}]}

    monkeypatch.setattr(reference_export_preparation, "prepare_reference_exports_for_settings", prepare)
    with DagsterInstance.ephemeral() as instance:
        run = address_refresh.address_refresh_job.execute_in_process(raise_on_error=False, instance=instance)
        tag = instance.get_run_by_id(run.run_id).tags.get("kortravel/collection-outcome")
    assert run.success and tag == "partial"
    output = next(event for event in run.all_events if event.event_type_value == "STEP_OUTPUT")
    metadata = output.event_specific_data.metadata
    assert metadata["error_code"].value == "REFERENCE_EXPORT_PARTIAL"
    assert metadata["failed_kinds"].value == "rail-stations-v1"
    # 주소 갱신 run 상한(120초) 안에서 준비 예산을 줄인다.
    assert 0 < budgets[0] <= 90


@op
def _collected_upstream() -> dict:
    return {"status": "success"}


@job
def _collection_tail_job() -> None:
    """5분 공항 수집처럼 수집 op 뒤에 준비 step이 붙은 job."""
    d.prepare_reference_exports(_collected_upstream())


def _run_prepare_job(monkeypatch, result, job_def=None, *, instance=None, budgets=None):
    """준비 step이 있는 job을 돌리고 (실행 결과, outcome 태그, WARNING 문장)을 돌려준다(기본은 전용 준비 job)."""
    async def fake_run_with_session(_settings, action, *_args, **_kwargs):
        if budgets is not None:
            budgets.append(action.keywords["total_budget_seconds"])
        return copy.deepcopy(result)

    monkeypatch.setattr(d, "_settings", lambda: SimpleNamespace(transport_map_current_enabled=True))
    monkeypatch.setattr(d, "_run_with_session", fake_run_with_session)

    def execute(instance):
        run = (job_def or d.reference_export_prepare_job).execute_in_process(raise_on_error=False, instance=instance)
        warnings = [entry.user_message for entry in instance.all_logs(run.run_id)
                    if entry.level == logging.WARNING and entry.step_key == "prepare_reference_exports"]
        tag = instance.get_run_by_id(run.run_id).tags.get("kortravel/collection-outcome")
        return run, tag, warnings

    if instance is not None:
        return execute(instance)
    with DagsterInstance.ephemeral() as ephemeral:
        return execute(ephemeral)


def _step_metadata(run, event_type):
    events = [event for event in run.all_events
              if event.step_key == "prepare_reference_exports" and event.event_type_value == event_type]
    assert events, event_type
    data = events[0].event_specific_data
    return data.metadata if event_type == "STEP_OUTPUT" else data.user_failure_data.metadata


def test_one_failed_kind_is_partial_success_not_run_failure(monkeypatch):
    """한 종류의 실패가 5분 공항 run을 FAILURE로 만들던 문제(T23-04·WLH-04): 부분 성공 + 태그 + 경고로 둔다."""
    result = {"status": "partial_success", "prepared": 1, "reused": 1, "failed": 1, "kinds": [
        {"kind": "bus-terminals-v1", "status": "reused", "duration_ms": 12, "artifact_id": "a1"},
        {"kind": "ferry-ports-v1", "status": "failed", "duration_ms": 15012, "error_type": "HTTPException",
         "reason": "reference 본문 구성 시간 상한을 초과했습니다."},
        {"kind": "rail-stations-v1", "status": "prepared", "duration_ms": 4321, "item_count": 1466},
    ], "gc": {"expired_handles": 2, "unused_artifacts": 1, "duration_ms": 40}}
    run, tag, warnings = _run_prepare_job(monkeypatch, result)
    assert run.success
    assert tag == "partial"
    metadata = _step_metadata(run, "STEP_OUTPUT")
    # 최상위 status는 쓰지 않는다(관리 콘솔이 "저장 결과: 실패"로 읽는다). 준비 결과는 reference_status다.
    assert "status" not in metadata and metadata["reference_status"].value == "partial_success"
    assert metadata["failed"].value == 1 and metadata["failed_kinds"].value == "ferry-ports-v1"
    assert metadata["collection_outcome"].value == "partial"
    assert metadata["error_code"].value == "REFERENCE_EXPORT_PARTIAL"
    assert metadata["gc_expired_handles"].value == 2 and metadata["gc_unused_artifacts"].value == 1
    kinds = metadata["kinds"].value
    assert [row["status"] for row in kinds] == ["reused", "failed", "prepared"]
    assert all("artifact_id" not in row for row in kinds)  # 공용 event log에는 고정 필드만 남긴다.
    assert kinds[1]["reason"] == "reference 본문 구성 시간 상한을 초과했습니다."
    assert any("ferry-ports-v1" in line for line in warnings)


_NOTHING_PREPARED = {"status": "failed", "prepared": 0, "reused": 0, "busy": 0, "failed": 2, "kinds": [
    {"kind": "ferry-ports-v1", "status": "failed", "duration_ms": 5, "error_type": "OSError"},
    {"kind": "rail-stations-v1", "status": "failed", "duration_ms": 5, "error_type": "OSError"},
]}


def test_dedicated_prepare_job_fails_when_nothing_could_be_prepared(monkeypatch):
    assert d.reference_export_prepare_job.name == d.REFERENCE_EXPORT_PREPARE_JOB
    budgets = []
    run, _tag, _warnings = _run_prepare_job(monkeypatch, _NOTHING_PREPARED, budgets=budgets)
    assert not run.success
    assert not any(event.is_step_up_for_retry for event in run.all_events)
    metadata = _step_metadata(run, "STEP_FAILURE")
    assert metadata["failed"].value == 2
    # 관리 콘솔이 미등록 오류로 보지 않게 고정 코드를 단다.
    assert metadata["error_code"].value == "REFERENCE_EXPORT_FAILED"
    assert metadata["failed_kinds"].value == "ferry-ports-v1,rail-stations-v1"
    # 전용 job(run 상한 180초)의 준비 예산은 run deadline(180 − 60)보다 먼저 끝난다.
    assert 0 < budgets[0] <= 110


def test_collection_run_stays_successful_when_nothing_could_be_prepared(monkeypatch):
    """수집 job 꼬리의 준비가 모두 실패해도 이미 commit된 수집 run을 FAILURE로 만들지 않는다(부분 완료)."""
    budgets = []
    run, tag, warnings = _run_prepare_job(monkeypatch, _NOTHING_PREPARED, _collection_tail_job, budgets=budgets)
    assert run.success
    assert tag == "partial"
    metadata = _step_metadata(run, "STEP_OUTPUT")
    assert metadata["collection_outcome"].value == "partial"
    assert metadata["error_code"].value == "REFERENCE_EXPORT_FAILED"
    assert "status" not in metadata and metadata["reference_status"].value == "failed"
    assert any("ferry-ports-v1, rail-stations-v1" in line for line in warnings)
    # 수집 job 꼬리는 5분 주기를 막지 않게 짧은 예산(60초)이다.
    assert budgets == [reference_export_preparation.COLLECTION_TAIL_PREPARE_BUDGET_SECONDS]


_BUSY = {"status": "success", "prepared": 0, "reused": 1, "busy": 1, "failed": 0, "kinds": [
    {"kind": "ferry-ports-v1", "status": "reused", "duration_ms": 3},
    {"kind": "rail-stations-v1", "status": "busy", "duration_ms": 5012, "error_type": "DBAPIError",
     "sqlstate": "55P03"},
], "gc": {"expired_handles": 0, "unused_artifacts": 0, "duration_ms": 4, "busy": True}}


def test_contention_is_an_explicit_deferred_outcome_not_a_failure(monkeypatch):
    """배포 직후 준비와 공항 수집의 준비가 겹친 쪽(busy)은 실패·부분이 아니지만 성공으로 숨기지도 않는다."""
    for job_def in (None, _collection_tail_job):
        with DagsterInstance.ephemeral() as instance:
            run, tag, warnings = _run_prepare_job(monkeypatch, _BUSY, job_def, instance=instance)
            run_tags = instance.get_run_by_id(run.run_id).tags
        assert run.success and tag == "deferred"
        metadata = _step_metadata(run, "STEP_OUTPUT")
        assert metadata["busy"].value == 1 and metadata["failed"].value == 0
        assert metadata["busy_kinds"].value == "rail-stations-v1"
        assert metadata["error_code"].value == "REFERENCE_EXPORT_BUSY"
        assert metadata["collection_outcome"].value == "deferred" and metadata["gc_busy"].value is True
        assert run_tags[d.REFERENCE_BUSY_TAG] == "rail-stations-v1"
        assert any("rail-stations-v1" in line and "다른 준비" in line for line in warnings)


def test_persistent_busy_is_escalated_after_consecutive_runs(monkeypatch):
    """같은 종류가 연속 3회 busy면(버려진 잠금 등) 실패로 올려 부분 완료로 보인다."""
    with DagsterInstance.ephemeral() as instance:
        outcomes = []
        for _ in range(3):
            run, tag, _warnings = _run_prepare_job(monkeypatch, _BUSY, _collection_tail_job, instance=instance)
            outcomes.append((run.success, tag, _step_metadata(run, "STEP_OUTPUT")["error_code"].value))
    assert outcomes[:2] == [(True, "deferred", "REFERENCE_EXPORT_BUSY")] * 2
    assert outcomes[2] == (True, "partial", "REFERENCE_EXPORT_PARTIAL")
    metadata = _step_metadata(run, "STEP_OUTPUT")
    assert metadata["failed_kinds"].value == "rail-stations-v1" and "busy_kinds" not in metadata


def test_budget_deferred_kinds_are_an_explicit_deferred_outcome(monkeypatch):
    result = {"status": "success", "prepared": 0, "reused": 2, "busy": 0, "deferred": 2, "failed": 0, "kinds": [
        {"kind": "rail-stations-v1", "status": "reused", "duration_ms": 3},
        {"kind": "ferry-ports-v1", "status": "reused", "duration_ms": 3},
        {"kind": "bus-terminals-v1", "status": "deferred", "duration_ms": 0, "reason": "준비 시간 예산을 다 써 다음 준비로 미뤘습니다."},
        {"kind": "parking-current-v1", "status": "deferred", "duration_ms": 0},
    ]}
    run, tag, _warnings = _run_prepare_job(monkeypatch, result, _collection_tail_job)
    metadata = _step_metadata(run, "STEP_OUTPUT")
    assert run.success and tag == "deferred"
    assert metadata["error_code"].value == "REFERENCE_EXPORT_DEFERRED"
    assert metadata["deferred_kinds"].value == "bus-terminals-v1,parking-current-v1"


def test_all_kinds_ready_is_plain_success(monkeypatch):
    result = {"status": "success", "prepared": 0, "reused": 4, "failed": 0, "kinds": [
        {"kind": kind, "status": "reused", "duration_ms": 3}
        for kind in ("bus-terminals-v1", "ferry-ports-v1", "rail-stations-v1", "parking-current-v1")
    ]}
    run, tag, warnings = _run_prepare_job(monkeypatch, result)
    assert run.success and tag is None and warnings == []
    metadata = _step_metadata(run, "STEP_OUTPUT")
    assert metadata["reused"].value == 4 and "error_code" not in metadata
