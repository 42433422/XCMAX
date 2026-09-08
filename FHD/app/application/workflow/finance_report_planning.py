"""Route receivable/payable and profit phrasings to finance tools.

「查一下应收账款 / 客户欠款多少 / 做个利润表 / 这个月毛利多少」 previously fell
through to the terminal ``products.query`` fallback. These planners keep them
inside the finance domain: aging reports answer outstanding-balance questions
and a month-bounded ledger query backs profit/毛利 summaries until a dedicated
P&L report exists.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from .types import WorkflowNode

_RECEIVABLE_RE = re.compile(r"应收账款?|应收款|客户欠款|欠款")
_PAYABLE_RE = re.compile(r"应付账款?|应付款|欠供应商")
_PROFIT_RE = re.compile(r"利润表|利润报表|毛利|净利|盈亏")
_QUERY_HINT_RE = re.compile(r"查|看|多少|列表|报表|做|出|来一份|来张")


def _month_bounds(current: date) -> tuple[str, str]:
    first = current.replace(day=1)
    last = current.replace(day=calendar.monthrange(current.year, current.month)[1])
    return first.isoformat(), last.isoformat()


def finance_aging_node(message: str) -> WorkflowNode | None:
    """「查一下应收账款 / 客户欠款多少」→ finance.aging_report(receivable)。"""
    text = str(message or "").strip()
    if not text or not _QUERY_HINT_RE.search(text):
        return None
    if _PAYABLE_RE.search(text):
        account_type = "payable"
        description = "查询应付账款账龄"
    elif _RECEIVABLE_RE.search(text):
        account_type = "receivable"
        description = "查询应收账款账龄"
    else:
        return None
    return WorkflowNode(
        node_id="finance_aging_report",
        tool_id="finance",
        action="aging_report",
        params={"account_type": account_type, "days": 90},
        risk="low",
        idempotent=True,
        description=description,
    )


def finance_profit_node(message: str, *, today: date | None = None) -> WorkflowNode | None:
    """「做个利润表 / 这个月毛利多少」→ 本月收支账本（利润口径的现有最近似工具）。"""
    text = str(message or "").strip()
    if not text or not _PROFIT_RE.search(text):
        return None
    if any(word in text for word in ("不要", "别", "不用", "取消", "删除")):
        return None
    first, last = _month_bounds(today or date.today())
    return WorkflowNode(
        node_id="finance_profit_ledger",
        tool_id="finance",
        action="ledger_query",
        params={"start_date": first, "end_date": last, "page": 1, "per_page": 100},
        risk="low",
        idempotent=True,
        description="查询本月收支流水，用于利润/毛利概览",
    )
