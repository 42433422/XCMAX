"""Offline safety + real rule routing, not online planner/tool acceptance (#1776)."""

import pytest

from app.domain.app_pure.chat_business_safety_core import classify_business_chat_intent
from app.domain.app_pure.intent_recognition_app import recognize_intents


@pytest.mark.parametrize("prefix", ["", "请AI员工帮我", "请AI业务员工帮我"])
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("查询客户订单", "shipments"),
        ("查询库存", "materials"),
        ("查询客户列表", "customers"),
        ("查询产品", "products"),
    ],
)
def test_ai_title_preserves_real_rule_business_route(prefix, query, expected):
    message = prefix + query
    assert classify_business_chat_intent(message) is None
    result = recognize_intents(message)
    assert result["primary_intent"] == expected
    assert result["tool_key"] == expected


@pytest.mark.parametrize("prefix", ["", "请AI员工帮我", "请AI业务员工帮我"])
@pytest.mark.parametrize(
    ("query", "operation", "domain"),
    [
        ("查询员工工号", "personnel_read", "personnel"),
        ("查询今天考勤", "attendance_read", "attendance"),
    ],
)
def test_ai_title_does_not_bypass_personnel_or_attendance_safety(prefix, query, operation, domain):
    intent = classify_business_chat_intent(prefix + query)
    assert intent is not None
    assert (intent.operation, intent.domain) == (operation, domain)


def test_original_inventory_phrase_reaches_real_inventory_rule():
    message = "让AI员工查一下库存"
    assert classify_business_chat_intent(message) is None
    result = recognize_intents(message)
    assert (result["primary_intent"], result["tool_key"]) == ("materials", "materials")


def test_scheduled_benchmark_executes_title_routing_matrix():
    from pathlib import Path

    fhd = Path(__file__).resolve().parents[2]
    for workflow in (
        fhd / ".github/workflows/intent-benchmark.yml",
        fhd.parent / ".github/workflows/fhd-intent-benchmark.yml",
    ):
        assert "tests/benchmarks/test_ai_title_routing.py -v --tb=short" in workflow.read_text()
