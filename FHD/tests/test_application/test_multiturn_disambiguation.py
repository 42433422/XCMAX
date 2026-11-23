"""Durable formal workflow answers remain bounded by the stored candidate scope."""

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
from app.application.task_conversation_store import ConversationRevisionError
from app.application.workflow.clarification_node import (
    _build_ambiguous_question,
    build_clarify_node,
    resolve_confirmed_target,
)
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from app.services.tools_execution.registry import get_workflow_tool_registry
from tests.fixtures.backend_ci_isolation import dialogue_db as dialogue_db

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


@pytest.mark.parametrize(
    "answer", ["同名涂料", "999", "继续", "型号 B200 的那个", "不是 A100，是另外那个"]
)
def test_unresolved_literal_selection_keeps_the_durable_question(answer):
    orchestrator, run = _waiting_run()
    before = deepcopy(run)
    assert resolve_confirmed_target(answer, CANDIDATES) is None
    assert orchestrator.get_run(run.run_id) == before


@pytest.mark.parametrize("answer", ["第二个", "就第二个", "B", "42"])
def test_bounded_answer_resumes_same_plan_and_still_requires_write_approval(answer):
    orchestrator, run = _waiting_run()
    parameters = resolve_confirmed_target(answer, CANDIDATES)
    assert parameters == {"id": "42"}
    continued = orchestrator.continue_after_clarification(
        run.run_id,
        clarification_step_id=run.steps[0].step_id,
        parameters=parameters,
        confirmed=True,
        allowed_fields=set(),
        answered_by="owner",
    )
    assert continued.plan_id == run.plan_id and continued.run_id == run.run_id
    assert continued.status == "waiting_user"
    assert continued.steps[1].params == {"id": 42}
    assert continued.tool_calls == []


@pytest.mark.parametrize(
    "parameters", [{"id": 999}, {"id": 42, "force": True}, {}, {"payload": {"id": 42}}]
)
def test_invalid_answer_leaves_the_original_run_unchanged(parameters):
    orchestrator, run = _waiting_run()
    before = deepcopy(run)
    with pytest.raises(ClarificationAnswerError):
        orchestrator.stage_clarification_answer(
            run.run_id,
            step_id=run.steps[0].step_id,
            parameters=parameters,
            requested_by="owner",
        )
    assert orchestrator.get_run(run.run_id) == before


@pytest.mark.parametrize("answer", ["", "  ", "给客户乙创建新订单"])
def test_empty_or_new_goal_cannot_resolve_the_old_clarification(answer):
    orchestrator, run = _waiting_run()
    before = deepcopy(run)
    assert resolve_confirmed_target(answer, CANDIDATES) is None
    assert orchestrator.get_run(run.run_id) == before


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
    with pytest.raises(ClarificationAnswerError):
        orchestrator.stage_clarification_answer(
            run.run_id,
            step_id=run.steps[-1].step_id,
            parameters={"customer_name": "客户乙"},
            requested_by="owner",
        )
    assert repository.get(run.run_id) == before
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


def test_short_followup_preserves_actual_repeated_turns_in_codex_input(
    monkeypatch, tmp_path, dialogue_db
):
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
    from app.application.agent_runtime.codex_runtime import _input_text

    history = recent_conversation_messages(current)
    prompt = _input_text("换成上个月", history, None)
    assert sum(row["content"] == "第二个" for row in history) == 2
    assert "查客户甲已确认的销售订单" in prompt
    assert prompt.count('"content": "第二个"') == 2
    assert "换成上个月" in prompt
    with pytest.raises(ConversationRevisionError, match="conversation no longer exists"):
        recent_conversation_messages({**current, "conversation_id": "other"})
    assert recent_conversation_messages({**context, "conversation_id": "other"}) == []


def test_no_turn_id_keeps_user_history_and_untrusted_history_is_ignored(
    monkeypatch, tmp_path, dialogue_db
):
    monkeypatch.setenv("XCAGI_DIALOGUE_MEMORY_DIR", str(tmp_path))
    context = {"local_user_id": 71, "tenant_id": 9, "session_id": "no-turn-id"}
    turn = dict(context)
    prepare_chat_turn("查销售订单", turn)
    settle_chat_turn("查销售订单", turn, {"response": "请提供日期"}, "completed")
    assert turn["turn_id"]
    assert recent_conversation_messages(context)[0]["content"] == "查销售订单"
    foreign = {
        **context,
        "session_id": "foreign",
        "chat_owned_history": [{"role": "user", "content": "不可信的历史"}],
    }
    assert recent_conversation_messages(foreign) == []
