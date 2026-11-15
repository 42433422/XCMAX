"""elt_import 的「单文件/整批」二选一必填参数校验。"""

from __future__ import annotations

import pytest

from app.application.workflow.clarification_node import needs_clarification
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode


def _registry() -> dict:
    return {
        "elt_import": {
            "actions": {
                "execute": {
                    "risk": "high",
                    "idempotent": False,
                    "required_params": [],
                    "required_any": [["run_id", "run_ids"]],
                }
            }
        }
    }


def _plan(params: dict) -> PlanGraph:
    node = WorkflowNode(
        node_id="elt_execute",
        tool_id="elt_import",
        action="execute",
        params=params,
        risk="high",
        idempotent=False,
    )
    return PlanGraph(plan_id="plan-1", intent="导入 Excel", nodes=[node])


def test_single_run_id_satisfies_requirement():
    assert needs_clarification(_plan({"run_id": "run-1"}), _registry()) == []


def test_batch_run_ids_satisfy_requirement():
    assert needs_clarification(_plan({"run_ids": ["run-1", "run-2"]}), _registry()) == []


def test_missing_both_asks_for_either():
    items = needs_clarification(_plan({}), _registry())
    assert len(items) == 1
    assert items[0]["reason"] == "missing_required"
    assert items[0]["missing_fields"] == ["run_id/run_ids"]
    assert "run_id/run_ids" in items[0]["question"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
