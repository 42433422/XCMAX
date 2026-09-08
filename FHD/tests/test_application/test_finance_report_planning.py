"""Unit tests for finance report/aging routing planners."""

from app.application.workflow.finance_report_planning import (
    finance_aging_node,
    finance_profit_node,
)


def test_receivable_query():
    node = finance_aging_node("查一下应收账款")
    assert node is not None
    assert node.tool_id == "finance"
    assert node.action == "aging_report"
    assert node.params["account_type"] == "receivable"


def test_customer_debt_query():
    node = finance_aging_node("客户欠款多少")
    assert node is not None
    assert node.params["account_type"] == "receivable"


def test_payable_query():
    node = finance_aging_node("看下应付账款")
    assert node is not None
    assert node.params["account_type"] == "payable"


def test_aging_rejects_unrelated():
    assert finance_aging_node("客户列表") is None
    assert finance_aging_node("产品 A100") is None


def test_profit_report():
    node = finance_profit_node("做个利润表")
    assert node is not None
    assert node.tool_id == "finance"
    assert node.action == "ledger_query"
    assert node.params["start_date"]
    assert node.params["end_date"]


def test_gross_margin_query():
    node = finance_profit_node("这个月毛利多少")
    assert node is not None
    assert node.action == "ledger_query"


def test_profit_rejects_unrelated():
    assert finance_profit_node("销售报表") is None
    assert finance_profit_node("不要删除利润表") is None
