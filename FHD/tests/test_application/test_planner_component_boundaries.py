"""Behavior of injectable plan generation and bounded, read-only refinement."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.application.workflow.llm_plan_generation import LlmPlanGeneration
from app.application.workflow.planning_graph_policy import validate_required_params
from app.application.workflow.planning_loop import PlanningLoop
from app.application.workflow.types import PlanGraph, WorkflowNode, validate_plan_graph


def test_generation_uses_injected_transport_and_retains_request_evidence():
    conversation = SimpleNamespace(
        get_context=lambda _: SimpleNamespace(
            conversation_history=[{"role": "user", "content": "之前"}]
        )
    )
    payload = {
        "intent": "stock_read",
        "risk_level": "low",
        "nodes": [
            {
                "node_id": "stock",
                "tool_id": "inventory",
                "action": "read",
                "params": {"id": 7},
                "idempotent": True,
            }
        ],
    }
    completion = Mock(
        return_value={
            "choices": [{"message": {"content": "```json\n" + json.dumps(payload) + "\n```"}}]
        }
    )
    direct_client = Mock(side_effect=AssertionError("injected completion must own transport"))
    generator = LlmPlanGeneration(conversation, completion, direct_client)

    plan = generator.generate(
        "plan-1",
        "owner",
        "查询库存",
        {},
        {"memory_v2": {"summary": "已确认偏好"}},
    )

    assert plan.plan_id == "plan-1" and plan.nodes[0].params == {"id": 7}
    assert plan.metadata["memory_v2_summary"] == "已确认偏好"
    request = json.loads(completion.call_args.kwargs["messages"][1]["content"])
    assert request["recent_messages"] == [{"role": "user", "content": "之前"}]
    direct_client.assert_not_called()


def test_refinement_never_probes_writes_or_nodes_with_missing_required_input():
    registry = {
        "inventory": {
            "actions": {
                "read": {"risk": "low", "idempotent": True, "required_params": ["id"]},
                "write": {"risk": "high", "idempotent": True},
            }
        }
    }
    candidate = PlanGraph(
        plan_id="plan-1",
        intent="inventory",
        nodes=[
            WorkflowNode(node_id="write", tool_id="inventory", action="write"),
            WorkflowNode(node_id="missing", tool_id="inventory", action="read"),
            WorkflowNode(node_id="first", tool_id="inventory", action="read", params={"id": 1}),
            WorkflowNode(node_id="second", tool_id="inventory", action="read", params={"id": 2}),
            WorkflowNode(
                node_id="over_limit", tool_id="inventory", action="read", params={"id": 3}
            ),
        ],
    )
    final = PlanGraph(plan_id="plan-1", intent="inventory", nodes=[candidate.nodes[2]])
    generate = Mock(side_effect=[candidate, final])
    repair = Mock()
    probe = Mock(return_value={"success": True, "data": [{"stock": 20}]})
    loop = PlanningLoop(generate, repair, probe, validate_plan_graph, validate_required_params)

    with patch("app.services.task_agent.TaskAgent", return_value=None):
        result = loop.plan("plan-1", "owner", "查询库存", registry, {"session_id": "same"})

    assert result is final
    assert [call.kwargs["params"]["id"] for call in probe.call_args_list] == [1, 2]
    assert all(call.kwargs["action"] == "read" for call in probe.call_args_list)
    assert all(
        call.kwargs["params"]["_runtime_context"]["session_id"] == "same"
        for call in probe.call_args_list
    )
    assert len(generate.call_args.kwargs["context"]["tool_probe_outputs"]) == 2
    repair.assert_not_called()


def test_invalid_critic_output_is_rejected_after_one_repair_attempt():
    candidate = PlanGraph(plan_id="plan-1", intent="candidate")
    invalid = PlanGraph(plan_id="plan-1", intent="invalid")
    generate = Mock(side_effect=[candidate, invalid])
    repair = Mock(return_value=invalid)
    probe = Mock()
    loop = PlanningLoop(generate, repair, probe, validate_plan_graph, validate_required_params)

    with patch("app.services.task_agent.TaskAgent", return_value=None):
        result = loop.plan("plan-1", "owner", "查询库存", {}, {})

    assert result is None
    assert repair.call_count == 1
    assert repair.call_args.kwargs["invalid_plan"] is invalid
    probe.assert_not_called()
