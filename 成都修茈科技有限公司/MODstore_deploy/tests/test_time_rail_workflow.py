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


def test_ensure_p2_line_mappings_fills_web_and_retention_nodes():
    from modstore_server.time_rail_workflow import (
        _ensure_p2_line_mappings,
        _node_status_shell,
    )

    derived = {
        "PW": _node_status_shell(
            "PW",
            last_run="2026-06-28T00:00:00+00:00",
            ok=True,
            source="daily_release_train_orchestrator_job.phase_b",
            detail={"line": "P-W"},
            observed=True,
            proof_status="shadow_observed",
        ),
        "SR": _node_status_shell(
            "SR",
            last_run="2026-06-28T00:00:01+00:00",
            ok=True,
            source="daily_release_train_orchestrator_job.phase_b",
            detail={"line": "S-R"},
            observed=True,
            proof_status="shadow_observed",
        ),
    }

    _ensure_p2_line_mappings(derived, record_id=47, release_kind="daily")

    assert derived["P2W"]["observed"] is True
    assert derived["P2W"]["proof_status"] == "shadow_observed"
    assert derived["P2W"]["detail"]["from_node"] == "PW"
    assert derived["P2R"]["observed"] is True
    assert derived["P2R"]["proof_status"] == "shadow_observed"
    assert derived["P2R"]["detail"]["from_node"] == "SR"


def test_ensure_non_triggered_time_rail_decisions_marks_daily_skips():
    from modstore_server.time_rail_workflow import (
        _ensure_non_triggered_time_rail_decisions,
        _node_status_shell,
    )

    derived = {
        "P5": _node_status_shell(
            "P5",
            last_run="2026-06-28T00:00:00+00:00",
            ok=True,
            source="existing",
            observed=True,
        )
    }

    _ensure_non_triggered_time_rail_decisions(
        derived,
        last_run="2026-06-28T00:06:05+00:00",
        record_id=47,
        release_kind="daily",
        line_dispatch={
            "line_meta": {
                "P-W": {"updates_sections": 0, "patches_sections": 0, "total_sections": 0},
                "S-R": {"updates_sections": 0, "patches_sections": 0, "total_sections": 0},
            }
        },
        phase_c_pipeline={"ok": True, "step_ids": ["P3", "P7", "P8"]},
        guard_active=False,
    )

    for node_id in (
        "DRPROBE",
        "PW",
        "P2W",
        "SR",
        "P2R",
        "P9I",
        "P5I",
        "P6I",
        "FASTGATE",
        "DLSSOT",
        "P4",
        "P6",
        "CANARY",
        "P6POP",
        "P6PW",
        "P9G",
        "ROLLBACK",
        "HEAL",
        "P9",
    ):
        assert derived[node_id]["observed"] is True
        assert derived[node_id]["proof_status"] == "decision_not_taken"
        assert derived[node_id]["detail"]["record_id"] == 47

    assert derived["P5"]["source"] == "existing"
    assert derived["P5"]["proof_status"] == "proved_ok"


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
