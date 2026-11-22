"""产品上报先于业务快路径，并覆盖工单010069中的实测原话。"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.agent_orchestrator import set_agent_run_repository_for_tests
from app.application.agent_orchestrator.run_sql_repository import SQLAlchemyAgentRunRepository
from app.application.ai_chat_app_service import AIChatApplicationService
from app.application.workflow.workflow_types import plan_fingerprint, plan_from_dict
from tests.fixtures.backend_ci_isolation import trusted_actor as trusted_actor
from tests.fixtures.codex_http_runtime import compiled_chat_runtime as compiled_chat_runtime
from tests.fixtures.codex_http_runtime import runtime_entry as runtime_entry
from tests.fixtures.planner_model import goal_review_response

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
def test_registered_intake_uses_authorized_planner_and_truthful_receipt(
    monkeypatch,
    guide,
    message,
    trusted_actor,
    local_tools,
    tmp_path,
    restart,
    compiled_chat_runtime,
):
    from app.infrastructure.auth.dependencies import session_id_from_request
    from app.legacy.routes.conversation.compat_routes import router

    state = compiled_chat_runtime
    actor = trusted_actor(user_id=2055, tenant_id=7, role="user", permissions=[])
    state.client.headers.update(actor.headers)
    calls = []
    planned = []
    reviewed = []
    repo = state.repository

    async def submit(request, context, original, reply):
        calls.append((session_id_from_request(request), str(context["tenant_id"]), original))
        return dict(guide)

    def completion(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"])
        if payload.get("task") == "audit_goal_coverage":
            reviewed.append(payload)
            node = payload["plan"]["nodes"][0]
            assert (node["tool_id"], node["action"], node["params"]) == (
                "client_product_issue",
                "submit",
                {},
            )
            return goal_review_response(
                payload, source=message, node_ids=["submit"], outcome="execute"
            )
        planned.append(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "mode": "workflow",
                                "intent": "product_issue",
                                "nodes": [
                                    {
                                        "node_id": "submit",
                                        "tool_id": "client_product_issue",
                                        "action": "submit",
                                        "params": {},
                                        "risk": "medium",
                                        "idempotent": False,
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(STREAM + "._classify_and_submit_client_issue_async", submit)
    service = AIChatApplicationService()
    state.completion = completion
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
        assert len(planned) == 1
        assert len(reviewed) == 1
        assert calls == [], "medium-risk submit must wait for explicit approval"
        assert result["runtime"] == "codex" and result["requires_confirmation"] is True, result
        parent_id = result["run_id"]
        frozen = repo.get(parent_id).metadata["runtime_frozen_plan"]
        assert frozen["nodes"][0]["risk"] == "high"
        assert frozen["nodes"][0]["params"] == {}
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
        assert plan_fingerprint(durable_plan) == plan_fingerprint(plan_from_dict(frozen))
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
        assert replay.status_code == 409, replay.text
        run = repo.get(run_id)
        assert run is not None, approval_result
        assert state.client.get(f"/api/agent/runs/{parent_id}").status_code == 200
        parent = repo.get(parent_id)
        assert parent.metadata["runtime_frozen_plan"] == frozen
        assert len(state.transports) == 1 and not service._pending_workflows
        result = service._format_agent_run_response(
            plan_from_dict(run.metadata["plan"]),
            run,
            user_message=message,
        )

    assert calls == [(actor.session_id, "7", message)], (
        approval_result,
        run.error,
        [(e.event_type, e.data) for e in run.events],
    )
    assert len(planned) == 1, "confirmation resumes the frozen plan, not a new model plan"
    assert len(reviewed) == 1, "approval resumes the reviewed plan without new model calls"
    assert parent.final_output["codex_result"]["business_completed"] is (
        guide["state"] != "OWNER_ROUTE_UNAVAILABLE"
    )
    text = str(result)
    assert "当前没有采购订单。" not in text
    assert run is not None and len(run.tool_calls) == 1
    assert run.tool_calls[0].tool_id == "client_product_issue"
    assert run.tool_calls[0].action == "submit"
    output = run.steps[0].output
    if guide["state"] == "NEEDS_MORE_EVIDENCE":
        assert "期望" in text and "实际" in text
        assert not output["data"].get("work_order_id")
        assert "暂未自动建单" in text
    elif guide["state"] == "OWNER_ROUTE_UNAVAILABLE":
        assert "业务结果未知" in output["message"]
        assert result["execution_state"] == "unknown"
        assert result["requires_reconciliation"] is True
        assert "勿重复提交" in result["response"]
        assert "WO-fixed-path" not in text
        assert output["success"] is False
        assert output["outcome"] == "unknown" and output["retryable"] is False
        assert run.status == "blocked"
        assert result["success"] is False
    else:
        assert "WO-fixed-path" in text
        assert output["data"]["owner_ticket_no"] == "CI-fixed-path"
        assert run.status == "completed"
        assert result["success"] is True


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
