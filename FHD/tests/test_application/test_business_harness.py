from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from app.application.agent_orchestrator.business_harness import (
    BUSINESS_HARNESS_PROTOCOL,
    attach_visible_business_result_to_chat_payload,
    ensure_business_harness_context,
    ensure_terminal_business_result,
    visible_chat_business_result,
)
from app.application.agent_orchestrator.run_models import AgentRun, AgentStep, ToolCall
from app.application.agent_orchestrator.task_context import apply_task_context
from app.application.business_harness_projection import project_terminal_run_to_conversation
from app.fastapi_routes.domains.misc.helpers import _message_to_dict


def test_context_creates_task_and_turn_without_reusing_conversation_id() -> None:
    context = ensure_business_harness_context(
        {"conversation_id": "conv-1", "session_id": "conv-1"},
        message="新增客户",
    )

    assert context["conversation_id"] == "conv-1"
    assert context["task_id"].startswith("task_")
    assert context["turn_id"].startswith("turn_")
    assert context["task_id"] != context["conversation_id"]
    assert context["business_harness_protocol"] == BUSINESS_HARNESS_PROTOCOL


def test_terminal_result_exposes_bounded_business_facts_and_event_identity() -> None:
    run = AgentRun(user_id="7", message="新增客户", status="completed")
    run.metadata["runtime_context"] = {
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "task_id": "task-1",
    }
    apply_task_context(run, run.metadata["runtime_context"])
    step = AgentStep(node_id="write", tool_id="business_db", action="write")
    step.output = {"success": True, "message": "客户创建成功", "customer_id": 23}
    step.status = "completed"
    run.steps = [step]
    run.tool_calls = [
        ToolCall(
            step_id=step.step_id,
            node_id=step.node_id,
            tool_id=step.tool_id,
            action=step.action,
            status="completed",
        )
    ]
    event = run.add_event("run.completed", "完成")

    result = ensure_terminal_business_result(run)

    assert event.data["harness"]["task_id"] == "task-1"
    assert event.data["harness"]["turn_id"] == "turn-1"
    assert result["summary"] == "客户创建成功"
    assert result["facts"]["customer_id"] == 23
    assert result["evidence"]["completed_tool_count"] == 1
    assert result["projection_key"].endswith(f":{run.run_id}:completed")


def test_approval_result_projection_is_idempotency_keyed_and_readable() -> None:
    run = AgentRun(user_id="7", message="新增客户", status="completed")
    run.metadata["runtime_context"] = {
        "conversation_id": "conv-1",
        "turn_id": "turn-1",
        "task_id": "task-1",
    }
    apply_task_context(run, run.metadata["runtime_context"])
    run.final_output = {
        "node_outputs": {"write": {"success": True, "message": "客户创建成功", "customer_id": 23}}
    }
    conversation = Mock()
    conversation.save_message.return_value = 91
    orchestrator = Mock()
    orchestrator.get_run.return_value = run

    with (
        patch("app.application.agent_orchestrator.AgentOrchestrator", return_value=orchestrator),
        patch("app.services.get_conversation_service", return_value=conversation),
    ):
        message_id = project_terminal_run_to_conversation(
            run.run_id,
            approval_request_id="APR-1",
        )

    assert message_id == 91
    call = conversation.save_message.call_args
    assert call.kwargs["session_id"] == "conv-1"
    assert call.kwargs["intent"] == "business_harness_result"
    assert call.kwargs["idempotency_key"].endswith(f":{run.run_id}:completed")
    assert "客户 ID：23" in call.kwargs["content"]
    assert "审批单：APR-1" in call.kwargs["content"]


def test_text_only_order_request_is_not_a_completed_business_result() -> None:
    run = AgentRun(
        user_id="2",
        message="请开一张测试订单：客户闭环验收，产品包装盒，数量1。开单后提交审批，并生成可下载的单据文件。",
        status="completed",
    )
    run.final_output = {
        "chat_payload": {
            "success": True,
            "response": "没问题，帮你开这张测试订单。先创建销售订单。",
        }
    }

    result = ensure_terminal_business_result(run)

    assert run.status == "failed"
    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["evidence"]["completed_tool_count"] == 0
    assert "没有工具调用" in result["summary"]


@pytest.mark.parametrize(
    "message,tool_completed,pending",
    [
        ("你好", False, False),
        ("请开一张测试订单", True, False),
        ("请开一张测试订单", False, True),
    ],
)
def test_completed_and_pending_order_results(message, tool_completed, pending) -> None:
    run = AgentRun(user_id="2", message=message, status="completed")
    if tool_completed:
        run.tool_calls = [
            ToolCall(
                step_id="step-1",
                node_id="write",
                tool_id="sales",
                action="create_order",
                status="completed",
            )
        ]
    if pending:
        run.final_output = {"chat_payload": {"pending_approval": True, "message": "请审批"}}
    result = ensure_terminal_business_result(run)
    assert run.status != "failed"
    assert result["success"] is not pending
    assert result["status"] == ("pending_approval" if pending else "completed")
    assert result["evidence"]["completed_tool_count"] == int(tool_completed)


def test_explicit_order_request_forces_the_registered_erp_tool() -> None:
    from app.application.agent_orchestrator.business_harness import forced_order_tool_choice

    tools = [{"type": "function", "function": {"name": "execute_erp_capability"}}]
    choice = forced_order_tool_choice("请开一张测试订单，客户闭环验收，数量1", tools)

    assert choice == {"type": "function", "function": {"name": "execute_erp_capability"}}
    assert forced_order_tool_choice("查询今天的订单", tools) is None
    assert forced_order_tool_choice("不要开单", tools) is None
    assert forced_order_tool_choice("请开一张测试订单", []) is None


def test_conversation_message_envelope_restores_whitelisted_harness_ui() -> None:
    row = _message_to_dict(
        (
            9,
            "conv-1",
            "7",
            "assistant",
            "业务任务已完成",
            "business_harness_result",
            '{"business_harness":{"run_id":"run-1"},"ui":{"businessResult":{"status":"completed"}}}',
            None,
        )
    )

    assert row["business_harness"] == {"run_id": "run-1"}
    assert row["ui_payload"] == {"businessResult": {"status": "completed"}}


@pytest.mark.parametrize(
    "run_status,plan_status,identity",
    [
        (state, final, identity)
        for state, final in [
            ("completed", "succeeded"),
            ("cancelled", "cancelled"),
            ("failed", "failed"),
        ]
        for identity in ["direct", "alias"]
    ]
    + [
        ("completed", "pending_awaiting", identity)
        for identity in [
            "actor-mismatch",
            "session-mismatch",
            "tenant-mismatch",
            "task-mismatch",
            "child-id-mismatch",
            "node-params-mismatch",
            "missing-parent-link",
            "multi-pending",
        ]
    ]
    + [("completed", "succeeded", "multi-completed")],
)
def test_terminal_projection_closes_original_plan_without_reexecuting(
    run_status, plan_status, identity
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.application.workflow.plan_store import WorkflowPlanStore
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
    from app.db.models.workflow import WorkflowPlan

    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    WorkflowPlan.__table__.create(engine)
    store = WorkflowPlanStore(session_factory=sessionmaker(bind=engine))
    node = WorkflowNode(
        node_id="sales_create_order", tool_id="sales", action="create_order", params={"quantity": 2}
    )
    nodes = [node]
    if identity.startswith("multi-"):
        nodes.append(
            WorkflowNode(
                node_id="second_order",
                tool_id="sales",
                action="create_order",
                params={"quantity": 3},
            )
        )
    plan = PlanGraph(plan_id="wp-projection-fixture", intent="sales", nodes=nodes, todo_steps=[])
    owner = "7" if identity == "direct" else "web_normal_conv-1"
    context = {
        "user_id": owner,
        "local_user_id": "7",
        "actor_id": "7",
        "session_id": "conv-1",
        "conversation_id": "conv-1",
        "tenant_id": "tenant-1",
        "task_id": "task-1",
    }
    stored_context = dict(context)
    if identity == "actor-mismatch":
        stored_context.update(local_user_id="8", actor_id="8")
    elif identity == "session-mismatch":
        stored_context["conversation_id"] = "other-session"
    elif identity == "tenant-mismatch":
        stored_context["tenant_id"] = "other-tenant"
    elif identity == "task-mismatch":
        stored_context["task_id"] = "other-task"
    store.save(
        plan=plan,
        runtime_context=stored_context,
        status="pending_awaiting",
        user_id=owner,
        session_id="conv-1",
    )
    run = AgentRun(user_id="7", message="synthetic sale", status=run_status)
    run.plan_id = f"{plan.plan_id}:{node.node_id}"
    run.metadata["runtime_context"] = context
    run.metadata["plan"] = {
        "metadata": {
            "approval_parent_plan_id": plan.plan_id,
            "approval_parent_node_id": node.node_id,
        }
    }
    run.steps = [
        AgentStep(
            node_id=node.node_id, tool_id=node.tool_id, action=node.action, params=node.params
        )
    ]
    if identity == "child-id-mismatch":
        run.plan_id += ":unrelated"
    elif identity == "node-params-mismatch":
        run.steps[0].params = {"quantity": 99}
    elif identity == "missing-parent-link":
        run.metadata["plan"] = {"metadata": {}}
    apply_task_context(run, context)
    run.final_output = {
        "node_outputs": {
            "write": {"success": True, "message": "synthetic sale saved", "order_id": 23}
        }
    }
    orchestrator, conversation = Mock(), Mock()
    orchestrator.get_run.return_value = run
    if identity.startswith("multi-"):
        import copy

        sibling = copy.deepcopy(run)
        sibling.run_id = "run-sibling-fixture"
        sibling.plan_id = f"{plan.plan_id}:{nodes[1].node_id}"
        sibling.metadata["plan"]["metadata"]["approval_parent_node_id"] = nodes[1].node_id
        sibling.steps = [
            AgentStep(
                node_id=nodes[1].node_id,
                tool_id=nodes[1].tool_id,
                action=nodes[1].action,
                params=nodes[1].params,
            )
        ]
        sibling.status = "waiting_user" if identity == "multi-pending" else "completed"
        orchestrator.list_task_runs.return_value = [run, sibling]
    conversation.save_message.return_value = 91
    try:
        with (
            patch(
                "app.application.agent_orchestrator.AgentOrchestrator", return_value=orchestrator
            ),
            patch("app.services.get_conversation_service", return_value=conversation),
            patch("app.application.workflow.plan_store.WorkflowPlanStore", return_value=store),
        ):
            assert (
                project_terminal_run_to_conversation(run.run_id, approval_request_id="APR-fixture")
                == 91
            )
            assert (
                project_terminal_run_to_conversation(run.run_id, approval_request_id="APR-fixture")
                == 91
            )
        assert store.load(plan.plan_id)["status"] == plan_status
        assert bool(store.list_active(owner)) == (plan_status == "pending_awaiting")
        orchestrator.continue_run.assert_not_called()
        assert (
            conversation.save_message.call_args_list[0].kwargs["idempotency_key"]
            == conversation.save_message.call_args_list[1].kwargs["idempotency_key"]
        )
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "message", ["请创建客户：测试客户", "请更新产品的型号", "删除数据库里的旧客户"]
)
def test_text_only_business_mutation_never_reports_completed(message):
    run = AgentRun(user_id="2", message=message, status="completed")
    run.final_output = {"chat_payload": {"success": True, "response": "已处理完成"}}
    result = ensure_terminal_business_result(run)
    assert result["success"] is False
    assert result["status"] == "failed"
    assert "没有工具调用" in result["summary"]


def test_negated_business_mutation_is_not_treated_as_unexecuted():
    run = AgentRun(user_id="2", message="不要删除客户，告诉我怎么办", status="completed")
    assert ensure_terminal_business_result(run)["success"] is True


def test_unplanned_tool_request_cannot_return_success_payload():
    from unittest.mock import patch

    from app.application.agent_orchestrator.chat_trace import (
        attach_chat_trace_run,
    )
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    payload = {
        "success": True,
        "response": "查询成功",
        "data": {"action": "tool_call", "tool_key": "products"},
    }
    with patch(
        "app.application.agent_orchestrator.chat_trace.get_agent_run_repository", return_value=repo
    ):
        result = attach_chat_trace_run(
            payload,
            message="查询产品",
            runtime_context={},
            user_id="u1",
        )
    assert result["success"] is False
    assert result["execution_state"] == "failed"
    assert result["data"]["execution_started"] is False
    run = repo.get(result["run_id"])
    assert run is not None and run.status == "failed" and run.tool_calls == []


def test_read_only_tool_is_not_evidence_of_customer_write():
    run = AgentRun(user_id="2", message="请更新产品的型号", status="completed")
    run.tool_calls = [
        ToolCall(
            step_id="s1", node_id="read", tool_id="business_db", action="read", status="completed"
        )
    ]
    run.final_output = {"chat_payload": {"success": True, "response": "产品已更新"}}
    result = ensure_terminal_business_result(run)
    assert result["success"] is False
    assert run.status == "failed"


def test_unrelated_export_artifact_does_not_prove_order_created():
    from app.application.agent_orchestrator.run_models import AgentArtifact

    run = AgentRun(user_id="2", message="请开一张订单并导出单据", status="completed")
    run.artifacts = [AgentArtifact(artifact_type="file", name="old.xlsx")]
    assert ensure_terminal_business_result(run)["success"] is False
    assert run.status == "failed"


def test_long_ordinary_chat_is_not_misclassified_as_a_write():
    run = AgentRun(user_id="2", message="请解释这个概念。" * 10000, status="completed")
    assert ensure_terminal_business_result(run)["success"] is True


def test_wrapped_read_is_not_evidence_of_a_write():
    run = AgentRun(user_id="2", message="请更新产品的型号", status="completed")
    run.tool_calls = [
        ToolCall(
            step_id="s1",
            node_id="read",
            tool_id="execute_erp_capability",
            action="execute",
            params={"tool_id": "business_db", "action": "read"},
            status="completed",
        )
    ]
    assert ensure_terminal_business_result(run)["success"] is False


def test_statistics_receipt_exposes_actual_rows_and_amount_without_recalculation():
    from app.application.agent_orchestrator.business_harness import _result_facts
    from app.application.business_harness_projection import _message_for_result

    facts = _result_facts(
        [{"success": True, "row_count": 2, "numeric_summary": {"total_amount": {"sum": 200.0}}}]
    )
    assert facts == {"row_count": 2, "amount_total": 200.0}
    text = _message_for_result({"status": "completed", "facts": facts}, "")
    assert "明细行数: 2" in text or "明细行数：2" in text
    assert "200" in text


def test_visible_chat_business_result_hides_completed_casual_turns() -> None:
    assert (
        visible_chat_business_result(
            {
                "protocol": BUSINESS_HARNESS_PROTOCOL,
                "status": "completed",
                "success": True,
                "summary": "你好",
                "facts": {},
            }
        )
        is None
    )


def test_visible_chat_business_result_keeps_facts_failures_and_pending() -> None:
    facts = visible_chat_business_result(
        {"status": "completed", "summary": "客户创建成功", "facts": {"customer_id": 23}}
    )
    assert facts is not None and facts["facts"]["customer_id"] == 23
    failed = visible_chat_business_result({"status": "failed", "summary": "写入失败", "facts": {}})
    assert failed is not None and failed["status"] == "failed"
    pending = visible_chat_business_result(
        {"status": "pending_approval", "pending_approval": True, "summary": "等待审批", "facts": {}}
    )
    assert pending is not None and pending["pending_approval"] is True


def test_attach_visible_business_result_uses_payload_or_saved_run() -> None:
    payload = attach_visible_business_result_to_chat_payload(
        {
            "success": True,
            "response": "客户创建成功",
            "business_result": {
                "status": "completed",
                "summary": "客户创建成功",
                "facts": {"customer_id": 23},
            },
        }
    )
    assert payload["businessResult"]["facts"]["customer_id"] == 23

    casual = attach_visible_business_result_to_chat_payload(
        {
            "success": True,
            "response": "你好",
            "run_id": "run-casual",
            "business_result": {"status": "completed", "summary": "你好", "facts": {}},
        }
    )
    assert "businessResult" not in casual

    run = AgentRun(user_id="7", message="新增客户", status="completed")
    run.run_id = "run-facts"
    run.final_output = {
        "business_result": {
            "protocol": BUSINESS_HARNESS_PROTOCOL,
            "status": "completed",
            "summary": "客户创建成功",
            "facts": {"customer_id": 23},
        }
    }
    repo = Mock()
    repo.get.return_value = run
    attached = attach_visible_business_result_to_chat_payload(
        {"success": True, "response": "完成", "run_id": "run-facts"},
        repository=repo,
    )
    assert attached["businessResult"]["facts"]["customer_id"] == 23
    repo.get.assert_called_once_with("run-facts")


def test_visible_chat_business_result_keeps_summary_only_tool_completions() -> None:
    visible = visible_chat_business_result(
        {
            "status": "completed",
            "summary": "已删除",
            "facts": {},
            "evidence": {"completed_tool_count": 1},
        }
    )
    assert visible is not None and visible["summary"] == "已删除"


def test_visible_chat_business_result_keeps_summary_only_toolcall_payloads() -> None:
    visible = visible_chat_business_result(
        {"status": "completed", "summary": "已删除", "facts": {}},
        payload={"success": True, "toolCall": {"tool_id": "customers", "action": "delete"}},
    )
    assert visible is not None and visible["summary"] == "已删除"


def test_attach_visible_business_result_keeps_failed_terminal_payload() -> None:
    payload = attach_visible_business_result_to_chat_payload(
        {
            "success": False,
            "message": "写入失败",
            "businessResult": {"status": "failed", "summary": "写入失败", "facts": {}},
        }
    )
    assert payload["businessResult"]["status"] == "failed"
    assert payload["success"] is False
