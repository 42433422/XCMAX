"""Route supplier / purchase / shipment-record / finance-report phrasings.

These everyday queries previously fell through to the terminal ``products.query``
catch-all — a cross-domain misroute. ``domain_query_nodes`` keeps each phrasing
inside its own domain and returns the (intent, todo, nodes) triple so the
fallback planner stays within its size budget.
"""

from __future__ import annotations

from typing import Any

from .types import WorkflowNode


def domain_query_nodes(
    message: str, tool_registry: dict[str, Any]
) -> tuple[str, list[str], list[WorkflowNode]] | None:
    """First matching domain route for the message, or None to fall through."""
    text = str(message or "")
    if "finance" in tool_registry:
        from .finance_report_planning import finance_aging_node, finance_profit_node

        aging_node = finance_aging_node(text)
        if aging_node is not None:
            return (
                "finance_aging_report",
                ["查询应收/应付账龄", "返回欠款明细", "输出账龄分布"],
                [aging_node],
            )
        profit_node = finance_profit_node(text)
        if profit_node is not None:
            return (
                "finance_profit_report",
                ["查询本月收支流水", "汇总利润/毛利概览", "返回结果"],
                [profit_node],
            )
    if "suppliers" in tool_registry:
        from .supplier_purchase_planning import supplier_query_node

        supplier_node = supplier_query_node(text)
        if supplier_node is not None:
            return ("suppliers_query", ["查询供应商列表", "返回供应商信息"], [supplier_node])
    if "purchase" in tool_registry:
        from .supplier_purchase_planning import (
            purchase_order_create_nodes,
            purchase_order_query_node,
        )

        purchase_query = purchase_order_query_node(text)
        if purchase_query is not None:
            return (
                "purchase_order_query",
                ["查询采购订单列表", "返回采购订单"],
                [purchase_query],
            )
        purchase_create = purchase_order_create_nodes(text)
        if purchase_create:
            return (
                "purchase_order_create",
                ["核对供应商与采购明细", "确认后创建采购订单", "返回创建结果"],
                purchase_create,
            )
    if "shipment_records" in tool_registry:
        from .shipment_records_planning import shipment_records_query_node

        records_node = shipment_records_query_node(text)
        if records_node is not None:
            return ("shipment_records_query", ["查询发货记录", "返回发货明细"], [records_node])
    return None
