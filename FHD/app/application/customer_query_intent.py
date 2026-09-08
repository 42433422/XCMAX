"""Conservative slots for explicit customer list/name queries, without DB access."""

import re

from app.domain.neuro.greeting import is_standalone_greeting

_PREFIXES = sorted(
    (
        "请",
        "帮我",
        "给我",
        "查看",
        "查询",
        "查一下",
        "查下",
        "查",
        "看看",
        "看下",
        "看",
        "搜索",
        "找下",
        "找",
        "列出",
        "显示",
    ),
    key=len,
    reverse=True,
)
_ENTITIES = ("客户", "购买单位", "买家")
_LIST = {"", "列表", "名单", "清单", "信息", "资料", "有多少", "有多少个", "有多少家", "有哪些"}


def customer_query_slots(message: str) -> dict[str, str] | None:
    text = str(message or "").strip()
    parts = re.split(r"[，,！!。]", text, maxsplit=1)
    if len(parts) == 2 and is_standalone_greeting(parts[0]):
        text = parts[1].strip()
    original = text
    offset = 0
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        prefix = next((word for word in _PREFIXES if text.startswith(word, offset)), None)
        if prefix is None:
            break
        offset += len(prefix)
    text = text[offset:].strip()
    clean = text.rstrip("?？。 \t\r\n")
    for who in ("我们", "我", ""):
        for have in ("有", ""):
            for amount in ("哪些", "多少", "多少个", "多少家"):
                if clean in {who + have + amount + entity for entity in _ENTITIES}:
                    return {"keyword": ""}
    tail = None
    if original.startswith(("查询", "查看", "查一下", "搜索")):
        for entity in _ENTITIES:
            suffix = "的" + entity
            if clean.endswith(suffix):
                tail = clean[: -len(suffix)].strip()
                break
    if tail is None:
        for qualifier in ("所有", "全部", "现有", "当前"):
            if text.startswith(qualifier):
                text = text[len(qualifier) :].lstrip()
                break
        for entity in _ENTITIES:
            if text.startswith(entity):
                tail = text[len(entity) :].strip(" ：:，,。.!！?？\t\r\n")
                break
    if tail is None:
        return None
    if tail in _LIST:
        return {"keyword": ""}
    for suffix in ("信息", "资料", "详情"):
        if tail.endswith(suffix):
            tail = tail[: -len(suffix)].rstrip()
            if tail.endswith("的"):
                tail = tail[:-1].rstrip()
            break
    if len(tail) >= 2 and (tail[0], tail[-1]) in {('"', '"'), ("'", "'"), ("「", "」"), ("“", "”")}:
        tail = tail[1:-1].strip()
        return {"keyword": tail} if tail else None
    # Writes and compound instructions must continue through their own planning path.
    if re.search(r"新增|新建|添加|创建|删除|修改|更新|写入|订单|产品|库存|发货|[，,；;]", tail):
        return None
    return {"keyword": tail} if tail else None
