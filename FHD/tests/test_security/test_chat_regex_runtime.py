"""Malformed reports cannot monopolize routing or deterministic planning."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

from app.application.normal_chat_dispatch import route_normal_mode_message


@pytest.mark.parametrize(
    "mode,message",
    [
        ("chat", "打印 " + "A" * 100_000 + "!"),
        ("chat", "9" * 100_000 + "!"),
        ("chat", "甲" * 100_000 + "的!"),
        ("chat", "查询 " + "A-" * 50_000 + "!"),
        ("chat", "型号" + "\t" * 100_000 + "!"),
        ("chat", "打印 " + "9" * 4000 + "桶" + "A" * 4000 + "规格" + "9" * 4000),
        ("planner", "请新增" + "\t" * 100_000 + "!"),
    ],
    ids=["print", "quantity", "unit", "model", "label", "number-style", "planner"],
)
def test_adversarial_routing_completes_in_bounded_process(mode, message):
    script = """
import sys
from unittest.mock import patch
from app.application.normal_chat_dispatch import route_normal_mode_message
from app.application.workflow.planner import LLMWorkflowPlanner
message = sys.stdin.read()
with patch('app.domain.ops_rules.llm_intent_gate.llm_route_message', return_value=None):
    if sys.argv[1] == 'chat':
        assert route_normal_mode_message(message)['intent'] == 'unknown'
    else:
        with patch('app.application.workflow.planner.get_ai_conversation_service'), patch(
            'app.application.workflow.deterministic_planning._route_by_intent_service',
            return_value=None,
        ):
            plan = LLMWorkflowPlanner()._fallback_plan('synthetic-redos', message, {'products': {}})
            assert plan.intent == 'clarify_ask'
"""
    subprocess.run(
        [sys.executable, "-c", script, mode], input=message, text=True, check=True, timeout=10
    )


@pytest.mark.parametrize(
    "message,intent",
    [
        ("查询 --A1", "product_query"),
        ("查询 1-ABC2", "product_query"),
        ("查询 1A2", "unknown"),
        ("查询 1234567A", "unknown"),
        ("查询 A١", "product_query"),
        ("查询 ١A2", "product_query"),
        ("查询 A²9", "unknown"),
        ("一12桶A规格2", "shipment"),
        ("打印---规格1", "shipment"),
    ],
)
def test_model_and_quantity_semantics_are_preserved(message, intent):
    with patch("app.domain.ops_rules.llm_intent_gate.llm_route_message", return_value=None):
        assert route_normal_mode_message(message)["intent"] == intent
