"""Product issue tools bind the original report to the signed local session."""

import pytest

from app.application.agent_orchestrator.run_models import AgentStep
from app.application.agent_orchestrator.tool_executor import AgentToolExecutor
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor


@pytest.mark.parametrize("state", ["ROUTED", "OWNER_ROUTE_UNAVAILABLE", "NEEDS_MORE_EVIDENCE"])
def test_registered_issue_uses_signed_actor_and_original_message(trusted_actor, monkeypatch, state):
    from app.infrastructure.auth.dependencies import session_id_from_request

    actor = trusted_actor(role="user")
    message = "保存采购订单报错，点保存没有反应。期望：保存成功。实际：服务器报错。"
    calls = []

    async def fake_submit(request, context, original, reply):
        calls.append((session_id_from_request(request), context["tenant_id"], original))
        return {"state": state, "work_order_id": "WO-test", "owner_ticket_no": "CI-test"}

    monkeypatch.setattr(
        "app.fastapi_routes.xcagi_compat_chat_stream._classify_and_submit_client_issue_async",
        fake_submit,
    )
    step = AgentStep(node_id="report", tool_id="client_product_issue", action="submit", params={})
    result = AgentToolExecutor().execute(
        step, runtime_context={**actor.context, "message": message}
    )
    assert calls == [(actor.session_id, str(actor.tenant_id), message)]
    assert result["success"] is (state != "OWNER_ROUTE_UNAVAILABLE")
    if state == "OWNER_ROUTE_UNAVAILABLE":
        assert result["outcome"] == "unknown" and result["retryable"] is False
        assert "WO-test" not in result["message"]
    elif state == "ROUTED":
        assert "WO-test" in result["message"]


def test_registered_issue_rejects_unbound_or_non_issue_context(trusted_actor, monkeypatch):
    actor = trusted_actor(role="user")
    calls = []

    async def fake_submit(*args, **kwargs):
        calls.append(1)
        return {"state": "ROUTED", "work_order_id": "WO-test"}

    monkeypatch.setattr(
        "app.fastapi_routes.xcagi_compat_chat_stream._classify_and_submit_client_issue_async",
        fake_submit,
    )
    step = AgentStep(node_id="report", tool_id="client_product_issue", action="submit", params={})
    executor = AgentToolExecutor()
    forged = executor.execute(
        step,
        runtime_context={
            "tenant_id": actor.tenant_id,
            "user_id": actor.user_id,
            "message": "提交产品故障工单",
        },
    )
    unrelated = executor.execute(step, runtime_context={**actor.context, "message": "查一下客户"})
    assert forged["success"] is False and unrelated["success"] is False
    assert calls == []


def test_issue_plan_executes_original_report_once_under_signed_account(
    trusted_actor, monkeypatch, local_tools
):
    from app.application.agent_orchestrator import AgentOrchestrator
    from app.application.agent_orchestrator.run_repository import InMemoryAgentRunRepository
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    actor = trusted_actor(role="user")
    message = "我要提交产品问题工单，保存采购订单报错，请返回工单编号。"
    calls = []

    async def fake_submit(request, context, original, reply):
        calls.append((context["tenant_id"], original))
        return {"state": "ROUTED", "work_order_id": "WO-test", "owner_ticket_no": "CI-test"}

    monkeypatch.setattr(
        "app.fastapi_routes.xcagi_compat_chat_stream._classify_and_submit_client_issue_async",
        fake_submit,
    )
    plan = PlanGraph(
        plan_id="issue-report-test",
        intent="product_issue",
        nodes=[
            WorkflowNode(
                node_id="submit",
                tool_id="client_product_issue",
                action="submit",
                params={},
                risk="medium",
                idempotent=False,
            )
        ],
    )
    runner = AgentOrchestrator(repository=InMemoryAgentRunRepository())
    run = runner.start_run_from_plan(
        user_id=str(actor.user_id), message=message, plan=plan, runtime_context=actor.context
    )
    if run.status == "waiting_user":
        run = runner.continue_run(
            run.run_id, approved_by=str(actor.user_id), approved_step_id="submit"
        )
    assert run is not None and run.status == "completed", run.error if run else None
    assert "WO-test" in str(run.steps[0].output)
    assert calls == [(str(actor.tenant_id), message)]
    runner.continue_run(run.run_id, approved_by=str(actor.user_id), approved_step_id="submit")
    assert len(calls) == 1
