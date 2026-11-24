"""수집/주소 갱신 뒤 내부 준비를 연결하고, 외부 수집과 예약 수를 늘리지 않는다."""
from types import SimpleNamespace

from dagster import job, op

from app.dagster import definitions as d
from app.dagster import address_refresh
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
    async def prepare(s):
        assert s is settings
        calls.append("prepare");return {"status":"success","prepared":1}
    monkeypatch.setattr(address_refresh,"run_address_refresh",addresses)
    monkeypatch.setattr(reference_export_preparation,"prepare_reference_exports_for_settings",prepare)
    assert address_refresh._run(False) is result
    assert calls == ["addresses","prepare"]


@op
def _collected_upstream() -> dict:
    return {"status": "success"}


@job
def _collection_tail_job() -> None:
    """5분 공항 수집처럼 수집 op 뒤에 준비 step이 붙은 job."""
    d.prepare_reference_exports(_collected_upstream())


def _run_prepare_job(monkeypatch, result, job_def=None):
    """준비 step이 있는 job을 돌리고 (실행 결과, outcome 태그, WARNING 문장)을 돌려준다(기본은 전용 준비 job)."""
    import logging

    from dagster import DagsterInstance

    async def fake_run_with_session(*_args, **_kwargs):
        return result

    monkeypatch.setattr(d, "_settings", lambda: SimpleNamespace(transport_map_current_enabled=True))
    monkeypatch.setattr(d, "_run_with_session", fake_run_with_session)
    with DagsterInstance.ephemeral() as instance:
        run = (job_def or d.reference_export_prepare_job).execute_in_process(raise_on_error=False, instance=instance)
        warnings = [entry.user_message for entry in instance.all_logs(run.run_id)
                    if entry.level == logging.WARNING and entry.step_key == "prepare_reference_exports"]
        tag = instance.get_run_by_id(run.run_id).tags.get("kortravel/collection-outcome")
    return run, tag, warnings


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
    assert metadata["status"].value == "partial_success"
    assert metadata["failed"].value == 1
    assert metadata["collection_outcome"].value == "partial"
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
    run, _tag, _warnings = _run_prepare_job(monkeypatch, _NOTHING_PREPARED)
    assert not run.success
    assert not any(event.is_step_up_for_retry for event in run.all_events)
    metadata = _step_metadata(run, "STEP_FAILURE")
    assert metadata["failed"].value == 2


def test_collection_run_stays_successful_when_nothing_could_be_prepared(monkeypatch):
    """수집 job 꼬리의 준비가 모두 실패해도 이미 commit된 수집 run을 FAILURE로 만들지 않는다(부분 완료)."""
    run, tag, warnings = _run_prepare_job(monkeypatch, _NOTHING_PREPARED, _collection_tail_job)
    assert run.success
    assert tag == "partial"
    metadata = _step_metadata(run, "STEP_OUTPUT")
    assert metadata["collection_outcome"].value == "partial"
    assert metadata["error_code"].value == "REFERENCE_EXPORT_FAILED"
    assert any("ferry-ports-v1, rail-stations-v1" in line for line in warnings)


def test_contention_with_another_preparation_is_not_a_failure(monkeypatch):
    """배포 직후 준비와 공항 수집의 준비가 같은 본문을 두고 겹친 쪽(busy)은 실패·부분이 아니다."""
    result = {"status": "success", "prepared": 0, "reused": 1, "busy": 1, "failed": 0, "kinds": [
        {"kind": "ferry-ports-v1", "status": "reused", "duration_ms": 3},
        {"kind": "rail-stations-v1", "status": "busy", "duration_ms": 5012, "error_type": "DBAPIError",
         "sqlstate": "55P03"},
    ], "gc": {"expired_handles": 0, "unused_artifacts": 0, "duration_ms": 4, "busy": True}}
    for job_def in (None, _collection_tail_job):
        run, tag, warnings = _run_prepare_job(monkeypatch, result, job_def)
        assert run.success and tag is None and warnings == []
        metadata = _step_metadata(run, "STEP_OUTPUT")
        assert metadata["busy"].value == 1 and metadata["failed"].value == 0
        assert metadata["gc_busy"].value is True
        assert "collection_outcome" not in metadata


def test_all_kinds_ready_is_plain_success(monkeypatch):
    result = {"status": "success", "prepared": 0, "reused": 4, "failed": 0, "kinds": [
        {"kind": kind, "status": "reused", "duration_ms": 3}
        for kind in ("bus-terminals-v1", "ferry-ports-v1", "rail-stations-v1", "parking-current-v1")
    ]}
    run, tag, warnings = _run_prepare_job(monkeypatch, result)
    assert run.success and tag is None and warnings == []
    assert _step_metadata(run, "STEP_OUTPUT")["reused"].value == 4
