"""产品上报先于业务快路径，并覆盖工单010069中的实测原话。"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.agent_runtime.chat import runtime_chat_payload
from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import dynamic_chat_runtime as dynamic_chat_runtime
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry
from tests.test_application.test_codex_goal_verifier import verifier as verifier

SERVICE = "app.application.planner_compat_service"
STREAM = "app.fastapi_routes.xcagi_compat_chat_stream"

DEFECT_MESSAGE = "保存采购订单报错，点保存没有任何反应。期望：保存成功。实际：报服务器内部错误。"


@pytest.mark.parametrize(
    "message",
    [
        DEFECT_MESSAGE,
        "我要提交产品问题工单，问题名称：管理端基础设施展示不直观，请返回工单编号。",
        "我不是查询生产任务，请使用产品问题上报功能，处理本问题，没有能力请如实说明。",
    ],
)
@pytest.mark.parametrize(
    "guide",
    [
        {"state": "ROUTED", "work_order_id": "WO-fixed-path", "owner_ticket_no": "CI-fixed-path"},
        {"state": "OWNER_ROUTE_UNAVAILABLE", "work_order_id": "WO-fixed-path"},
        {"state": "NEEDS_MORE_EVIDENCE"},
    ],
)
@pytest.mark.parametrize("restart", [False, True])
def test_registered_intake_uses_dynamic_codex_and_truthful_original_receipt(
    monkeypatch,
    guide,
    message,
    trusted_actor,
    local_tools,
    tmp_path,
    restart,
    dynamic_chat_runtime,
):
    from app.infrastructure.auth.dependencies import session_id_from_request
    from app.legacy.routes.conversation.compat_routes import router

    state = dynamic_chat_runtime
    actor = trusted_actor(user_id=2055, tenant_id=7, role="user", permissions=[])
    state.client.headers.update(actor.headers)
    calls = []
    repo = state.repository

    async def submit(request, context, original, reply):
        calls.append((session_id_from_request(request), str(context["tenant_id"]), original))
        return dict(guide)

    state.actions = [
        {"tool_id": "client_product_issue", "action": "submit", "params": {}, "call_id": "submit"}
    ]
    state.review = lambda prompt: pytest.fail(
        "unproven remote issue acceptance must not reach final model review"
    )
    monkeypatch.setattr(STREAM + "._classify_and_submit_client_issue_async", submit)
    service = AIChatApplicationService()
    monkeypatch.setattr("app.application.get_ai_chat_app_service", lambda: service)
    monkeypatch.setenv("MODEL_USAGE_LEDGER_PATH", str(tmp_path / "usage.json"))
    monkeypatch.setenv("MODEL_USAGE_WALLET_BACKEND", "audit")
    app = FastAPI()
    app.include_router(router, prefix="/api")

    context = {"session_id": "issue-2055", "tenant_id": 99, "user_id": 99}

    def send(client, text):
        response = client.post(
            "/api/ai/chat/stream",
            json={
                "message": text,
                "mode": "online",
                "user_id": "untrusted-client-alias",
                "context": context,
            },
        )
        assert response.status_code == 200, response.text
        events = [
            json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
        ]
        result = next(event["result"] for event in events if event["type"] == "done")
        context.update(result.get("runtime_context_update") or {})
        return result

    with TestClient(app, headers=actor.headers) as client:
        result = send(client, message)
        assert len(state.transports) == 1
        assert state.model_requests == []
        assert calls == [], "medium-risk submit must wait for explicit approval"
        assert result["runtime"] == "codex" and result["requires_confirmation"] is True, result
        parent_id = result["run_id"]
        contract = repo.get(parent_id).metadata["runtime_goal_contract"]
        assert contract["request"]["text"] == message
        result = send(client, "确认")
        assert result["data"]["action"] == "approval_pending"
        assert result["run_id"] == parent_id
        assert calls == [], "chat confirmation alone is not workbench approval"
        run_id = result["data"]["data"]["approval_card"]["run_id"]
        assert run_id != parent_id
        if restart:
            repo = SQLAlchemyAgentRunRepository(session_factory=actor.factory)
            set_agent_run_repository_for_tests(repo)
        durable_plan = plan_from_dict(repo.get(run_id).metadata["plan"])
        assert len(durable_plan.nodes) == 1
        assert durable_plan.nodes[0].risk == "medium"
        assert repo.get(run_id).steps[0].status == "waiting_user"
        assert durable_plan.nodes[0].params == {}
        approved_fingerprint = plan_fingerprint(durable_plan)
        approval = state.client.get(f"/api/agent/runs/{run_id}")
        assert approval.status_code == 200, approval.text
        grant = approval.json()["approval"]["grant"]
        approval_result = state.client.post(
            f"/api/agent/runs/{run_id}/continue", json={"approval_grant": grant}
        )
        assert approval_result.status_code == 202, approval_result.text
        assert calls == [], "durable approval enqueues the same child before execution"
        state.drain(run_id)
        before_replay = list(calls)
        replay = state.client.post(
            f"/api/agent/runs/{run_id}/continue", json={"approval_grant": grant}
        )
        assert calls == before_replay
        assert replay.status_code in {403, 409}, replay.text
        run = repo.get(run_id)
        assert run is not None, approval_result
        assert state.client.get(f"/api/agent/runs/{parent_id}").status_code == 200
        parent = repo.get(parent_id)
        assert parent.metadata["runtime_goal_contract"] == contract
        assert plan_fingerprint(plan_from_dict(run.metadata["plan"])) == approved_fingerprint
        assert len(state.transports) == 1 and not hasattr(service, "_pending_workflows")
        result = runtime_chat_payload(parent.final_output["codex_result"])

    assert calls == [(actor.session_id, "7", message)], (
        approval_result,
        run.error,
        [(e.event_type, e.data) for e in run.events],
    )
    assert state.model_requests == [], (
        "approval or remote acceptance flags are not final goal proof"
    )
    assert parent.final_output["codex_result"]["business_completed"] is False
    text = str(result["response"])
    assert "当前没有采购订单。" not in text
    assert run is not None and len(run.tool_calls) == 1
    assert run.tool_calls[0].tool_id == "client_product_issue"
    assert run.tool_calls[0].action == "submit"
    output = run.steps[0].output
    if guide["state"] == "NEEDS_MORE_EVIDENCE":
        assert "期望" in str(output) and "实际" in str(output)
        assert not output["data"].get("work_order_id")
        assert "暂未自动建单" in str(output)
    elif guide["state"] == "OWNER_ROUTE_UNAVAILABLE":
        assert "无法确认受理结果" in output["message"]
        assert "避免重复提交" in output["message"]
        assert result["execution_state"] == "unknown"
        assert result["requires_reconciliation"] is True
        assert result["success"] is False
        assert "WO-fixed-path" not in text
        assert output["success"] is False
        assert output["outcome"] == "unknown" and output["retryable"] is False
        assert run.status == "blocked"
        assert result["success"] is False
    else:
        assert output["data"]["work_order_id"] == "WO-fixed-path"
        assert output["data"]["owner_ticket_no"] == "CI-fixed-path"
        # The fake transport receipt cannot independently prove market-side persistence.
        assert run.status == "blocked"
        assert run.tool_calls[0].metadata["verification"]["code"] == "result_verifier_unavailable"
        assert result["success"] is False
        assert result["execution_state"] == "unknown"
        assert result["requires_reconciliation"] is True


@pytest.mark.parametrize(
    "message, expected",
    [
        ("我不是查询生产任务，请使用产品问题上报功能，处理本问题，没有能力请如实说明。", True),
        ("查询生产任务，然后创建生产工单", False),
        ("请使用产品问题上报功能，也创建生产工单", False),
        ("我不是查询生产任务，请使用产品问题上报功能，但也要安排生产", False),
        ("生产任务有问题，帮我处理", False),
    ],
)
def test_product_report_negation_does_not_capture_real_manufacturing(message, expected):
    from app.application.client_product_issue_intake import looks_like_issue_report

    assert looks_like_issue_report(message) is expected


def test_approval_freeze_is_idempotent_detached_and_elevates_all_required_nodes():
    from app.application.workflow.approval_persistence import freeze_approval_plan
    from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

    original = PlanGraph(
        "freeze-test",
        "product_issue",
        nodes=[
            WorkflowNode(
                "first",
                "client_product_issue",
                "submit",
                params={"nested": {"value": 1}},
                risk="medium",
            ),
            WorkflowNode(
                "second", "client_product_issue", "submit", depends_on=["first"], risk="medium"
            ),
        ],
        metadata={"approval_required_node_ids": ["second"]},
    )
    frozen = freeze_approval_plan(original, "first")
    assert frozen is not None
    assert [node.risk for node in original.nodes] == ["medium", "medium"]
    assert [node.risk for node in frozen.nodes] == ["high", "high"]
    assert plan_fingerprint(frozen) == plan_fingerprint(freeze_approval_plan(frozen, "first"))
    original.nodes[0].params["nested"]["value"] = 99
    original.nodes[1].depends_on.clear()
    assert frozen.nodes[0].params == {"nested": {"value": 1}}
    assert frozen.nodes[1].depends_on == ["first"]


@pytest.mark.parametrize("verdict", ["verified", "failed", "inconclusive"])
def test_chat_projection_preserves_independent_verdict_and_original_receipts(verifier, verdict):
    import copy

    from tests.test_application.test_codex_goal_verifier import goal, response, review

    accepted = verdict == "verified"
    if accepted:
        verifier.replies = [response(review(goal(), goal("再查询second", goal_id="second")))]
    else:
        for row in verifier.rows:
            row["state"] = "unknown"
            row["receipt"].update(
                status="unknown",
                success=False,
                verified=False,
                verification={"status": verdict, "accepted": False},
            )
    before = copy.deepcopy(verifier.rows)
    report = verifier.verify()
    for _ in range(2):
        _status, runtime_result = verifier.classify(report)
        result = runtime_chat_payload(runtime_result)
        assert result["success"] is accepted
        if accepted:
            assert result["execution_state"] == "completed"
            assert not result.get("requires_reconciliation")
        else:
            assert result["execution_state"] == "unknown"
            assert result["requires_reconciliation"] is True
            assert result["retryable"] is False
        assert verifier.rows == before


@pytest.mark.parametrize("approval", [False, True])
def test_chat_projection_keeps_preexecution_refusal_and_approval_without_effect(approval):
    from app.domain.task_lifecycle.agent_runtime_results import (
        base_runtime_result,
        classify_runtime_result,
    )

    result = base_runtime_result("original-parent")
    receipt = {
        "success": False,
        "verified": False,
        "status": "waiting_user" if approval else "blocked",
        "execution_started": False,
        "pending_approval": approval,
        "tool_calls": [],
        "message": "approval required" if approval else "permission denied",
    }
    rows = [
        {
            "call_id": "write",
            "tool_id": "products",
            "action": "create",
            "params": {},
            "state": receipt["status"],
            "receipt": receipt,
        }
    ]
    classify_runtime_result(result, rows, {}, "business", "completed")
    projected = runtime_chat_payload(result)
    assert projected["success"] is False
    assert projected["execution_state"] == ("waiting_user" if approval else "blocked")
    assert not projected.get("requires_reconciliation")
    assert result["business_completed"] is False and receipt["tool_calls"] == []
