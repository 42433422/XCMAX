"""Resolve explicit calendar-month ledger requests to bounded dates."""

from __future__ import annotations

import calendar
import re
from datetime import date

from .types import WorkflowNode


def monthly_ledger_node(message: str, *, today: date | None = None) -> WorkflowNode | None:
    if not re.fullmatch(
        r"(?:请|帮我)?(?:查询|查看|查一下|看看)(?:这个月|本月)(?:的)?(?:账本|总账)[。？?\s]*",
        str(message or "").strip(),
    ):
        return None
    current = today or date.today()
    first = current.replace(day=1)
    last = current.replace(day=calendar.monthrange(current.year, current.month)[1])
    return WorkflowNode(
        node_id="query_monthly_ledger",
        tool_id="finance",
        action="ledger_query",
        params={
            "start_date": first.isoformat(),
            "end_date": last.isoformat(),
            "page": 1,
            "per_page": 20,
        },
        risk="low",
        idempotent=True,
        description="查询本月账本",
    )
