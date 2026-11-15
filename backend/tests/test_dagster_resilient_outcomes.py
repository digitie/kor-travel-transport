from types import SimpleNamespace

import pytest
from app.dagster import definitions
from dagster import DagsterInstance


@pytest.mark.parametrize("scope", ["highway", "fuel"])
def test_saved_partial_source_completes_with_visible_warning(monkeypatch, scope):
    result = {"status": "partial_success", "collection_run_id": 17, "raw_response_count": 1,
              "traffic_snapshot_count": 2, "incident_snapshot_count": 0,
              "fuel_station_count": 1 if scope == "fuel" else 0,
              "fuel_price_count": 1 if scope == "fuel" else 0,
              "errors": ["traffic flow count must match the complete list"]}

    async def collected(*args, **kwargs):
        return dict(result)

    async def close():
        pass

    monkeypatch.setattr(definitions, "_settings", lambda: None)
    monkeypatch.setattr(definitions, "_secret_forms", lambda: [])
    monkeypatch.setattr(definitions, "TransportCollectionService",
                        lambda _: SimpleNamespace(collect=None, close=close))
    monkeypatch.setattr(definitions, "_run_with_session", collected)
    with DagsterInstance.ephemeral() as instance:
        job = getattr(definitions, f"{scope}_collection_job").execute_in_process(
            raise_on_error=False, instance=instance,
        )
        assert instance.get_run_by_id(job.run_id).tags["kortravel/collection-outcome"] == "partial"
    assert job.success
    assert job.output_for_node(f"collect_{scope}_transport")["status"] == "partial_success"
    output = next(event.step_output_data for event in job.all_events if event.event_type_value == "STEP_OUTPUT")
    assert output.metadata["collection_outcome"].value == "partial"
    assert output.metadata["raw_response_count"].value == 1
    assert output.metadata["error_code"].value == "TRAFFIC_FLOW_COUNT"
    assert output.metadata["previous_data_preserved"].value is True
    assert not any(event.is_step_up_for_retry for event in job.all_events)


def test_optional_cache_warning_does_not_hide_provider_diagnostic():
    meta = definitions._collection_output_metadata({
        "status": "partial_success", "collection_run_id": 18, "snapshot_count": 2,
        "cache_refresh_failed": True, "errors": ["data.ex.co.kr returned EXPIRED_KEY: private-value"],
    }, "airport")
    assert meta["collection_outcome"] == "partial"
    assert meta["cache_refresh_failed"] is True
    assert meta["error_code"] == "PROVIDER_AUTH"
    assert "private-value" not in str(meta)


@pytest.mark.parametrize("invalid_count", [False, None, "1", -1])
def test_no_progress_is_not_fabricated_from_invalid_counter(invalid_count):
    assert not definitions._has_collection_progress({"raw_response_count": invalid_count})
