"""Targeted smoke tests for high-churn/low-coverage hotspots (workflow/webhook/engine)."""

from __future__ import annotations

from modstore_server import webhook_dispatcher as wd
from modstore_server.workflow_engine import _detect_cycle, _json_safe


def test_json_safe_truncates_deep_and_long_strings():
    circular: dict = {}
    circular["self"] = circular
    out = _json_safe(circular, max_depth=2, max_str=4)
    assert isinstance(out, dict)
    long = "x" * 20_000
    assert len(str(_json_safe(long, max_str=100))) <= 200


def test_detect_cycle_finds_loop():
    adj = {1: [2], 2: [3], 3: [1]}
    cyc = _detect_cycle(adj, 1)
    assert set(cyc).issuperset({1, 2, 3})


def test_webhook_stable_event_and_build_payload():
    eid = wd.stable_event_id("workflow.event_trigger.v1", "agg-123")
    assert "agg-123" in eid
    payload = wd.build_event("workflow.event_trigger.v1", "u1", {"k": "v"})
    assert payload["aggregate_id"] == "u1"
    assert isinstance(payload["data"], dict)


def test_validate_workflow_missing_row(tmp_path, monkeypatch):
    import modstore_server.models as models

    models._engine = None
    models._SessionFactory = None
    monkeypatch.setenv("MODSTORE_DB_PATH", str(tmp_path / "wf.sqlite"))
    models.init_db()

    from modstore_server.workflow_engine import validate_workflow

    errs = validate_workflow(987_654_321)
    assert errs and errs[0].startswith("工作流不存在")
