"""Resolve explicit calendar-month ledger requests to bounded dates."""

from __future__ import annotations

import calendar
import re
from datetime import date

from .types import WorkflowNode

_LEDGER_RE = re.compile(
    r"^(?:请|帮我)?(?:查询|查看|查一下|看看|打开|看下)?"
    r"(?:这个月|本月)?(?:的)?(?:财务)?(?:账本|总账|账目|流水|账|财务)[。？?\s]*$"
)
_MONTH_MONEY_RE = re.compile(
    r"(?:这个月|本月)[^，,。？?]{0,8}(?:收入|支出|花了|赚了|营业额|营收|回款)"
    r"|(?:收入|支出|营业额|营收|回款)[^，,。？?]{0,6}(?:多少|几多)"
)


def _month_bounds(current: date) -> tuple[str, str]:
    first = current.replace(day=1)
    last = current.replace(day=calendar.monthrange(current.year, current.month)[1])
    return first.isoformat(), last.isoformat()


def _ledger_node(first: str, last: str, description: str) -> WorkflowNode:
    return WorkflowNode(
        node_id="query_monthly_ledger",
        tool_id="finance",
        action="ledger_query",
        params={
            "start_date": first,
            "end_date": last,
            "page": 1,
            "per_page": 20,
        },
        risk="low",
        idempotent=True,
        description=description,
    )


def monthly_ledger_node(message: str, *, today: date | None = None) -> WorkflowNode | None:
    text = str(message or "").strip()
    current = today or date.today()
    if _LEDGER_RE.match(text):
        first, last = _month_bounds(current)
        return _ledger_node(first, last, "查询本月账本")
    # 「这个月财务收入多少 / 本月支出多少」：按月限定的账本查询，不得落到产品搜索。
    if _MONTH_MONEY_RE.search(text) and any(k in text for k in ("多少", "？", "?")):
        first, last = _month_bounds(current)
        return _ledger_node(first, last, "查询本月财务收支")
    return None
