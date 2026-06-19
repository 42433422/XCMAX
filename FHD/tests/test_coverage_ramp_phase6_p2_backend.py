"""COVERAGE_RAMP Phase 6 round 2: approval_gated_engine + ai_intent routes.

Targets:
- ``app.application.workflow.approval_gated_engine`` (~33.1% line coverage)
- ``app.fastapi_routes.ai_intent`` (~27.1% line coverage)

Strategy:
- ApprovalGatedEngine: 用 MagicMock 替换 WorkflowEngine / ApprovalService,
  构造真实 PlanGraph + HybridRiskGate,覆盖 auto / interactive / reject 三种策略
  以及 ``to_dict`` / ``build_gated_evidence`` / ``_summarize_output`` 各分支。
- ai_intent: 用 TestClient + FastAPI 子应用挂载 router,mock 掉
  ``unified_chat_single_payload`` / ``recognize_intents`` / ``BertIntentClassifier``
  等外部依赖,覆盖 400/404/500/200 各路径。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.workflow.approval_gated_engine import (
    ApprovalGatedEngine,
    GatedNodeDecision,
    GatedPlanDecision,
    _summarize_output,
    build_gated_evidence,
)
from app.application.workflow.risk_gate import RiskDecision
from app.application.workflow.types import (
    NodeExecutionResult,
    PlanGraph,
    WorkflowNode,
    WorkflowRunResult,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_plan(*, plan_id: str = "plan-1", risk: str = "high") -> PlanGraph:
    """构造一个包含高/低风险节点的 PlanGraph。"""
    return PlanGraph(
        plan_id=plan_id,
        intent="shipment_generate",
        nodes=[
            WorkflowNode(
                node_id="read_only",
                tool_id="products",
                action="query",
                risk="low",
                params={"keyword": "ABC"},
            ),
            WorkflowNode(
                node_id="write_op",
                tool_id="orders",
                action="create",
                risk=risk,
                params={"unit_name": "甲公司"},
                depends_on=["read_only"],
            ),
        ],
        risk_level=risk,
    )


def _make_engine() -> ApprovalGatedEngine:
    """构造 ApprovalGatedEngine,内部依赖全部 mock。"""
    mock_engine = MagicMock(name="WorkflowEngine")
    mock_engine.run.return_value = WorkflowRunResult(
        plan_id="plan-1",
        success=True,
        node_results=[
            NodeExecutionResult(
                node_id="read_only",
                success=True,
                tool_id="products",
                action="query",
                output={"success": True, "data": [{"name": "P1"}]},
            ),
            NodeExecutionResult(
                node_id="write_op",
                success=True,
                tool_id="orders",
                action="create",
                output={"success": True, "id": 42, "unit_name": "甲公司"},
            ),
        ],
        message="工作流执行完成",
    )
    # ApprovalService 用真实实例,但持久化到 DB 的部分会失败/被吞掉,不影响行为
    engine = ApprovalGatedEngine(
        engine=mock_engine,
        risk_gate=None,  # 使用真实 HybridRiskGate
        approval_service=None,  # 使用真实 ApprovalService
    )
    return engine


# ---------------------------------------------------------------------------
# GatedNodeDecision / GatedPlanDecision.to_dict
# ---------------------------------------------------------------------------


def test_gated_node_decision_defaults() -> None:
    nd = GatedNodeDecision(
        node_id="n1",
        tool_id="orders",
        action="create",
        risk="high",
        requires_approval=True,
    )
    assert nd.approval_request_id == ""
    assert nd.approved is None
    assert nd.rejected is None
    assert nd.reason == ""


def test_gated_plan_decision_to_dict_full() -> None:
    risk_decision = RiskDecision(
        requires_confirmation=True,
        reason="高风险写操作",
        blocking_nodes=["n1"],
    )
    plan_decision = GatedPlanDecision(
        plan_id="p1",
        risk_decision=risk_decision,
        node_decisions=[
            GatedNodeDecision(
                node_id="n1",
                tool_id="orders",
                action="create",
                risk="high",
                requires_approval=True,
                approval_request_id="req-1",
                approved=True,
                rejected=False,
                reason="auto-approved",
            ),
            GatedNodeDecision(
                node_id="n2",
                tool_id="products",
                action="query",
                risk="low",
                requires_approval=False,
                approved=True,
                reason="low-risk auto-approved",
            ),
        ],
        approval_request_ids=["req-1"],
        all_approved=True,
        any_rejected=False,
        pending_approval=False,
    )

    out = plan_decision.to_dict()
    assert out["plan_id"] == "p1"
    assert out["risk_decision"]["requires_confirmation"] is True
    assert out["risk_decision"]["reason"] == "高风险写操作"
    assert out["risk_decision"]["blocking_nodes"] == ["n1"]
    assert len(out["node_decisions"]) == 2
    assert out["node_decisions"][0]["approval_request_id"] == "req-1"
    assert out["approval_request_ids"] == ["req-1"]
    assert out["all_approved"] is True
    assert out["any_rejected"] is False
    assert out["pending_approval"] is False


def test_gated_plan_decision_to_dict_empty_node_decisions() -> None:
    """空 node_decisions 与 None blocking_nodes 的边界。"""
    risk_decision = RiskDecision(
        requires_confirmation=False,
        reason="ok",
        blocking_nodes=None,  # type: ignore[arg-type]
    )
    plan_decision = GatedPlanDecision(
        plan_id="p2",
        risk_decision=risk_decision,
        node_decisions=[],
        approval_request_ids=[],
    )
    out = plan_decision.to_dict()
    assert out["node_decisions"] == []
    # blocking_nodes 为 None 时 to_dict 应转成空 list
    assert out["risk_decision"]["blocking_nodes"] == []


# ---------------------------------------------------------------------------
# ApprovalGatedEngine.evaluate_plan — auto / interactive / reject
# ---------------------------------------------------------------------------


def test_evaluate_plan_auto_strategy_all_approved() -> None:
    engine = _make_engine()
    plan = _make_plan()
    decision = engine.evaluate_plan(plan, runtime_context={}, strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_AUTO)

    # write_op 是 high risk → requires_approval=True, auto → approved=True
    nd_write = next(nd for nd in decision.node_decisions if nd.node_id == "write_op")
    assert nd_write.requires_approval is True
    assert nd_write.approved is True
    assert nd_write.rejected is None
    assert nd_write.reason == "auto-approved"
    assert nd_write.approval_request_id != ""

    nd_read = next(nd for nd in decision.node_decisions if nd.node_id == "read_only")
    assert nd_read.requires_approval is False
    assert nd_read.approved is True
    assert nd_read.reason == "low-risk auto-approved"

    assert decision.all_approved is True
    assert decision.any_rejected is False
    assert decision.pending_approval is False
    assert len(decision.approval_request_ids) == 1


def test_evaluate_plan_reject_strategy_marks_rejected() -> None:
    engine = _make_engine()
    plan = _make_plan()
    decision = engine.evaluate_plan(
        plan, runtime_context={}, strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_REJECT
    )

    nd_write = next(nd for nd in decision.node_decisions if nd.node_id == "write_op")
    assert nd_write.requires_approval is True
    assert nd_write.rejected is True
    assert nd_write.approved is None
    assert nd_write.reason == "auto-rejected"

    assert decision.any_rejected is True
    assert decision.all_approved is False
    assert decision.pending_approval is False


def test_evaluate_plan_interactive_strategy_pending() -> None:
    engine = _make_engine()
    plan = _make_plan()
    decision = engine.evaluate_plan(
        plan,
        runtime_context={},
        strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_INTERACTIVE,
    )

    nd_write = next(nd for nd in decision.node_decisions if nd.node_id == "write_op")
    assert nd_write.requires_approval is True
    assert nd_write.approved is None
    assert nd_write.rejected is None
    assert nd_write.reason == "pending human approval"

    assert decision.pending_approval is True
    assert decision.all_approved is False
    assert decision.any_rejected is False


def test_evaluate_plan_low_risk_only_no_approval_needed() -> None:
    """全部 low 风险节点 → 不需要审批,全部 auto-approved。"""
    engine = _make_engine()
    plan = PlanGraph(
        plan_id="p-low",
        intent="query",
        nodes=[
            WorkflowNode(node_id="n1", tool_id="products", action="query", risk="low"),
            WorkflowNode(node_id="n2", tool_id="customers", action="query", risk="low"),
        ],
    )
    decision = engine.evaluate_plan(plan, strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_INTERACTIVE)
    assert decision.all_approved is True
    assert decision.pending_approval is False
    assert decision.any_rejected is False
    assert decision.approval_request_ids == []


def test_evaluate_plan_runtime_context_auto_approve_high_risk() -> None:
    """context.workflow_auto_approve_high_risk=True → HybridRiskGate 直接放行。"""
    engine = _make_engine()
    plan = _make_plan()
    decision = engine.evaluate_plan(
        plan,
        runtime_context={"workflow_auto_approve_high_risk": True},
        strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_INTERACTIVE,
    )
    # risk_gate 直接返回 requires_confirmation=False, blocking_nodes=[]
    assert decision.risk_decision.requires_confirmation is False
    assert decision.risk_decision.blocking_nodes == []
    assert decision.all_approved is True
    assert decision.pending_approval is False


# ---------------------------------------------------------------------------
# ApprovalGatedEngine.run
# ---------------------------------------------------------------------------


def test_run_auto_strategy_executes_engine() -> None:
    engine = _make_engine()
    plan = _make_plan()
    decision, run_result = engine.run(
        plan, runtime_context={}, strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_AUTO
    )
    assert decision.all_approved is True
    assert run_result is not None
    assert run_result.success is True
    engine._engine.run.assert_called_once()


def test_run_interactive_strategy_returns_none_run_result() -> None:
    engine = _make_engine()
    plan = _make_plan()
    decision, run_result = engine.run(
        plan,
        runtime_context={},
        strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_INTERACTIVE,
    )
    assert decision.pending_approval is True
    assert run_result is None
    engine._engine.run.assert_not_called()


def test_run_reject_strategy_returns_none_run_result() -> None:
    engine = _make_engine()
    plan = _make_plan()
    decision, run_result = engine.run(
        plan,
        runtime_context={},
        strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_REJECT,
    )
    assert decision.any_rejected is True
    assert run_result is None
    engine._engine.run.assert_not_called()


# ---------------------------------------------------------------------------
# ApprovalGatedEngine.resume_after_approval
# ---------------------------------------------------------------------------


def test_resume_after_approval_all_approved_runs_engine() -> None:
    engine = _make_engine()
    plan = _make_plan()
    # 先 interactive 拿到 request_id
    decision = engine.evaluate_plan(
        plan, strategy=ApprovalGatedEngine.APPROVAL_STRATEGY_INTERACTIVE
    )
    req_ids = decision.approval_request_ids
    assert len(req_ids) == 1

    result = engine.resume_after_approval(plan, {req_ids[0]: True}, runtime_context={})
    assert result.success is True
    engine._engine.run.assert_called_once()


def test_resume_after_approval_partial_rejected_skips_engine() -> None:
    engine = _make_engine()
    plan = _make_plan()
    result = engine.resume_after_approval(
        plan, {"req-x": False, "req-y": True}, runtime_context={}
    )
    assert result.success is False
    assert "未全部通过审批" in result.message
    engine._engine.run.assert_not_called()


def test_resume_after_approval_empty_map_treated_as_all_approved() -> None:
    """all([]) == True → 空字典视为全部通过,会调用 engine.run。"""
    engine = _make_engine()
    plan = _make_plan()
    result = engine.resume_after_approval(plan, {}, runtime_context=None)
    assert result.success is True
    engine._engine.run.assert_called_once()


# ---------------------------------------------------------------------------
# build_gated_evidence
# ---------------------------------------------------------------------------


def _make_decision_for_evidence(*, pending: bool = False, rejected: bool = False) -> GatedPlanDecision:
    risk_decision = RiskDecision(
        requires_confirmation=pending or rejected,
        reason="测试",
        blocking_nodes=["write_op"] if (pending or rejected) else [],
    )
    return GatedPlanDecision(
        plan_id="plan-1",
        risk_decision=risk_decision,
        node_decisions=[
            GatedNodeDecision(
                node_id="read_only",
                tool_id="products",
                action="query",
                risk="low",
                requires_approval=False,
                approved=True,
                reason="low-risk auto-approved",
            ),
            GatedNodeDecision(
                node_id="write_op",
                tool_id="orders",
                action="create",
                risk="high",
                requires_approval=pending or rejected,
                approved=not (pending or rejected),
                rejected=rejected,
                reason="auto-approved" if not (pending or rejected) else "pending",
            ),
        ],
        approval_request_ids=["req-1"] if (pending or rejected) else [],
        all_approved=not (pending or rejected),
        any_rejected=rejected,
        pending_approval=pending,
    )


def test_build_gated_evidence_with_run_result() -> None:
    plan = _make_plan()
    decision = _make_decision_for_evidence()
    run_result = WorkflowRunResult(
        plan_id="plan-1",
        success=True,
        node_results=[
            NodeExecutionResult(
                node_id="read_only",
                success=True,
                tool_id="products",
                action="query",
                output={"success": True, "data": [{"name": "P1"}]},
            ),
        ],
        message="ok",
    )
    payload = build_gated_evidence(
        input_message="创建订单",
        plan=plan,
        decision=decision,
        run_result=run_result,
        execution_mode="agentic",
        strategy="auto",
    )
    assert payload["success"] is True
    assert payload["message"] == "ok"
    assert payload["plan_id"] == "plan-1"
    assert payload["input_message"] == "创建订单"
    assert payload["execution_mode"] == "agentic"
    assert payload["approval_strategy"] == "auto"
    assert payload["intent"] == "shipment_generate"
    assert payload["risk_level"] == "high"
    assert len(payload["nodes"]) == 2
    assert payload["gated_decision"]["all_approved"] is True
    assert "node_results_summary" in payload
    assert payload["node_results_summary"][0]["node_id"] == "read_only"


def test_build_gated_evidence_pending_approval_no_run_result() -> None:
    plan = _make_plan()
    decision = _make_decision_for_evidence(pending=True)
    payload = build_gated_evidence(
        input_message="msg",
        plan=plan,
        decision=decision,
        run_result=None,
        execution_mode="batch",
        strategy="interactive",
    )
    assert payload["success"] is False
    assert "pending approval" in payload["message"]
    assert "node_results_summary" not in payload


def test_build_gated_evidence_rejected_no_run_result() -> None:
    plan = _make_plan()
    decision = _make_decision_for_evidence(rejected=True)
    payload = build_gated_evidence(
        input_message="msg",
        plan=plan,
        decision=decision,
        run_result=None,
        execution_mode="batch",
        strategy="reject",
    )
    assert payload["success"] is False
    assert "rejected" in payload["message"]


def test_build_gated_evidence_not_executed_fallback() -> None:
    """decision 既不 pending 也不 rejected,但 run_result=None → 走 'not executed' 分支。"""
    plan = _make_plan()
    # 构造一个 all_approved=False 但 pending/rejected 都为 False 的 decision
    risk_decision = RiskDecision(
        requires_confirmation=False, reason="ok", blocking_nodes=[]
    )
    decision = GatedPlanDecision(
        plan_id="plan-1",
        risk_decision=risk_decision,
        node_decisions=[],
        all_approved=False,
        any_rejected=False,
        pending_approval=False,
    )
    payload = build_gated_evidence(
        input_message="msg",
        plan=plan,
        decision=decision,
        run_result=None,
        execution_mode="batch",
        strategy="auto",
    )
    assert payload["success"] is False
    assert payload["message"] == "not executed"


def test_build_gated_evidence_node_depends_on_and_params_serialized() -> None:
    """节点的 depends_on / params 应被序列化到 evidence。"""
    plan = PlanGraph(
        plan_id="p-deps",
        intent="i",
        nodes=[
            WorkflowNode(
                node_id="n1",
                tool_id="t1",
                action="a1",
                risk="low",
                params={"k": "v"},
                depends_on=["n0"],
            ),
        ],
    )
    risk_decision = RiskDecision(
        requires_confirmation=False, reason="ok", blocking_nodes=[]
    )
    decision = GatedPlanDecision(
        plan_id="p-deps",
        risk_decision=risk_decision,
        node_decisions=[
            GatedNodeDecision(
                node_id="n1",
                tool_id="t1",
                action="a1",
                risk="low",
                requires_approval=False,
                approved=True,
            )
        ],
        all_approved=True,
    )
    payload = build_gated_evidence(
        input_message="m",
        plan=plan,
        decision=decision,
        run_result=None,
        execution_mode="batch",
        strategy="auto",
    )
    assert payload["nodes"][0]["depends_on"] == ["n0"]
    assert payload["nodes"][0]["params"] == {"k": "v"}


# ---------------------------------------------------------------------------
# _summarize_output
# ---------------------------------------------------------------------------


def test_summarize_output_non_dict_truncates() -> None:
    long_text = "x" * 500
    out = _summarize_output(long_text, max_len=100)
    assert isinstance(out, str)
    assert len(out) == 100


def test_summarize_output_non_dict_short_passthrough() -> None:
    assert _summarize_output("short") == "short"


def test_summarize_output_none() -> None:
    assert _summarize_output(None) == "None"


def test_summarize_output_list_input() -> None:
    out = _summarize_output([1, 2, 3])
    assert out == "[1, 2, 3]"


def test_summarize_output_dict_with_success_and_message() -> None:
    out = _summarize_output({"success": True, "message": "done"})
    assert out["success"] is True
    assert out["message"] == "done"


def test_summarize_output_dict_with_list_data() -> None:
    out = _summarize_output({"data": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]})
    assert out["data_count"] == 2
    assert out["data_sample_keys"] == ["id", "name"]


def test_summarize_output_dict_with_non_list_data() -> None:
    out = _summarize_output({"data": {"foo": "bar"}})
    assert "data_preview" in out
    assert isinstance(out["data_preview"], str)


def test_summarize_output_dict_with_special_keys() -> None:
    out = _summarize_output(
        {"unit_name": "甲公司", "exists": True, "created": False, "matched_count": 5, "id": 99}
    )
    assert out["unit_name"] == "甲公司"
    assert out["exists"] is True
    assert out["created"] is False
    assert out["matched_count"] == 5
    assert out["id"] == 99


def test_summarize_output_dict_message_truncation() -> None:
    long_msg = "y" * 500
    out = _summarize_output({"message": long_msg})
    assert isinstance(out["message"], str)
    assert len(out["message"]) == 200


def test_summarize_output_dict_fallback_first_keys() -> None:
    """无 success/message/data/特殊 key → 返回前 8 个 key。"""
    out = _summarize_output({"a": 1, "b": 2, "c": 3})
    assert out == {"a": 1, "b": 2, "c": 3}


def test_summarize_output_dict_empty_dict() -> None:
    """空 dict → summary 为空 → fallback 返回空 dict。"""
    out = _summarize_output({})
    assert out == {}


# ---------------------------------------------------------------------------
# ai_intent routes — fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def ai_intent_client() -> TestClient:
    """挂载 ai_intent router 的最小 FastAPI 应用。"""
    from app.fastapi_routes import ai_intent

    # 重置模块级状态,避免被其他测试污染
    ai_intent._INTENT_PACKAGES_STATE.update(
        {
            "base": True,
            "industry": True,
            "product": True,
            "quantity": True,
            "customer": True,
        }
    )
    app = FastAPI()
    app.include_router(ai_intent.router)
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# GET /api/ai/test
# ---------------------------------------------------------------------------


def test_ai_test_endpoint(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.get("/api/ai/test")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "message" in body
    assert "timestamp" in body


# ---------------------------------------------------------------------------
# POST /api/ai/chat-unified
# ---------------------------------------------------------------------------


def test_chat_unified_empty_message_returns_400(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post("/api/ai/chat-unified", json={"message": ""})
    assert r.status_code == 400
    body = r.json()
    assert body["success"] is False
    assert "消息内容不能为空" in body["message"]


def test_chat_unified_missing_message_returns_400(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post("/api/ai/chat-unified", json={})
    assert r.status_code == 400
    assert r.json()["success"] is False


def test_chat_unified_success(ai_intent_client: TestClient) -> None:
    with patch("app.application.ai_chat_helpers.unified_chat_single_payload") as mock_payload:
        mock_payload.return_value = {
            "success": True,
            "message": "处理完成",
            "response": "ok",
            "data": {"text": "ok"},
        }
        r = ai_intent_client.post(
            "/api/ai/chat-unified",
            json={"message": "你好", "user_id": "u1", "source": "web"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    # _http_status 应被 pop 掉
    assert "_http_status" not in body


def test_chat_unified_alias_attaches_agent_run(ai_intent_client: TestClient) -> None:
    from app.application.agent_orchestrator import get_agent_run_repository

    get_agent_run_repository().clear()
    with patch("app.application.ai_chat_helpers.unified_chat_single_payload") as mock_payload:
        mock_payload.return_value = {
            "success": True,
            "message": "处理完成",
            "response": "ok",
            "data": {"text": "ok"},
        }
        r = ai_intent_client.post(
            "/api/ai/chat-unified",
            json={"message": "普通版问答", "user_id": "u1", "source": "web"},
        )

    assert r.status_code == 200
    body = r.json()
    run_id = body.get("run_id")
    assert run_id
    assert body["agent_run_id"] == run_id
    run = get_agent_run_repository().get(run_id)
    assert run is not None
    assert run.intent == "chat_unified_alias"
    assert run.metadata["runtime_context"]["route"] == "/api/ai/chat-unified"
    assert run.metadata["runtime_context"]["channel"] == "chat_unified_alias"


def test_chat_unified_propagates_explicit_http_status(
    ai_intent_client: TestClient,
) -> None:
    with patch("app.application.ai_chat_helpers.unified_chat_single_payload") as mock_payload:
        mock_payload.return_value = {
            "success": False,
            "message": "AI 服务错误",
            "_http_status": 500,
        }
        r = ai_intent_client.post("/api/ai/chat-unified", json={"message": "测试"})
    assert r.status_code == 500
    assert r.json()["success"] is False


# ---------------------------------------------------------------------------
# POST /api/ai/chat-unified/batch
# ---------------------------------------------------------------------------


def test_chat_unified_batch_empty_returns_400(ai_intent_client: TestClient) -> None:
    with patch(
        "app.application.ai_chat_helpers.normalize_batch_messages_payload", return_value=[]
    ):
        r = ai_intent_client.post(
            "/api/ai/chat-unified/batch", json={"messages": []}
        )
    assert r.status_code == 400
    assert r.json()["success"] is False


def test_chat_unified_batch_too_many_returns_400(ai_intent_client: TestClient) -> None:
    with patch(
        "app.application.ai_chat_helpers.normalize_batch_messages_payload",
        return_value=[f"m{i}" for i in range(25)],
    ):
        r = ai_intent_client.post(
            "/api/ai/chat-unified/batch", json={"messages": ["x"] * 25}
        )
    assert r.status_code == 400
    assert "最多 20 条" in r.json()["message"]


def test_chat_unified_batch_success(ai_intent_client: TestClient) -> None:
    with (
        patch(
            "app.application.ai_chat_helpers.normalize_batch_messages_payload",
            return_value=["a", "b"],
        ),
        patch(
            "app.application.ai_chat_helpers.unified_chat_single_payload",
            side_effect=lambda msg, *a, **kw: {
                "success": True,
                "data": {"text": f"reply-{msg}"},
            },
        ),
    ):
        r = ai_intent_client.post(
            "/api/ai/chat-unified/batch", json={"messages": ["a", "b"]}
        )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["batch"] is True
    assert body["count"] == 2


def test_chat_unified_batch_with_error_status_preserved(
    ai_intent_client: TestClient,
) -> None:
    """批量中某条返回 _http_status>=400 → 应保留在结果中,且整体 success=False。"""
    with (
        patch(
            "app.application.ai_chat_helpers.normalize_batch_messages_payload",
            return_value=["ok", "bad"],
        ),
        patch(
            "app.application.ai_chat_helpers.unified_chat_single_payload",
            side_effect=[
                {"success": True, "data": {"text": "ok"}},
                {"success": False, "message": "err", "_http_status": 500},
            ],
        ),
    ):
        r = ai_intent_client.post(
            "/api/ai/chat-unified/batch", json={"messages": ["ok", "bad"]}
        )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False  # 因为有一条失败
    assert body["results"][1]["_http_status"] == 500


# ---------------------------------------------------------------------------
# POST /api/ai/intent/test
# ---------------------------------------------------------------------------


def test_intent_test_empty_message_returns_400(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post("/api/ai/intent/test", json={"message": ""})
    assert r.status_code == 400
    assert r.json()["success"] is False


def test_intent_test_missing_message_returns_400(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post("/api/ai/intent/test", json={})
    assert r.status_code == 400


def test_intent_test_success(ai_intent_client: TestClient) -> None:
    from app.application.agent_orchestrator import InMemoryAgentRunRepository

    repo = InMemoryAgentRunRepository()
    with (
        patch("app.application.ai_chat_helpers.recognize_intents") as mock_rec,
        patch(
            "app.application.agent_orchestrator.chat_trace.get_agent_run_repository",
            return_value=repo,
        ),
    ):
        mock_rec.return_value = {
            "primary_intent": "shipment_generate",
            "tool_key": "shipment_generate",
            "intent_hints": ["生成发货单"],
        }
        r = ai_intent_client.post(
            "/api/ai/intent/test", json={"message": "生成发货单", "user_id": "u-intent"}
        )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["primary_intent"] == "shipment_generate"
    run = repo.get(body["run_id"])
    assert run is not None
    assert run.user_id == "u-intent"
    assert run.intent == "intent_recognition"
    assert run.metadata["channel"] == "intent_test_route"
    assert run.metadata["runtime_context"]["route"] == "/api/ai/intent/test"
    assert run.metadata["runtime_context"]["tool_key"] == "shipment_generate"


def test_intent_test_recognizer_raises_returns_500(
    ai_intent_client: TestClient,
) -> None:
    with patch(
        "app.application.ai_chat_helpers.recognize_intents",
        side_effect=ValueError("意图识别错误"),
    ):
        r = ai_intent_client.post("/api/ai/intent/test", json={"message": "测试"})
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert "意图识别失败" in body["message"]


# ---------------------------------------------------------------------------
# GET /api/intent/health
# ---------------------------------------------------------------------------


def test_intent_health_ok(ai_intent_client: TestClient) -> None:
    with patch(
        "app.application.facades.intent_facade.BertIntentClassifier"
    ) as mock_cls:
        mock_cls.return_value.is_available.return_value = True
        r = ai_intent_client.get("/api/intent/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_available"] is True


def test_intent_health_with_model_path_env(
    ai_intent_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INTENT_MODEL_PATH", "/tmp/fake-model")
    with patch(
        "app.application.facades.intent_facade.BertIntentClassifier"
    ) as mock_cls:
        mock_cls.return_value.is_available.return_value = False
        r = ai_intent_client.get("/api/intent/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["model_available"] is False
    # 应该用 model_path 调用
    mock_cls.assert_called_once_with(model_path="/tmp/fake-model")


def test_intent_health_recoverable_error_returns_500(
    ai_intent_client: TestClient,
) -> None:
    with patch(
        "app.application.facades.intent_facade.BertIntentClassifier",
        side_effect=RuntimeError("model load failed"),
    ):
        r = ai_intent_client.get("/api/intent/health")
    assert r.status_code == 500
    body = r.json()
    assert body["status"] == "error"
    assert body["model_available"] is False


# ---------------------------------------------------------------------------
# POST /api/intent-packages
# ---------------------------------------------------------------------------


def test_intent_packages_post_updates_known(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post(
        "/api/intent-packages",
        json={"packages": {"base": False, "industry": False, "unknown_pkg": True}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "已更新" in body["message"]
    # 已知的 base/industry 应被更新
    assert body["data"]["packages"]["base"] is False
    assert body["data"]["packages"]["industry"] is False
    # 未知的 unknown_pkg 不应出现在 state 中
    assert "unknown_pkg" not in body["data"]["packages"]


def test_intent_packages_post_empty_body(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post("/api/intent-packages", json={})
    assert r.status_code == 200
    assert r.json()["success"] is True


def test_intent_packages_post_no_packages_key(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post(
        "/api/intent-packages", json={"other": "value"}
    )
    assert r.status_code == 200
    assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# PUT /api/intent-packages/{package_id}
# ---------------------------------------------------------------------------


def test_intent_packages_put_unknown_returns_404(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.put(
        "/api/intent-packages/nonexistent", json={"enabled": True}
    )
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert "未知的意图包" in body["error"]


def test_intent_packages_put_known_with_enabled(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.put(
        "/api/intent-packages/base", json={"enabled": False}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["package_id"] == "base"
    assert body["data"]["enabled"] is False


def test_intent_packages_put_known_without_enabled_key(
    ai_intent_client: TestClient,
) -> None:
    """body 不含 enabled → 不更新,返回当前状态。"""
    # 先确保 base 是 True
    ai_intent_client.put("/api/intent-packages/base", json={"enabled": True})
    r = ai_intent_client.put(
        "/api/intent-packages/base", json={"other": "value"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    # enabled 仍为 True
    assert body["data"]["enabled"] is True


def test_intent_packages_put_empty_body(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.put("/api/intent-packages/base", json={})
    assert r.status_code == 200
    assert r.json()["success"] is True


# ---------------------------------------------------------------------------
# POST /api/intent/predict
# ---------------------------------------------------------------------------


def test_intent_predict_empty_text_returns_400(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post("/api/intent/predict", json={"text": ""})
    assert r.status_code == 400
    assert r.json()["error"] == "text is required"


def test_intent_predict_missing_text_returns_400(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post("/api/intent/predict", json={})
    assert r.status_code == 400


def test_intent_predict_success(ai_intent_client: TestClient) -> None:
    with patch(
        "app.application.facades.intent_facade.BertIntentClassifier"
    ) as mock_cls:
        mock_cls.return_value.predict.return_value = {
            "text": "你好",
            "intent": "greeting",
            "confidence": 0.95,
        }
        r = ai_intent_client.post(
            "/api/intent/predict", json={"text": "你好"}
        )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "greeting"
    mock_cls.return_value.predict.assert_called_once_with("你好", return_probs=True)


def test_intent_predict_with_model_path_env(
    ai_intent_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INTENT_MODEL_PATH", "/tmp/model")
    with patch(
        "app.application.facades.intent_facade.BertIntentClassifier"
    ) as mock_cls:
        mock_cls.return_value.predict.return_value = {"intent": "x"}
        r = ai_intent_client.post(
            "/api/intent/predict", json={"text": "hi"}
        )
    assert r.status_code == 200
    mock_cls.assert_called_once_with(model_path="/tmp/model")


def test_intent_predict_recoverable_error_returns_500(
    ai_intent_client: TestClient,
) -> None:
    with patch(
        "app.application.facades.intent_facade.BertIntentClassifier",
        side_effect=RuntimeError("model down"),
    ):
        r = ai_intent_client.post(
            "/api/intent/predict", json={"text": "hi"}
        )
    assert r.status_code == 500
    assert "model down" in r.json()["error"]


# ---------------------------------------------------------------------------
# POST /api/intent/predict_batch
# ---------------------------------------------------------------------------


def test_intent_predict_batch_empty_returns_400(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post(
        "/api/intent/predict_batch", json={"texts": []}
    )
    assert r.status_code == 400
    assert r.json()["error"] == "texts is required"


def test_intent_predict_batch_missing_returns_400(ai_intent_client: TestClient) -> None:
    r = ai_intent_client.post("/api/intent/predict_batch", json={})
    assert r.status_code == 400


def test_intent_predict_batch_success(ai_intent_client: TestClient) -> None:
    with patch(
        "app.application.facades.intent_facade.BertIntentClassifier"
    ) as mock_cls:
        mock_cls.return_value.predict_batch.return_value = [
            {"text": "a", "intent": "x"},
            {"text": "b", "intent": "y"},
        ]
        r = ai_intent_client.post(
            "/api/intent/predict_batch", json={"texts": ["a", "b"]}
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 2
    mock_cls.return_value.predict_batch.assert_called_once_with(
        ["a", "b"], return_probs=True
    )


def test_intent_predict_batch_recoverable_error_returns_500(
    ai_intent_client: TestClient,
) -> None:
    with patch(
        "app.application.facades.intent_facade.BertIntentClassifier",
        side_effect=ValueError("batch failed"),
    ):
        r = ai_intent_client.post(
            "/api/intent/predict_batch", json={"texts": ["a"]}
        )
    assert r.status_code == 500
    assert "batch failed" in r.json()["error"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
