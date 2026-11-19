"""Pure customer-service triage policies; no service facade or database imports."""

from __future__ import annotations

import re

INTAKE_SCENE_INTENTS = {
    "refund": "refund",
    "complaint": "catalog_complaint",
    "catalog_complaint": "catalog_complaint",
    "review": "catalog_review",
    "catalog_review": "catalog_review",
    "account": "account_support",
    "account_support": "account_support",
    "llm_extension": "llm_extension",
}


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


# --- 工单三维分类：类型 × 业务域 × 来源（纯派生，不改库表） ---

TICKET_TYPE_LABELS = {
    "incident": "事故",
    "defect": "缺陷",
    "request": "服务请求",
    "question": "咨询",
    "complaint": "投诉",
    "delivery": "交付实施",
    "account": "账号权益",
}
TICKET_TYPE_BY_INTENT = {
    "product_issue": "defect",
    "custom_delivery": "delivery",
    "refund": "request",
    "catalog_review": "request",
    "llm_extension": "request",
    "catalog_complaint": "complaint",
    "account_support": "account",
    "general": "question",
    "greeting": "question",
}
TICKET_TYPE_INTENTS = {
    "defect": ("product_issue",),
    "delivery": ("custom_delivery",),
    "request": ("refund", "catalog_review", "llm_extension"),
    "complaint": ("catalog_complaint",),
    "account": ("account_support",),
    "question": ("general", "greeting"),
}
TICKET_DOMAINS = ("platform", "software", "custom")
TICKET_DOMAIN_LABELS = {"platform": "平台", "software": "软件", "custom": "客户定制"}
TICKET_SOURCES = ("customer_chat", "admin_created", "github_self_heal")
TICKET_SOURCE_LABELS = {
    "customer_chat": "客户对话",
    "admin_created": "管理员自建",
    "github_self_heal": "GitHub 自愈",
}


def ticket_type_for(intent: str, source: str = "") -> str:
    if source == "github_self_heal":
        return "incident"
    return TICKET_TYPE_BY_INTENT.get(str(intent or "").strip().lower(), "")


def ticket_domain_for(intent: str, issue_domain: str = "") -> str:
    if str(intent or "").strip().lower() == "custom_delivery":
        return "custom"
    domain = str(issue_domain or "").strip().lower()
    return domain if domain in TICKET_DOMAINS else ""


def ticket_source_for(submitter_type: str, evidence: dict) -> str:
    raw = str(evidence.get("source") or "").strip().lower()
    if raw in TICKET_SOURCES:
        return raw
    kind = str(submitter_type or "").strip().lower()
    if kind == "admin":
        return "admin_created"
    if kind == "customer":
        return "customer_chat"
    return ""


def ticket_taxonomy(intent: str, submitter_type: str, evidence: dict) -> dict[str, str]:
    source = ticket_source_for(submitter_type, evidence)
    ticket_type = ticket_type_for(intent, source)
    domain = ticket_domain_for(intent, (evidence or {}).get("issue_domain") or "")
    return {
        "ticket_type": ticket_type,
        "ticket_type_label": TICKET_TYPE_LABELS.get(ticket_type, ""),
        "ticket_domain": domain,
        "ticket_domain_label": TICKET_DOMAIN_LABELS.get(domain, ""),
        "ticket_source": source,
        "ticket_source_label": TICKET_SOURCE_LABELS.get(source, ""),
    }
