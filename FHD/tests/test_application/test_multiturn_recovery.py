"""多轮续跑：选项字母解析、跨轮恢复与只读动作风险收敛。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.ai_chat.workflow_session import WorkflowSession
from app.application.workflow.clarification_lifecycle import (
    option_letter_ordinal,
    resolve_confirmed_target,
)
from app.application.workflow.clarification_selection import select_clarified_target
from app.application.workflow.risk_gate import HybridRiskGate
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

CANDIDATES = [
    {"id": 31, "name": "澜宇电视柜", "model_number": "A100"},
    {"id": 42, "name": "澜宇电视柜", "model_number": "B200"},
]


@pytest.mark.parametrize(
    ("answer", "expected_id"),
    [
        ("A", "31"),
        ("a", "31"),
        ("选A", "31"),
        ("A选项", "31"),
        ("选项 A", "31"),
        ("b", "42"),
        ("Ｂ", "42"),
    ],
)
def test_option_letter_maps_to_candidate_position(answer: str, expected_id: str) -> None:
    assert resolve_confirmed_target(answer, CANDIDATES) == {"id": expected_id}


def test_option_letter_beyond_candidates_is_not_guessed() -> None:
    assert option_letter_ordinal("C") == 3
    assert resolve_confirmed_target("C", CANDIDATES) is None


def test_letter_selection_never_delegates_to_model() -> None:
    extract = Mock(return_value={"id": 31})
    selected = select_clarified_target(
        "A", CANDIDATES, affirmative=False, extract=extract, request={}
    )
    assert selected == {"id": "31"}
    extract.assert_not_called()


def test_no_pending_confirmation_cannot_resume_history_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.application.ai_chat.dialogue_memory.conversation_history_messages",
        lambda *args, **kwargs: [
            {"role": "assistant", "content": "请选择日期范围：A. 当天 B. 整月"}
        ],
    )
    session = WorkflowSession({}, SimpleNamespace())
    handled, reply = session.resume_pending_dynamic_workflow("owner", "确认", "确认", {})
    assert handled is True and reply is not None
    assert (reply.get("data") or {}).get("data", {}).get("reason") == "no_pending_workflow"


def test_no_pending_confirmation_without_question_keeps_explicit_reply() -> None:
    session = WorkflowSession({}, SimpleNamespace())
    handled, reply = session.resume_pending_dynamic_workflow("owner", "确认", "确认", {})
    assert handled is True
    assert reply is not None
    assert (reply.get("data") or {}).get("data", {}).get("reason") == "no_pending_workflow"
    assert "没有待确认的操作" in str(reply.get("response"))


def _plan(tool_id: str, action: str, risk: str) -> PlanGraph:
    return PlanGraph(
        plan_id="plan-multiturn",
        intent="multiturn",
        nodes=[WorkflowNode(node_id="step", tool_id=tool_id, action=action, risk=risk)],
        risk_level=risk,
    )


def test_read_only_action_ignores_planner_inflated_risk() -> None:
    decision = HybridRiskGate().evaluate(_plan("excel_analysis", "query", "high"), {})
    assert decision.allowed is True
    assert decision.requires_confirmation is False
    assert decision.risk_level.value == "low"


def test_write_action_keeps_high_risk_confirmation() -> None:
    decision = HybridRiskGate().evaluate(_plan("products", "delete", "high"), {})
    assert decision.requires_confirmation is True


@pytest.mark.parametrize(
    ("registry_risk", "allow_auto_execute"), [("high", False), ("blocked", True), ("low", False)]
)
def test_read_only_flag_preserves_the_registry_admission_floor(
    monkeypatch, registry_risk, allow_auto_execute
) -> None:
    from app.application.workflow import risk_gate
    from app.domain.autonomy.autonomy_guard import AutonomyGuard

    guard = AutonomyGuard(audit_sink=lambda record: record)
    guard.register_actions(
        "guarded_read",
        actions={
            "query": {
                "risk": registry_risk,
                "read_only": True,
                "allow_auto_execute": allow_auto_execute,
            }
        },
    )
    monkeypatch.setattr(risk_gate, "get_autonomy_guard", lambda: guard)
    monkeypatch.setattr(risk_gate, "evaluate_risk", guard.evaluate)
    decision = HybridRiskGate().evaluate(_plan("guarded_read", "query", "low"), {})
    assert decision.risk_level.value == registry_risk
    assert decision.allowed is False
    assert decision.requires_confirmation is (registry_risk != "blocked")


@pytest.mark.parametrize("intervening_user", [False, True])
def test_last_question_never_crosses_a_new_user_request(monkeypatch, intervening_user):
    from app.application.ai_chat import dialogue_memory

    question = "请选择：A. 查询客户 B. 查询产品"
    history = [{"role": "assistant", "content": question}]
    if intervening_user:
        history.append({"role": "user", "content": "换一个任务，帮我查库存"})
    monkeypatch.setattr(dialogue_memory, "conversation_history_messages", lambda _: history)
    assert dialogue_memory.last_assistant_question({}) == (None if intervening_user else question)


def test_compact_schema_preserves_composed_and_nested_constraints():
    from app.application.workflow.planner_prompt_profile import _slim_schema

    schema = {
        "type": "object",
        "anyOf": [{"required": ["customer_id"]}, {"required": ["customer_name"]}],
        "additionalProperties": False,
        "properties": {
            "customer_id": {"type": "integer", "minimum": 1},
            "customer_name": {"type": "string", "minLength": 1, "description": "说明" * 80},
            "items": {"type": "array", "items": {"allOf": [{"$ref": "#/$defs/item"}]}},
        },
        "$defs": {"item": {"type": "object", "required": ["sku"]}},
    }
    compact = _slim_schema(schema)
    assert compact["anyOf"] == schema["anyOf"]
    assert compact["$defs"] == schema["$defs"]
    assert compact["additionalProperties"] is False
    assert compact["properties"]["items"] == schema["properties"]["items"]
    assert compact["properties"]["customer_id"] == schema["properties"]["customer_id"]
    assert compact["properties"]["customer_name"]["minLength"] == 1
    assert len(compact["properties"]["customer_name"]["description"]) == 80
    assert len(schema["properties"]["customer_name"]["description"]) == 160
