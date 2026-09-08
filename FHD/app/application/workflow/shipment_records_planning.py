"""Route shipment-record listing requests to the shipment records tool.

「今天的发货记录 / 看下发货记录」 previously fell through to the terminal
``products.query`` fallback. This planner answers them with
``shipment_records.list`` so shipment history stays in the shipment domain.
"""

from __future__ import annotations

import re

from .types import WorkflowNode

_RECORD_RE = re.compile(r"发货记录|出货记录|发货列表|发货单列表|发货情况")
_QUERY_HINT_RE = re.compile(r"查|看|列出|有哪些|多少|记录|列表|今天|昨天|本周|本月|这周|这个月")
_DATE_RE = re.compile(r"(今天|今日|昨天|本周|这周|本月|这个月|上个月|上月)")


def _day_bounds(keyword: str, today) -> tuple[str, str] | None:
    """Best-effort date window for the common relative-day phrasings."""
    from datetime import timedelta

    if keyword in ("今天", "今日"):
        return today.isoformat(), (today + timedelta(days=1)).isoformat()
    if keyword == "昨天":
        day = today - timedelta(days=1)
        return day.isoformat(), today.isoformat()
    if keyword in ("本周", "这周"):
        start = today - timedelta(days=today.weekday())
        return start.isoformat(), (start + timedelta(days=7)).isoformat()
    if keyword in ("本月", "这个月"):
        return today.replace(day=1).isoformat(), (
            today.replace(day=28) + timedelta(days=7)
        ).isoformat()
    return None


def shipment_records_query_node(message: str) -> WorkflowNode | None:
    """「今天的发货记录 / 看下发货记录」→ shipment_records.list。"""
    text = str(message or "").strip()
    if not text or not _RECORD_RE.search(text):
        return None
    if not _QUERY_HINT_RE.search(text):
        return None
    if any(word in text for word in ("不要", "别", "不用", "取消", "删除", "清空", "打印", "补开")):
        return None
    from datetime import date

    params: dict[str, object] = {"page": 1, "per_page": 50}
    dated = _DATE_RE.search(text)
    if dated:
        bounds = _day_bounds(dated.group(1), date.today())
        if bounds:
            params["start_date"], params["end_date"] = bounds
    return WorkflowNode(
        node_id="list_shipment_records",
        tool_id="shipment_records",
        action="list",
        params=params,
        risk="low",
        idempotent=True,
        description="查询发货记录",
    )
