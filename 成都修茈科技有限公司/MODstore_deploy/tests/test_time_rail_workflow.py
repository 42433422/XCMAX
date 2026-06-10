"""时间轨 workflow 图 export + runtime 状态 API。"""

from __future__ import annotations

import json

import pytest


def test_load_workflow_graph_has_nodes():
    from modstore_server.time_rail_workflow import load_workflow_graph

    doc = load_workflow_graph()
    assert doc.get("schema") == "time_rail_workflow_graph/v1"
    nodes = doc.get("nodes") or []
    edges = doc.get("edges") or []
    assert len(nodes) >= 60
    assert len(edges) >= 90
    ids = {n["id"] for n in nodes if n.get("id")}
    assert "BK" in ids
    assert "ASM" in ids


def test_record_node_run_roundtrip(tmp_path, monkeypatch):
    from modstore_server.time_rail_runtime import get_node_record, record_node_run

    store = tmp_path / "time_rail_node_runtime.json"
    monkeypatch.setenv("MODSTORE_TIME_RAIL_RUNTIME_JSON", str(store))

    record_node_run("BK", ok=True, source="test", meta={"stamp": "t1"})
    row = get_node_record("BK")
    assert row is not None
    assert row.get("ok") is True
    assert row.get("source") == "test"
    assert row.get("last_run")


def test_collect_node_runtime_status_shape(tmp_path, monkeypatch):
    from modstore_server.time_rail_runtime import record_node_run
    from modstore_server.time_rail_workflow import collect_node_runtime_status

    store = tmp_path / "time_rail_node_runtime.json"
    monkeypatch.setenv("MODSTORE_TIME_RAIL_RUNTIME_JSON", str(store))
    record_node_run("SW", ok=True, source="test")

    out = collect_node_runtime_status(node_ids=["SW", "MISSING"])
    assert out.get("nodes")
    sw = out["nodes"]["SW"]
    assert sw["node_id"] == "SW"
    assert sw["ok"] is True
    assert sw["last_run"]
    assert "guard_active" in sw
    missing = out["nodes"]["MISSING"]
    assert missing["ok"] is None
    assert missing["last_run"] is None


def test_graph_api_payload():
    from modstore_server.time_rail_workflow import graph_api_payload

    payload = graph_api_payload()
    assert payload.get("ok") is True
    assert isinstance(payload.get("nodes"), list)
    assert isinstance(payload.get("edges"), list)


def test_sync_script_output_matches_schema():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    graph_path = root / "FHD" / "config" / "time_rail_workflow_graph.json"
    if not graph_path.is_file():
        pytest.skip("time_rail_workflow_graph.json not generated yet")
    doc = json.loads(graph_path.read_text(encoding="utf-8"))
    assert doc.get("center_id") == "daily-hub"
    for edge in doc.get("edges") or []:
        assert edge.get("from")
        assert edge.get("to")
