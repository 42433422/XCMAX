"""Side questions preserve durable workflow waits, receipts and approval boundaries."""

import json
from copy import deepcopy
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.application.workflow.workflow_types import (
    PlanGraph,
    WorkflowNode,
    plan_from_dict,
)
from app.infrastructure.tenant_scope import tenant_scope
from tests.fixtures.backend_ci_isolation import (
    trusted_actor as trusted_actor,
)
from tests.fixtures.planning_clarification import (
    ORIGINAL,
    _planning_requests,
)
from tests.fixtures.planning_clarification import native_preview as native_preview
from tests.fixtures.planning_clarification import roundtrip as roundtrip


def _cached_clarification(roundtrip, *, confirmation=False):
    from app.application.ai_chat.dialogue_memory import bind_chat_turn_context
    from app.application.workflow.clarification_node import build_clarify_node

    context = {**roundtrip.context, "turn_id": uuid4().hex}
    bind_chat_turn_context("删除同名客户", context)
    question = build_clarify_node(
        "请选择客户",
        ambient={
            "target_node_id": "delete",
            "clarification": {
                "reason": "ambiguous_target",
                "field": "id",
                "candidates": [{"id": 31, "name": "客户 A"}, {"id": 42, "name": "客户 B"}],
            },
        },
    )
    target = WorkflowNode("delete", "customers", "delete", {})
    if confirmation:
        question.params = {"question": "确认删除客户 42 吗？"}
        target.params, target.depends_on = {"id": 42}, [question.node_id]
    run = roundtrip.orchestrator().start_run_from_plan(
        user_id=str(roundtrip.actor.user_id),
        message="删除同名客户",
        plan=PlanGraph(plan_id=uuid4().hex, intent="delete", nodes=[question, target]),
        runtime_context=context,
        auto_execute=True,
    )
    assert run.status == "waiting_user"
    service = roundtrip.service()
    service._capture_agent_run_interaction(
        user_id=roundtrip.chat_user, agent_run=run, runtime_context=run.metadata["runtime_context"]
    )
    return service, roundtrip.repository.get(run.run_id)


@pytest.mark.parametrize(
    ("state", "confirmation"),
    [
        ("unknown", False),
        ("running", False),
        ("unknown", True),
        ("running", True),
        ("non_retryable", False),
        ("step_unknown", False),
        ("step_unknown_status", False),
        ("step_running", False),
        ("call_unknown", False),
        ("call_unknown_status", False),
        ("call_running", False),
        ("failed_call_running", False),
    ],
)
def test_cached_clarification_cannot_bypass_unsettled_run(roundtrip, state, confirmation):
    from app.application.agent_orchestrator.run_models import ToolCall
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )

    service, run = _cached_clarification(roundtrip, confirmation=confirmation)
    queue = SQLAlchemyTaskExecutionRepository(session_factory=roundtrip.actor.factory)
    queue.enqueue(run)
    assert queue.claim("original-worker", lease_seconds=300) is not None
    assert queue.mark_open_effect(run.run_id, "original-effect", owner_id="original-worker")
    receipt = {"success": False, "outcome": "unknown", "requires_reconciliation": True}
    if state in {"unknown", "running"}:
        run.status = state
    elif state == "non_retryable":
        run.metadata["non_retryable"] = True
    elif state.startswith("step_"):
        run.steps[1].status = (
            "unknown"
            if state == "step_unknown_status"
            else "running"
            if state == "step_running"
            else "failed"
        )
        run.steps[1].output = receipt if state == "step_unknown" else {}
    else:
        step = run.steps[1]
        running = state in {"call_running", "failed_call_running"}
        if state == "failed_call_running":
            run.status = "failed"
        run.tool_calls.append(
            ToolCall(
                step_id=step.step_id,
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                status="unknown"
                if state == "call_unknown_status"
                else "running"
                if running
                else "failed",
                output=receipt if state == "call_unknown" else {},
            )
        )
    if state != "running":
        assert queue.finish(run.run_id, "original-worker", "failed").state == "unknown"
    roundtrip.repository.save(run)
    before = roundtrip.repository.get(run.run_id)
    plan_before = roundtrip.store.load(run.plan_id)
    pending_before = deepcopy(service._pending_workflows[roundtrip.chat_user])
    lifecycle_before = queue.lifecycle(run.run_id)
    queue_before = queue.get(run.run_id)
    roundtrip.state.classification = {"turn_kind": "new_goal", "resolved": False, "parameters": {}}
    roundtrip.state.reply = "这是新的独立回答。"

    response = roundtrip.send(service, "先解释一下采购成本")

    assert response["success"] is False
    assert response["run_id"] == response["agent_run_id"] == run.run_id
    assert response["execution_state"] == ("running" if state == "running" else "unknown")
    assert response["data"]["action"] == f"workflow_{response['execution_state']}"
    if state != "running":
        assert response["requires_reconciliation"] is True and response["retryable"] is False
    assert not roundtrip.requests
    roundtrip.executor.execute_with_deadline.assert_not_called()
    assert roundtrip.repository.get(run.run_id) == before
    assert roundtrip.store.load(run.plan_id) == plan_before
    assert service._pending_workflows[roundtrip.chat_user] == pending_before
    assert queue.get(run.run_id) == queue_before
    assert queue.lifecycle(run.run_id) == lifecycle_before
    assert lifecycle_before["effects"] == ["original-effect"]


@pytest.mark.parametrize(
    ("state", "write_receipt"),
    [("completed", True), ("completed", False), ("cancelled", False), ("failed", False)],
)
def test_cached_clarification_settles_known_terminal_before_next_turn(
    roundtrip, state, write_receipt
):
    from app.application.agent_orchestrator.run_models import ToolCall

    service, run = _cached_clarification(roundtrip, confirmation=True)
    run.status = state
    for step in run.steps:
        step.status = "completed" if state == "completed" else "failed"
        step.output = {"success": state == "completed"}
    if write_receipt:
        # A persisted terminal write has a matching call receipt. Status flags
        # alone must still be rejected by the business harness.
        step = run.steps[1]
        step.output = {"success": True, "deleted_count": 1, "data": {"id": 42}}
        run.tool_calls.append(
            ToolCall(
                step_id=step.step_id,
                node_id=step.node_id,
                tool_id=step.tool_id,
                action=step.action,
                params=dict(step.params),
                status="completed",
                output=dict(step.output),
            )
        )
    roundtrip.repository.save(run)
    before = roundtrip.repository.get(run.run_id)
    expected = "failed" if state == "completed" and not write_receipt else state

    response = roundtrip.send(service, "先解释一下采购成本")

    assert response["run_id"] == run.run_id and response["execution_state"] == expected
    assert not roundtrip.requests
    assert roundtrip.repository.get(run.run_id) == before
    assert roundtrip.chat_user not in service._pending_workflows
    assert roundtrip.store.load(run.plan_id)["status"] == (
        "succeeded" if expected == "completed" else expected
    )
    roundtrip.state.reply = "这是之后的新回答。"
    following = roundtrip.send(service, "现在解释一下采购成本")
    assert following["success"] is True and following["response"] == roundtrip.state.reply
    assert len(_planning_requests(roundtrip.requests)) == 1
    assert roundtrip.repository.get(run.run_id) == before
    roundtrip.executor.execute_with_deadline.assert_not_called()


@pytest.mark.parametrize("prior_unknown", [False, True])
def test_nonretryable_host_refusal_settles_only_with_certain_terminal_receipt(
    roundtrip, prior_unknown
):
    from app.application.agent_orchestrator.task_execution_sql_repository import (
        SQLAlchemyTaskExecutionRepository,
    )
    from app.application.agent_orchestrator.tool_executor import execute_with_tool_deadline

    service, run = _cached_clarification(roundtrip)
    executor = Mock()
    denial = execute_with_tool_deadline(
        executor,
        run.steps[1],
        runtime_context={
            **run.metadata["runtime_context"],
            "_mod_authorization": {
                "session_row_id": roundtrip.actor.session_row_id,
                "user_id": str(roundtrip.actor.user_id),
                "mod_id": "ungranted-review-mod",
            },
        },
        timeout_seconds=5,
    )
    assert denial["error_code"] == "mod_authorization_invalid"
    assert denial["execution_status"] == "not_started" and denial["retryable"] is False
    executor.execute_with_deadline.assert_not_called()
    run.status = "failed"
    run.steps[1].status, run.steps[1].output = "failed", denial
    run.metadata["non_retryable"] = True
    queue = SQLAlchemyTaskExecutionRepository(session_factory=roundtrip.actor.factory)
    queue.enqueue(run)
    assert queue.claim("original-worker", lease_seconds=300) is not None
    if prior_unknown:
        assert queue.mark_open_effect(run.run_id, "prior-effect", owner_id="original-worker")
        run.final_output = {"requires_reconciliation": True, "outcome": "unknown"}
    queue.finish(run.run_id, "original-worker", "failed")
    roundtrip.repository.save(run)
    before = roundtrip.repository.get(run.run_id)
    lifecycle_before = queue.lifecycle(run.run_id)
    pending_before = deepcopy(service._pending_workflows[roundtrip.chat_user])

    response = roundtrip.send(service, "先解释一下采购成本")

    assert response["run_id"] == run.run_id
    assert response["execution_state"] == ("unknown" if prior_unknown else "failed")
    assert not roundtrip.requests
    assert roundtrip.repository.get(run.run_id) == before
    assert before.metadata["non_retryable"] is True
    assert queue.lifecycle(run.run_id) == lifecycle_before
    if prior_unknown:
        assert service._pending_workflows[roundtrip.chat_user] == pending_before
        assert roundtrip.store.load(run.plan_id)["status"] == "pending_awaiting"
        assert lifecycle_before["effects"] == ["prior-effect"]
    else:
        assert roundtrip.chat_user not in service._pending_workflows
        assert roundtrip.store.load(run.plan_id)["status"] == "failed"


@pytest.mark.parametrize("tool", ["conversation_history", "dataset_rag"])
@pytest.mark.parametrize("unknown_call", [False, True])
def test_terminal_retrieval_guard_does_not_synthesize_before_state_check(
    roundtrip, monkeypatch, tool, unknown_call
):
    from app.application.agent_orchestrator.run_models import ToolCall
    from app.application.ai_chat.dialogue_memory import bind_chat_turn_context

    context = {**roundtrip.context, "turn_id": uuid4().hex}
    bind_chat_turn_context("解释原始资料", context)
    node = WorkflowNode(
        "read",
        tool,
        "read" if tool == "conversation_history" else "query",
        {"message_id": 81}
        if tool == "conversation_history"
        else {"dataset_id": "synthetic-purchases", "query": "解释原始资料"},
    )
    run = roundtrip.orchestrator().start_run_from_plan(
        user_id=str(roundtrip.actor.user_id),
        message="解释原始资料",
        plan=PlanGraph(plan_id=uuid4().hex, intent="query", nodes=[node]),
        runtime_context=context,
        auto_execute=False,
    )
    run.status = run.steps[0].status = "waiting_user"
    roundtrip.repository.save(run)
    service = roundtrip.service()
    service._capture_agent_run_interaction(
        user_id=roundtrip.chat_user, agent_run=run, runtime_context=run.metadata["runtime_context"]
    )
    row = {
        "id": 81,
        "role": "user",
        "content": "采购资料原文",
        "offset": 0,
        "total_chars": 6,
        "content_complete": True,
    }
    output = {
        "success": True,
        **(
            {"data": {"messages": [row], "has_more": False}}
            if tool == "conversation_history"
            else {"chunks": [{"text": row["content"]}], "query": "解释原始资料"}
        ),
    }
    run.status = run.steps[0].status = "completed"
    run.steps[0].output = output
    run.tool_calls = [
        ToolCall(
            step_id=run.steps[0].step_id,
            node_id=node.node_id,
            tool_id=node.tool_id,
            action=node.action,
            status="unknown" if unknown_call else "completed",
            output={} if unknown_call else deepcopy(output),
        )
    ]
    roundtrip.repository.save(run)
    before = roundtrip.repository.get(run.run_id)
    synthesize = Mock(return_value={"choices": [{"message": {"content": "依据资料整理的答复"}}]})
    monkeypatch.setattr(service.workflow_planner, "complete_messages", synthesize)

    response = roundtrip.send(service, "先解释一下采购成本")

    assert response["run_id"] == run.run_id
    assert response["execution_state"] == ("unknown" if unknown_call else "completed")
    assert synthesize.call_count == (0 if unknown_call else 1)
    assert not roundtrip.requests
    assert roundtrip.repository.get(run.run_id) == before
    assert (roundtrip.chat_user in service._pending_workflows) is unknown_call


@pytest.mark.parametrize(
    ("changed", "turn_kind", "tool_wait"),
    [
        ("unknown", "new_goal", False),
        ("running", "new_goal", False),
        ("unknown", "unclear", False),
        ("unknown", "failure", False),
        ("question", "new_goal", False),
        ("plan", "new_goal", False),
        ("unknown", "new_goal", True),
        ("running", "new_goal", True),
    ],
)
def test_classification_cannot_outlive_its_waiting_snapshot(
    roundtrip, monkeypatch, changed, turn_kind, tool_wait
):
    from app.application.workflow.workflow_types import plan_to_dict

    service, waiting = _paused_preview(roundtrip) if tool_wait else _cached_clarification(roundtrip)
    classify = service.workflow_planner.extract_clarification_turn
    roundtrip.state.classification = {
        "turn_kind": "new_goal" if turn_kind == "failure" else turn_kind,
        "resolved": False,
        "parameters": {},
    }
    if turn_kind == "failure":
        roundtrip.state.classification_error = TimeoutError("provider stalled")
    current_snapshots = []

    def change_during_classification(**request):
        try:
            return classify(**request)
        finally:
            current = roundtrip.repository.get(waiting.run_id)
            if changed in {"unknown", "running"}:
                current.status = changed
            elif changed == "question":
                current.steps[0].output["question"] = "这是另一条待回答的问题。"
            else:
                plan = plan_from_dict(current.metadata["plan"])
                plan.nodes[1].params["id"] = 43
                current.steps[1].params["id"] = 43
                current.metadata["plan"] = plan_to_dict(plan)
            roundtrip.repository.save(current)
            current_snapshots.append(roundtrip.repository.get(waiting.run_id))

    monkeypatch.setattr(
        service.workflow_planner, "extract_clarification_turn", change_during_classification
    )
    pending_before = deepcopy(service._pending_workflows[roundtrip.chat_user])
    plan_before = roundtrip.store.load(waiting.plan_id)
    calls_before = roundtrip.executor.execute_with_deadline.call_count
    response = roundtrip.send(service, "先解释一下采购成本")

    assert response["success"] is False and response["run_id"] == waiting.run_id
    if changed in {"unknown", "running"}:
        assert response["execution_state"] == changed
        assert response["data"]["action"] == f"workflow_{changed}"
    else:
        assert response["data"]["action"] == "workflow_confirmation_stale"
    assert [request["task"] for request in roundtrip.requests] == ["classify_clarification_turn"]
    assert len(current_snapshots) == 1
    assert roundtrip.repository.get(waiting.run_id) == current_snapshots[0]
    assert service._pending_workflows[roundtrip.chat_user] == pending_before
    assert roundtrip.store.load(waiting.plan_id) == plan_before
    assert roundtrip.executor.execute_with_deadline.call_count == calls_before


def _paused_preview(roundtrip):
    from app.application.ai_chat.dialogue_memory import bind_chat_turn_context
    from tests.test_application.test_agent_user_decision_pause import _approve_and_execute, _run

    run = _run(roundtrip.actor)
    context = {**roundtrip.context, "turn_id": uuid4().hex}
    bind_chat_turn_context(run.message, context)
    run.metadata["runtime_context"] = context
    roundtrip.executor.execute_with_deadline.side_effect = [
        roundtrip.preview(roundtrip.actor),
        roundtrip.preview(roundtrip.actor, executable=True),
    ]
    roundtrip.repository.save(run)
    paused = _approve_and_execute(roundtrip.orchestrator(), run, roundtrip.actor)
    service = roundtrip.service()
    service._capture_agent_run_interaction(
        user_id=roundtrip.chat_user,
        agent_run=paused,
        runtime_context=paused.metadata["runtime_context"],
    )
    return service, roundtrip.repository.get(run.run_id)


def test_preview_side_question_preserves_grant_and_resumes_after_restart(roundtrip):
    from app.application.agent_orchestrator.approval_grant import (
        issue_approval_grant,
        validate_approval_grant,
    )

    service, waiting = _paused_preview(roundtrip)
    original_call = deepcopy(waiting.tool_calls[0].to_dict())
    original_call["metadata"].pop("verification", None)
    grant = issue_approval_grant(waiting, principal_id=waiting.user_id)
    roundtrip.state.classification = {"turn_kind": "new_goal", "resolved": False, "parameters": {}}
    roundtrip.state.reply = "宣传文案：从每一份可靠数据开始。"
    reply = roundtrip.send(service, "先帮我写一句宣传文案")
    assert reply["success"] is True and reply["response"] == roundtrip.state.reply
    assert reply["data"]["pending_workflow"]["run_id"] == waiting.run_id
    assert roundtrip.repository.get(waiting.run_id) == waiting
    validate_approval_grant(grant["grant"], run=waiting, principal_id=waiting.user_id)
    assert roundtrip.executor.execute_with_deadline.call_count == 1
    continued = roundtrip.send(roundtrip.service(), "继续")
    assert continued["run_id"] == waiting.run_id
    approved = roundtrip.repository.get(waiting.run_id)
    assert approved.run_id == waiting.run_id and approved.plan_id == waiting.plan_id
    assert approved.steps[0].status == "completed"
    assert approved.steps[1].status == "waiting_user"
    assert roundtrip.executor.execute_with_deadline.call_count == 2
    assert (
        roundtrip.executor.execute_with_deadline.call_args.args[0].params["valid_rows_only"] is True
    )
    assert all(call.action == "preview" for call in approved.tool_calls)
    retained_call = deepcopy(approved.tool_calls[0].to_dict())
    retained_call["metadata"].pop("verification", None)
    assert retained_call == original_call


@pytest.mark.parametrize("ask_side_question", [False, True])
def test_approval_wait_side_question_keeps_original_request(roundtrip, ask_side_question):
    from app.application.agent_orchestrator.approval_grant import (
        issue_approval_grant,
        validate_approval_grant,
    )
    from app.db.models.approval import ApprovalRequest

    def approval_snapshot():
        with tenant_scope(roundtrip.actor.tenant_id), roundtrip.actor.factory() as db:
            return (
                db.query(
                    ApprovalRequest.request_no,
                    ApprovalRequest.status,
                    ApprovalRequest.business_data,
                )
                .order_by(ApprovalRequest.request_no)
                .all()
            )

    roundtrip.state.write = True
    first = roundtrip.send(roundtrip.service(), ORIGINAL)
    roundtrip.send(roundtrip.service(), "删除")
    waiting = roundtrip.repository.get(first["run_id"])
    assert waiting.status == "waiting_user"
    approvals = approval_snapshot()
    assert approvals
    grant = issue_approval_grant(waiting, principal_id=waiting.user_id)
    if ask_side_question:
        roundtrip.state.classification = {
            "turn_kind": "new_goal",
            "resolved": False,
            "parameters": {},
        }
        roundtrip.state.reply = "这是插问的说明。"
        response = roundtrip.send(roundtrip.service(), "先解释一下采购成本")
        assert response["success"] is True and response["response"] == roundtrip.state.reply
        assert "_workflow_new_goal" not in json.dumps(response)
        assert response["data"]["pending_workflow"] == {
            "run_id": waiting.run_id,
            "plan_id": waiting.plan_id,
            "status": "waiting_user",
        }
        others = [r for r in roundtrip.repository.list_recent() if r.run_id != waiting.run_id]
        assert others and all(r.status == "completed" and not r.tool_calls for r in others)
    assert roundtrip.repository.get(waiting.run_id) == waiting
    validate_approval_grant(grant["grant"], run=waiting, principal_id=waiting.user_id)
    assert approval_snapshot() == approvals
    roundtrip.executor.execute_with_deadline.assert_not_called()

    continued = roundtrip.send(roundtrip.service(), "确认")
    assert continued["run_id"] == waiting.run_id
    assert continued["data"]["action"] == "approval_pending", continued
    restored = roundtrip.repository.get(waiting.run_id)
    assert restored.plan_id == waiting.plan_id and restored.status == "waiting_user"
    assert restored.steps[0].tool_id == waiting.steps[0].tool_id
    assert restored.steps[0].action == "delete"
    repeated = roundtrip.send(roundtrip.service(), "确认")
    assert repeated["run_id"] == waiting.run_id
    assert repeated["data"]["action"] == "approval_pending", repeated
    assert approval_snapshot() == approvals
    assert [r.run_id for r in roundtrip.repository.list_recent() if r.status == "waiting_user"] == [
        waiting.run_id
    ]
    roundtrip.executor.execute_with_deadline.assert_not_called()


@pytest.mark.parametrize("turn_kind", ["answer", "unclear"])
def test_free_text_cannot_approve_a_tool_wait(roundtrip, turn_kind):
    service, waiting = _paused_preview(roundtrip)
    roundtrip.state.classification = {
        "turn_kind": turn_kind,
        "resolved": turn_kind == "answer",
        "parameters": {},
    }
    response = roundtrip.send(service, "只保留正确数据就行")
    assert response["data"]["action"] == "workflow_confirmation_required"
    assert response["run_id"] == waiting.run_id
    assert roundtrip.repository.get(waiting.run_id) == waiting
    assert roundtrip.executor.execute_with_deadline.call_count == 1
    assert len(roundtrip.repository.list_recent()) == 1


def test_tool_wait_classification_failure_preserves_original_run(roundtrip):
    service, waiting = _paused_preview(roundtrip)
    roundtrip.state.classification_error = TimeoutError("private provider details")
    response = roundtrip.send(service, "先解释一下文案风格")
    assert response["success"] is False and response["data"]["error_code"] == "model_timeout"
    assert response["run_id"] == waiting.run_id
    assert "private" not in json.dumps(response)
    assert roundtrip.repository.get(waiting.run_id) == waiting
    assert roundtrip.executor.execute_with_deadline.call_count == 1


@pytest.mark.parametrize("mismatch", ["owner", "session", "plan", "unknown"])
def test_tool_wait_side_question_cannot_bypass_durable_guards(roundtrip, mismatch):
    from app.application.ai_chat.workflow_session import WorkflowSession

    service, waiting = _paused_preview(roundtrip)
    pending = service._pending_workflows[roundtrip.chat_user]
    current = deepcopy(waiting)
    if mismatch == "owner":
        current.user_id = "another-owner"
        with pytest.raises(ValueError, match="frozen verification run identity cannot change"):
            roundtrip.repository.save(current)
        assert roundtrip.repository.get(waiting.run_id) == waiting
        assert not roundtrip.requests
        assert roundtrip.executor.execute_with_deadline.call_count == 1
        return
    elif mismatch == "session":
        current.metadata["runtime_context"]["session_id"] = "other-session"
    elif mismatch == "plan":
        pending["plan"] = deepcopy(pending["plan"])
        pending["plan"].nodes[0].params["valid_rows_only"] = False
    else:
        current.steps[0].output["requires_reconciliation"] = True
    if mismatch != "plan":
        roundtrip.repository.save(current)
    before = roundtrip.repository.get(waiting.run_id)
    context = {**waiting.metadata["runtime_context"], "turn_id": uuid4().hex}
    handled, response = WorkflowSession(
        service._pending_workflows, service
    ).resume_pending_dynamic_workflow(roundtrip.chat_user, "先写一句文案", "先写一句文案", context)
    assert handled is True and response["success"] is False
    assert response["data"]["action"] == (
        "workflow_unknown" if mismatch == "unknown" else "workflow_resume_failed"
    )
    assert not roundtrip.requests
    assert roundtrip.repository.get(waiting.run_id) == before
    assert roundtrip.executor.execute_with_deadline.call_count == 1
