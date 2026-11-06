"""把订单查询、统计和导出规划到已注册的 sales / reports 工具。

未识别的句子返回 None，交给既有规则。概念、否定和含糊意图不产出销售或报表节点。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.application.workflow.clarification_lifecycle import build_clarify_node
from app.application.workflow.workflow_types import PlanGraph, WorkflowNode

_ORDER_HINTS = ("查", "查询", "统计", "导出", "多少", "数量", "这些")
_RANGE = re.compile(r"(\d{1,2})月(\d{1,2})日到(\d{1,2})月(\d{1,2})日")
_AMOUNT = re.compile(r"(?:超过|大于|高于)\s*(\d+(?:\.\d+)?)")
_REGION = re.compile(r"([\u4e00-\u9fff]{2,8})地区")


def plan_business_turn(
    plan_id: str,
    message: str,
    tool_registry: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> PlanGraph | None:
    text = str(message or "").strip()
    if not text:
        return None
    if any(mark in text for mark in ("什么是", "是什么意思", "怎么理解")) and "订单" in text:
        return _bare(plan_id, "chitchat")
    if any(mark in text for mark in ("不要查", "别查", "不用查", "不要查询")):
        return _bare(plan_id, "refused")
    if "订单" in text and any(mark in text for mark in ("处理一下", "搞定", "弄一下")):
        return _clarify(
            plan_id, "ambiguous", "请说明要查询、统计、导出还是创建，未说明前不会改订单。"
        )
    if any(mark in text for mark in ("创建订单", "新建订单", "下一个订单")):
        return _clarify(
            plan_id,
            "sales_create_incomplete",
            "请提供客户和商品明细（数量、单价）。未提供前不会创建订单。",
        )
    if not ("订单" in text and any(mark in text for mark in _ORDER_HINTS)):
        return None

    today = _today(context)
    filters = _filters(text, context, today)
    if filters.get("start_date") and filters.get("end_date"):
        if str(filters["start_date"]) > str(filters["end_date"]):
            return _clarify(plan_id, "invalid_range", "开始日期晚于结束日期，未执行查询。")
    if "这些" in text and not filters:
        return _clarify(plan_id, "missing_scope", "请先说明要导出的订单范围，未说明前不会导出。")

    wants_query = any(mark in text for mark in ("查", "查询", "多少", "数量"))
    wants_export = "导出" in text
    wants_summary = "统计" in text or "总金额" in text
    parallel = all(mark in text for mark in ("订单", "客户", "库存")) and any(
        mark in text for mark in ("同时", "并行")
    )
    if parallel:
        return _parallel(plan_id, tool_registry, filters)
    nodes = _order_nodes(
        tool_registry, filters, query=wants_query, export=wants_export, summary=wants_summary
    )
    if nodes is None:
        return _clarify(plan_id, "tool_unavailable", "销售查询或报表工具当前不可用，未执行。")
    return PlanGraph(
        plan_id=plan_id,
        intent="sales_order_read",
        nodes=nodes,
        risk_level="low",
        metadata={"tool_turn_filters": filters},
    )


def _bare(plan_id: str, intent: str) -> PlanGraph:
    return PlanGraph(plan_id=plan_id, intent=intent, nodes=[], risk_level="low")


def _clarify(plan_id: str, intent: str, question: str) -> PlanGraph:
    return PlanGraph(
        plan_id=plan_id,
        intent=intent,
        nodes=[build_clarify_node(question, {"node_id": "clarify_business"})],
        risk_level="low",
    )


def _today(context: dict[str, Any] | None) -> date:
    raw = str((context or {}).get("today") or "").strip()
    if raw:
        return date.fromisoformat(raw[:10])
    return date.today()


def _filters(text: str, context: dict[str, Any] | None, today: date) -> dict[str, Any]:
    filters = dict((context or {}).get("tool_turn_filters") or {})
    if "今天" in text or "今日" in text:
        filters["start_date"] = today.isoformat()
        filters["end_date"] = today.isoformat()
    found = _RANGE.search(text)
    rest = text
    if found:
        year = today.year
        filters["start_date"] = _day(year, found.group(1), found.group(2))
        filters["end_date"] = _day(year, found.group(3), found.group(4))
        rest = text[found.end() :]
    if "未付款" in text:
        filters["payment_state"] = "unpaid"
    elif "已付款" in text:
        filters["payment_state"] = "paid"
    amount = _AMOUNT.search(text)
    if amount:
        filters["min_amount_exclusive"] = float(amount.group(1))
    region = _REGION.search(rest)
    if region:
        filters["region"] = region.group(1)
    return filters


def _day(year: int, month: str, day: str) -> str:
    return datetime(year, int(month), int(day)).date().isoformat()


def _ready(registry: dict[str, Any], tool_id: str, action: str) -> bool:
    return action in ((registry.get(tool_id) or {}).get("actions") or {})


def _read(
    node_id: str, tool_id: str, action: str, params: dict[str, Any], description: str
) -> WorkflowNode:
    return WorkflowNode(
        node_id=node_id,
        tool_id=tool_id,
        action=action,
        params=params,
        risk="low",
        idempotent=True,
        description=description,
    )


def _parallel(plan_id: str, registry: dict[str, Any], filters: dict[str, Any]) -> PlanGraph | None:
    needed = (
        ("sales", "query"),
        ("customers", "query"),
        ("inventory", "query_transactions"),
    )
    if any(not _ready(registry, tool_id, action) for tool_id, action in needed):
        return _clarify(plan_id, "tool_unavailable", "订单、客户或库存流水工具当前不可用，未执行。")
    nodes = [
        _read("query_orders", "sales", "query", {**filters, "per_page": 100}, "查询订单"),
        _read("query_customers", "customers", "query", {}, "查询客户"),
        _read("query_inventory", "inventory", "query_transactions", {}, "查询库存流水"),
    ]
    return PlanGraph(
        plan_id=plan_id,
        intent="parallel_reads",
        nodes=nodes,
        risk_level="low",
        metadata={"tool_turn_filters": filters},
    )


def _order_nodes(
    registry: dict[str, Any],
    filters: dict[str, Any],
    *,
    query: bool,
    export: bool,
    summary: bool,
) -> list[WorkflowNode] | None:
    nodes: list[WorkflowNode] = []
    if query:
        if not _ready(registry, "sales", "query"):
            return None
        nodes.append(
            _read("query_orders", "sales", "query", {**filters, "per_page": 100}, "查询订单")
        )
    if summary:
        if not _ready(registry, "reports", "sales_summary"):
            return None
        nodes.append(
            _read(
                "sales_summary",
                "reports",
                "sales_summary",
                {**filters, "group_by": "customer"},
                "统计订单金额",
            )
        )
    if export:
        if not _ready(registry, "reports", "export"):
            return None
        nodes.append(
            WorkflowNode(
                node_id="export_orders",
                tool_id="reports",
                action="export",
                params={**filters, "report_type": "sales", "group_by": "customer"},
                risk="low",
                idempotent=True,
                description="导出订单报表",
                depends_on=["query_orders"] if query else [],
            )
        )
    if not nodes:
        return None
    return nodes
