from datetime import date
from unittest.mock import patch

import pytest

from app.application.workflow.finance_query import monthly_ledger_node
from app.application.workflow.planner import LLMWorkflowPlanner
from app.services.tools_execution.registry import get_workflow_tool_registry


@pytest.mark.parametrize(
    "today,end",
    [
        (date(2024, 2, 10), "2024-02-29"),
        (date(2025, 2, 10), "2025-02-28"),
        (date(2026, 12, 31), "2026-12-31"),
        (date(2027, 1, 1), "2027-01-31"),
    ],
)
def test_month_boundaries(today, end):
    node = monthly_ledger_node("查询这个月的账本", today=today)
    assert node.params["start_date"] == today.replace(day=1).isoformat()
    assert node.params["end_date"] == end
    assert node.idempotent and node.risk == "low"


def test_fallback_uses_ledger_instead_of_products():
    with patch("app.application.workflow.planner.get_ai_conversation_service", return_value=None):
        planner = LLMWorkflowPlanner()
    plan = planner._fallback_plan("p", "查询这个月的账本", get_workflow_tool_registry())
    assert [(n.tool_id, n.action) for n in plan.nodes] == [("finance", "ledger_query")]


def test_compound_instruction_not_silently_dropped():
    assert monthly_ledger_node("查询这个月的账本，然后导出") is None
