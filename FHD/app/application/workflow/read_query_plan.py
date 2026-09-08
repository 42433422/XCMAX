"""Deterministic customer reads shared by the workflow fallback.

Only explicit read requests qualify. Customer mentions in orders and writes must
remain with their own planner instead of being downgraded to a customer lookup.
"""

from __future__ import annotations

import re
from typing import Any

from app.application.workflow.types import WorkflowNode


def customer_read_node(
    message: str, route: dict[str, Any], registry: dict[str, Any]
) -> WorkflowNode | None:
    if route.get("intent") != "customers_query" or "customers" not in registry:
        return None
    if re.search(
        r"新增|添加|新建|创建|修改|更新|删除|移除|写入|订单|报价|发货|收款|开票|库存|产品|商品",
        message,
    ):
        return None
    text = message.strip().rstrip("。？！?!")
    listing = re.fullmatch(
        r"(?:请|帮我)?(?:查询|查一下|查看|看看|看下)?\s*(?:全部|所有)?\s*(?:客户|购买单位|买家)(?:列表|清单|有哪些|都有谁)",
        text,
    )
    if listing:
        keyword = ""
    else:
        match = re.fullmatch(
            r"(?:请|帮我)?\s*(?:查询|查一下|查看|看看|看下|搜索|查下|找下)\s*(?:客户|购买单位|买家)\s*[:：]?\s*(.+?)(?:\s*的?(?:信息|资料|详情))?",
            text,
        )
        if not match:
            return None
        keyword = match.group(1).strip().strip('「」“”"')
        if not keyword:
            return None
    return WorkflowNode(
        node_id="query_customers",
        tool_id="customers",
        action="query",
        params={"keyword": keyword},
        risk="low",
        idempotent=True,
        description="查询客户信息",
    )
