"""多轮续跑：选项字母解析、跨轮恢复与只读动作风险收敛。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.workflow.clarification_lifecycle import (
    option_letter_ordinal,
    resolve_confirmed_target,
)
from app.application.workflow.clarification_selection import (
    build_continuation_message,
    looks_like_continuation_reply,
    select_clarified_target,
)
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


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("A", True),
        ("Ｂ", True),
        ("2", True),
        ("确认", True),
        ("继续", True),
        ("取消", False),
        ("帮我查一下澜宇 2026/9/30 的购货明细", False),
    ],
)
def test_continuation_reply_shape(message: str, expected: bool) -> None:
    assert looks_like_continuation_reply(message) is expected


def test_continuation_message_keeps_prior_question() -> None:
    composed = build_continuation_message("A", "请选择日期范围：A. 当天 B. 整月")
    assert "A" in composed
    assert "请选择日期范围" in composed
    assert "不要再追问" in composed


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
