"""Bound explicit monthly sales reports to calendar dates."""

import calendar
from datetime import date

from .types import WorkflowNode

_MONTH_TOKENS = ("本月", "这个月")


def monthly_sales_report_node(message: str, *, today: date | None = None) -> WorkflowNode | None:
    text = message.strip().rstrip("。？?")
    for prefix in ("请查询", "帮我查询", "查询", "查看", "查一下", "看下", "看看"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    # 必须带明确月份限定，否则「销售报表」裸词应留给导出澄清路径处理。
    has_month = False
    for token in _MONTH_TOKENS:
        if text.startswith(token):
            text = text[len(token) :].strip()
            has_month = True
            break
    if not has_month:
        return None
    if text not in {
        "销售汇总",
        "销售报表",
        "销售情况",
        "销售怎么样",
        "销售排名",
        "销售排行",
        "销售额",
        "销售额多少",
        "卖了多少",
        "的销售额",
        "的销售汇总",
        "的销售报表",
        "的销售情况",
        "的销售怎么样",
        "的销售排名",
        "的销售排行",
    }:
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


def sales_report_query_node(message: str) -> WorkflowNode | None:
    """裸「销售报表 / 看下销售」：无月份限定的销售汇总，日期由澄清规则补齐。"""
    text = message.strip().rstrip("。？?")
    for prefix in (
        "请查询",
        "帮我查询",
        "查询",
        "查看",
        "查一下",
        "看下",
        "看看",
        "打开",
        "帮我",
        "请",
    ):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if text not in {"销售报表", "销售汇总", "销售情况", "销售数据", "销售"}:
        return None
    return WorkflowNode(
        node_id="sales_report",
        tool_id="reports",
        action="sales_summary",
        params={"group_by": "product"},
        risk="low",
        idempotent=True,
        description="按产品汇总销售，等待确认日期范围",
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
