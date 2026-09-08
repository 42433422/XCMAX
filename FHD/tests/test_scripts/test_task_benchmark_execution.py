"""Exercise real orchestration so planned actions cannot masquerade as executed work."""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest


@pytest.fixture
def execute_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    monkeypatch.setenv("XCAGI_AGENT_RUNTIME_HOOKS", "0")
    monkeypatch.delenv("MODEL_USAGE_WALLET_REQUIRED", raising=False)
    return runpy.run_path(str(Path(__file__).parents[1] / "benchmarks" / "task_success_runner.py"))[
        "_execute_plan"
    ]


@pytest.mark.parametrize("expected, passes", [("waiting_user", True), ("completed", False)])
def test_clarification_is_waiting_and_never_business_completion(
    execute_plan, monkeypatch, expected, passes
):
    from app.application.facades import tools_facade
    from app.application.workflow.types import PlanGraph, WorkflowNode

    calls = []
    monkeypatch.setattr(
        tools_facade, "execute_registered_workflow_tool", lambda *args: calls.append(args)
    )
    from app.application.workflow.clarification_node import build_clarify_node

    plan = PlanGraph(
        plan_id="clarify",
        intent="create",
        nodes=[
            build_clarify_node("请提供客户名称", ambient={"target_node_id": "write"}),
            WorkflowNode(
                node_id="write",
                tool_id="customers",
                action="create",
                params={"unit_name": "fixture"},
            ),
        ],
    )
    ok, reason, receipt = execute_plan(
        plan, {"instruction": "新增客户", "expect": {"run_status": expected}}
    )
    assert ok is passes
    assert receipt["status"] == "waiting_user"
    assert receipt["final_output"]["clarification"]["question"] == "请提供客户名称"
    assert not calls and not receipt["tool_calls"]
    assert bool(reason) is (not passes)


def test_benchmark_never_infers_approval_from_expected_success(execute_plan, monkeypatch):
    from app.application.facades import tools_facade
    from app.application.workflow.types import PlanGraph, WorkflowNode

    calls = []
    monkeypatch.setattr(
        tools_facade, "execute_registered_workflow_tool", lambda *args: calls.append(args)
    )
    plan = PlanGraph(
        plan_id="write",
        intent="create",
        nodes=[
            WorkflowNode(
                node_id="write",
                tool_id="business_db",
                action="write",
                params={"entity": "customers", "payload": {"unit_name": "fixture"}},
            ),
        ],
    )
    ok, reason, receipt = execute_plan(plan, {"instruction": "新增客户"})
    assert not ok and "waiting_user" in reason
    assert not calls and not receipt["tool_calls"]


def test_scripted_approval_requires_exact_pending_parameters(execute_plan, monkeypatch):
    from app.application.facades import tools_facade
    from app.application.workflow.types import PlanGraph, WorkflowNode

    calls = []
    monkeypatch.setattr(
        tools_facade, "execute_registered_workflow_tool", lambda *args: calls.append(args)
    )
    plan = PlanGraph(
        plan_id="write",
        intent="create",
        nodes=[
            WorkflowNode(
                node_id="write",
                tool_id="business_db",
                action="write",
                params={"entity": "customers", "payload": {"unit_name": "actual"}},
            ),
        ],
    )
    ok, reason, receipt = execute_plan(
        plan,
        {
            "instruction": "新增客户",
            "approvals": [
                {
                    "tool_id": "business_db",
                    "action": "write",
                    "params": {"entity": "customers", "payload": {"unit_name": "different"}},
                },
            ],
        },
    )
    assert not ok and "does not match" in reason
    assert not calls and not receipt["tool_calls"]
