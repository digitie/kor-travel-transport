"""오래된 수집 실행 수동 정리는 Dagster 활성 실행이 있으면 실패해야 한다."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest


def _module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "reconcile-stale-collector-runs.py"
    if not script.is_file():
        script = Path(__file__).resolve().parents[1] / "scripts" / "reconcile-stale-collector-runs.py"
    spec = importlib.util.spec_from_file_location("reconcile_stale_collector_runs", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("payload,allowed", [
    ({"data": {"runsOrError": {"__typename": "Runs", "results": []}}}, True),
    ({"data": {"runsOrError": {"__typename": "Runs", "results": [{"runId": "alive"}]}}}, False),
    ({"data": {"runsOrError": {"__typename": "PythonError"}}}, False),
    ({"errors": [{"message": "unavailable"}]}, False),
])
def test_reconcile_requires_zero_active_dagster_runs(monkeypatch, payload, allowed) -> None:
    module = _module()
    monkeypatch.setattr(module, "urlopen", lambda _request, timeout: io.BytesIO(json.dumps(payload).encode()))
    if allowed:
        module.require_no_active_dagster_runs()
    else:
        with pytest.raises(RuntimeError):
            module.require_no_active_dagster_runs()
