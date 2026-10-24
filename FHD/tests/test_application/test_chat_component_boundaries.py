"""Behavior at the injectable history, session and task-ledger boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.runtime_dependencies import RuntimeDependencies
from app.application.agent_orchestrator.step_execution import StepExecution
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, ToolValidationResult
from app.application.ai_chat.agent_workflow_bridge import AgentWorkflowBridge
from app.application.ai_chat.context_enrichment import (
    inject_excel_vector_context,
    inject_wechat_contact_context,
)
from app.application.ai_chat.conversation_history import ConversationStore, persist_chat_turn
from app.application.ai_chat.workflow_session import (
    PlanStateStore,
    SessionCallbacks,
    WorkflowSession,
)
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
    WorkflowRunResult,
)


def _plan():
    return PlanGraph(
        plan_id="plan-session-boundary",
        intent="product_query",
        nodes=[WorkflowNode(node_id="read", tool_id="products", action="query")],
    )


def test_history_uses_trusted_owner_and_stable_per_role_idempotency():
    store = Mock(spec=ConversationStore)
    context = {"session_id": "session-1", "turn_id": "turn-1", "local_user_id": 42}
    response = {"success": True, "response": "查询完成", "run_id": "run-1"}

    for _ in range(2):
        persist_chat_turn("web_normal_untrusted", "查询产品", context, response, store=store)

    calls = [call.kwargs for call in store.save_message.call_args_list]
    assert [call["role"] for call in calls] == ["user", "assistant", "user", "assistant"]
    assert {call["user_id"] for call in calls} == {"42"}
    assert calls[0]["idempotency_key"] == calls[2]["idempotency_key"]
    assert calls[1]["idempotency_key"] == calls[3]["idempotency_key"]
    assert calls[0]["idempotency_key"] != calls[1]["idempotency_key"]
    assert json.loads(calls[1]["metadata"])["summary"]["run_id"] == "run-1"


def test_retrieval_ports_enrich_a_copy_and_clear_stale_contact_context():
    context = {"excel_index_id": " index-1 ", "wechat_contact_context": {"name": "old"}}
    search = SimpleNamespace(query=Mock(return_value={"success": True, "hits": [{"row": 4}]}))

    enriched = inject_excel_vector_context("单价", context, search_service=search)
    assert enriched["excel_vector_context"]["hits"] == [{"row": 4}]
    assert "excel_vector_context" not in context
    search.query.assert_called_once_with(index_id="index-1", query_text="单价", top_k=5)
    cleared = inject_wechat_contact_context("新消息", enriched, resolver=lambda *_: None)
    assert cleared["wechat_contact_context"] is None
    assert enriched["wechat_contact_context"] == {"name": "old"}


def test_cancellation_retains_pending_until_the_durable_store_commits():
    plan = _plan()
    pending = {"owner": {"plan": plan, "runtime_context": {"session_id": "same"}}}
    callbacks = Mock(spec=SessionCallbacks)
    store = Mock(spec=PlanStateStore)
    session = WorkflowSession(pending, callbacks, store=store)
    callbacks._persist_plan_state.side_effect = session.persist_plan_state
    store.save.side_effect = RuntimeError("commit failed")

    handled, failed = session.resume_pending_dynamic_workflow(
        "owner", "取消", "取消", {"session_id": "same"}
    )
    assert handled and not failed["success"]
    assert pending["owner"]["plan"] is plan
    assert store.save.call_args.kwargs["require_commit"] is True

    store.save.side_effect = None
    handled, cancelled = session.resume_pending_dynamic_workflow(
        "owner", "取消", "取消", {"session_id": "same"}
    )
    assert handled and cancelled["data"]["action"] == "workflow_cancelled"
    assert pending == {}


def test_confirmation_cannot_resume_another_sessions_pending_plan():
    pending = {"owner": {"plan": _plan(), "runtime_context": {"session_id": "original"}}}
    callbacks = Mock(spec=SessionCallbacks)
    callbacks._hydrate_pending_workflow.return_value = False
    session = WorkflowSession(pending, callbacks)

    handled, response = session.resume_pending_dynamic_workflow(
        "owner", "确认", "确认", {"session_id": "different"}
    )

    assert handled and response["data"]["action"] == "clarification_required"
    callbacks._hydrate_pending_workflow.assert_called_once_with("owner", "different")
    callbacks._run_workflow_with_state_updates.assert_not_called()
    assert pending["owner"]["runtime_context"]["session_id"] == "original"


def test_checkpoint_resume_records_state_without_reexecuting_completed_nodes():
    plan = _plan()
    callbacks = Mock(spec=SessionCallbacks)
    runtime = Mock()
    runtime.resume_run.return_value = WorkflowRunResult(plan_id=plan.plan_id, success=True)
    checkpointer = Mock()
    checkpointer.latest_checkpoint.return_value = {"checkpoint_id": "checkpoint-7"}
    session = WorkflowSession({}, callbacks, runtime=runtime, checkpointer=checkpointer)

    result, events = session.run_workflow_with_state_updates(
        plan=plan, runtime_context={"session_id": "same"}, resume=True
    )

    assert result.success and events == []
    runtime.run.assert_not_called()
    runtime.resume_run.assert_called_once_with(
        plan, "checkpoint-7", checkpointer=checkpointer, max_retries=1
    )
    assert [call.kwargs["status"] for call in callbacks._persist_plan_state.call_args_list] == [
        "running",
        "succeeded",
    ]


def test_agentic_bridge_records_observed_results_in_the_injected_repository():
    repository = InMemoryAgentRunRepository()
    bridge = AgentWorkflowBridge(
        repository,
        lambda output: str(output.get("message", "")),
        AgentWorkflowBridge.iter_artifact_payloads,
    )
    plan = _plan()
    result = WorkflowRunResult(
        plan_id=plan.plan_id,
        success=False,
        message="query failed",
        node_results=[
            NodeExecutionResult(
                node_id="read",
                tool_id="products",
                action="query",
                success=False,
                output={"message": "query unavailable"},
            )
        ],
    )

    run = bridge.record_result(
        user_id="owner",
        message="查询产品",
        plan=plan,
        run_result=result,
        runtime_context={"session_id": "same"},
    )

    assert repository.get(run.run_id).status == "failed"
    assert run.steps[0].error == "query unavailable"
    assert run.tool_calls[0].metadata["observed"] is True
    assert run.metadata["tool_call_count"] == 1
    assert len([event for event in run.events if event.event_type == "run.created"]) == 1


def test_injected_validation_rejects_before_dispatch_or_billing():
    repository = InMemoryAgentRunRepository()
    executor = Mock()
    dependencies = RuntimeDependencies(
        action_spec=lambda tool, action: ToolActionSpecV2(tool_id=tool, action=action),
        validate=lambda tool, action, params: ToolValidationResult(
            ok=False, tool_id=tool, action=action, error_code="invalid_input", message="blocked"
        ),
        refresh_budget=lambda run: None,
        repair_enabled=lambda run, context: False,
        repair_limit=lambda run, step, context: 0,
        request_repair=lambda run, step, context: {},
    )
    usage = Mock(spec=RunUsageLedger)
    execute = StepExecution(
        repository,
        executor,
        usage,
        dependencies,
        attach_artifacts=lambda *args, **kwargs: None,
        observe=lambda *args, **kwargs: {},
    )
    run = AgentRun(user_id="owner", message="query")
    step = AgentStep(node_id="read", tool_id="products", action="query")

    execute.execute_step(run, step, runtime_context={}, node_outputs={})

    executor.execute.assert_not_called()
    usage.record_tool_usage_entry.assert_not_called()
    assert step.status == "failed" and step.output["error_code"] == "invalid_input"
