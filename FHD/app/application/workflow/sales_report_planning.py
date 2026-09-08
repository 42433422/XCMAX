"""Bound explicit monthly sales reports to calendar dates."""

import calendar
from datetime import date

from .types import WorkflowNode


def monthly_sales_report_node(message: str, *, today: date | None = None) -> WorkflowNode | None:
    text = message.strip().rstrip("。？?")
    for prefix in ("请查询", "帮我查询", "查询", "查看"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if text not in {"本月销售汇总", "这个月销售汇总", "本月销售报表", "这个月的销售汇总"}:
        return None
    current = today or date.today()
    return WorkflowNode(
        node_id="monthly_sales_report",
        tool_id="reports",
        action="sales_summary",
        params={
            "start_date": current.replace(day=1).isoformat(),
            "end_date": current.replace(
                day=calendar.monthrange(current.year, current.month)[1]
            ).isoformat()
            + " 23:59:59.999999",
            "group_by": "product",
        },
        risk="low",
        idempotent=True,
        description="查询本月销售汇总",
    )
