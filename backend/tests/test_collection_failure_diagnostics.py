from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from app.dagster import definitions
from app.dagster.definitions import _collection_failure_metadata
from dagster import Failure


def test_parse_diagnostics_keep_counts_without_raw_response_or_secrets():
    result = {
        "collection_run_id": 12, "status": "partial_success", "raw_response_count": 1,
        "traffic_snapshot_count": 0, "incident_snapshot_count": 18,
        "errors": ["traffic flow response contains invalid records (received_rows=8352, parsed_rows=8351, invalid_rows=1) https://provider.invalid?key=private"],
        "url": "https://provider.invalid?key=private", "raw_body": "private",
    }
    detail = _collection_failure_metadata(result, "highway")
    assert detail["error_code"] == "TRAFFIC_FLOW_INVALID_RECORDS"
    assert detail["stage"] == "provider_parse"
    assert detail["invalid_rows"] == 1 and detail["received_rows"] == 8352
    assert detail["incident_snapshot_count"] == 18
    assert detail["successful_data_preserved"] is True
    assert detail["retryable"] is False
    assert "private" not in str(detail) and "http" not in str(detail)


def test_opinet_timeout_reports_bounded_retry_after_protection():
    detail = _collection_failure_metadata({
        "collection_run_id": 13, "status": "failed", "errors": ["Opinet browser action failed: TimeoutError"],
        "fuel_price_count": True, "traffic_snapshot_count": -1,
    }, "fuel")
    assert detail["error_code"] == "OPINET_BROWSER_TIMEOUT"
    assert detail["recovery_hint"] == "RETRY_AFTER_BACKOFF"
    assert detail["retryable"] is True
    assert "fuel_price_count" not in detail and "traffic_snapshot_count" not in detail


@pytest.mark.parametrize("provider_code", ["EXCEEDED_LIMIT", "INVALID_KEY", "EXPIRED_KEY", "NO_REGISTERED_KEY"])
def test_fixed_provider_code_keeps_quota_and_auth_remedies_without_raw_text(provider_code):
    detail = _collection_failure_metadata({
        "collection_run_id": 14, "status": "failed",
        "errors": [f"data.ex.co.kr returned {provider_code}: provider-private-value"],
    }, "highway")
    quota = provider_code == "EXCEEDED_LIMIT"
    assert detail["error_code"] == ("PROVIDER_RATE_LIMIT" if quota else "PROVIDER_AUTH")
    assert detail["stage"] == "provider_fetch"
    assert detail["retryable"] is quota
    assert detail["recovery_hint"] == ("RETRY_AFTER_BACKOFF" if quota else "CHECK_RUN_DETAIL")
    assert "provider-private-value" not in str(detail) and "data.ex.co.kr" not in str(detail)


def test_declared_count_failure_keeps_incomplete_snapshot_reason():
    detail = _collection_failure_metadata({
        "collection_run_id": 15, "status": "failed",
        "errors": ["traffic flow count must match the complete list"],
    }, "highway")
    assert detail["error_code"] == "TRAFFIC_FLOW_COUNT"
    assert detail["stage"] == "provider_parse"
    assert detail["recovery_hint"] == "CHECK_RESPONSE_CONTRACT"
    assert detail["retryable"] is False and detail["successful_data_preserved"] is True


@pytest.mark.parametrize("counts", [
    {"passenger_routes": 10, "ferry_routes": 3, "ferry_facilities": 5},
    {"passenger_routes": 0, "ferry_routes": 0, "ferry_facilities": 0},
    {},
])
def test_vadahub_partial_exposes_selected_source_and_preserved_success(monkeypatch, counts):
    async def result(*args, **kwargs):
        return {"status": "partial_success", "failed_datasets": ["official_terminals"],
                "counts": counts,
                "failure_details": [{"dataset": "official_terminals", "error_type": "SchemaError",
                                     "stage": "provider_parse", "error_code": "VADAHUB_SCHEMA_CHANGED"}]}
    monkeypatch.setattr(definitions, "_run_with_session", result)
    monkeypatch.setattr(definitions, "_settings", lambda: None)
    monkeypatch.setattr(definitions, "collection_owner", lambda *args: nullcontext())
    recorded = {}
    context = SimpleNamespace(run_id="fixture", instance=None, add_output_metadata=recorded.update,
                              log=SimpleNamespace(warning=lambda *args: None, info=lambda *args: None))
    if counts:
        output = definitions.collect_vadahub_reference.compute_fn.decorated_fn(context)
        assert output["status"] == "partial_success"
        assert recorded["collection_outcome"] == "partial"
        assert recorded["successful_dataset_count"] == 3
        assert recorded["previous_data_preserved"] is True
        assert recorded["dataset"] == "official_terminals"
    else:
        with pytest.raises(Failure) as caught:
            definitions.collect_vadahub_reference.compute_fn.decorated_fn(context)
        meta = caught.value.metadata
        assert meta["dataset"].value == "official_terminals"
        assert meta["error_code"].value == "VADAHUB_SCHEMA_CHANGED"
        assert meta["failed_dataset_count"].value == 1
        assert meta["successful_dataset_count"].value == 0
        assert meta["successful_data_preserved"].value is True
        assert caught.value.allow_retries is False
