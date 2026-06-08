"""独立 AI 客服编排层。

第一版先用可审计的规则引擎做意图识别和动作计划，后续可以把 LLM function
calling 接到本层，而不是让前端或提示词直接执行业务动作。
"""

from __future__ import annotations

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


def ensure_session(
    db: Session,
    *,
    user: User,
    session_id: Optional[int] = None,
    context: Optional[Dict[str, Any]] = None,
) -> CustomerServiceSession:
    if session_id:
        row = (
            db.query(CustomerServiceSession)
            .filter(
                CustomerServiceSession.id == session_id, CustomerServiceSession.user_id == user.id
            )
            .first()
        )
        if row:
            return row
    row = CustomerServiceSession(
        user_id=user.id,
        channel=str((context or {}).get("channel") or "web")[:32],
        status="open",
        title="AI 客服会话",
        context_json=json_dumps(context or {}),
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
    context = context or {}
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
    intent = infer_intent(text, extracted)
    session.intent = intent
    standard = choose_standard(db, intent)
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
        scenario=intent,
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
        detail={"decision": decision.decision, "intent": intent, "extracted": extracted},
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


def infer_intent(text: str, extracted: Dict[str, Any]) -> str:
    lowered = text.lower()
    if (
        extracted.get("provider")
        and extracted.get("model")
        and any(x in text for x in ("模型扩展", "开通模型", "模型上架", "不支持该模型", "申请模型"))
    ):
        return "llm_extension"
    if "退款" in text or "refund" in lowered or extracted.get("order_no"):
        return "refund"
    if any(word in text for word in ("投诉", "抄袭", "侵权", "无法下载", "举报")):
        return "catalog_complaint"
    if any(word in text for word in ("上架", "审核", "合规", "下架")):
        return "catalog_review"
    if any(word in text for word in ("账号", "会员", "权益", "额度", "登录")):
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


def build_reply(
    *,
    ticket: CustomerServiceTicket,
    decision: CustomerServiceDecision,
    actions: list[Any],
    extracted: Dict[str, Any],
) -> tuple[str, list[Dict[str, Any]]]:
    if decision.decision == "needs_more_info":
        reply = f"我已创建工单 {ticket.ticket_no}，但还需要补充材料：{decision.rationale}"
    elif actions:
        done = "、".join(f"{a.action_type}:{a.status}" for a in actions)
        reply = f"我已按审核标准自动处理工单 {ticket.ticket_no}。执行结果：{done}。"
    else:
        reply = f"我已受理工单 {ticket.ticket_no}，当前结论：{decision.rationale}"
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
