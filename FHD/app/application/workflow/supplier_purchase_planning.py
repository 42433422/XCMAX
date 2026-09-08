"""Route supplier and purchase-domain requests to their own tools.

「供应商列表 / 采购订单有哪些 / 开一张采购单」 previously fell through to the
terminal ``products.query`` fallback. These planners keep each phrasing inside
its own domain: supplier queries hit ``suppliers.query_suppliers``, purchase
order queries hit ``purchase.query_orders``, and an under-specified purchase
order creation pauses on a clarification instead of guessing a write.
"""

from __future__ import annotations

import re
import uuid

from .types import WorkflowNode

_SUPPLIER_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看看|看下|列出)?\s*"
    r"(?:所有|全部)?供应商(?:列表|名单|信息|资料)?(?:有哪些|都有哪些|有什么|是什么)?[。？?\s]*$"
)
_PURCHASE_ORDER_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看看|看下|列出)?\s*"
    r"(?:所有|全部)?采购(?:订单|单)(?:列表|记录)?(?:有哪些|都有哪些|有什么|是什么)?[。？?\s]*$"
)
_PURCHASE_CREATE_RE = re.compile(
    r"(?:开|创建|新增|添加|下)\s*(?:一张|一个|一份)?\s*采购(?:订单|单)"
)


def supplier_query_node(message: str) -> WorkflowNode | None:
    """「供应商列表 / 查一下供应商」→ suppliers.query_suppliers。"""
    text = str(message or "").strip()
    if not text or not _SUPPLIER_RE.match(text):
        return None
    return WorkflowNode(
        node_id="query_suppliers",
        tool_id="suppliers",
        action="query_suppliers",
        params={"page": 1, "per_page": 50},
        risk="low",
        idempotent=True,
        description="查询供应商列表",
    )


def purchase_order_query_node(message: str) -> WorkflowNode | None:
    """「采购订单有哪些 / 看下采购单」→ purchase.query_orders。"""
    text = str(message or "").strip()
    if not text or not _PURCHASE_ORDER_RE.match(text):
        return None
    return WorkflowNode(
        node_id="query_purchase_orders",
        tool_id="purchase",
        action="query_orders",
        params={"page": 1, "per_page": 50},
        risk="low",
        idempotent=True,
        description="查询采购订单列表",
    )


def purchase_order_create_nodes(message: str) -> list[WorkflowNode]:
    """「开一张采购单」等缺槽位的采购开单：先反问补齐，不猜测写入。"""
    text = str(message or "").strip()
    if not text or not _PURCHASE_CREATE_RE.search(text):
        return []
    if any(word in text for word in ("不要", "别", "不用", "取消", "删除", "清空")):
        return []
    return [
        WorkflowNode(
            node_id=f"clarify_{uuid.uuid4().hex[:8]}",
            tool_id="clarify",
            action="ask",
            params={
                "question": "请告诉我要向哪个供应商采购、产品（型号）和数量，我再创建采购订单。",
                "answer_key": "confirmed",
                "target_node_id": "",
            },
            risk="low",
            idempotent=True,
            description="反问澄清：采购单信息不足，待用户补充后再继续",
        )
    ]
