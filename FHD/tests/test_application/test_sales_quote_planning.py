"""Regression tests for bare-customer quotation clarification routing."""

from app.application.workflow.sales_quote_planning import explicit_sales_quote_node


def test_bare_customer_quote_asks_for_product():
    node = explicit_sales_quote_node("给星光报价")
    assert node is not None
    assert node.tool_id == "clarify"
    assert node.action == "ask"
    assert "星光" in node.params["question"]


def test_full_unpriced_quote_still_routes_to_sales():
    # 「给X的产品Y报个价」走 sales.quote（无 DB 时 params 可为空，但工具归属不变）。
    node = explicit_sales_quote_node("给星光贸易的产品A100报个价")
    assert node is not None
    assert node.tool_id == "sales"
    assert node.action == "quote"


def test_unrelated_message_returns_none():
    assert explicit_sales_quote_node("客户列表") is None
    assert explicit_sales_quote_node("不要给星光报价") is None
