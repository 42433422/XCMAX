"""Formal graph admission validates real tools and required parameters."""

from app.application.workflow.planning_graph_policy import validate_required_params
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode


def test_plan_check_rejects_unregistered_tool_before_execution():
    plan = PlanGraph(
        plan_id="untrusted-plan",
        intent="query",
        nodes=[WorkflowNode("n1", "model_invented_tool", "delete", params={})],
    )

    error = validate_required_params(plan, {})

    assert error and "未授权工具" in error


def test_plan_check_owns_required_parameter_validation(monkeypatch):
    from types import SimpleNamespace

    from app.application.agent_orchestrator import tool_spec

    monkeypatch.setattr(
        tool_spec,
        "validate_tool_call",
        lambda *_args, **_kwargs: SimpleNamespace(ok=True, message=""),
    )
    registry = {
        "catalog": {
            "actions": {
                "lookup": {
                    "required_params": ["sku"],
                    "risk": "low",
                    "idempotent": True,
                }
            }
        }
    }
    plan = PlanGraph(
        plan_id="checked-plan",
        intent="query",
        nodes=[WorkflowNode("n1", "catalog", "lookup", params={})],
    )

    error = validate_required_params(plan, registry)

    assert error and "sku" in error
