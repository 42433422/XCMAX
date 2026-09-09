"""Route sales-order list/lookup requests to the sales query tool.

「销售订单列表 / 查一下订单」 previously fell through to the terminal
``products.query`` catch-all — a cross-domain misroute because the request
targets sales orders, not the product catalog. Creation phrasings
(「下订单」「新建」) stay with ``sales_order_nodes`` and are excluded here.
"""

import re

from .types import WorkflowNode

_QUERY_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看下|看看|列出)?\s*"
    r"(?:这个月|本月|上个月|上月|最近)?(?:的)?\s*"
    r"(?:销售订单|销售单|订单)(?:列表|清单)?(?:有哪些|都有哪些|有什么|明细)?[。？?\s]*$"
)
# 否定/复合指令单独排除；建单句（「给客户X下订单…」）整体不匹配锚定正则，无需在此拦截。
_NEGATION_WORDS = ("不要", "别", "不用", "取消", "删除", "清空", "然后", "并且")


def sales_order_query_node(message: str) -> WorkflowNode | None:
    text = str(message or "").strip()
    if not _QUERY_RE.match(text):
        return None
    if any(word in text for word in _NEGATION_WORDS):
        return None
    return WorkflowNode(
        node_id="query_sales_orders",
        tool_id="sales",
        action="query",
        params={"page": 1, "per_page": 20},
        risk="low",
        idempotent=True,
        description="查询销售订单列表",
    )
