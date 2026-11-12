"""수집/주소 갱신 뒤 내부 준비를 연결하고, 외부 수집과 예약 수를 늘리지 않는다."""
from types import SimpleNamespace

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
