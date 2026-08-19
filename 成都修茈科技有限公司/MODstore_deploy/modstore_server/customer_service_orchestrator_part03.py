# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def choose_standard(
    db: _facade().Session, intent: str
) -> _facade().Optional[_facade().CustomerServiceStandard]:
    return (
        db.query(_facade().CustomerServiceStandard)
        .filter(_facade().CustomerServiceStandard.auto_enabled.is_(True))
        .filter(_facade().CustomerServiceStandard.scenario.in_([intent, "general"]))
        .order_by(
            _facade().CustomerServiceStandard.scenario.desc(),
            _facade().CustomerServiceStandard.priority.asc(),
        )
        .first()
    )


def ensure_ticket(
    db: _facade().Session,
    *,
    user: _facade().User,
    session: _facade().CustomerServiceSession,
    intent: str,
    extracted: _facade().Dict[str, _facade().Any],
) -> _facade().CustomerServiceTicket:
    existing = (
        db.query(_facade().CustomerServiceTicket)
        .filter(_facade().CustomerServiceTicket.session_id == session.id)
        .filter(_facade().CustomerServiceTicket.status.in_(["open", "waiting_user", "processing"]))
        .order_by(_facade().CustomerServiceTicket.id.desc())
        .first()
    )
    if existing and existing.intent == intent:
        existing.evidence_json = _facade().json_dumps(extracted)
        existing.updated_at = _facade().datetime.now(_facade().timezone.utc)
        return existing
    ticket = _facade().CustomerServiceTicket(
        session_id=session.id,
        user_id=user.id,
        ticket_no=f"CS{_facade().datetime.now(_facade().timezone.utc).strftime('%Y%m%d%H%M%S')}{user.id:04d}{session.id:04d}",
        title=_facade().title_for_intent(intent, extracted),
        intent=intent,
        subject_type=_facade().subject_type_for_intent(intent),
        subject_id=str(extracted.get("order_no") or extracted.get("catalog_id") or ""),
        status="open",
        priority="high" if intent == "catalog_review" else "normal",
        evidence_json=_facade().json_dumps(extracted),
        summary=str(extracted.get("reason") or "")[:2000],
    )
    db.add(ticket)
    db.flush()
    _facade().audit(
        db,
        event_type="ticket_created",
        session_id=session.id,
        ticket_id=ticket.id,
        actor=user,
        detail={"intent": intent, "extracted": extracted},
    )
    _facade().enqueue_customer_service_event(
        db,
        "customer_service.ticket_created",
        ticket.ticket_no,
        {"ticket_id": ticket.id, "ticket_no": ticket.ticket_no, "intent": intent},
    )
    return ticket


def decide(
    db: _facade().Session,
    *,
    user: _facade().User,
    ticket: _facade().CustomerServiceTicket,
    standard: _facade().Optional[_facade().CustomerServiceStandard],
    extracted: _facade().Dict[str, _facade().Any],
    message: str,
) -> _facade().CustomerServiceDecision:
    missing = _facade().missing_fields(ticket.intent, extracted)
    risk_level = standard.risk_level if standard else "low"
    if missing:
        decision = "needs_more_info"
        prefix = "已收到图片。" if extracted.get("has_image") else ""
        rationale = f"{prefix}还需要补充：{'、'.join(_facade().humanize_field_names(missing))}。"
        confidence = 0.45
    elif ticket.intent == "catalog_review" and (not user.is_admin):
        decision = "approved"
        rationale = "已进入审核队列，结果会尽快反馈给你。"
        confidence = 0.72
    elif ticket.intent in _facade().FOLLOWUP_INTENTS:
        decision = "accepted"
        rationale = "已登记，我们会跟进处理。可继续补充截图、页面位置或复现步骤。"
        confidence = 0.7
    else:
        decision = "approved"
        rationale = "材料已齐，已开始自动受理。"
        confidence = 0.82
    row = _facade().CustomerServiceDecision(
        ticket_id=ticket.id,
        user_id=user.id,
        standard_id=standard.id if standard else None,
        intent=ticket.intent,
        decision=decision,
        risk_level=risk_level,
        confidence=confidence,
        rationale=rationale,
        extracted_json=_facade().json_dumps(extracted),
        criteria_json=_facade().json_dumps(
            [{"name": standard.name if standard else "默认客服规则", "missing": missing}]
        ),
    )
    db.add(row)
    db.flush()
    return row


def missing_fields(intent: str, extracted: _facade().Dict[str, _facade().Any]) -> list[str]:
    required = {
        "refund": ["order_no", "reason"],
        "catalog_complaint": ["catalog_id", "complaint_type", "reason"],
        "catalog_review": ["catalog_id"],
        "llm_extension": ["provider", "model", "reason"],
    }.get(intent, [])
    return [key for key in required if not extracted.get(key)]


def humanize_field_names(keys: list[str]) -> list[str]:
    labels = {
        "order_no": "订单号",
        "reason": "原因说明",
        "catalog_id": "商品编号",
        "complaint_type": "问题类型",
        "provider": "模型厂商",
        "model": "模型名称",
    }
    return [labels.get(k, k) for k in keys]


def _attach_image_to_ticket(ticket: _facade().CustomerServiceTicket, *, message_id: int) -> None:
    """把用户附图记入工单证据（完整图片在消息 payload，工单侧只留索引）。"""
    evidence = _facade().json_loads(ticket.evidence_json, {})
    if not isinstance(evidence, dict):
        evidence = {}
    atts = list(evidence.get("attachments") or [])
    atts.append(
        {
            "type": "image",
            "message_id": message_id,
            "note": "用户补充截图",
            "at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
    )
    evidence["attachments"] = atts[-20:]
    evidence["has_image"] = True
    ticket.evidence_json = _facade().json_dumps(evidence)
    ticket.updated_at = _facade().datetime.now(_facade().timezone.utc)


def plan_actions(
    db: _facade().Session,
    *,
    user: _facade().User,
    ticket: _facade().CustomerServiceTicket,
    decision: _facade().CustomerServiceDecision,
    extracted: _facade().Dict[str, _facade().Any],
) -> list[_facade().Any]:
    actions: list[_facade().Any] = []
    if decision.decision == "accepted" and ticket.intent == "product_issue":
        return []
    if decision.decision != "approved":
        return []
    if ticket.intent == "refund":
        action = _facade().build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="refund.apply",
            target_type="order",
            target_id=str(extracted.get("order_no") or ""),
            request=extracted,
        )
        _facade().execute_action(db, action, user)
        actions.append(action)
    elif ticket.intent == "catalog_complaint":
        action = _facade().build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="catalog.complaint.create",
            target_type="catalog_item",
            target_id=str(extracted.get("catalog_id") or ""),
            request=extracted,
        )
        _facade().execute_action(db, action, user)
        actions.append(action)
    elif ticket.intent == "catalog_review":
        action = _facade().build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="catalog.compliance.review",
            target_type="catalog_item",
            target_id=str(extracted.get("catalog_id") or ""),
            request={**extracted, "compliance_status": "reviewing"},
        )
        _facade().execute_action(db, action, user)
        actions.append(action)
    elif ticket.intent == "llm_extension":
        prov = str(extracted.get("provider") or "").strip().lower()
        mod = str(extracted.get("model") or "").strip()
        action = _facade().build_action(
            db,
            ticket_id=ticket.id,
            decision_id=decision.id,
            user_id=user.id,
            action_type="llm.model_capability.propose",
            target_type="llm_model",
            target_id=f"{prov}:{mod}"[:240],
            request=extracted,
        )
        _facade().execute_action(db, action, user)
        actions.append(action)
    followup = _facade()._maybe_dispatch_employee_followup(
        db, user=user, ticket=ticket, decision=decision, extracted=extracted
    )
    if followup is not None:
        actions.append(followup)
    return actions


def _maybe_dispatch_employee_followup(
    db: _facade().Session,
    *,
    user: _facade().User,
    ticket: _facade().CustomerServiceTicket,
    decision: _facade().CustomerServiceDecision,
    extracted: _facade().Dict[str, _facade().Any],
) -> _facade().Optional[_facade().Any]:
    """对需要落地代码/文档/配置改动的工单，派一名 AI 员工处理。

    仅在 ``decision.decision == 'approved'`` 时同步触发；``product_issue`` 走
    API 层 ``ops.intake.customer_ticket`` 异步 bus，避免阻塞客服会话。
    返回一个 ``CustomerServiceAction``（已 ``completed`` 或 ``failed``），便于
    回写工单的执行历史；无匹配 intent 时返回 ``None``。
    """
    if decision.decision != "approved":
        return None
    intent = ticket.intent or ""
    brief = ""
    if intent == "catalog_complaint":
        brief = f"用户对商品 ID {extracted.get('catalog_id') or '未知'} 提出投诉（类型：{extracted.get('complaint_type') or '未指定'}）。请相关员工评估证据并产出处置建议（更新合规标签 / 修订商品文案 / 补充使用说明等）。原因摘要：{(extracted.get('reason') or '')[:400]}"
    elif intent == "catalog_review":
        brief = f"商品 ID {extracted.get('catalog_id') or '未知'} 进入合规审核。请相关员工核对 manifest / catalog 元数据，必要时产出文档/字段修改建议。"
    elif intent == "llm_extension":
        prov = extracted.get("provider") or ""
        mod = extracted.get("model") or ""
        brief = f"用户申请扩展大模型：provider={prov} model={mod}。请评估接入成本，产出 modstore_server/llm_*.py 与文档的最小变更建议。"
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
        action = _facade().build_action(
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
        action.result_json = _facade().json_dumps({"ok": ok, "summary": str(out)[:4000]})
        action.error = "" if ok else str(out.get("error") or "")[:1000]
        db.flush()
        return action
    except Exception as exc:
        action = _facade().build_action(
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
