"""Route supplier / purchase / shipment-record / finance-report / materials /
settings phrasings.

These everyday queries previously fell through to the terminal ``products.query``
catch-all — a cross-domain misroute. ``domain_query_nodes`` keeps each phrasing
inside its own domain and returns the (intent, todo, nodes) triple so the
fallback planner stays within its size budget.
"""

from __future__ import annotations

import re
from typing import Any

from .types import WorkflowNode

_NEGATION_WORDS = ("不要", "别", "不用", "取消", "删除", "清空", "然后", "并且")

# 物料/原材料目录查询：「物料列表 / 原材料有哪些 / 查一下物料 树脂」。
_MATERIALS_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看下|看看|列出)?\s*"
    r"(?:物料|原材料|材料)(?:列表|清单|目录)?(?:有哪些|都有哪些|有什么)?(?:\s+\S+)?[。？?\s]*$"
)
# 系统设置：「系统设置 / 查看公司信息」。
_SETTINGS_RE = re.compile(
    r"^(?:请|帮我)?(?:打开|进入|查看|查询|看下|看看)?\s*"
    r"(?:系统设置|设置|公司信息|公司资料)(?:页面)?[。？?\s]*$"
)
# 采购汇总报表：「采购汇总 / 采购报表 / 采购统计」。
_PURCHASE_SUMMARY_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|生成|看下|看看)?\s*"
    r"(?:采购汇总|采购报表|采购统计|采购明细表)(?:报表)?[。？?\s]*$"
)


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
    if "materials" in tool_registry:
        materials_node = _materials_query_node(text)
        if materials_node is not None:
            return ("materials_query", ["查询物料列表", "返回物料信息"], [materials_node])
    if "settings" in tool_registry:
        settings_node = _settings_query_node(text)
        if settings_node is not None:
            return ("settings_query", ["查看系统设置", "返回设置信息"], [settings_node])
    if "reports" in tool_registry:
        purchase_summary = _purchase_summary_node(text)
        if purchase_summary is not None:
            return ("purchase_summary", ["生成采购汇总报表", "返回汇总结果"], [purchase_summary])
    return None


def _has_negation(text: str) -> bool:
    return any(word in text for word in _NEGATION_WORDS)


def _materials_query_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _MATERIALS_RE.match(stripped):
        return None
    keyword_match = re.search(
        r"(?:物料|原材料|材料)(?:列表|清单|目录)?(?:有哪些|都有哪些|有什么)?\s+(\S+)", stripped
    )
    params: dict[str, Any] = {"page": 1, "per_page": 50}
    if keyword_match:
        params["keyword"] = keyword_match.group(1)
    return WorkflowNode(
        node_id="materials_query",
        tool_id="materials",
        action="list" if not keyword_match else "query",
        params=params,
        risk="low",
        idempotent=True,
        description="查询物料/原材料目录",
    )


def _settings_query_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _SETTINGS_RE.match(stripped):
        return None
    return WorkflowNode(
        node_id="settings_query",
        tool_id="settings",
        action="query",
        params={},
        risk="low",
        idempotent=True,
        description="查看系统设置/公司信息",
    )


def _purchase_summary_node(text: str) -> WorkflowNode | None:
    stripped = text.strip()
    if not stripped or _has_negation(stripped) or not _PURCHASE_SUMMARY_RE.match(stripped):
        return None
    return WorkflowNode(
        node_id="purchase_summary",
        tool_id="reports",
        action="purchase_summary",
        params={},
        risk="low",
        idempotent=True,
        description="生成采购汇总报表",
    )
