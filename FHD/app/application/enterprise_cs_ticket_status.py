"""Read verified ticket progress through the existing MODstore customer view."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlencode

from app.application.private_mod_delivery_artifacts import custom_delivery_remote_json

_STATUS_REQUEST = re.compile(r"查|进度|状态|处理到|处理完|怎么样|到哪|修好|解决|办好")
_FEATURE_REFERENCE = re.compile(r"工单(?:进度|状态)?(?:查询|查看)?(?:页面|按钮|入口|功能)")
_NUMBERLESS_QUERY = re.compile(
    r"(?:查(?:询|一下|看|查)?|看一下|我的).{0,20}工单(?:的?(?:处理)?(?:进度|状态))?[？?。\s]*$"
)
_TICKET_NUMBER = re.compile(
    r"(?<![a-z0-9-])(?:c[disx]-?[a-f0-9][a-z0-9-]{1,61}|[0-9]{3,18})(?![a-z0-9-])",
    re.I | re.ASCII,
)
_LIFECYCLE_LABELS = frozenset({"已收到", "处理中", "有结果", "待补充", "待客户确认", "已完成"})
_TERMINAL_LABELS = {
    "closed": "已关闭",
    "rejected": "已拒绝",
    "cancelled": "已取消",
    "expired": "已过期不再处理",
}


async def reply_to_ticket_status_request(
    text: str, *, market_user_id: int, market_token: str
) -> str | None:
    """Return the current customer-visible status for an explicit ticket enquiry."""
    text = text.strip()
    if "工单" not in text or not _STATUS_REQUEST.search(text) or _FEATURE_REFERENCE.search(text):
        return None
    numbers = list(dict.fromkeys(_TICKET_NUMBER.findall(text)))
    if len(numbers) != 1:
        if numbers or _NUMBERLESS_QUERY.search(text):
            return "请发送要查询的一个完整工单编号，我会核对后台状态。"
        return None
    number = numbers[0]
    if re.fullmatch(r"(?:CI[a-f0-9]{48}|CS[a-f0-9]{32})", number, re.I):
        number = number[:2].upper() + number[2:].lower()
    elif not number.isdigit():
        number = number.upper()
    if not market_token or market_user_id <= 0:
        return "当前无法验证企业账号身份，请重新登录企业账号后查询工单。"

    params = urlencode({"search": number, "account_id": market_user_id, "limit": 10})
    try:
        async with asyncio.timeout(8):
            result = await custom_delivery_remote_json(
                market_token, f"/api/customer-service/tickets?{params}"
            )
    except (RuntimeError, ConnectionError, TimeoutError):
        return "工单状态暂时无法核对，请稍后查询或打开原工单查看。"

    tickets = result.get("items")
    if not isinstance(tickets, list):
        return "工单状态暂时无法核对，请稍后查询或打开原工单查看。"
    for ticket in tickets:
        if (
            isinstance(ticket, dict)
            and str(ticket.get("user_id")) == str(market_user_id)
            and ticket.get("ticket_no") == number
        ):
            label = _TERMINAL_LABELS.get(
                str(ticket.get("status")), str(ticket.get("lifecycle_label") or "")
            )
            if label in _LIFECYCLE_LABELS or label in _TERMINAL_LABELS.values():
                return f"工单 {number} 当前为「{label}」。具体进度和待补充事项可在原工单查看。"
            return f"已找到工单 {number}，当前状态请打开原工单查看。"
    return "当前企业账号下未查到该工单，请核对完整工单编号。"
