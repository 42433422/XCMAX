"""Pure customer-service triage policies; no service facade or database imports."""

from __future__ import annotations

import re


def _parse_domain_clarify_reply(text: str) -> str:
    """用户短句确认归属：是平台 / 是软件 / 是定制。返回 domain 或空串。"""
    t = re.sub("\\s+", "", (text or "").strip())
    t = t.rstrip("。.！!？?~～")
    if not t:
        return ""
    exact = {
        "平台": "platform",
        "是平台": "platform",
        "平台的": "platform",
        "平台问题": "platform",
        "宿主": "platform",
        "软件": "software",
        "是软件": "software",
        "软件问题": "software",
        "商品": "software",
        "是商品": "software",
        "定制": "custom",
        "是定制": "custom",
        "客户定制": "custom",
        "账号定制": "custom",
        "定制的": "custom",
    }
    if t in exact:
        return exact[t]
    if any((x in t for x in ("客户定制", "账号定制", "定制员工", "定制线"))) and len(t) <= 24:
        return "custom"
    if any((x in t for x in ("是平台", "平台问题", "宿主问题"))) and len(t) <= 24:
        return "platform"
    if (
        any((x in t for x in ("是软件", "软件问题", "商品问题", "这个Mod", "这个mod")))
        and len(t) <= 24
    ):
        return "software"
    return ""


def resolve_triage_lane(intent: str) -> str:
    """intent → 分诊车道。账号/不确定 → ultimate_review（终极员工可介入）；ops_fast_fix 预留。"""
    if intent == "product_issue":
        return "product_defect"
    if intent in {"account_support", "general", "greeting"}:
        return "ultimate_review"
    if intent in {"refund", "catalog_complaint", "catalog_review", "llm_extension"}:
        return "commerce"
    return "general"
