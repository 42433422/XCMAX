"""Decide when a chat turn is conversation memory instead of an enterprise lookup.

Ordinary facts and fact questions stay in the current conversation. The customer
database is used only when the user explicitly asks to read that database.
"""

from __future__ import annotations

import re

_DATABASE_MARKERS = ("客户库", "企业数据库", "业务数据库", "业务库")
_CLIENT_VERSION = re.compile(r"(桌面|客户端|软件).{0,8}版本|当前版本")
_OPERATIONAL = re.compile(r"(发货单|送货单|出货单|开单|打印标签|导入产品|导入数据库|导入到库)")


def is_explicit_enterprise_customer_query(text: str) -> bool:
    """True only for a request to read the enterprise customer database."""
    raw = str(text or "").strip()
    if not raw:
        return False
    if any(marker in raw for marker in _DATABASE_MARKERS):
        return True
    if re.search(r"客户(有哪些|列表|资料|信息|名录)", raw):
        return True
    if re.search(r"(有哪些|列出全部|全部).{0,8}客户", raw):
        return True
    if re.search(r"(查一下|查询|查下|看看|查看|帮我查)\s*客户(?!总数|数|分类)", raw):
        return True
    if re.search(r"查询.{0,32}的客户", raw):
        return True
    if re.search(r"(多少个客户|有多少.{0,6}客户|客户名单|客户\s*ID|联系人|实际记录)", raw):
        return not bool(re.search(r"(已确认|本会话|假设|暂时不要|会话标记|刚才)", raw))
    return False


def is_client_version_question(text: str) -> bool:
    raw = str(text or "")
    if any(word in raw for word in ("产品", "商品", "货品")):
        return False
    return bool(_CLIENT_VERSION.search(raw))


def is_dialogue_fact_message(text: str) -> bool:
    """A spoken fact, correction, hypothesis, or question about this conversation."""
    raw = str(text or "").strip()
    if not raw or _OPERATIONAL.search(raw):
        return False
    if re.search(r"(卖给|销售给|出售给|单价|开票|收款|人工审批|手动审批|出货|发货|送货|客户名称)", raw):
        return False
    if is_explicit_enterprise_customer_query(raw) or is_client_version_question(raw):
        return False
    if re.search(
        r"(假设|暂时不要|不要修改|只做风险|撤销|恢复基线|恢复最初|恢复原来|恢复原始|"
        r"更正|改正|纠正|已确认|会话标记|合同总额|客户总数|[AB]类)",
        raw,
    ):
        return True
    if re.search(r"如果", raw) and re.search(r"(客户|合同|标记|增加|减少)", raw):
        return True
    if re.search(r"\d", raw) and re.search(r"(客户|合同|万元|标记)", raw):
        return True
    return bool(
        re.search(
            r"(多少|是什么|几家|几个).{0,16}(客户|合同|标记)|(客户|合同|标记).{0,16}(多少|是什么)",
            raw,
        )
    )
