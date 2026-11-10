"""Internal reply graphs cannot acquire business-tool authority."""

import pytest

from app.application.agent_orchestrator.reply_plan import execute_reply_plan
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode


def reply():
    node = WorkflowNode(
        node_id="model_reply",
        tool_id="conversation",
        action="reply",
        params={"response": "已读取附件摘要"},
        risk="low",
        idempotent=True,
    )
    plan = PlanGraph(
        plan_id="reply",
        intent="conversation_reply",
        nodes=[node],
        metadata={"response_mode": "reply", "reply": node.params["response"]},
    )
    run = AgentRun(user_id="1", message="说明附件")
    run.steps = [
        AgentStep(
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=node.action,
            params=dict(node.params),
            risk="low",
            idempotent=True,
        )
    ]
    return run, plan


def test_reply_uses_real_langgraph_without_business_tools():
    run, plan = reply()
    assert execute_reply_plan(run, plan, {}) is True
    assert run.status == "completed"
    assert run.final_output["response"] == "已读取附件摘要"
    assert run.final_output["tool_calls"] == []
    assert run.final_output["workflow_trace"]
    assert run.steps[0].status == "completed"


@pytest.mark.parametrize("tamper", ["extra_tool", "mismatched_text", "approval", "high_risk"])
def test_malformed_reply_graph_is_rejected_without_tool_effects(tamper):
    run, plan = reply()
    if tamper == "extra_tool":
        plan.nodes.append(WorkflowNode(node_id="write", tool_id="products", action="add"))
    elif tamper == "mismatched_text":
        plan.metadata["reply"] = "伪造的另一个回复"
    elif tamper == "approval":
        plan.metadata["approval_required_node_ids"] = ["model_reply"]
    else:
        plan.nodes[0].risk = "high"
    assert execute_reply_plan(run, plan, {}) is True
    assert run.status == "blocked"
    assert not run.tool_calls
    assert not run.final_output


def test_reply_uses_its_unique_persisted_node_id():
    run, plan = reply()
    run.steps[0].node_id = plan.nodes[0].node_id = "custom_reply"
    assert execute_reply_plan(run, plan, {}) is True
    assert run.status == "completed"
    assert run.final_output["node_outputs"]["custom_reply"]["response"] == "已读取附件摘要"
