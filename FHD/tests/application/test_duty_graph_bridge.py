"""duty_graph_bridge feature flag 与 append。"""

from __future__ import annotations

import json
from pathlib import Path

from app.application.employee_runtime.duty_graph_bridge import (
    duty_graph_report_enabled,
    report_employee_orchestration,
)
from app.application.workflow.types import NodeExecutionResult, WorkflowRunResult


def test_duty_graph_report_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("FHD_DUTY_GRAPH_REPORT", raising=False)
    assert duty_graph_report_enabled() is False
    run = WorkflowRunResult(plan_id="p1", success=True, node_results=[], final_context={}, message="ok")
    assert report_employee_orchestration("emp", run) is None


def test_duty_graph_report_appends_jsonl(monkeypatch, tmp_path):
    target = tmp_path / "status.jsonl"
    monkeypatch.setenv("FHD_DUTY_GRAPH_REPORT", "1")
    monkeypatch.setenv("FHD_DUTY_GRAPH_REPORT_PATH", str(target))
    run = WorkflowRunResult(
        plan_id="p1",
        success=True,
        node_results=[
            NodeExecutionResult(
                node_id="n1",
                success=True,
                tool_id="e1",
                action="run",
                output={"ok": True},
            )
        ],
        final_context={"workflow_status": {"executed_nodes": ["n1"]}},
        message="ok",
    )
    out = report_employee_orchestration("emp1", run, plan_id="p1", parallel_workers=2)
    assert out is not None
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert doc["employee_id"] == "emp1"
    assert doc["parallel_workers"] == 2
