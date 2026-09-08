"""Conservative slots for explicit customer list/name queries, without DB access."""

import re

from app.domain.neuro.greeting import is_standalone_greeting

_PREFIX = re.compile(
    r"^(?:(?:请|帮我|给我|查看|查询|查一下|查下|查|看看|看下|看|搜索|找下|找|列出|显示)\s*)*"
    r"(?:(?:所有|全部|现有|当前)\s*)?(?:客户|购买单位|买家)\s*(.*)$"
)
_LIST = {"", "列表", "名单", "清单", "信息", "资料", "有多少", "有多少个", "有多少家", "有哪些"}


def customer_query_slots(message: str) -> dict[str, str] | None:
    text = str(message or "").strip()
    parts = re.split(r"[，,！!。]", text, maxsplit=1)
    if len(parts) == 2 and is_standalone_greeting(parts[0]):
        text = parts[1].strip()
    if re.fullmatch(
        r"(?:(?:请|帮我|查看|查询|查一下|看看|看下)\s*)*(?:我(?:们)?)?"
        r"(?:有)?(?:哪些|多少(?:个|家)?)(?:客户|购买单位|买家)[?？。\s]*",
        text,
    ):
        return {"keyword": ""}
    named = re.fullmatch(
        r"(?:查询|查看|查一下|搜索)\s*(.+?)\s*的(?:客户|购买单位|买家)[?？。\s]*",
        text,
    )
    if named:
        # Reuse the same keyword validation as the customer-first phrasing.
        text = "查询客户 " + named.group(1)
    match = _PREFIX.fullmatch(text)
    if not match:
        return None
    tail = match.group(1).strip(" ：:，,。.!！?？")
    if tail in _LIST:
        return {"keyword": ""}
    tail = re.sub(r"\s*(?:的\s*)?(?:信息|资料|详情)\s*$", "", tail).strip()
    if len(tail) >= 2 and (tail[0], tail[-1]) in {('"', '"'), ("'", "'"), ("「", "」"), ("“", "”")}:
        tail = tail[1:-1].strip()
        return {"keyword": tail} if tail else None
    # Writes and compound instructions must continue through their own planning path.
    if re.search(r"新增|新建|添加|创建|删除|修改|更新|写入|订单|产品|库存|发货|[，,；;]", tail):
        return None
    return {"keyword": tail} if tail else None
