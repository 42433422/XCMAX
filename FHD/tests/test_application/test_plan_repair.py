"""计划修复闭环：错误分类、最小修改约束与规划器接线。"""

from __future__ import annotations

import copy
import json
from unittest.mock import Mock

import pytest

from app.application.workflow.llm_plan_generation import (
    _decode_completion,
    _load_model_json,
    build_plan_from_payload,
)
from app.application.workflow.plan_repair import (
    classify_plan_error,
    enforce_repair_scope,
    repair_plan,
)
from app.application.workflow.planner import LLMWorkflowPlanner
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode
from tests.fixtures.planner_model import goal_review_response


def _node(
    node_id: str,
    *,
    tool_id: str = "products",
    action: str = "query",
    params: dict | None = None,
    risk: str = "low",
) -> WorkflowNode:
    return WorkflowNode(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        params=params if params is not None else {},
        risk=risk,
        idempotent=True,
    )


def _plan(*nodes: WorkflowNode) -> PlanGraph:
    return PlanGraph(plan_id="p1", intent="demo", nodes=list(nodes), metadata={})


def _completion(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


def test_classify_plan_error_maps_known_failures() -> None:
    assert classify_plan_error("节点 n1 使用未授权动作: products.delete") == "unauthorized_action"
    assert classify_plan_error("节点 n1 缺少 required_params: keyword") == "missing_param"
    assert classify_plan_error("节点 n1 参数预检失败：引用不存在") == "bad_reference"
    assert classify_plan_error("计划图存在成环") == "graph_cycle"
    assert classify_plan_error("某种未知错误") == "graph_invalid"


def test_repair_plan_fixes_missing_param() -> None:
    planned = _plan(_node("n1"))
    calls: list[dict] = []

    def validate(plan: PlanGraph) -> str | None:
        if not plan.nodes[0].params.get("keyword"):
            return "节点 n1 缺少 required_params: keyword"
        return None

    def complete(**kwargs):
        calls.append(kwargs)
        return _completion(
            {
                "mode": "workflow",
                "intent": "demo",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "products",
                        "action": "query",
                        "params": {"keyword": "木门"},
                    }
                ],
            }
        )

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="查木门",
        context={},
        tool_registry={},
        validate=validate,
        complete=complete,
    )

    assert fixed is not None
    assert fixed.nodes[0].params["keyword"] == "木门"
    assert trace["fixed"] is True
    assert trace["attempts"] == 1
    assert trace["first_pass_valid"] is False
    assert len(calls) == 1
    assert calls[0]["temperature"] == 0.0


def test_repair_rejects_changes_to_unmentioned_nodes() -> None:
    planned = _plan(
        _node("n1"),
        _node("n2", action="export", params={"keyword": "a"}),
    )

    def validate(plan: PlanGraph) -> str | None:
        return "节点 n1 缺少 required_params: keyword"

    def complete(**kwargs):
        return _completion(
            {
                "mode": "workflow",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "products",
                        "action": "query",
                        "params": {"keyword": "木门"},
                    },
                    {
                        "node_id": "n2",
                        "tool_id": "products",
                        "action": "export",
                        "params": {"keyword": "被篡改"},
                    },
                ],
            }
        )

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="查木门并导出",
        context={},
        tool_registry={},
        validate=validate,
        complete=complete,
    )

    assert fixed is None
    assert any(item["code"] == "scope_violation" for item in trace["errors"])
    assert "未报错" in trace["errors"][-1]["message"]


def test_repair_rejects_risk_downgrade() -> None:
    planned = _plan(_node("n1", risk="high"))

    def validate(plan: PlanGraph) -> str | None:
        return "节点 n1 使用未授权动作: products.delete"

    def complete(**kwargs):
        return _completion(
            {
                "mode": "workflow",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "products",
                        "action": "delete",
                        "params": {},
                        "risk": "low",
                    }
                ],
            }
        )

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="删除产品",
        context={},
        tool_registry={},
        validate=validate,
        complete=complete,
    )

    assert fixed is None
    assert any("风险等级" in item["message"] for item in trace["errors"])


def test_non_repairable_shape_skips_model_call() -> None:
    planned = _plan(_node("reply", tool_id="conversation", action="reply"))
    calls: list[dict] = []

    def validate(plan: PlanGraph) -> str | None:
        return "普通回复计划必须是唯一的内部 conversation.reply 节点"

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="你好",
        context={},
        tool_registry={},
        validate=validate,
        complete=lambda **kwargs: calls.append(kwargs),
    )

    assert fixed is None
    assert calls == []
    assert trace["errors"][0]["code"] == "reply_shape"


def test_repair_stops_after_attempt_limit() -> None:
    planned = _plan(_node("n1"))
    calls: list[dict] = []

    def validate(plan: PlanGraph) -> str | None:
        return "节点 n1 缺少 required_params: keyword"

    def complete(**kwargs):
        calls.append(kwargs)
        return _completion(
            {
                "mode": "workflow",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "products",
                        "action": "query",
                        "params": {},
                    }
                ],
            }
        )

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="查木门",
        context={},
        tool_registry={},
        validate=validate,
        complete=complete,
        max_attempts=2,
    )

    assert fixed is None
    assert trace["attempts"] == 2
    assert len(calls) == 2


def test_enforce_scope_allows_fixing_mentioned_node() -> None:
    original = _plan(_node("n1"))
    candidate = _plan(_node("n1", params={"keyword": "门"}))
    assert (
        enforce_repair_scope(original, candidate, "节点 n1 缺少 required_params: keyword") is None
    )


def test_model_json_falls_back_to_repair() -> None:
    parsed = _load_model_json('{"mode":"workflow","nodes":[{"node_id":"n1",}]}')
    assert parsed["nodes"][0]["node_id"] == "n1"


def test_planner_records_repair_trace(monkeypatch) -> None:
    ai = Mock()
    ai.get_context.return_value = None
    planner = LLMWorkflowPlanner(
        ai_service=ai,
        completion=lambda **kwargs: goal_review_response(
            json.loads(kwargs["messages"][1]["content"]),
            source="解释木门",
            node_ids=["reply"],
            outcome="reply",
        ),
    )
    reply_node = _node("reply", tool_id="conversation", action="reply", params={"response": "ok"})
    broken = _plan(reply_node)
    broken.metadata = {"response_mode": "reply", "reply": "ok"}
    fixed = _plan(reply_node)
    fixed.metadata = {"response_mode": "reply", "reply": "ok"}

    monkeypatch.setattr(planner, "_plan_with_llm", lambda *args, **kwargs: broken)
    from app.infrastructure.llm import model_admission

    previous_identity = model_admission._MODEL_IDENTITY.get()

    def repaired(**kwargs):
        assert model_admission._MODEL_IDENTITY.get() == "tenant:t:actor:7"
        return fixed, {"attempts": 1, "errors": [], "fixed": True, "first_pass_valid": False}

    monkeypatch.setattr("app.application.workflow.plan_repair.repair_plan", repaired)
    monkeypatch.setattr(
        "app.application.workflow.planner.validate_plan_graph", lambda plan: None, raising=False
    )

    result = planner.plan(
        "7", "解释木门", {}, context={"session_id": "s1", "local_user_id": "7", "tenant_id": "t"}
    )
    assert model_admission._MODEL_IDENTITY.get() == previous_identity

    assert result is fixed
    assert result.metadata["plan_repair"]["fixed"] is True
    assert result.metadata["plan_repair"]["attempts"] == 1


@pytest.mark.parametrize("risk", ["low", "medium", "high"])
def test_enforce_scope_never_raises_on_same_plan(risk: str) -> None:
    original = _plan(_node("n1", risk=risk))
    assert enforce_repair_scope(original, _plan(_node("n1", risk=risk)), "") is None


@pytest.mark.parametrize(
    "error, field, value",
    [
        ("节点 n1 缺少参数", "idempotent", False),
        ("节点 n1 缺少参数", "description", "changed"),
        ("无法定位的图错误", "params", {"keyword": "changed"}),
        ("节点 n1 参数值包含 节点 n2", "params", {"keyword": "changed"}),
    ],
)
def test_scope_preserves_every_unreported_field(error, field, value):
    original = _plan(_node("n1"), _node("n2"))
    candidate = copy.deepcopy(original)
    setattr(candidate.nodes[1], field, value)
    assert enforce_repair_scope(original, candidate, error) is not None


@pytest.mark.parametrize("node_id", ["n1", "中文节点", "n.1", "n-1"])
def test_scope_supports_real_node_ids(node_id):
    original = _plan(_node(node_id))
    candidate = _plan(_node(node_id, params={"keyword": "门"}))
    assert enforce_repair_scope(original, candidate, f"节点 {node_id} 缺少参数") is None


def test_scope_preserves_clarification_and_plan_risk():
    original = _plan(_node("n1", tool_id="clarify", action="ask"))
    assert enforce_repair_scope(original, _plan(_node("n1")), "节点 n1 缺少参数")
    candidate = copy.deepcopy(original)
    original.risk_level = "high"
    assert enforce_repair_scope(original, candidate, "节点 n1 缺少参数")


def test_repair_prompt_redacts_authority_and_secrets():
    from app.application.workflow.plan_repair import build_repair_messages

    plan = _plan(_node("n1", params={"tenant_id": "private", "keyword": "门"}))
    plan.metadata = {"api_key": "synthetic-secret", "summary": "safe"}
    messages = build_repair_messages(
        plan=plan,
        error="节点 n1 缺少参数",
        tool_registry={},
        user_message="查门",
        error_code="missing_param",
    )
    payload = json.loads(messages[1]["content"])
    assert payload["original_plan"]["nodes"][0]["params"] == {"keyword": "门"}
    assert "api_key" not in payload["original_plan"]["metadata"]
    assert "synthetic-secret" not in messages[1]["content"]


def test_repair_preserves_provider_failure_reason():
    from app.infrastructure.modstore_transport import MarketModelError

    def fail(**kwargs):
        raise MarketModelError({"status": 402})

    fixed, trace = repair_plan(
        planned=_plan(_node("n1")),
        plan_id="p1",
        message="查门",
        context={},
        tool_registry={},
        validate=lambda plan: "节点 n1 缺少参数",
        complete=fail,
    )
    assert fixed is None
    diagnostic = trace["errors"][-1]
    assert diagnostic["code"] == "repair_request_failed"
    assert diagnostic["message"] == "修茈市场模型余额不足，请在「模型支付」充值后重试。"
    assert diagnostic["error_type"] == "MarketModelError"
    assert diagnostic["error_length"] == len(diagnostic["message"])
    assert len(diagnostic["error_sha256"]) == 64


@pytest.mark.parametrize("requested, expected", [(999, 3), (0, 0), (-1, 0)])
def test_explicit_repair_attempts_remain_bounded(requested, expected):
    calls = []

    def complete(**kwargs):
        calls.append(kwargs)
        return _completion({"nodes": [{"node_id": "n1", "tool_id": "products", "action": "query"}]})

    fixed, trace = repair_plan(
        planned=_plan(_node("n1")),
        plan_id="p1",
        message="查门",
        context={},
        tool_registry={},
        validate=lambda plan: "节点 n1 缺少参数",
        complete=complete,
        max_attempts=requested,
    )
    assert fixed is None
    assert len(calls) == trace["attempts"] == expected


@pytest.mark.parametrize(
    ("tool_id", "action", "expected"),
    [
        ("clarify", "ask", ("clarify", "ask")),
        ("clarify", "ask.ask", ("clarify", "ask")),
        ("clarify.ask", "ask", ("clarify", "ask")),
        ("clarify", "ask.delete", ("clarify", "ask.delete")),
        ("clarify", "ask.ask.extra", ("clarify", "ask.ask.extra")),
        ("clarify.ask.other", "ask", ("clarify.ask.other", "ask")),
    ],
)
def test_exact_clarify_aliases_are_normalized_only_at_plan_build(tool_id, action, expected):
    from app.application.workflow.planning_graph_policy import validate_required_params

    response = _completion(
        {
            "mode": "workflow",
            "nodes": [
                {
                    "node_id": "n1",
                    "tool_id": tool_id,
                    "action": action,
                    "params": {"question": "请确认业务对象"},
                    "depends_on": ["source"],
                }
            ],
        }
    )
    decoded = _decode_completion(response)
    assert decoded is not None
    parsed, nodes = decoded
    first = build_plan_from_payload(
        plan_id="p1", message="请确认", parsed=parsed, nodes=nodes, context={}
    )
    node = first.nodes[0]
    assert (node.tool_id, node.action) == expected
    assert node.node_id == "n1" and node.depends_on == ["source"]
    assert node.params == {"question": "请确认业务对象"}
    if (tool_id, action) != expected:
        assert first.metadata["normalized_actions"] == [
            {"node_id": "n1", "tool_id": tool_id, "action": action}
        ]
    else:
        assert "normalized_actions" not in first.metadata
    second = build_plan_from_payload(
        plan_id="p1", message="请确认", parsed=parsed, nodes=nodes, context={}
    )
    assert (second.nodes[0].tool_id, second.nodes[0].action) == expected
    if expected == ("clarify", "ask"):
        assert validate_required_params(first, {}) is None
    else:
        assert validate_required_params(first, {}) is not None


def test_repair_uses_same_exact_clarify_alias_normalization():
    planned = _plan(_node("n1", tool_id="clarify", action="ask.invalid"))

    def validate(plan):
        return (
            None
            if (plan.nodes[0].tool_id, plan.nodes[0].action) == ("clarify", "ask")
            else "节点 n1 使用未授权动作: clarify.ask.invalid"
        )

    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="请确认",
        context={},
        tool_registry={},
        validate=validate,
        complete=lambda **_: _completion(
            {
                "mode": "workflow",
                "nodes": [
                    {
                        "node_id": "n1",
                        "tool_id": "clarify.ask",
                        "action": "ask",
                        "params": {"question": "请确认业务对象"},
                    }
                ],
            }
        ),
        max_attempts=1,
    )
    assert fixed is not None and (fixed.nodes[0].tool_id, fixed.nodes[0].action) == (
        "clarify",
        "ask",
    )
    assert trace["attempts"] == 1 and trace["fixed"] is True


@pytest.mark.parametrize(
    ("content", "reason"),
    [('{"mode":"workflow","nodes":[]}', "schema_invalid"), ("\ud800", "invalid_json")],
)
def test_failed_repair_preserves_initial_error_and_response_diagnostic(content, reason):
    planned = _plan(_node("node_1", tool_id="clarify", action="ask.invalid"))
    fixed, trace = repair_plan(
        planned=planned,
        plan_id="p1",
        message="处理业务",
        context={},
        tool_registry={},
        validate=lambda _: "节点 node_1 使用未授权动作: clarify.ask.invalid",
        complete=lambda **_: {"choices": [{"message": {"content": content}}]},
        max_attempts=1,
    )
    assert fixed is None and trace["attempts"] == 1
    assert trace["initial_error"] == "节点 node_1 使用未授权动作: clarify.ask.invalid"
    assert trace["invalid_node_actions"] == [
        {"node_id": "node_1", "tool_id": "clarify", "action": "ask.invalid"}
    ]
    assert trace["errors"][0]["code"] == "unauthorized_action"
    diagnostic = trace["errors"][-1]
    assert diagnostic["code"] == "unparsable_repair"
    assert diagnostic["reason"] == reason
    assert diagnostic["response_length"] == len(content)
    assert len(diagnostic["response_sha256"]) == 64


def test_planner_repair_failure_is_not_mislabeled_model_unavailable(monkeypatch):
    planner = LLMWorkflowPlanner(
        ai_service=Mock(),
        completion=lambda **_: _completion({"mode": "workflow", "nodes": []}),
    )
    monkeypatch.setattr(
        planner,
        "_plan_with_llm",
        lambda *_: _plan(_node("node_1", tool_id="clarify", action="ask.invalid")),
    )
    result = planner.plan("owner", "处理业务", {}, context={"session_id": "s1"})
    assert result.metadata["planning_rejected"] is True
    assert result.metadata["planning_unavailable"] is False
    assert result.metadata["planning_failure_kind"] == "plan_repair_failed"
    trace = result.metadata["plan_repair"]
    assert trace["attempts"] >= 1
    assert trace["errors"][0]["code"] == "unauthorized_action"
    assert trace["errors"][-1]["code"] == "unparsable_repair"


def test_failed_repair_trace_redacts_validator_and_provider_secrets(caplog):
    secret = "sk-private-repair-credential"
    email = "private.person@example.com"
    private_detail = "客户内部报价为四百元"

    def fail(**kwargs):
        raise RuntimeError(f"upstream api_key={secret} contact={email}; {private_detail}")

    fixed, trace = repair_plan(
        planned=_plan(_node("n1")),
        plan_id="p1",
        message="查门",
        context={},
        tool_registry={},
        validate=lambda _: f"节点 n1 参数预检失败：api_key={secret} contact={email}",
        complete=fail,
    )
    assert fixed is None and trace["attempts"] == 1
    assert trace["errors"][-1]["code"] == "repair_request_failed"
    assert trace["errors"][-1]["error_type"] == "RuntimeError"
    assert len(trace["errors"][-1]["error_sha256"]) == 64
    exported = json.dumps(trace, ensure_ascii=False) + caplog.text
    assert secret not in exported and email not in exported
    assert private_detail not in exported


def test_failed_repair_trace_bounds_scope_error():
    fixed, trace = repair_plan(
        planned=_plan(_node("n1")),
        plan_id="p1",
        message="查门",
        context={},
        tool_registry={},
        validate=lambda _: "节点 n1 缺少参数",
        complete=lambda **_: _completion(
            {
                "nodes": [
                    {"node_id": node_id, "tool_id": "products", "action": "query"}
                    for node_id in ("n1", "extra-" + "x" * 2000)
                ]
            }
        ),
    )
    assert fixed is None and trace["attempts"] == 1
    assert trace["errors"][-1]["code"] == "scope_violation"
    assert len(trace["errors"][-1]["message"]) <= 240


def test_planner_discards_prior_turn_failure_diagnostics(monkeypatch):
    context = {
        "session_id": "s1",
        "planning_failure_reason": "old failure",
        "planning_failure_kind": "plan_repair_failed",
        "plan_repair_trace": {"errors": [{"message": "old secret"}]},
        "goal_coverage_rejected": True,
    }

    def generate(plan_id, user_id, message, registry, current):
        assert {key: value for key, value in current.items() if key != "_planner_model_budget"} == {
            "session_id": "s1"
        }
        current["planning_failure_kind"] = "plan_format_invalid"
        return None

    planner = LLMWorkflowPlanner(ai_service=Mock())
    monkeypatch.setattr(planner, "_plan_with_llm", generate)
    result = planner.plan("owner", "处理业务", {}, context=context)
    assert result.metadata["planning_failure_kind"] == "plan_format_invalid"
    assert "plan_repair" not in result.metadata
    assert "goal_coverage_rejected" not in result.metadata
    assert context["planning_failure_reason"] == "old failure"


@pytest.mark.parametrize("failure_kind", ["balance", "context", "revision"])
def test_replanning_repair_preserves_typed_failure(monkeypatch, failure_kind):
    from app.application.agent_orchestrator.context_window_manager import ContextWindowExceeded
    from app.application.ai_chat.planned_workflow_dispatch import PlannedWorkflowDispatch
    from app.application.facades.tools_facade import get_workflow_tool_registry
    from app.domain.shared_services.conversation_service import ConversationRevisionError
    from app.infrastructure.modstore_transport import MarketModelError

    failure, code, status, public_message = {
        "balance": (MarketModelError({"status": 402}), "model_balance_insufficient", 402, "充值"),
        "context": (
            ContextWindowExceeded("系统指令和工具定义超过模型的上下文预算。"),
            "context_window_exceeded",
            413,
            "上下文预算",
        ),
        "revision": (
            ConversationRevisionError("private-revision-detail"),
            "conversation_changed",
            409,
            "会话已更新或删除",
        ),
    }[failure_kind]
    message = "查询产品 A1"
    node = {
        "node_id": "n1",
        "tool_id": "products",
        "action": "query",
        "params": {"keyword": "A0"},
    }
    completion = Mock(
        side_effect=[
            _completion({"nodes": [node]}),
            _completion(
                {
                    "goals": [
                        {
                            "goal_id": "g1",
                            "source": message,
                            "outcome": "execute",
                            "node_ids": ["n1"],
                        }
                    ],
                    "violations": ["遗漏产品 A1"],
                }
            ),
            _completion({"nodes": [{**node, "action": "query.invalid"}]}),
            failure,
        ]
    )
    planner = LLMWorkflowPlanner(
        ai_service=Mock(get_context=Mock(return_value=None)), completion=completion
    )
    registry = {"products": get_workflow_tool_registry()["products"]}
    monkeypatch.setattr(
        "app.application.facades.tools_facade.get_workflow_tool_registry", lambda: registry
    )
    callbacks, risk_gate, approval = Mock(), Mock(), Mock()
    callbacks._resume_pending_dynamic_workflow.return_value = (False, None)
    result = PlannedWorkflowDispatch({}, callbacks, planner, risk_gate, approval).handle(
        "owner", message, "pro", {"session_id": "s1"}, message
    )
    assert completion.call_count == 4
    assert "coverage_feedback" in json.loads(
        completion.call_args_list[2].kwargs["messages"][1]["content"]
    )
    assert result["data"]["planning_failure_kind"] == code
    assert result["data"]["error_code"] == code
    assert result["data"]["planning_failure_status"] == status
    assert result["data"]["planning_failure_retryable"] is False
    assert result["data"]["planning_failure_stage"] == "repair"
    assert public_message in result["response"]
    assert "private-revision-detail" not in json.dumps(result, ensure_ascii=False)
    assert result["data"]["execution_started"] is False
    risk_gate.evaluate.assert_not_called()
    assert approval.method_calls == []
    callbacks._persist_plan_state.assert_not_called()
