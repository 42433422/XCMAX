# ruff: noqa
"""Implementation extracted from the public facade module."""
from __future__ import annotations
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def _enrich_cs_context(
    user: _facade().User,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    *,
    db: _facade().Optional[_facade().Session] = None,
) -> _facade().Dict[str, _facade().Any]:
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
    except Exception:
        ctx["user_id"] = getattr(user, "id", None)
        name = str(getattr(user, "username", None) or "").strip()
        if name:
            ctx["display_name"] = name[:32]
    return ctx


def ensure_session(
    db: _facade().Session,
    *,
    user: _facade().User,
    session_id: _facade().Optional[int] = None,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().CustomerServiceSession:
    enriched = _facade()._enrich_cs_context(user, context, db=db)
    if session_id:
        row = (
            db.query(_facade().CustomerServiceSession)
            .filter(
                _facade().CustomerServiceSession.id == session_id,
                _facade().CustomerServiceSession.user_id == user.id,
            )
            .first()
        )
        if row:
            try:
                prev = _facade().json_loads(row.context_json) if row.context_json else {}
                if not isinstance(prev, dict):
                    prev = {}
                merged = {**prev, **{k: v for (k, v) in enriched.items() if v is not None}}
                row.context_json = _facade().json_dumps(merged)
            except Exception:
                pass
            return row
    row = _facade().CustomerServiceSession(
        user_id=user.id,
        channel=str(enriched.get("channel") or "web")[:32],
        status="open",
        title="AI 客服会话",
        context_json=_facade().json_dumps(enriched),
    )
    db.add(row)
    db.flush()
    _facade().audit(
        db,
        event_type="session_created",
        session_id=row.id,
        actor=user,
        detail={"channel": row.channel, "context": context or {}},
    )
    return row


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
        db, user=user, ticket=ticket, standard=standard, extracted=extracted, message=text
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
    (reply, cards) = _facade().build_reply(
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


def extract_fields(
    text: str, context: _facade().Dict[str, _facade().Any]
) -> _facade().Dict[str, _facade().Any]:
    data: _facade().Dict[str, _facade().Any] = {}
    for key in (
        "order_no",
        "catalog_id",
        "pkg_id",
        "item_name",
        "complaint_type",
        "reason",
        "artifact",
        "material_category",
        "account_custom",
        "issue_domain",
        "scene",
    ):
        value = context.get(key)
        if value not in (None, ""):
            data[key] = value
    order = _facade().ORDER_RE.search(text)
    if order and (not data.get("order_no")):
        data["order_no"] = order.group(1)
    catalog = _facade().CATALOG_RE.search(text)
    if catalog and (not data.get("catalog_id")):
        data["catalog_id"] = int(catalog.group(1))
    if not data.get("reason") and text and (not _facade()._is_escalate_only(text)):
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
    lp = _facade().LLM_PROVIDER_RE.search(text)
    if lp:
        data["provider"] = lp.group(1).lower()
    lm = _facade().LLM_MODEL_RE.search(text)
    if lm:
        data["model"] = lm.group(1).strip()
    if not data.get("provider") or not data.get("model"):
        sl = _facade().LLM_SLASH_RE.search(text)
        if sl:
            data.setdefault("provider", sl.group(1).lower())
            data.setdefault("model", sl.group(2).strip())
    return data


def is_greeting(text: str) -> bool:
    return bool(_facade().GREETING_RE.match((text or "").strip()))


def wants_ticket_escalation(text: str) -> bool:
    return bool(_facade().ESCALATE_RE.search(text or ""))


def should_create_ticket(
    intent: str, text: str, extracted: _facade().Optional[_facade().Dict[str, _facade().Any]] = None
) -> bool:
    """是否建单：明确升级；或业务意图且关键材料已齐（避免闲聊/示例误建单）。"""
    if _facade().wants_ticket_escalation(text):
        return True
    if intent not in _facade().TICKET_INTENTS:
        return False
    required = {
        "refund": ["order_no", "reason"],
        "catalog_complaint": ["catalog_id", "complaint_type", "reason"],
        "catalog_review": ["catalog_id"],
        "llm_extension": ["provider", "model", "reason"],
    }.get(intent)
    if not required:
        return False
    data = extracted or {}
    return all((data.get(key) for key in required))


def infer_intent(
    text: str,
    extracted: _facade().Dict[str, _facade().Any],
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
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
    if _facade().is_greeting(text):
        return "greeting"
    if (
        extracted.get("provider")
        and extracted.get("model")
        and any(
            (x in text for x in ("模型扩展", "开通模型", "模型上架", "不支持该模型", "申请模型"))
        )
    ):
        return "llm_extension"
    if "退款" in text or "refund" in lowered:
        return "refund"
    if any((word in text for word in ("投诉", "抄袭", "侵权", "无法下载", "举报"))):
        return "catalog_complaint"
    if any((word in text for word in ("上架", "审核", "合规", "下架"))):
        return "catalog_review"
    if any(
        (
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
        )
    ):
        return "account_support"
    if any(
        (
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
        )
    ) or (("模型" in text or "model" in lowered) and ("扩展" in text or "上架" in text or "审核" in text)):
        return "llm_extension"
    return "general"


def classify_customer_intent(
    text: str,
    extracted: _facade().Dict[str, _facade().Any],
    *,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
) -> _facade().Dict[str, _facade().Any]:
    """明确业务关键词走规则；模糊语义优先 LLM；LLM 失败再缺陷兜底。"""
    rule_intent = _facade().infer_intent(text, extracted, context=context)
    escalate = _facade().wants_ticket_escalation(text)
    if rule_intent not in {"general"}:
        return {
            "intent": rule_intent,
            "need_ticket": _facade().should_create_ticket(rule_intent, text, extracted),
            "confidence": 0.92 if rule_intent != "greeting" else 0.98,
            "source": "rules",
            "reason": "keyword_or_scene",
        }
    llm = _facade()._llm_classify_intent(text)
    if llm:
        intent = str(llm.get("intent") or "general").strip().lower()
        if intent not in _facade().KNOWN_INTENTS:
            intent = "general"
        if intent == "general" and _facade()._looks_like_product_issue(text):
            intent = "product_issue"
        if intent in _facade().FOLLOWUP_INTENTS:
            need_ticket = escalate
        else:
            need_ticket = _facade().should_create_ticket(intent, text, extracted)
            if escalate:
                need_ticket = True
        return {
            "intent": intent,
            "need_ticket": need_ticket,
            "confidence": float(llm.get("confidence") or 0.6),
            "source": "llm",
            "reason": str(llm.get("reason") or "")[:200],
        }
    if _facade()._looks_like_product_issue(text):
        return {
            "intent": "product_issue",
            "need_ticket": escalate,
            "confidence": 0.62,
            "source": "rules",
            "reason": "product_issue_fallback",
        }
    return {
        "intent": "general",
        "need_ticket": escalate,
        "confidence": 0.55,
        "source": "rules",
        "reason": "escalate" if escalate else "default_general",
    }


def _parse_intent_json(content: str) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """解析意图 JSON；兼容截断输出（MiniMax thinking 占 token 时常见）。"""
    raw = (content or "").strip()
    if not raw:
        return None
    if "```" in raw:
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        raw = raw.lstrip("json").strip()
    start = raw.find("{")
    if start < 0:
        m = _facade().re.search('"intent"\\s*:\\s*"([a-z_]+)"', raw, _facade().re.I)
        if not m:
            return None
        return {
            "intent": m.group(1).lower(),
            "need_ticket": False,
            "confidence": 0.55,
            "reason": "partial",
        }
    chunk = raw[start:]
    end = chunk.rfind("}")
    if end > 0:
        try:
            data = _facade().json.loads(chunk[: end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            pass
    m = _facade().re.search('"intent"\\s*:\\s*"([a-z_]+)"', chunk, _facade().re.I)
    if not m:
        return None
    conf_m = _facade().re.search('"confidence"\\s*:\\s*([0-9]*\\.?[0-9]+)', chunk)
    need_m = _facade().re.search('"need_ticket"\\s*:\\s*(true|false)', chunk, _facade().re.I)
    return {
        "intent": m.group(1).lower(),
        "need_ticket": need_m.group(1).lower() == "true" if need_m else False,
        "confidence": float(conf_m.group(1)) if conf_m else 0.55,
        "reason": "truncated_json",
    }


def _llm_classify_intent(text: str) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
    """同步包装平台 LLM；失败或未配置时返回 None。"""
    flag = (_facade().os.environ.get("MODSTORE_CS_LLM_INTENT") or "1").strip().lower()
    if flag in {"0", "false", "off", "no"}:
        return None
    sample = (text or "").strip()
    if not sample or len(sample) < 2:
        return None

    async def _inner() -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
        from modstore_server.services.llm import (
            chat_dispatch_via_platform_only,
            resolve_platform_bench_llm,
        )

        (prov, mdl) = resolve_platform_bench_llm()
        if not prov or not mdl:
            return None
        out = await chat_dispatch_via_platform_only(
            prov,
            mdl,
            [
                {"role": "system", "content": _facade()._INTENT_CLASSIFY_PROMPT},
                {"role": "user", "content": f"请分类下面这句话，只输出 JSON：\n{sample[:1500]}"},
            ],
            max_tokens=512,
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
        if not content and isinstance(out.get("raw"), dict):
            blocks = out["raw"].get("content")
            if isinstance(blocks, list):
                for b in blocks:
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                        content = str(b["text"])
                        break
        return _facade()._parse_intent_json(content)

    try:
        with _facade().concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_facade().asyncio.run, _inner()).result(timeout=15)
    except Exception:
        return None


def _chat_only_reply(
    text: str,
    *,
    intent: str,
    user: _facade().Optional[_facade().User] = None,
    db: _facade().Optional[_facade().Session] = None,
) -> str:
    if intent == "greeting" or _facade().is_greeting(text):
        name = ""
        try:
            from modstore_server.xiaoc_cs_ssot import resolve_user_identity

            if user is not None:
                ident = resolve_user_identity(user, db=db, source="market_cs")
                if ident.display_name and ident.display_name not in {"用户", "访客", "匿名访客"}:
                    name = ident.display_name
        except Exception:
            pass
        hello = f"{name}，" if name else ""
        return f"我是小C。{hello}你好！有什么可以帮你的？比如产品怎么买、会员权益，或订单/退款问题，直接说就行。"
    if intent == "refund":
        return "我是小C。可以帮你办退款。请发一下订单号和退款原因；材料齐后点击「提交工单」，我会正式登记处理。"
    if intent == "catalog_complaint":
        return "我是小C。投诉可以受理。请补充商品 ID、问题类型和具体说明；齐了之后点击「提交工单」即可。"
    if intent == "product_issue":
        summary = _facade()._summarize_user_issue(text)
        return f"我是小C。收到，这是功能/界面问题：「{summary}」。方便补充一下大概在哪个页面、能否复现吗？若是某个市场上架软件或你们账号定制的 Mod/员工，也可以一并说明。需要正式跟进修复时，点击「提交工单」即可。"
    if intent == "account_support":
        return "我是小C。账号/权益问题可以先说明现象（比如未到账、余额不对）；需要正式核查时，点击「提交工单」。"
    xiaoc = _facade()._xiaoc_general_reply(text, user=user, db=db, ticketed=False)
    if xiaoc:
        return xiaoc
    return "我是小C。已收到你的问题。你可以继续补充细节；若需要平台正式受理，点击「提交工单」即可。"
