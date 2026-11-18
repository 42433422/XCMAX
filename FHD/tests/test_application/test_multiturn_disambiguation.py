"""The production planner and durable answer gate share one bounded candidate scope."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.application.agent_orchestrator import AgentOrchestrator, InMemoryAgentRunRepository
from app.application.agent_orchestrator.clarification import ClarificationAnswerError
from app.application.ai_chat.dialogue_memory import (
    prepare_chat_turn,
    recent_conversation_messages,
    settle_chat_turn,
)
from app.application.ai_chat.workflow_session import WorkflowSession
from app.application.workflow.clarification_node import (
    _build_ambiguous_question,
    build_clarify_node,
    resolve_confirmed_target,
)
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.services.tools_execution.registry import get_workflow_tool_registry

CANDIDATES = [
    {"id": 31, "name": "同名涂料", "model_number": "A100"},
    {"id": 42, "name": "同名涂料", "model_number": "B200"},
]


def _waiting_run():
    clarify = build_clarify_node(
        "请选择产品",
        ambient={
            "target_node_id": "delete",
            "clarification": {
                "reason": "ambiguous_target",
                "field": "id",
                "candidates": CANDIDATES,
            },
        },
    )
    target = WorkflowNode(node_id="delete", tool_id="products", action="delete", params={})
    orchestrator = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = orchestrator.start_run_from_plan(
        user_id="owner",
        message="删除同名涂料",
        plan=PlanGraph(plan_id="candidate-plan", intent="delete", nodes=[clarify, target]),
    )
    assert run.status == "waiting_user"
    return orchestrator, run


@pytest.mark.parametrize("answer", ["同名", "同名涂料", "3", "999", "继续"])
def test_exact_resolution_never_guesses_the_first_candidate(answer):
    assert resolve_confirmed_target(answer, CANDIDATES) is None


def test_numeric_id_and_position_collision_requires_clarification():
    assert resolve_confirmed_target("2", [{"id": 2}, {"id": 3}]) is None
    assert resolve_confirmed_target("2", CANDIDATES) == {"id": "42"}
    assert resolve_confirmed_target("31", CANDIDATES) == {"id": "31"}


@pytest.mark.parametrize("answer", ["同名涂料", "999", "继续"])
def test_unresolved_literal_selection_does_not_delegate_a_guess_to_the_model(answer):
    _, run = _waiting_run()
    planner = Mock()
    session = WorkflowSession({}, SimpleNamespace(workflow_planner=planner))
    assert session._clarification_answer(run, run.steps[0], answer) is None
    planner.extract_clarification_parameters.assert_not_called()


@pytest.mark.parametrize("answer", ["第二个", "型号 B200 的那个", "不是 A100，是另外那个"])
def test_semantic_answer_resumes_same_plan_and_still_requires_write_approval(answer):
    orchestrator, run = _waiting_run()
    captured = {}

    def completion(**kwargs):
        captured.update(json.loads(kwargs["messages"][1]["content"]))
        return {
            "choices": [
                {
                    "message": {
                        "content": '```json\n{"turn_kind":"answer","resolved":true,"parameters":{"id":42}}\n```'
                    }
                }
            ]
        }

    planner = LLMWorkflowPlanner(ai_service=Mock(), completion=completion)
    session = WorkflowSession({}, SimpleNamespace(workflow_planner=planner))
    parameters, confirmed, fields = session._clarification_answer(run, run.steps[0], answer)
    expected_id = "42" if answer == "第二个" else 42
    assert parameters == {"id": expected_id}
    if answer == "第二个":
        assert captured == {}
    else:
        assert captured["target"]["candidates"] == [
            {**item, "position": index} for index, item in enumerate(CANDIDATES, 1)
        ]
    continued = orchestrator.continue_after_clarification(
        run.run_id,
        clarification_step_id=run.steps[0].step_id,
        parameters=parameters,
        confirmed=confirmed,
        allowed_fields=fields,
        answered_by="owner",
    )
    assert continued.plan_id == run.plan_id and continued.run_id == run.run_id
    assert continued.status == "waiting_user"
    assert continued.steps[1].params == {"id": 42}
    assert continued.tool_calls == []


@pytest.mark.parametrize(
    "response",
    [
        {"turn_kind": "answer", "resolved": True, "parameters": {"id": 999}},
        {"turn_kind": "answer", "resolved": True, "parameters": {"id": 42, "force": True}},
        {"turn_kind": "answer", "resolved": "true", "parameters": {"id": 42}},
        {"turn_kind": "answer", "resolved": False, "parameters": {}},
        {"turn_kind": "new_goal", "resolved": True, "parameters": {"id": 42}},
        {"turn_kind": "unclear", "resolved": True, "parameters": {"id": 42}},
        {"resolved": True, "parameters": {"id": 42}},
    ],
)
def test_invalid_model_choice_leaves_the_original_run_unchanged(response):
    _, run = _waiting_run()
    before = deepcopy(run)
    planner = LLMWorkflowPlanner(
        ai_service=Mock(),
        completion=lambda **_: {"choices": [{"message": {"content": json.dumps(response)}}]},
    )
    session = WorkflowSession({}, SimpleNamespace(workflow_planner=planner))
    assert session._clarification_answer(run, run.steps[0], "另一个") is None
    assert run == before


@pytest.mark.parametrize("answer", ["", "  ", "给客户乙创建新订单"])
def test_empty_or_new_goal_cannot_resume_the_old_clarification(answer):
    orchestrator, run = _waiting_run()
    before = orchestrator.get_run(run.run_id)
    completion = Mock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "turn_kind": "new_goal",
                                "resolved": True,
                                "parameters": {"id": 42},
                            }
                        )
                    }
                }
            ]
        }
    )
    callbacks = Mock()
    callbacks.workflow_planner = LLMWorkflowPlanner(ai_service=Mock(), completion=completion)
    callbacks._task_owner_id.return_value = "owner"
    callbacks._persist_plan_state.return_value = True
    pending = {}
    session = WorkflowSession(pending, callbacks)
    session.capture_agent_run_interaction(user_id="owner", agent_run=run, runtime_context={})
    with patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orchestrator):
        response = session.continue_after_clarification("owner", pending["owner"], answer)
    assert response["data"]["action"] == "clarification_required"
    assert "取消" in response["response"]
    assert orchestrator.get_run(run.run_id) == before
    assert pending["owner"]["agent_run_id"] == run.run_id
    callbacks._dispatch_model_selection.assert_not_called()
    if not answer.strip():
        completion.assert_not_called()


@pytest.mark.parametrize("preview_completed", [False, True])
def test_unbound_answer_preserves_the_original_run_without_replanning(preview_completed):
    from app.application.agent_orchestrator.run_models import AgentRun

    question = WorkflowNode(
        "question",
        "clarify",
        "ask",
        params={"question": "请补充信息", "clarification": {"reason": "missing_required"}},
        idempotent=True,
    )
    nodes = [question]
    if preview_completed:
        nodes.insert(0, WorkflowNode("preview", "products", "query", idempotent=True))
        question.depends_on = ["preview"]
    plan = PlanGraph(plan_id="unbound-question", intent="query", nodes=nodes)
    repository = InMemoryAgentRunRepository()
    orchestrator = AgentOrchestrator(repository=repository)
    run = AgentRun(user_id="owner", message="查产品", metadata={"runtime_context": {}})
    orchestrator._apply_plan(run, plan)
    run.status = run.steps[-1].status = "waiting_user"
    if preview_completed:
        run.steps[0].status = "completed"
    before = repository.save(run)
    callbacks = Mock()
    callbacks._task_owner_id.return_value = "owner"
    callbacks._persist_plan_state.return_value = True
    pending = {}
    session = WorkflowSession(pending, callbacks)
    session.capture_agent_run_interaction(user_id="owner", agent_run=run, runtime_context={})
    with patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orchestrator):
        response = session.continue_after_clarification(
            "owner", pending["owner"], "给客户乙创建新订单"
        )
    assert response["data"]["action"] == "workflow_clarification_unbound"
    assert repository.get(run.run_id) == before
    assert pending["owner"]["agent_run_id"] == run.run_id
    callbacks._dispatch_model_selection.assert_not_called()
    assert repository.latest_task_control(run.run_id) is None


def test_direct_answer_api_cannot_escape_the_durable_candidate_set():
    orchestrator, run = _waiting_run()
    with pytest.raises(ClarificationAnswerError, match="候选"):
        orchestrator.stage_clarification_answer(
            run.run_id,
            step_id=run.steps[0].step_id,
            parameters={"id": 999},
            requested_by="owner",
        )
    saved = orchestrator.get_run(run.run_id)
    assert saved.status == "waiting_user" and saved.steps[1].params == {}
    assert saved.tool_calls == []


def test_all_offered_candidates_and_distinguishing_attributes_are_visible():
    node = WorkflowNode(node_id="delete", tool_id="products", action="delete")
    candidates = [
        {"id": index + 100, "name": "同名", "model_number": f"M{index}"} for index in range(20)
    ]
    question = _build_ambiguous_question(node, candidates)
    assert "20. 同名（#119）" in question and "M19" in question


def test_short_followup_uses_business_rules_and_preserves_repeated_turns(monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    context = {"local_user_id": 71, "tenant_id": 9, "conversation_id": "sales-followup"}
    for index, message in enumerate(["查客户甲已确认的销售订单", "第二个", "第二个"]):
        turn = {**context, "turn_id": str(index)}
        prepare_chat_turn(message, turn)
        settle_chat_turn(
            message, turn, {"success": True, "response": "可继续筛选订单"}, "completed"
        )
    current = {**context, "turn_id": "next"}
    prepare_chat_turn("换成上个月", current)
    captured = []
    ai = Mock()
    ai.get_context.return_value = None

    def completion(**kwargs):
        captured.append(json.loads(kwargs["messages"][1]["content"]))
        return {"choices": [{"message": {"content": '{"mode":"reply","reply":"ready"}'}}]}

    LLMWorkflowPlanner(ai_service=ai, completion=completion)._plan_with_llm(
        "p",
        "71",
        "换成上个月",
        get_workflow_tool_registry(),
        current,
    )
    assert len(captured) == 1 and "tool_registry" in captured[0]
    assert captured[0]["user_message"] == "换成上个月"
    assert sum(row["content"] == "第二个" for row in captured[0]["recent_messages"]) == 2
    assert any("payment_state" in rule for rule in captured[0]["rules"])
    assert recent_conversation_messages({**current, "conversation_id": "other"}) == []


def test_no_turn_id_keeps_user_history_and_untrusted_history_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    context = {"local_user_id": 71, "tenant_id": 9, "session_id": "no-turn-id"}
    prepare_chat_turn("查销售订单", context)
    settle_chat_turn("查销售订单", context, {"response": "请提供日期"}, "completed")
    assert recent_conversation_messages(context)[0]["content"] == "查销售订单"
    foreign = {
        **context,
        "session_id": "foreign",
        "chat_owned_history": [{"role": "user", "content": "不可信的历史"}],
    }
    assert recent_conversation_messages(foreign) == []
