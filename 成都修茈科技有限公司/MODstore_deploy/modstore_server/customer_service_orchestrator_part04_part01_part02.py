# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def title_for_intent(intent: str, extracted: _facade().Dict[str, _facade().Any]) -> str:
    domain = str(extracted.get("issue_domain") or "").strip().lower()
    domain_title = {
        "platform": "平台功能问题",
        "software": "软件功能问题",
        "custom": "定制功能问题",
    }
    labels = {
        "refund": "订单退款处理",
        "catalog_complaint": "商品投诉处理",
        "catalog_review": "商品合规审核",
        "account_support": "账号权益支持",
        "llm_extension": "大模型扩展申请",
        "product_issue": domain_title.get(domain, "功能问题反馈"),
        "general": "平台客服咨询",
        "greeting": "平台客服咨询",
    }
    suffix = (
        extracted.get("order_no") or extracted.get("catalog_id") or extracted.get("pkg_id") or ""
    )
    if intent == "llm_extension":
        suffix = f"{extracted.get('provider') or ''}/{extracted.get('model') or ''}".strip("/")
    if intent in {"general", "greeting"}:
        issue = str(extracted.get("reason") or extracted.get("_issue_summary") or "")
        if _facade()._looks_like_product_issue(issue) or _facade()._looks_like_concrete_issue(
            issue
        ):
            return domain_title.get(domain, "功能问题反馈")
    return f"{labels.get(intent, '平台客服咨询')}{(f' #{suffix}' if suffix else '')}"


def _is_escalate_only(text: str) -> bool:
    """纯升级话术（无业务内容）。避免与 concrete_issue 互相调用造成递归。"""
    t = (text or "").strip()
    return bool(
        _facade().re.fullmatch(
            "(请)?(帮我)?(提交工单|创建工单|转人工|人工客服|升级处理|要工单|找人工)(吧|一下|处理|核查)?[.!！。]?",
            t,
        )
    )


def _peek_prior_user_issue(
    db: _facade().Session,
    *,
    session: _facade().CustomerServiceSession,
    exclude_text: str = "",
) -> str:
    rows = (
        db.query(_facade().CustomerServiceMessage)
        .filter(_facade().CustomerServiceMessage.session_id == session.id)
        .filter(_facade().CustomerServiceMessage.role == "user")
        .order_by(_facade().CustomerServiceMessage.id.desc())
        .limit(8)
        .all()
    )
    exclude = (exclude_text or "").strip()
    for row in rows:
        content = str(getattr(row, "content", "") or "").strip()
        if not content or content == exclude:
            continue
        if _facade()._is_escalate_only(content):
            continue
        if len(content) < 4:
            continue
        return content
    return ""


def _resolve_issue_text_for_reply(
    *,
    extracted: _facade().Dict[str, _facade().Any],
    text: str,
    prior_issue: str = "",
    ticket: _facade().Optional[_facade().CustomerServiceTicket] = None,
) -> str:
    """回复复述用真实问题，绝不拿「提交工单」当摘要。"""
    for candidate in (
        extracted.get("reason"),
        extracted.get("_issue_summary"),
        prior_issue,
        getattr(ticket, "summary", None) if ticket is not None else None,
        text,
    ):
        s = str(candidate or "").strip()
        if s and (not _facade()._is_escalate_only(s)):
            return s
    return "你反馈的功能问题"


def _enrich_extracted_from_prior_issue(
    db: _facade().Session,
    *,
    session: _facade().CustomerServiceSession,
    text: str,
    extracted: _facade().Dict[str, _facade().Any],
) -> None:
    """升级话术本身无内容时，从上一条用户消息继承问题摘要。"""
    existing = str(extracted.get("reason") or "").strip()
    if existing and (not _facade()._is_escalate_only(existing)):
        return
    if not _facade().wants_ticket_escalation(text):
        return
    if _facade()._looks_like_concrete_issue(text) and (not _facade()._is_escalate_only(text)):
        extracted["reason"] = text[:500]
        extracted["_issue_summary"] = _facade()._summarize_user_issue(text)
        return
    prior = _facade()._peek_prior_user_issue(db, session=session, exclude_text=text)
    if prior:
        extracted["reason"] = prior[:500]
        extracted["_issue_summary"] = _facade()._summarize_user_issue(prior)


def subject_type_for_intent(intent: str) -> str:
    return {
        "refund": "order",
        "catalog_complaint": "catalog_item",
        "catalog_review": "catalog_item",
        "account_support": "account",
        "llm_extension": "llm_model",
        "product_issue": "product",
    }.get(intent, "general")


def session_payload(
    row: _facade().CustomerServiceSession,
) -> _facade().Dict[str, _facade().Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "channel": row.channel,
        "status": row.status,
        "title": row.title,
        "intent": row.intent,
        "context": _facade().json_loads(row.context_json, {}),
        "last_message": row.last_message,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }
