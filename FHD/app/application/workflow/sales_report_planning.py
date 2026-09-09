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


def monthly_sales_export_nodes(message: str) -> list[WorkflowNode]:
    text = message.strip().rstrip("。？?")
    for prefix in ("请导出", "帮我导出", "导出"):
        if text.startswith(prefix):
            report = monthly_sales_report_node(text[len(prefix) :].strip())
            if report is None and text[len(prefix) :].strip() in {"销售报表", "销售汇总"}:
                report = WorkflowNode(
                    node_id="sales_report",
                    tool_id="reports",
                    action="sales_summary",
                    params={"group_by": "product"},
                    risk="low",
                    idempotent=True,
                    description="按产品汇总销售，等待确认日期范围",
                )
            if report is None:
                return []
            return [
                report,
                WorkflowNode(
                    node_id="sales_report_export",
                    tool_id="reports",
                    action="export",
                    params={
                        "report_type": "sales",
                        "filename": "销售汇总",
                        "data_node_id": report.node_id,
                    },
                    depends_on=[report.node_id],
                    risk="low",
                    idempotent=True,
                    description="将销售查询结果导出为 Excel",
                ),
            ]
    return []
