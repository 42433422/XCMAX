"""Behavior at the injectable history, session and task-ledger boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from starlette.responses import JSONResponse

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


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("completed", "执行完成，正在整理结果…"),
        ("waiting_user", "执行已暂停，等待你确认或补充信息…"),
        ("failed", "执行失败，正在整理失败回执…"),
        ("blocked", "执行已阻断，正在整理处理说明…"),
        ("running", "任务仍在执行，正在读取处理状态…"),
    ],
)
def test_planned_workflow_stream_reports_the_actual_run_outcome(status, expected):
    from app.application.ai_chat.planned_workflow_dispatch import (
        PlannedWorkflowDispatch,
        WorkflowDispatchCallbacks,
    )
    from app.infrastructure.chat_stream_lifetime import StreamLifetime, current_lifetime

    callbacks = Mock(spec=WorkflowDispatchCallbacks)
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    callbacks._merge_tool_runtime_context.return_value = {}
    callbacks._task_owner_id.return_value = "owner"
    callbacks._build_workflow_thinking_steps.return_value = "读取产品记录"
    dispatch = PlannedWorkflowDispatch(
        {},
        callbacks,
        SimpleNamespace(plan=lambda **kwargs: _plan()),
        SimpleNamespace(
            evaluate=lambda **kwargs: SimpleNamespace(
                allowed=True,
                requires_confirmation=False,
                denied_nodes=[],
                blocking_nodes=[],
                reason="只读",
            )
        ),
        SimpleNamespace(get_approval_required_nodes=lambda plan: []),
    )
    notes = []
    lifetime = StreamLifetime()
    lifetime.observe_notes(notes.append)
    token = current_lifetime.set(lifetime)
    try:
        with (
            patch(
                "app.application.facades.tools_facade.get_workflow_tool_registry", return_value={}
            ),
            patch("app.application.agent_orchestrator.AgentOrchestrator") as orchestrator,
        ):
            orchestrator.return_value.start_run_from_plan.return_value = SimpleNamespace(
                status=status
            )
            dispatch.handle("owner", "查询产品", "chat", {}, "查询产品")
    finally:
        current_lifetime.reset(token)
    assert notes[-1] == expected
    if status == "waiting_user":
        callbacks._capture_agent_run_interaction.assert_called_once()
        callbacks._format_agent_run_response.assert_not_called()
    else:
        callbacks._format_agent_run_response.assert_called_once()
    if status != "completed":
        assert all("执行完成" not in note for note in notes)


def test_history_uses_trusted_owner_and_stable_per_role_idempotency():
    store = Mock(spec=ConversationStore)
    context = {"session_id": "session-1", "turn_id": "turn-1", "local_user_id": 42}
    response = {"success": True, "response": "查询完成", "run_id": "run-1"}

    for _ in range(2):
        persist_chat_turn("web_normal_untrusted", "查询产品", context, response, store=store)

    calls = [
        {**call.kwargs, **message}
        for call in store.save_turn.call_args_list
        for message in call.kwargs["messages"]
    ]
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


def test_scoped_cancellation_records_the_authenticated_task_owner():
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_task_context import (
        authenticated_task_owner,
        scoped_conversation_user_id,
    )

    runtime = {"user_id": "42", "local_user_id": 42, "tenant_id": 1, "session_id": "same"}
    scoped = scoped_conversation_user_id("42", runtime)
    repository = InMemoryAgentRunRepository()
    run = AgentRun(user_id="42", message="query", metadata={"runtime_context": runtime})
    orchestrator = AgentOrchestrator(repository=repository)
    plan = _plan()
    orchestrator._apply_plan(run, plan)
    run.status = run.steps[0].status = "waiting_user"
    repository.save(run)
    pending = {scoped: {"plan": plan, "runtime_context": runtime, "agent_run_id": run.run_id}}
    callbacks = Mock(spec=SessionCallbacks)
    callbacks._task_owner_id.side_effect = authenticated_task_owner
    callbacks._persist_plan_state.return_value = True
    session = WorkflowSession(pending, callbacks)

    with patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orchestrator):
        handled, response = session.resume_pending_dynamic_workflow(scoped, "取消", "取消", runtime)
    assert handled and response["success"]
    assert repository.get(run.run_id).status == "cancelled"
    assert repository.latest_task_control(run.run_id).requested_by == "42"
    assert pending == {}


def test_dispatch_does_not_offer_confirmation_for_an_unpersisted_plan():
    from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch

    plan = _plan()
    callbacks = Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    callbacks._merge_tool_runtime_context.return_value = {"user_id": "owner"}
    callbacks._persist_plan_state.return_value = False
    decision = SimpleNamespace(
        allowed=False,
        requires_confirmation=True,
        denied_nodes=[],
        blocking_nodes=["read"],
        reason="approval required",
    )
    dispatch = PlannedWorkflowDispatch(
        {},
        callbacks,
        SimpleNamespace(plan=lambda **_: plan),
        SimpleNamespace(evaluate=lambda **_: decision),
        SimpleNamespace(get_approval_required_nodes=lambda _: [plan.nodes[0]]),
    )
    with (
        patch("app.application.facades.tools_facade.get_workflow_tool_registry", return_value={}),
        patch("app.application.agent_orchestrator.AgentOrchestrator") as orchestrator,
    ):
        response = dispatch.handle("owner", "查询产品", "chat", {}, "查询产品")
    assert response["success"] is False
    assert response["data"]["action"] == "workflow_persistence_failed"
    assert response["execution"]["outcome"] == "not_executed"
    assert dispatch.pending == {}
    orchestrator.assert_not_called()


@pytest.mark.parametrize("missing_spec", [False, True])
def test_injected_validation_rejects_before_dispatch_or_billing(missing_spec):
    repository = InMemoryAgentRunRepository()
    executor = Mock()
    dependencies = RuntimeDependencies(
        action_spec=lambda tool, action: (
            None if missing_spec else ToolActionSpecV2(tool_id=tool, action=action)
        ),
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
    executor.execute_with_deadline.assert_not_called()
    assert run.tool_calls[0].permission == ""
    assert "authorization_permission" not in run.tool_calls[0].metadata
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
    calls = [
        {**call.kwargs, **message}
        for call in store.save_turn.call_args_list
        for message in call.kwargs["messages"]
    ]
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
    store.save_turn.assert_not_called()


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


def test_auto_approval_waits_for_user_decision_without_reporting_failure():
    """预演需要用户确认时，自动审批已通过，不能报成审批取消/执行失败。"""
    from contextlib import contextmanager

    callbacks = Mock(spec=SessionCallbacks)
    session = WorkflowSession({}, callbacks)
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock()

    @contextmanager
    def fake_get_db():
        yield db

    question = "预演完成：目标「abnormal」，13 行源数据未通过校验"
    with (
        patch("app.db.session.get_db", fake_get_db),
        patch(
            "app.application.approval_workspace_app_service."
            "_approve_ai_workflow_request_without_node",
            return_value={
                "success": False,
                "accepted": True,
                "data": {
                    "workflow_execution": {
                        "success": False,
                        "waiting_user_decision": True,
                        "message": question,
                    }
                },
                "message": question,
            },
        ),
    ):
        reply = session._auto_approve_waiting_request(
            request_id="req-auto",
            user_id="chat:scoped-conversation",
            runtime_context={"actor_id": 7, "user_id": "7"},
            plan=_plan(),
            agent_run=AgentRun(user_id="7", message="导入"),
        )

    assert reply["success"] is True
    assert reply["data"]["action"] == "workflow_waiting"
    assert "需要你确认" in reply["response"]
    assert "审批已取消" not in reply["response"]


def test_auto_approval_reports_partial_elt_writes_from_the_saved_run():
    from contextlib import nullcontext

    session = WorkflowSession({}, Mock(spec=SessionCallbacks))
    db = Mock()
    run = AgentRun(user_id="7", message="导入")
    step = AgentStep(node_id="import", tool_id="elt_import", action="execute")
    run.steps = [step]
    saved = SimpleNamespace(
        steps=[
            SimpleNamespace(
                tool_id="elt_import",
                action="execute",
                status="failed",
                output={"message": "完成 1 份，已确认写入 3 行", "data": {"executed_rows": 3}},
            )
        ]
    )
    with (
        patch("app.db.session.get_db", lambda: nullcontext(db)),
        patch(
            "app.application.approval_workspace_app_service._approve_ai_workflow_request_without_node",
            return_value={"success": False, "data": {"workflow_execution": {"nodes_executed": 0}}},
        ),
        patch("app.application.agent_orchestrator.AgentOrchestrator") as orchestrator,
    ):
        orchestrator.return_value.get_run.return_value = saved
        reply = session._auto_approve_waiting_request(
            request_id="req-elt",
            user_id="7",
            runtime_context={"actor_id": 7},
            plan=_plan(),
            agent_run=run,
        )
    assert "已确认写入 3 行" in reply["response"]
    assert reply["data"]["data"]["execution"] == {
        "committed": True,
        "effect": "partial",
        "outcome": "partial",
    }


def test_approved_background_import_is_not_persisted_as_completed():
    from contextlib import nullcontext

    from app.application.agent_orchestrator.trace_payloads import _payload_status

    session = WorkflowSession({}, Mock(spec=SessionCallbacks))
    run = AgentRun(user_id="7", message="导入", status="queued", metadata={
        "runtime_context": {"turn_id": "turn-1"},
    })
    run.steps = [AgentStep(node_id="import", tool_id="elt_import", action="execute", params={
        "file_paths": ["upload-1"],
    })]
    approval = {"success": True, "accepted": True, "data": {"workflow_execution": {"success": True}}}
    with (
        patch("app.db.session.get_db", lambda: nullcontext(Mock())),
        patch("app.application.approval_workspace_app_service._approve_ai_workflow_request_without_node", return_value=approval),
        patch("app.application.agent_orchestrator.AgentOrchestrator.get_run", return_value=run),
    ):
        reply = session._auto_approve_waiting_request(
            request_id="req-elt", user_id="7", runtime_context={"actor_id": 7},
            plan=_plan(), agent_run=run,
        )
    assert reply["active_turn"]["status"] == "queued"
    assert _payload_status(reply) == "queued"


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


def test_history_persists_visible_business_result_on_assistant_ui() -> None:
    store = Mock(spec=ConversationStore)
    persist_chat_turn(
        "web_normal_untrusted",
        "新增客户",
        {"session_id": "session-1", "turn_id": "turn-1", "local_user_id": 42},
        {
            "success": True,
            "response": "客户创建成功",
            "run_id": "run-1",
            "businessResult": {
                "status": "completed",
                "summary": "客户创建成功",
                "facts": {"customer_id": 23},
            },
        },
        store=store,
    )
    metadata = json.loads(store.save_turn.call_args.kwargs["messages"][1]["metadata"])
    assert metadata["ui"]["businessResult"]["facts"]["customer_id"] == 23


def test_history_does_not_persist_casual_completed_business_result() -> None:
    store = Mock(spec=ConversationStore)
    persist_chat_turn(
        "web_normal_untrusted",
        "你好",
        {"session_id": "session-1", "turn_id": "turn-1", "local_user_id": 42},
        {
            "success": True,
            "response": "你好，需要我做什么？",
            "run_id": "run-casual",
            "business_result": {
                "status": "completed",
                "summary": "你好，需要我做什么？",
                "facts": {},
            },
        },
        store=store,
    )
    metadata = json.loads(store.save_turn.call_args.kwargs["messages"][1]["metadata"])
    assert "businessResult" not in metadata["ui"]


def test_history_persists_summary_only_tool_business_result() -> None:
    store = Mock(spec=ConversationStore)
    persist_chat_turn(
        "web_normal_untrusted",
        "删除该客户",
        {"session_id": "session-1", "turn_id": "turn-1", "local_user_id": 42},
        {
            "success": True,
            "response": "已删除",
            "run_id": "run-delete",
            "business_result": {
                "status": "completed",
                "summary": "已删除",
                "facts": {},
                "evidence": {"completed_tool_count": 1},
            },
        },
        store=store,
    )
    metadata = json.loads(store.save_turn.call_args.kwargs["messages"][1]["metadata"])
    assert metadata["ui"]["businessResult"]["summary"] == "已删除"


@pytest.mark.parametrize("as_response", [False, True])
@pytest.mark.parametrize(
    ("tool_id", "action"),
    [
        ("products", "query"),
        ("shipment_records", "clear"),
        ("dataset_rag", "clear_dataset"),
        ("document_template", "clear"),
        ("materials", "batch_delete"),
    ],
)
def test_auto_approval_uses_authenticated_actor_and_executes_in_same_turn(
    as_response, tool_id, action
):
    from contextlib import contextmanager

    callbacks = Mock(spec=SessionCallbacks)
    session = WorkflowSession({}, callbacks)
    plan = _plan()
    plan.nodes = [WorkflowNode(node_id="selected", tool_id=tool_id, action=action)]
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = Mock()

    @contextmanager
    def fake_get_db():
        yield db

    payload = {
        "success": True,
        "data": {"workflow_execution": {"success": True, "message": "清理完成"}},
    }
    with (
        patch("app.db.session.get_db", fake_get_db),
        patch(
            "app.application.approval_workspace_app_service."
            "_approve_ai_workflow_request_without_node",
            return_value=JSONResponse(payload) if as_response else payload,
        ) as approve,
    ):
        reply = session._auto_approve_waiting_request(
            request_id="req-auto",
            user_id="chat:scoped-conversation",
            runtime_context={"actor_id": 7, "user_id": "7"},
            plan=plan,
            agent_run=AgentRun(user_id="7", message="清理知识库"),
        )

    assert approve.call_args.kwargs["actor"] == 7
    assert reply["success"] is True
    assert reply["data"]["action"] == "workflow_done"
    assert reply["data"]["data"]["auto_approved"] is True
    assert "自动审批已通过并执行完成" in reply["response"]


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
