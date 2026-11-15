"""새 원본의 통계 게시 유예만 경고로 구분하고 원천 상태·원인·과거 통계는 보존한다."""

import pytest
from app.dagster.definitions import _collection_output_metadata


@pytest.mark.parametrize("status,flag,outcome,code", [
    ("success", False, "partial", "DERIVED_CACHE_DEFERRED"),
    ("partial_success", False, "partial", "DERIVED_CACHE_DEFERRED"),
    ("success", True, "success", None),
    ("success", None, "success", None),
    ("success", "missing", "success", None),
    ("success", 0, "success", None),
    ("skipped", False, "deferred", "COLLECTION_DEFERRED"),
    ("disabled", False, "deferred", "COLLECTION_DEFERRED"),
    ("not_ready", False, "deferred", "COLLECTION_DEFERRED"),
])
def test_only_attempted_false_publication_changes_success_outcome(status, flag, outcome, code):
    result = {"status": status, "fuel_ready": True}
    if flag != "missing":
        result["fuel_statistics_published"] = flag
    previous = dict(result)
    metadata = _collection_output_metadata(result, "fuel")
    assert result == previous and metadata["status"] == status
    assert metadata["collection_outcome"] == outcome
    assert metadata.get("error_code") == code
    assert metadata["previous_data_preserved"] is True
    if type(flag) is bool:
        assert metadata["fuel_statistics_published"] is flag
    else:
        assert "fuel_statistics_published" not in metadata


@pytest.mark.parametrize("status", ["success", "partial_success"])
@pytest.mark.parametrize("id_key", ["collection_run_id", "run_id"])
def test_derived_warning_cannot_overwrite_original_provider_error(status, id_key):
    result = {
        "status": status, "fuel_statistics_published": False, id_key: 17,
        "errors": ["data.ex.co.kr returned EXPIRED_KEY: private-provider-detail"],
    }
    metadata = _collection_output_metadata(result, "fuel")
    assert metadata["status"] == result["status"] == status
    assert metadata["collection_outcome"] == "partial"
    assert metadata["error_code"] == "PROVIDER_AUTH"
    assert metadata["run_id"] == 17 and result[id_key] == 17
    assert ("collection_run_id" in result) is (id_key == "collection_run_id")
    assert "private-provider-detail" not in str(metadata)
