# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# ruff: noqa: E402, F401
# Compatibility facade: late imports intentionally follow the dynamic facade resolver.
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


from modstore_server.customer_service_orchestrator_part02_part01_part01 import (
    _enrich_cs_context as _enrich_cs_context,
    ensure_session as ensure_session,
)


def handle_customer_message(
    db: _facade().Session,
    *,
    user: _facade().User,
    message: str,
    session_id: _facade().Optional[int] = None,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    context = _facade()._enrich_cs_context(user, context, db=db)
    text = (message or "").strip()
    image_data_url = str((context or {}).get("image_data_url") or "").strip()
    if image_data_url and (not image_data_url.startswith("data:image/")):
        image_data_url = ""
    if len(image_data_url) > 4500000:
        image_data_url = ""
    if not text and image_data_url:
        text = "[用户补充了图片资料]"
    session = _facade().ensure_session(db, user=user, session_id=session_id, context=context)
    session.last_message = text
    session.updated_at = _facade().datetime.now(_facade().timezone.utc)
    ctx_for_store = {k: v for (k, v) in (context or {}).items() if k not in {"image_data_url"}}
    if image_data_url:
        ctx_for_store["has_image"] = True
    user_payload: _facade().Dict[str, _facade().Any] = {"context": ctx_for_store}
    if image_data_url:
        user_payload["image_data_url"] = image_data_url
        user_payload["has_image"] = True
    user_msg = _facade().CustomerServiceMessage(
        session_id=session.id,
        user_id=user.id,
        role="user",
        content=text,
        payload_json=_facade().json_dumps(user_payload),
    )
    db.add(user_msg)
    db.flush()
    if _facade()._looks_like_forbidden_privilege_request(text):
        reply = _facade()._refuse_forbidden_privilege_reply(text)
        assistant_msg = _facade().CustomerServiceMessage(
            session_id=session.id,
            ticket_id=None,
            user_id=user.id,
            role="assistant",
            content=reply,
            payload_json=_facade().json_dumps(
                {
                    "ticket": None,
                    "decision": None,
                    "actions": [],
                    "cards": [],
                    "intent": {
                        "intent": "forbidden_request",
                        "need_ticket": False,
                        "confidence": 1.0,
                        "source": "safety",
                        "reason": "privilege_escalation_refused",
                    },
                    "safety": {"refused": True, "kind": "privilege_escalation"},
                }
            ),
        )
        db.add(assistant_msg)
        _facade().audit(
            db,
            event_type="forbidden_request_refused",
            session_id=session.id,
            actor=user,
            detail={"kind": "privilege_escalation", "text": text[:500]},
        )
        return {
            "ok": True,
            "session": _facade().session_payload(session),
            "ticket": None,
            "message": {
                "role": "assistant",
                "content": reply,
                "payload": _facade().json_loads(assistant_msg.payload_json, {}),
            },
            "decision": None,
            "actions": [],
            "cards": [],
            "intent": {
                "intent": "forbidden_request",
                "need_ticket": False,
                "confidence": 1.0,
                "source": "safety",
                "reason": "privilege_escalation_refused",
            },
        }
    extracted = _facade().extract_fields(text, context)
    if image_data_url:
        extracted["has_image"] = True
    classify_text = text
    prior_issue = ""
    if _facade()._is_escalate_only(text) or (
        _facade().wants_ticket_escalation(text) and (not _facade()._looks_like_concrete_issue(text))
    ):
        ctx_reason = str((context or {}).get("reason") or extracted.get("reason") or "").strip()
        if ctx_reason and (not _facade()._is_escalate_only(ctx_reason)):
            prior_issue = ctx_reason
        else:
            prior_issue = _facade()._peek_prior_user_issue(db, session=session, exclude_text=text)
        if prior_issue:
            classify_text = prior_issue
            for k, v in _facade().extract_fields(prior_issue, context).items():
                extracted.setdefault(k, v)
            extracted["reason"] = prior_issue[:500]
            extracted["_issue_summary"] = _facade()._summarize_user_issue(prior_issue)
    safety_text = prior_issue or classify_text or text
    if _facade()._looks_like_forbidden_privilege_request(safety_text):
        reply = _facade()._refuse_forbidden_privilege_reply(safety_text)
        assistant_msg = _facade().CustomerServiceMessage(
            session_id=session.id,
            ticket_id=None,
            user_id=user.id,
            role="assistant",
            content=reply,
            payload_json=_facade().json_dumps(
                {
                    "ticket": None,
                    "decision": None,
                    "actions": [],
                    "cards": [],
                    "intent": {
                        "intent": "forbidden_request",
                        "need_ticket": False,
                        "confidence": 1.0,
                        "source": "safety",
                        "reason": "privilege_escalation_refused",
                    },
                    "safety": {"refused": True, "kind": "privilege_escalation"},
                }
            ),
        )
        db.add(assistant_msg)
        _facade().audit(
            db,
            event_type="forbidden_request_refused",
            session_id=session.id,
            actor=user,
            detail={
                "kind": "privilege_escalation",
                "text": text[:200],
                "prior_issue": (prior_issue or "")[:300],
            },
        )
        return {
            "ok": True,
            "session": _facade().session_payload(session),
            "ticket": None,
            "message": {
                "role": "assistant",
                "content": reply,
                "payload": _facade().json_loads(assistant_msg.payload_json, {}),
            },
            "decision": None,
            "actions": [],
            "cards": [],
            "intent": {
                "intent": "forbidden_request",
                "need_ticket": False,
                "confidence": 1.0,
                "source": "safety",
                "reason": "privilege_escalation_refused",
            },
        }
    classified = _facade().classify_customer_intent(classify_text, extracted, context=context)
    intent = str(classified.get("intent") or "general")
    need_ticket = bool(classified.get("need_ticket"))
    if _facade().wants_ticket_escalation(text):
        need_ticket = True
    domain_clarify = _facade()._parse_domain_clarify_reply(text)
    domain_info = _facade().resolve_issue_domain(
        intent=intent,
        text=classify_text or text,
        extracted=extracted,
        context=context,
        llm_domain=classified.get("issue_domain") or domain_clarify or None,
    )
    if domain_clarify:
        domain_info = {
            "domain": domain_clarify,
            "label": _facade().ISSUE_DOMAIN_LABELS.get(domain_clarify, "平台"),
            "source": "user_clarify",
        }
    extracted["issue_domain"] = domain_info["domain"]
    extracted["issue_domain_label"] = domain_info["label"]
    extracted["issue_domain_source"] = domain_info["source"]
    if domain_clarify:
        extracted["user_confirmed_domain"] = domain_clarify
        extracted["user_followup"] = (text or "").strip()[:200]
    classified["issue_domain"] = domain_info["domain"]
    classified["issue_domain_label"] = domain_info["label"]
    session.intent = intent
    standard = _facade().choose_standard(db, intent)
    open_ticket = (
        db.query(_facade().CustomerServiceTicket)
        .filter(_facade().CustomerServiceTicket.session_id == session.id)
        .filter(_facade().CustomerServiceTicket.status.in_(["open", "waiting_user", "processing"]))
        .order_by(_facade().CustomerServiceTicket.id.desc())
        .first()
    )
    if open_ticket:
        if open_ticket.status == "waiting_user" and intent in _facade().FOLLOWUP_INTENTS:
            intent = open_ticket.intent or intent
            session.intent = intent
            need_ticket = True
        elif open_ticket.intent == intent and intent in _facade().TICKET_INTENTS:
            need_ticket = True
        elif open_ticket.intent == "product_issue" and (
            domain_clarify
            or extracted.get("has_image")
            or _facade()._looks_like_concrete_issue(text)
            or _facade()._looks_like_product_issue(text)
        ):
            intent = "product_issue"
            session.intent = intent
            need_ticket = True
            standard = _facade().choose_standard(db, intent)
            prior_summary = str(open_ticket.summary or "").strip()
            if prior_summary and (
                domain_clarify
                or _facade()._is_escalate_only(text)
                or (not _facade()._looks_like_concrete_issue(text))
            ):
                extracted["reason"] = prior_summary[:500]
                extracted["_issue_summary"] = _facade()._summarize_user_issue(prior_summary)
    if need_ticket:
        _facade()._enrich_extracted_from_prior_issue(
            db, session=session, text=text, extracted=extracted
        )
    if not need_ticket:
        reply = _facade()._chat_only_reply(text, intent=intent, user=user, db=db)
        cards: list[_facade().Dict[str, _facade().Any]] = []
        assistant_msg = _facade().CustomerServiceMessage(
            session_id=session.id,
            ticket_id=None,
            user_id=user.id,
            role="assistant",
            content=reply,
            payload_json=_facade().json_dumps(
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
        _facade().audit(
            db,
            event_type="chat_only_reply",
            session_id=session.id,
            actor=user,
            detail={"intent": intent, "classified": classified, "extracted": extracted},
        )
        return {
            "ok": True,
            "session": _facade().session_payload(session),
            "ticket": None,
            "message": {
                "role": "assistant",
                "content": reply,
                "payload": _facade().json_loads(assistant_msg.payload_json, {}),
            },
            "decision": None,
            "actions": [],
            "cards": cards,
            "intent": classified,
        }
    ticket = _facade().ensure_ticket(
        db, user=user, session=session, intent=intent, extracted=extracted
    )
    user_msg.ticket_id = ticket.id
    if image_data_url:
        _facade()._attach_image_to_ticket(ticket, message_id=int(user_msg.id))
    decision = _facade().decide(
        db,
        user=user,
        ticket=ticket,
        standard=standard,
        extracted=extracted,
        message=text,
    )
    actions = _facade().plan_actions(
        db, user=user, ticket=ticket, decision=decision, extracted=extracted
    )
    integration_actions = _facade().execute_matching_integrations(
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
    if decision.decision == "rejected":
        ticket.status = "resolved"
        ticket.closed_at = _facade().datetime.now(_facade().timezone.utc)
    elif (
        decision.decision == "approved"
        and actions
        and all((a.status in {"completed", "skipped"} for a in actions))
    ):
        ticket.status = "resolved"
        ticket.closed_at = _facade().datetime.now(_facade().timezone.utc)
    elif decision.decision == "needs_more_info":
        ticket.status = "waiting_user"
    else:
        ticket.status = "processing"
        ticket.closed_at = None
    ticket.updated_at = _facade().datetime.now(_facade().timezone.utc)
    reply, cards = _facade().build_reply(
        ticket=ticket, decision=decision, actions=actions, extracted=extracted
    )
    if intent in {"general", "greeting", "product_issue"}:
        issue_text = _facade()._resolve_issue_text_for_reply(
            extracted=extracted, text=text, prior_issue=prior_issue, ticket=ticket
        )
        if intent == "product_issue":
            summary = _facade()._summarize_user_issue(issue_text)
            domain_cn = str(extracted.get("issue_domain_label") or "平台")
            if extracted.get("user_confirmed_domain"):
                reply = f"我是小C。已确认归属为{domain_cn}，工单「{summary}」继续处理中；已通过现有客服工单通道通知值班员工排查修复，有进展会更新本工单。也可继续补充截图或具体页面。"
            else:
                reply = f"我是小C。已登记{domain_cn}功能问题：「{summary}」，正在跟进处理；还不会结案。可继续补充截图或具体页面。"
        else:
            xiaoc_reply = _facade()._xiaoc_general_reply(
                issue_text, user=user, db=db, ticketed=True
            )
            if xiaoc_reply:
                reply = xiaoc_reply
        if ticket and issue_text and (not _facade()._is_escalate_only(issue_text)):
            ticket.summary = issue_text[:2000]
            ticket.title = _facade().title_for_intent(intent, {**extracted, "reason": issue_text})
            ev = _facade().json_loads(ticket.evidence_json, {})
            if not isinstance(ev, dict):
                ev = {}
            ev.update(
                {
                    "issue_domain": extracted.get("issue_domain"),
                    "issue_domain_label": extracted.get("issue_domain_label"),
                    "issue_domain_source": extracted.get("issue_domain_source"),
                    "reason": issue_text[:500],
                }
            )
            if extracted.get("user_confirmed_domain"):
                followups = list(ev.get("followups") or [])
                followups.append(
                    {
                        "type": "domain_clarify",
                        "text": str(extracted.get("user_followup") or text)[:200],
                        "issue_domain": extracted.get("issue_domain"),
                        "at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
                    }
                )
                ev["followups"] = followups[-20:]
                ev["user_confirmed_domain"] = extracted.get("user_confirmed_domain")
            ticket.evidence_json = _facade().json_dumps(ev)
    assistant_msg = _facade().CustomerServiceMessage(
        session_id=session.id,
        ticket_id=ticket.id,
        user_id=user.id,
        role="assistant",
        content=reply,
        payload_json=_facade().json_dumps(
            {
                "ticket": _facade().ticket_payload(ticket),
                "decision": _facade().decision_payload(decision),
                "actions": [_facade().action_payload(a) for a in actions],
                "cards": cards,
                "intent": classified,
            }
        ),
    )
    db.add(assistant_msg)
    _facade().audit(
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
    _facade().enqueue_customer_service_event(
        db,
        "customer_service.decision_made",
        f"{ticket.ticket_no}:{decision.id}",
        {
            "ticket_id": ticket.id,
            "ticket_no": ticket.ticket_no,
            "decision_id": decision.id,
            "intent": intent,
            "decision": decision.decision,
            "issue_domain": extracted.get("issue_domain"),
            "user_confirmed_domain": extracted.get("user_confirmed_domain"),
        },
    )
    return {
        "ok": True,
        "session": _facade().session_payload(session),
        "ticket": _facade().ticket_payload(ticket),
        "message": {
            "role": "assistant",
            "content": reply,
            "payload": _facade().json_loads(assistant_msg.payload_json, {}),
        },
        "decision": _facade().decision_payload(decision),
        "actions": [_facade().action_payload(a) for a in actions],
        "cards": cards,
        "intent": classified,
    }


from modstore_server.customer_service_orchestrator_part02_part01_part02 import (
    extract_fields as extract_fields,
    is_greeting as is_greeting,
    wants_ticket_escalation as wants_ticket_escalation,
    should_create_ticket as should_create_ticket,
    infer_intent as infer_intent,
    classify_customer_intent as classify_customer_intent,
    _parse_intent_json as _parse_intent_json,
    _llm_classify_intent as _llm_classify_intent,
)
