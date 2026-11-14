"""Behavior at the injectable history, session and task-ledger boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.application.agent_orchestrator.run_models import AgentRun, AgentStep
from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
from app.application.agent_orchestrator.run_usage import RunUsageLedger
from app.application.agent_orchestrator.runtime_dependencies import RuntimeDependencies
from app.application.agent_orchestrator.step_execution import StepExecution
from app.application.agent_orchestrator.tool_spec import ToolActionSpecV2, ToolValidationResult
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
from app.application.workflow.workflow_types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
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

    with patch("app.application.agent_orchestrator.AgentOrchestrator") as orchestrator:
        handled, response = session.resume_pending_dynamic_workflow(
            "owner", "确认", "确认", {"session_id": "different"}
        )
    orchestrator.assert_not_called()

    assert handled and response["data"]["action"] == "clarification_required"
    callbacks._hydrate_pending_workflow.assert_called_once_with("owner", "different")
    assert pending["owner"]["runtime_context"]["session_id"] == "original"


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


@pytest.mark.parametrize("state", ["selected", "completed", "failed", "invalid"])
def test_history_saves_only_public_route_receipt_for_the_authenticated_owner(state):
    store = Mock(spec=ConversationStore)
    public = {
        "provider": "xiaomi",
        "model": "flash",
        "route_source": "platform_default",
        "key_source": "platform",
        "config_revision": "r1",
    }
    persist_chat_turn(
        "forged-owner",
        "hello",
        {
            "session_id": "owned-session",
            "turn_id": "turn-1",
            "local_user_id": 42,
        },
        {
            "success": state == "completed",
            "response": "reply",
            "route_metadata": {
                **public,
                "route_state": state,
                "route_token": "private-token",
                "api_key": "private-key",
                "api_key_masked": "private-mask",
                "base_url": "https://private.invalid",
            },
        },
        store=store,
    )
    calls = [call.kwargs for call in store.save_message.call_args_list]
    assert {call["user_id"] for call in calls} == {"42"}
    assert "route_metadata" not in json.loads(calls[0]["metadata"])
    saved = json.loads(calls[1]["metadata"])["route_metadata"]
    assert saved == {**public, **({"route_state": state} if state != "invalid" else {})}
    assert "private-" not in calls[1]["metadata"] and "private.invalid" not in calls[1]["metadata"]


def test_history_route_receipt_does_not_authorize_a_foreign_session_owner():
    store = Mock(spec=ConversationStore)
    persist_chat_turn(
        "42",
        "hello",
        {"session_id": "foreign-session", "local_user_id": 42, "actor_id": 43},
        {
            "success": True,
            "response": "reply",
            "route_metadata": {"provider": "xiaomi", "model": "flash", "route_state": "completed"},
        },
        store=store,
    )
    store.save_message.assert_not_called()


@pytest.mark.parametrize(
    "detail,message",
    [
        ("safe failure", "safe failure"),
        ({"message": "safe failure"}, "safe failure"),
        (["private-mask"], "对话执行失败"),
    ],
)
@pytest.mark.asyncio
async def test_sync_error_receipt_preserves_status_and_safe_history_for_any_detail(
    monkeypatch, detail, message
):
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from app.application import planner_compat_service as compat

    body = SimpleNamespace(message="触发错误回执测试", context={}, mode="online")
    route = {"provider": "xiaomi", "model": "flash", "route_state": "failed"}
    monkeypatch.setattr(compat, "_prepare_compat_chat_body", lambda request, value: body)
    monkeypatch.setattr(
        compat,
        "_execute_compat_chat_impl",
        AsyncMock(side_effect=HTTPException(status_code=401, detail=detail)),
    )
    monkeypatch.setattr(compat, "request_route_metadata", lambda request: route)
    persist = Mock()
    monkeypatch.setattr(compat, "_persist_compat_chat_turn", persist)
    with pytest.raises(HTTPException) as failure:
        await compat.execute_compat_chat(SimpleNamespace(), body)
    assert failure.value.status_code == 401
    assert failure.value.detail == {"message": message, "route_metadata": route}
    assert persist.call_args.args == (
        body,
        {"success": False, "response": message, "route_metadata": route, "turn_id": None},
    )


def test_auto_approval_uses_authenticated_actor_and_executes_in_same_turn():
    from contextlib import contextmanager

    callbacks = Mock(spec=SessionCallbacks)
    session = WorkflowSession({}, callbacks)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock()

    @contextmanager
    def fake_get_db():
        yield db

    with (
        patch("app.db.session.get_db", fake_get_db),
        patch(
            "app.application.approval_workspace_app_service."
            "_approve_ai_workflow_request_without_node",
            return_value={
                "success": True,
                "data": {"workflow_execution": {"success": True, "message": "清理完成"}},
            },
        ) as approve,
    ):
        reply = session._auto_approve_waiting_request(
            request_id="req-auto",
            user_id="chat:scoped-conversation",
            runtime_context={"actor_id": 7, "user_id": "7"},
            plan=_plan(),
            agent_run=AgentRun(user_id="7", message="清理知识库"),
        )

    assert approve.call_args.kwargs["actor"] == 7
    assert reply["success"] is True
    assert reply["data"]["action"] == "workflow_done"
    assert reply["data"]["data"]["auto_approved"] is True
    assert "自动审批已通过并执行完成" in reply["response"]


def test_auto_approval_reply_includes_generated_file_download_url():
    from contextlib import contextmanager

    callbacks = Mock(spec=SessionCallbacks)
    session = WorkflowSession({}, callbacks)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock()

    @contextmanager
    def fake_get_db():
        yield db

    run = AgentRun(user_id="7", message="生成生产表")
    run.steps.append(
        AgentStep(
            node_id="n3",
            tool_id="generate_office_document",
            action="execute",
            status="completed",
            output={
                "success": True,
                "file_name": "宗南家私生产表.xlsx",
                "download_url": "/api/ai/kitten/document/pickup/token-1",
            },
        )
    )
    with (
        patch("app.db.session.get_db", fake_get_db),
        patch(
            "app.application.agent_orchestrator.AgentOrchestrator.get_run",
            return_value=run,
        ),
        patch(
            "app.application.approval_workspace_app_service."
            "_approve_ai_workflow_request_without_node",
            return_value={
                "success": True,
                "data": {"workflow_execution": {"success": True, "message": "AI 工作流执行完成"}},
            },
        ),
    ):
        reply = session._auto_approve_waiting_request(
            request_id="req-file",
            user_id="chat:scoped-conversation",
            runtime_context={"actor_id": 7, "user_id": "7"},
            plan=_plan(),
            agent_run=run,
        )

    assert reply["success"] is True
    assert "宗南家私生产表.xlsx" in reply["response"]
    assert "/api/ai/kitten/document/pickup/token-1" in reply["response"]


def test_auto_approval_without_authenticated_actor_falls_back_to_manual_approval():
    session = WorkflowSession({}, Mock(spec=SessionCallbacks))

    reply = session._auto_approve_waiting_request(
        request_id="req-auto",
        user_id="chat:scoped-conversation",
        runtime_context={},
        plan=_plan(),
        agent_run=AgentRun(user_id="7", message="清理知识库"),
    )

    assert reply is None


def test_auto_approval_continues_through_every_pending_step():
    from contextlib import contextmanager

    session = WorkflowSession({}, Mock(spec=SessionCallbacks))
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock()

    @contextmanager
    def fake_get_db():
        yield db

    step_one = {
        "success": False,
        "data": {
            "workflow_execution": {
                "success": False,
                "execution_accepted": True,
                "next_approval_request_id": "req-2",
                "message": "当前步骤已获批，后续步骤等待审批",
            }
        },
    }
    step_two = {
        "success": True,
        "data": {"workflow_execution": {"success": True, "message": "全部清理完成"}},
    }

    with (
        patch("app.db.session.get_db", fake_get_db),
        patch(
            "app.application.approval_workspace_app_service."
            "_approve_ai_workflow_request_without_node",
            side_effect=[step_one, step_two],
        ) as approve,
    ):
        reply = session._auto_approve_waiting_request(
            request_id="req-1",
            user_id="chat:scoped-conversation",
            runtime_context={"actor_id": 7},
            plan=_plan(),
            agent_run=AgentRun(user_id="7", message="初始化业务数据"),
        )

    assert approve.call_count == 2
    assert reply["success"] is True
    assert reply["data"]["action"] == "workflow_done"
    assert "全部清理完成" in reply["response"]
