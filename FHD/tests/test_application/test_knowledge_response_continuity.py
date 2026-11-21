"""The chat renderer preserves the executed query and the RAG answer contract."""

from types import SimpleNamespace

import pytest

from app.application.ai_chat.workflow_response_builder import AIChatWorkflowResponseMixin


@pytest.fixture
def builder():
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "本期购货合计 120 元。[1]"}}]}

    instance = AIChatWorkflowResponseMixin()
    instance.workflow_planner = SimpleNamespace(complete_messages=complete)
    return instance, calls


def test_completed_query_answer_is_not_replaced_by_a_second_model(builder):
    instance, calls = builder
    answer = "澜宇 2026/9/27—10/24 购货明细：配件 3 件，合计 120 元。[1]"
    step = SimpleNamespace(
        output={
            "query": "澜宇 2026/9/27—10/24 购货明细",
            "answer": answer,
            "answer_grounded": True,
            "chunks": [{"text": "配件 3 件 120 元", "source_url": "购货台账.xlsx"}],
        }
    )
    rendered = instance._knowledge_answer(step, "A")
    assert rendered.startswith(answer)
    assert "来源：购货台账.xlsx" in rendered
    assert calls == []


@pytest.mark.parametrize("contract", [{"no_answer": True}, {"answer_grounded": False}])
def test_failed_grounding_cannot_be_overwritten_by_secondary_synthesis(builder, contract):
    instance, calls = builder
    step = SimpleNamespace(
        output={
            "query": "澜宇2026/9/30购货明细",
            "answer": "没有找到符合该日期的明细。",
            "chunks": [{"text": "仅有另一日期的记录"}],
            **contract,
        }
    )
    assert instance._knowledge_answer(step, "确认") == "没有找到符合该日期的明细。"
    assert calls == []


@pytest.mark.parametrize("query_source", ["output", "params"])
def test_raw_retrieval_uses_executed_query_and_preserves_evidence(builder, query_source):
    instance, calls = builder
    query = "澜宇2026/9/27—10/24购货明细"
    output = {"chunks": [{"text": "购货记录" * 250 + "末尾金额120元"}], "answer_grounded": True}
    params = {}
    (output if query_source == "output" else params)["query"] = query
    step = SimpleNamespace(output=output, params=params)
    assert "合计 120 元" in instance._knowledge_answer(step, "A")
    prompt = calls[0]["messages"][-1]["content"]
    assert query in prompt
    assert "末尾金额120元" in prompt
    assert "问题：A" not in prompt


def test_truncated_knowledge_evidence_remains_visible(builder):
    instance, calls = builder
    step = SimpleNamespace(
        output={
            "answer": "当前片段含 3 件配件。",
            "context_truncated": True,
            "chunks": [{"text": "配件 3 件"}],
        }
    )
    answer = instance._knowledge_answer(step, "全部多少")
    assert "当前片段含 3 件配件。" in answer
    assert "截断" in answer
    assert calls == []


def test_empty_successful_retrieval_explains_missing_answer(builder):
    instance, calls = builder
    step = SimpleNamespace(output={"success": True, "query": "澜宇购货", "chunks": []})
    answer = instance._knowledge_answer(step, "A")
    assert "没有找到" in answer
    assert calls == []


@pytest.mark.parametrize("state", ["completed", "waiting_user", "unknown"])
def test_scope_answer_that_needs_only_a_reply_is_not_a_tool_execution(builder, state):
    from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    instance, calls = builder
    response = "已明确范围；现有资料只包含区间合计，无法核实当日购货金额。"
    plan = PlanGraph(
        plan_id="scope-plan",
        intent="conversation_reply",
        nodes=[
            WorkflowNode(
                node_id="reply",
                tool_id="conversation",
                action="reply",
                params={"response": response},
            )
        ],
        metadata={"response_mode": "reply", "reply": response},
    )
    step = AgentStep(
        node_id="reply",
        tool_id="conversation",
        action="reply",
        status="waiting_user" if state == "waiting_user" else "completed",
        output={"success": True, "response": response},
    )
    if state == "unknown":
        step.output["requires_reconciliation"] = True
    run = AgentRun(
        user_id="17",
        message="A",
        plan_id=plan.plan_id,
        status="waiting_user" if state == "waiting_user" else "completed",
        steps=[step],
        final_output={"response": response},
    )
    result = instance._format_agent_run_response(plan, run, user_message="A")
    if state == "completed":
        assert result["response"] == response
        assert result["data"]["action"] == "model_reply"
        assert result["data"]["data"]["node_results"] == []
        assert result["data"]["data"]["tool_calls"] == []
        assert result["data"]["data"]["tool_call_count"] == 0
    else:
        assert result["success"] is False
        assert result["data"]["action"] != "model_reply"
        assert result["data"]["data"]["node_results"]
    assert calls == []
