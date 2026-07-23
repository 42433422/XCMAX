"""独立 AI 客服编排层。

对话优先：寒暄 / 一般咨询只回复不建单；规则 + LLM 识别意图后，
仅在业务受理或用户明确升级时创建工单并执行动作。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from modstore_server.customer_service_tools import (
    audit,
    build_action,
    enqueue_customer_service_event,
    execute_action,
    execute_matching_integrations,
    json_dumps,
    json_loads,
)
from modstore_server.models import User
from modstore_server.models_cs import (
    CustomerServiceDecision,
    CustomerServiceMessage,
    CustomerServiceSession,
    CustomerServiceStandard,
    CustomerServiceTicket,
)

ORDER_RE = re.compile(r"(?:订单号|order[_ -]?no|订单)[:：\s]*([A-Za-z0-9_-]{6,64})", re.I)
CATALOG_RE = re.compile(r"(?:商品\s*ID|catalog[_ -]?id|商品)[:：\s#]*([0-9]{1,12})", re.I)
LLM_PROVIDER_RE = re.compile(r"(?:厂商|provider)\s*[:：]\s*([a-z0-9_-]+)", re.I)
LLM_MODEL_RE = re.compile(r"(?:模型|model)\s*[:：]\s*(\S+)", re.I)
LLM_SLASH_RE = re.compile(r"\b([a-z0-9_-]{2,32})\s*/\s*([^\s,，。]{1,120})", re.I)
GREETING_RE = re.compile(
    r"^(你好|您好|嗨|哈喽|hello|hi|hey|在吗|早上好|上午好|下午好|晚上好|你好呀|您好呀)"
    r"[!！。.?？~\s]*$",
    re.I,
)
ESCALATE_RE = re.compile(
    r"转人工|人工客服|提交工单|创建工单|升级处理|要工单|找人工|处理不了|没解决",
)
TICKET_INTENTS = frozenset(
    {"refund", "catalog_complaint", "catalog_review", "account_support", "llm_extension"}
)
KNOWN_INTENTS = frozenset(
    {
        "greeting",
        "general",
        "refund",
        "catalog_complaint",
        "catalog_review",
        "account_support",
        "llm_extension",
    }
)
_INTENT_CLASSIFY_PROMPT = """你是 MODstore 客服意图分类器。只输出一行 JSON，不要其它文字。
字段：intent, need_ticket, confidence, reason。
intent 只能是：greeting|general|refund|catalog_complaint|catalog_review|account_support|llm_extension。
规则：
- 寒暄/闲聊 → greeting，need_ticket=false
- 产品咨询、怎么用、报价 FAQ → general，need_ticket=false
- 明确退款/投诉/上架审核/账号权益/余额钱包/模型扩展申请 → 对应 intent，need_ticket=true
- 用户要转人工或提交工单 → need_ticket=true（intent 仍按内容选，不清则 general）
confidence 为 0~1。"""


def _enrich_cs_context(
    user: User,
    context: Optional[Dict[str, Any]] = None,
    *,
    db: Optional[Session] = None,
) -> Dict[str, Any]:
    """会话 context 写入可信用户身份（不信任前端伪造的 user_id）。"""
    ctx = dict(context or {})
    try:
        from modstore_server.xiaoc_cs_ssot import resolve_user_identity

        ident = resolve_user_identity(user, db=db, source="market_cs")
        ctx["user_id"] = ident.user_id
        ctx["display_name"] = ident.display_name
        ctx["membership"] = ident.membership
        ctx["account_role"] = ident.account_role
        if ident.plan_id:
            ctx["plan_id"] = ident.plan_id
        if ident.email_hint:
            ctx["email_hint"] = ident.email_hint
    except Exception:  # noqa: BLE001
        ctx["user_id"] = getattr(user, "id", None)
        name = str(getattr(user, "username", None) or "").strip()
        if name:
            ctx["display_name"] = name[:32]
    return ctx


def ensure_session(
    db: Session,
    *,
    user: User,
    session_id: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
) -> CustomerServiceSession:
    enriched = _enrich_cs_context(user, context, db=db)
    if session_id:
        row = (
            db.query(CustomerServiceSession)
            .filter(
                CustomerServiceSession.id == session_id, CustomerServiceSession.user_id == user.id
            )
            .first()
        )
        if row:
            # 补全已有会话的称呼字段（不覆盖渠道等前端上下文）
            try:
                prev = json_loads(row.context_json) if row.context_json else {}
                if not isinstance(prev, dict):
                    prev = {}
                merged = {**prev, **{k: v for k, v in enriched.items() if v is not None}}
                row.context_json = json_dumps(merged)
            except Exception:  # noqa: BLE001
                pass
            return row
    row = CustomerServiceSession(
        user_id=user.id,
        channel=str(enriched.get("channel") or "web")[:32],
        status="open",
        title="AI 客服会话",
        context_json=json_dumps(enriched),
    )
    db.add(row)
    db.flush()
    audit(
        db,
        event_type="session_created",
        session_id=row.id,
        actor=user,
        detail={"channel": row.channel, "context": context or {}},
    )
    return row


def handle_customer_message(
    db: Session,
    *,
    user: User,
    message: str,
    session_id: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context = _enrich_cs_context(user, context, db=db)
    text = (message or "").strip()
    session = ensure_session(db, user=user, session_id=session_id, context=context)
    session.last_message = text
    session.updated_at = datetime.now(timezone.utc)

    user_msg = CustomerServiceMessage(
        session_id=session.id,
        user_id=user.id,
        role="user",
        content=text,
        payload_json=json_dumps({"context": context}),
    )
    db.add(user_msg)
    db.flush()

    extracted = extract_fields(text, context)
    classified = classify_customer_intent(text, extracted, context=context)
    intent = str(classified.get("intent") or "general")
    need_ticket = bool(classified.get("need_ticket"))
    session.intent = intent
    standard = choose_standard(db, intent)

    # 未结案工单：补材料 / 同意图跟进时继续走工单，不强制寒暄也建单
    open_ticket = (
        db.query(CustomerServiceTicket)
        .filter(CustomerServiceTicket.session_id == session.id)
        .filter(CustomerServiceTicket.status.in_(["open", "waiting_user", "processing"]))
        .order_by(CustomerServiceTicket.id.desc())
        .first()
    )
    if open_ticket:
        if open_ticket.status == "waiting_user" and intent in {"general", "greeting"}:
            intent = open_ticket.intent or intent
            session.intent = intent
            need_ticket = True
        elif open_ticket.intent == intent and intent in TICKET_INTENTS:
            need_ticket = True

    if not need_ticket:
        reply = _chat_only_reply(text, intent=intent, user=user, db=db)
        # 对话优先：不对客户展示意图/调试卡片，元数据只进 payload 供审计
        cards: list[Dict[str, Any]] = []
        assistant_msg = CustomerServiceMessage(
            session_id=session.id,
            ticket_id=None,
            user_id=user.id,
            role="assistant",
            content=reply,
            payload_json=json_dumps(
                {
                    "ticket": None,
                    "decision": None,
                    "actions": [],
                    "cards": cards,
                    "intent": classified,
                }
            ),
        )
        db.add(assistant_msg)
        audit(
            db,
            event_type="chat_only_reply",
            session_id=session.id,
            actor=user,
            detail={"intent": intent, "classified": classified, "extracted": extracted},
        )
        return {
            "ok": True,
            "session": session_payload(session),
            "ticket": None,
            "message": {
                "role": "assistant",
                "content": reply,
                "payload": json_loads(assistant_msg.payload_json, {}),
            },
            "decision": None,
            "actions": [],
            "cards": cards,
            "intent": classified,
        }

    ticket = ensure_ticket(db, user=user, session=session, intent=intent, extracted=extracted)
    user_msg.ticket_id = ticket.id

    decision = decide(
        db, user=user, ticket=ticket, standard=standard, extracted=extracted, message=text
    )
    actions = plan_actions(db, user=user, ticket=ticket, decision=decision, extracted=extracted)
    integration_actions = execute_matching_integrations(
        db,
        ticket_id=ticket.id,
        decision_id=decision.id,
        user=user,
        scenario=intent if intent != "greeting" else "general",
        payload={
            "ticket_id": ticket.id,
            "ticket_no": ticket.ticket_no,
            "intent": intent,
            "extracted": extracted,
            "decision": decision.decision,
        },
    )
    actions.extend(integration_actions)

    ticket.decision_status = decision.decision
    if decision.decision in {"approved", "rejected"} and all(
        a.status in {"completed", "skipped"} for a in actions
    ):
        ticket.status = "resolved"
        ticket.closed_at = datetime.now(timezone.utc)
    elif decision.decision == "needs_more_info":
        ticket.status = "waiting_user"
    else:
        ticket.status = "processing"
    ticket.updated_at = datetime.now(timezone.utc)

    reply, cards = build_reply(
        ticket=ticket, decision=decision, actions=actions, extracted=extracted
    )
    if intent in {"general", "greeting"}:
        xiaoc_reply = _xiaoc_general_reply(text, user=user, db=db, ticketed=True)
        if xiaoc_reply:
            reply = xiaoc_reply
    assistant_msg = CustomerServiceMessage(
        session_id=session.id,
        ticket_id=ticket.id,
        user_id=user.id,
        role="assistant",
        content=reply,
        payload_json=json_dumps(
            {
                "ticket": ticket_payload(ticket),
                "decision": decision_payload(decision),
                "actions": [action_payload(a) for a in actions],
                "cards": cards,
                "intent": classified,
            }
        ),
    )
    db.add(assistant_msg)

    audit(
        db,
        event_type="decision_made",
        session_id=session.id,
        ticket_id=ticket.id,
        actor=user,
        detail={
            "decision": decision.decision,
            "intent": intent,
            "classified": classified,
            "extracted": extracted,
        },
    )
    enqueue_customer_service_event(
        db,
        "customer_service.decision_made",
        ticket.ticket_no,
        {
            "ticket_id": ticket.id,
            "ticket_no": ticket.ticket_no,
            "intent": intent,
            "decision": decision.decision,
        },
    )
    return {
        "ok": True,
        "session": session_payload(session),
        "ticket": ticket_payload(ticket),
        "message": {
            "role": "assistant",
            "content": reply,
            "payload": json_loads(assistant_msg.payload_json, {}),
        },
        "decision": decision_payload(decision),
        "actions": [action_payload(a) for a in actions],
        "cards": cards,
        "intent": classified,
    }


def extract_fields(text: str, context: Dict[str, Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for key in ("order_no", "catalog_id", "pkg_id", "item_name", "complaint_type", "reason"):
        value = context.get(key)
        if value not in (None, ""):
            data[key] = value
    order = ORDER_RE.search(text)
    if order and not data.get("order_no"):
        data["order_no"] = order.group(1)
    catalog = CATALOG_RE.search(text)
    if catalog and not data.get("catalog_id"):
        data["catalog_id"] = int(catalog.group(1))
    if not data.get("reason"):
        data["reason"] = text[:1000]
    lowered = text.lower()
    if "抄袭" in text:
        data.setdefault("complaint_type", "plagiarism")
    elif "侵权" in text or "授权" in text:
        data.setdefault("complaint_type", "license")
    elif "下载" in text:
        data.setdefault("complaint_type", "download")
    elif "refund" in lowered or "退款" in text:
        data.setdefault("complaint_type", "refund")
    evidence = context.get("evidence")
    if evidence:
        data["evidence"] = evidence
    lp = LLM_PROVIDER_RE.search(text)
    if lp:
        data["provider"] = lp.group(1).lower()
    lm = LLM_MODEL_RE.search(text)
    if lm:
        data["model"] = lm.group(1).strip()
    if not data.get("provider") or not data.get("model"):
        sl = LLM_SLASH_RE.search(text)
        if sl:
            data.setdefault("provider", sl.group(1).lower())
            data.setdefault("model", sl.group(2).strip())
    return data


def is_greeting(text: str) -> bool:
    return bool(GREETING_RE.match((text or "").strip()))


def wants_ticket_escalation(text: str) -> bool:
    return bool(ESCALATE_RE.search(text or ""))


def should_create_ticket(intent: str, text: str) -> bool:
    if wants_ticket_escalation(text):
        return True
    return intent in TICKET_INTENTS


def infer_intent(
    text: str,
    extracted: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """规则意图识别（明确关键词优先；订单号单独出现不再默认退款）。"""
    ctx = context or {}
    scene = str(ctx.get("scene") or "").strip().lower()
    scene_map = {
        "refund": "refund",
        "complaint": "catalog_complaint",
        "catalog_complaint": "catalog_complaint",
        "review": "catalog_review",
        "catalog_review": "catalog_review",
        "account": "account_support",
        "account_support": "account_support",
        "llm_extension": "llm_extension",
    }
    if scene in scene_map:
        return scene_map[scene]

    complaint_type = str(extracted.get("complaint_type") or ctx.get("complaint_type") or "").lower()
    if complaint_type in {"plagiarism", "license", "download", "侵权", "抄袭"}:
        return "catalog_complaint"
    if complaint_type in {"refund", "退款"}:
        return "refund"

    lowered = text.lower()
    if is_greeting(text):
        return "greeting"
    if (
        extracted.get("provider")
        and extracted.get("model")
        and any(x in text for x in ("模型扩展", "开通模型", "模型上架", "不支持该模型", "申请模型"))
    ):
        return "llm_extension"
    if "退款" in text or "refund" in lowered:
        return "refund"
    if any(word in text for word in ("投诉", "抄袭", "侵权", "无法下载", "举报")):
        return "catalog_complaint"
    if any(word in text for word in ("上架", "审核", "合规", "下架")):
        return "catalog_review"
    if any(
        word in text
        for word in (
            "账号",
            "会员",
            "权益",
            "额度",
            "登录",
            "余额",
            "钱包",
            "充值",
            "到账",
            "扣费",
            "账单",
            "消费记录",
            "余额不对",
            "余额有误",
        )
    ):
        return "account_support"
    if any(
        x in text
        for x in (
            "模型扩展",
            "新模型",
            "模型审核",
            "上架模型",
            "不支持该模型",
            "LLM 扩展",
            "大模型扩展",
        )
    ) or (("模型" in text or "model" in lowered) and ("扩展" in text or "上架" in text or "审核" in text)):
        return "llm_extension"
    return "general"


def classify_customer_intent(
    text: str,
    extracted: Dict[str, Any],
    *,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """规则优先；模糊 general 时可选 LLM 助判。"""
    rule_intent = infer_intent(text, extracted, context=context)
    escalate = wants_ticket_escalation(text)
    if rule_intent != "general":
        return {
            "intent": rule_intent,
            "need_ticket": should_create_ticket(rule_intent, text),
            "confidence": 0.92 if rule_intent != "greeting" else 0.98,
            "source": "rules",
            "reason": "keyword_or_scene",
        }

    llm = _llm_classify_intent(text)
    if llm:
        intent = str(llm.get("intent") or "general")
        if intent not in KNOWN_INTENTS:
            intent = "general"
        need_ticket = (
            bool(llm.get("need_ticket"))
            if "need_ticket" in llm
            else should_create_ticket(intent, text)
        )
        if escalate:
            need_ticket = True
        return {
            "intent": intent,
            "need_ticket": need_ticket,
            "confidence": float(llm.get("confidence") or 0.6),
            "source": "llm",
            "reason": str(llm.get("reason") or "")[:200],
        }

    return {
        "intent": "general",
        "need_ticket": escalate,
        "confidence": 0.55,
        "source": "rules",
        "reason": "escalate" if escalate else "default_general",
    }


def _llm_classify_intent(text: str) -> Optional[Dict[str, Any]]:
    """同步包装平台 LLM；失败或未配置时返回 None。"""
    flag = (os.environ.get("MODSTORE_CS_LLM_INTENT") or "1").strip().lower()
    if flag in {"0", "false", "off", "no"}:
        return None
    sample = (text or "").strip()
    if not sample or len(sample) < 2:
        return None

    async def _inner() -> Optional[Dict[str, Any]]:
        from modstore_server.services.llm import (
            chat_dispatch_via_platform_only,
            resolve_platform_bench_llm,
        )

        prov, mdl = resolve_platform_bench_llm()
        if not prov or not mdl:
            return None
        out = await chat_dispatch_via_platform_only(
            prov,
            mdl,
            [
                {"role": "system", "content": _INTENT_CLASSIFY_PROMPT},
                {"role": "user", "content": sample[:1500]},
            ],
            max_tokens=160,
        )
        if not isinstance(out, dict) or not out.get("ok"):
            return None
        content = ""
        if isinstance(out.get("content"), str):
            content = out["content"]
        elif isinstance(out.get("text"), str):
            content = out["text"]
        elif isinstance(out.get("message"), dict):
            content = str(out["message"].get("content") or "")
        content = content.strip()
        if not content:
            return None
        # 容忍模型包一层 ```json
        if "```" in content:
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else content
            content = content.lstrip("json").strip()
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            return None
        data = json.loads(content[start : end + 1])
        return data if isinstance(data, dict) else None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, _inner()).result(timeout=6)
    except Exception:  # noqa: BLE001
        return None


def _chat_only_reply(
    text: str,
    *,
    intent: str,
    user: Optional[User] = None,
    db: Optional[Session] = None,
) -> str:
    if intent == "greeting" or is_greeting(text):
        name = ""
        try:
            from modstore_server.xiaoc_cs_ssot import resolve_user_identity

            if user is not None:
                ident = resolve_user_identity(user, db=db, source="market_cs")
                if ident.display_name and ident.display_name not in {"用户", "访客", "匿名访客"}:
                    name = ident.display_name
        except Exception:  # noqa: BLE001
            pass
        hello = f"{name}，" if name else ""
        return (
            f"我是小C。{hello}你好！有什么可以帮你的？"
            "比如产品怎么买、会员权益，或订单/退款问题，直接说就行。"
        )
    xiaoc = _xiaoc_general_reply(text, user=user, db=db, ticketed=False)
    if xiaoc:
        return xiaoc
    return (
        "我是小C。已收到你的问题。你可以继续补充细节；"
        "若需要平台正式受理，直接说「提交工单」或说明退款/投诉诉求。"
    )


def choose_standard(db: Session, intent: str) -> Optional[CustomerServiceStandard]:
    return (
        db.query(CustomerServiceStandard)
        .filter(CustomerServiceStandard.auto_enabled == True)
        .filter(CustomerServiceStandard.scenario.in_([intent, "general"]))
        .order_by(CustomerServiceStandard.scenario.desc(), CustomerServiceStandard.priority.asc())
        .first()
    )


def ensure_ticket(
    db: Session,
    *,
    user: User,
    session: CustomerServiceSession,
    intent: str,
    extracted: Dict[str, Any],
) -> CustomerServiceTicket:
    existing = (
        db.query(CustomerServiceTicket)
        .filter(CustomerServiceTicket.session_id == session.id)
        .filter(CustomerServiceTicket.status.in_(["open", "waiting_user", "processing"]))
        .order_by(CustomerServiceTicket.id.desc())
        .first()
    )
    if existing and existing.intent == intent:
        existing.evidence_json = json_dumps(extracted)
        existing.updated_at = datetime.now(timezone.utc)
        return existing
    ticket = CustomerServiceTicket(
        session_id=session.id,
        user_id=user.id,
        ticket_no=f"CS{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{user.id:04d}{session.id:04d}",
        title=title_for_intent(intent, extracted),
        intent=intent,
        subject_type=subject_type_for_intent(intent),
        subject_id=str(extracted.get("order_no") or extracted.get("catalog_id") or ""),
        status="open",
        priority="high" if intent == "catalog_review" else "normal",
        evidence_json=json_dumps(extracted),
        summary=str(extracted.get("reason") or "")[:2000],
    )
    db.add(ticket)
    db.flush()
    audit(
        db,
        event_type="ticket_created",
        session_id=session.id,
        ticket_id=ticket.id,
        actor=user,
        detail={"intent": intent, "extracted": extracted},
    )
    enqueue_customer_service_event(
        db,
        "customer_service.ticket_created",
        ticket.ticket_no,
        {"ticket_id": ticket.id, "ticket_no": ticket.ticket_no, "intent": intent},
    )
    return ticket


def decide(
    db: Session,
    *,
    user: User,
    ticket: CustomerServiceTicket,
    standard: Optional[CustomerServiceStandard],
    extracted: Dict[str, Any],
    message: str,
) -> CustomerServiceDecision:
    missing = missing_fields(ticket.intent, extracted)
    risk_level = standard.risk_level if standard else "low"
    if missing:
        decision = "needs_more_info"
        rationale = f"还需要补充：{'、'.join(missing)}。"
        confidence = 0.45
    elif ticket.intent == "catalog_review" and not user.is_admin:
        decision = "approved"
        rationale = "已自动进入合规审核队列，涉及上架/下架的最终状态会写入审计。"
        confidence = 0.72
    else:
        decision = "approved"
        rationale = "材料满足当前审核标准，允许 AI 客服自动受理并执行低风险动作。"
        confidence = 0.82
    row = CustomerServiceDecision(
        ticket_id=ticket.id,
        user_id=user.id,
        standard_id=standard.id if standard else None,
        intent=ticket.intent,
        decision=decision,
        risk_level=risk_level,
        confidence=confidence,
        rationale=rationale,
        extracted_json=json_dumps(extracted),
        criteria_json=json_dumps(
            [{"name": standard.name if standard else "默认客服规则", "missing": missing}]
        ),
    )
    db.add(row)
    db.flush()
    return row


def missing_fields(intent: str, extracted: Dict[str, Any]) -> list[str]:
    required = {
        "refund": ["order_no", "reason"],
        "catalog_complaint": ["catalog_id", "complaint_type", "reason"],
        "catalog_review": ["catalog_id"],
        "llm_extension": ["provider", "model", "reason"],
    }.get(intent, [])
    return [key for key in required if not extracted.get(key)]


def plan_actions(
    db: Session,
    *,
    user: User,
    ticket: CustomerServiceTicket,
    decision: CustomerServiceDecision,
    extracted: Dict[str, Any],
) -> list[Any]:
    if decision.decision != "approved":
        return []
    actions = []
    if ticket.intent == "refund":
        action = build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="refund.apply",
            target_type="order",
            target_id=str(extracted.get("order_no") or ""),
            request=extracted,
        )
        execute_action(db, action, user)
        actions.append(action)
    elif ticket.intent == "catalog_complaint":
        action = build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="catalog.complaint.create",
            target_type="catalog_item",
            target_id=str(extracted.get("catalog_id") or ""),
            request=extracted,
        )
        execute_action(db, action, user)
        actions.append(action)
    elif ticket.intent == "catalog_review":
        action = build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="catalog.compliance.review",
            target_type="catalog_item",
            target_id=str(extracted.get("catalog_id") or ""),
            request={**extracted, "compliance_status": "reviewing"},
        )
        execute_action(db, action, user)
        actions.append(action)
    elif ticket.intent == "llm_extension":
        prov = str(extracted.get("provider") or "").strip().lower()
        mod = str(extracted.get("model") or "").strip()
        action = build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="llm.model_capability.propose",
            target_type="llm_model",
            target_id=f"{prov}:{mod}"[:240],
            request=extracted,
        )
        execute_action(db, action, user)
        actions.append(action)

    # 客服 → AI 员工管线：投诉/合规/扩展类工单结论已落地后，再派一名相应的 AI 员工
    # 进行代码/文档变更建议（生成 EmployeeChangeRequest），由管理员审批后落地。
    followup = _maybe_dispatch_employee_followup(
        db,
        user=user,
        ticket=ticket,
        decision=decision,
        extracted=extracted,
    )
    if followup is not None:
        actions.append(followup)

    return actions


def _maybe_dispatch_employee_followup(
    db: Session,
    *,
    user: User,
    ticket: CustomerServiceTicket,
    decision: CustomerServiceDecision,
    extracted: Dict[str, Any],
) -> Optional[Any]:
    """对需要落地代码/文档/配置改动的工单，派一名 AI 员工处理。

    仅在 ``decision.decision == 'approved'`` 时触发；按 ``intent`` 决定 brief。
    返回一个 ``CustomerServiceAction``（已 ``completed`` 或 ``failed``），便于
    回写工单的执行历史；无匹配 intent 时返回 ``None``。
    """
    if decision.decision != "approved":
        return None
    intent = ticket.intent or ""
    brief = ""
    if intent == "catalog_complaint":
        brief = (
            f"用户对商品 ID {extracted.get('catalog_id') or '未知'} 提出投诉（类型："
            f"{extracted.get('complaint_type') or '未指定'}）。请相关员工评估证据并"
            f"产出处置建议（更新合规标签 / 修订商品文案 / 补充使用说明等）。"
            f"原因摘要：{(extracted.get('reason') or '')[:400]}"
        )
    elif intent == "catalog_review":
        brief = (
            f"商品 ID {extracted.get('catalog_id') or '未知'} 进入合规审核。"
            f"请相关员工核对 manifest / catalog 元数据，必要时产出文档/字段修改建议。"
        )
    elif intent == "llm_extension":
        prov = extracted.get("provider") or ""
        mod = extracted.get("model") or ""
        brief = (
            f"用户申请扩展大模型：provider={prov} model={mod}。"
            f"请评估接入成本，产出 modstore_server/llm_*.py 与文档的最小变更建议。"
        )
    if not brief:
        return None

    try:
        from modstore_server.task_router import route_and_dispatch

        out = route_and_dispatch(
            brief,
            created_by_user_id=int(user.id),
            llm_provider="auto",
            llm_model="auto",
            max_concurrency=2,
            allow_high_risk_real_run=False,
        )
        ok = bool(out.get("ok"))
        action = build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="employee.dispatch",
            target_type="orchestrate",
            target_id=str(out.get("run_id") or out.get("job_id") or "")[:240],
            request={"brief": brief[:2000], "intent": intent},
        )
        action.status = "completed" if ok else "failed"
        action.result_json = json_dumps({"ok": ok, "summary": str(out)[:4000]})
        action.error = "" if ok else str(out.get("error") or "")[:1000]
        db.flush()
        return action
    except Exception as exc:
        action = build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="employee.dispatch",
            target_type="orchestrate",
            target_id="",
            request={"brief": brief[:2000], "intent": intent},
        )
        action.status = "failed"
        action.error = str(exc)[:1000]
        db.flush()
        return action


_RAW_STRUCTURE_RE = re.compile(
    r"(\(hybrid\)|\[hybrid\]|template_name|template_scope|\"fields\"\s*:|\{[\"']fields)",
    re.I,
)


def _looks_like_raw_kb_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return True
    if _RAW_STRUCTURE_RE.search(s):
        return True
    if s.count("{") + s.count("}") >= 2:
        return True
    if s.startswith("【") and "摘录" in s:
        return True
    return False


def _human_kb_tips(kb: str, *, limit: int = 3) -> list[str]:
    """从知识库块里只取可读自然语言行，过滤模板/JSON 脏数据。"""
    tips: list[str] = []
    for raw in (kb or "").splitlines():
        ln = raw.strip()
        if not ln or _looks_like_raw_kb_line(ln):
            continue
        if re.match(r"^\d+[\.、]\s*", ln):
            ln = re.sub(r"^\d+[\.、]\s*", "", ln)
        if ". " in ln[:5]:
            ln = ln.split(". ", 1)[-1].strip()
        if len(ln) < 8 or _looks_like_raw_kb_line(ln):
            continue
        tips.append(ln[:120])
        if len(tips) >= limit:
            break
    return tips


def _display_name_for_user(
    user: Optional[User],
    *,
    db: Optional[Session] = None,
) -> tuple[str, str]:
    address = ""
    member_hint = ""
    try:
        from modstore_server.xiaoc_cs_ssot import resolve_user_identity

        if user is not None:
            ident = resolve_user_identity(user, db=db, source="market_cs")
            address = ident.display_name
            if ident.membership and ident.membership != "普通用户":
                member_hint = f"（{ident.membership}）"
            elif ident.account_role == "admin":
                member_hint = "（管理员）"
    except Exception:  # noqa: BLE001
        pass
    return address, member_hint


def _summarize_user_issue(user_text: str, *, max_len: int = 48) -> str:
    """压缩用户原话，供兜底复述；去掉寒暄前缀。"""
    t = re.sub(r"\s+", "", (user_text or "").strip())
    for prefix in ("我有问题", "有个问题", "请问一下", "请问", "你好", "您好"):
        if t.startswith(prefix):
            t = t[len(prefix) :]
            break
    t = t.lstrip("，,。.!！、：:")
    if not t:
        t = (user_text or "").strip()
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def _looks_like_concrete_issue(user_text: str) -> bool:
    """用户是否已描述具体问题（而非空话/寒暄）。"""
    t = (user_text or "").strip()
    if len(t) < 6:
        return False
    if is_greeting(t):
        return False
    # 明显在陈述故障/体验/诉求
    if any(
        x in t
        for x in (
            "看不清",
            "浅色",
            "深色",
            "对比",
            "按钮",
            "打不开",
            "进不去",
            "失败",
            "报错",
            "卡住",
            "加载",
            "空白",
            "闪退",
            "用不了",
            "没反应",
            "太慢",
            "bug",
            "Bug",
            "问题",
            "故障",
            "异常",
        )
    ):
        return True
    return len(re.sub(r"\s+", "", t)) >= 10


def _ack_concrete_issue_reply(user_text: str, *, hello: str, ticketed: bool) -> str:
    """知识库无可用摘录时：复述用户问题，不再甩购买/会员开场白。"""
    summary = _summarize_user_issue(user_text)
    if ticketed:
        return (
            f"我是小C。{hello}已记下你的问题：「{summary}」，并登记工单；"
            "你可以继续补充页面位置、截图或复现步骤，我们会尽快处理。"
        )
    return (
        f"我是小C。{hello}收到，你说的是「{summary}」。"
        "方便补充一下大概在哪个页面/功能、是文字还是图标按钮吗？"
        "需要正式跟进修复时，直接回「提交工单」即可。"
    )


def _xiaoc_general_reply(
    user_text: str,
    *,
    user: Optional[User] = None,
    db: Optional[Session] = None,
    ticketed: bool = False,
) -> str:
    """general 意图走小C SSOT；只输出可读话术，绝不把知识库原始结构甩给客户。"""
    address, member_hint = _display_name_for_user(user, db=db)
    hello = (
        f"{address}{member_hint}，"
        if address and address not in {"用户", "访客", "匿名访客"}
        else ""
    )
    kb = ""
    try:
        from modstore_server.xiaoc_cs_ssot import knowledge_block_for_query

        kb = knowledge_block_for_query(user_text, top_k=4, mode="market_cs")
    except Exception:  # noqa: BLE001
        kb = ""
    tips = _human_kb_tips(kb)
    if tips:
        body = "；".join(tips)
        return f"我是小C。{hello}{body} 若还要补充，直接说具体场景就行。"
    if ticketed:
        if _looks_like_concrete_issue(user_text):
            return _ack_concrete_issue_reply(user_text, hello=hello, ticketed=True)
        return f"我是小C。{hello}已为你登记工单；" "你可以继续补充材料，我们会尽快处理。"
    if _looks_like_concrete_issue(user_text):
        return _ack_concrete_issue_reply(user_text, hello=hello, ticketed=False)
    return (
        f"我是小C。{hello}可以先说说你的具体问题，"
        "比如购买、会员权益、订单或余额；需要正式受理时我会帮你建工单。"
    )


def build_reply(
    *,
    ticket: CustomerServiceTicket,
    decision: CustomerServiceDecision,
    actions: list[Any],
    extracted: Dict[str, Any],
) -> tuple[str, list[Dict[str, Any]]]:
    intent = ticket.intent or "general"
    if intent == "account_support":
        reply = (
            f"我是小C。已收到你的账户/余额问题，并创建工单 {ticket.ticket_no}。"
            "请补充：最近一次充值或扣费的时间、金额，或钱包页截图，方便尽快核查。"
        )
    elif decision.decision == "needs_more_info":
        reply = f"我是小C。已创建工单 {ticket.ticket_no}，" f"还需要你补充：{decision.rationale}"
    elif actions:
        done = "、".join(
            f"{getattr(a, 'action_type', '')}"
            for a in actions
            if getattr(a, "status", "") in {"completed", "skipped"}
        )
        if done:
            reply = f"我是小C。工单 {ticket.ticket_no} 已自动受理，已执行：{done}。"
        else:
            reply = f"我是小C。工单 {ticket.ticket_no} 已受理，正在处理中。"
    else:
        reply = f"我是小C。已受理工单 {ticket.ticket_no}。{decision.rationale}"
    cards = [
        {
            "type": "ticket",
            "title": ticket.title,
            "ticket_no": ticket.ticket_no,
            "status": ticket.status,
            "intent": ticket.intent,
            "subject_type": ticket.subject_type,
            "subject_id": ticket.subject_id,
        },
        {
            "type": "decision",
            "decision": decision.decision,
            "risk_level": decision.risk_level,
            "confidence": decision.confidence,
            "rationale": decision.rationale,
            "extracted": extracted,
        },
    ]
    if actions:
        cards.append({"type": "actions", "items": [action_payload(a) for a in actions]})
    return reply, cards


def title_for_intent(intent: str, extracted: Dict[str, Any]) -> str:
    labels = {
        "refund": "订单退款处理",
        "catalog_complaint": "商品投诉处理",
        "catalog_review": "商品合规审核",
        "account_support": "账号权益支持",
        "llm_extension": "大模型扩展申请",
        "general": "平台客服咨询",
        "greeting": "平台客服咨询",
    }
    suffix = extracted.get("order_no") or extracted.get("catalog_id") or ""
    if intent == "llm_extension":
        suffix = f"{extracted.get('provider') or ''}/{extracted.get('model') or ''}".strip("/")
    return f"{labels.get(intent, '平台客服咨询')}{f' #{suffix}' if suffix else ''}"


def subject_type_for_intent(intent: str) -> str:
    return {
        "refund": "order",
        "catalog_complaint": "catalog_item",
        "catalog_review": "catalog_item",
        "account_support": "account",
        "llm_extension": "llm_model",
    }.get(intent, "general")


def session_payload(row: CustomerServiceSession) -> Dict[str, Any]:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "channel": row.channel,
        "status": row.status,
        "title": row.title,
        "intent": row.intent,
        "context": json_loads(row.context_json, {}),
        "last_message": row.last_message,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def ticket_payload(row: CustomerServiceTicket) -> Dict[str, Any]:
    return {
        "id": row.id,
        "session_id": row.session_id,
        "ticket_no": row.ticket_no,
        "title": row.title,
        "intent": row.intent,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "status": row.status,
        "priority": row.priority,
        "evidence": json_loads(row.evidence_json, {}),
        "summary": row.summary,
        "decision_status": row.decision_status,
        "automation_level": row.automation_level,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "closed_at": row.closed_at.isoformat() if row.closed_at else "",
    }


def decision_payload(row: CustomerServiceDecision) -> Dict[str, Any]:
    return {
        "id": row.id,
        "ticket_id": row.ticket_id,
        "standard_id": row.standard_id,
        "intent": row.intent,
        "decision": row.decision,
        "risk_level": row.risk_level,
        "confidence": row.confidence,
        "rationale": row.rationale,
        "extracted": json_loads(row.extracted_json, {}),
        "criteria": json_loads(row.criteria_json, []),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def action_payload(row: Any) -> Dict[str, Any]:
    return {
        "id": row.id,
        "ticket_id": row.ticket_id,
        "decision_id": row.decision_id,
        "action_type": row.action_type,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "status": row.status,
        "request": json_loads(row.request_json, {}),
        "result": json_loads(row.result_json, {}),
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }
