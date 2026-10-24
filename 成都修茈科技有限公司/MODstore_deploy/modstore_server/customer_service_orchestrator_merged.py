"""Auto-merged part* modules (debt24)."""
from __future__ import annotations
import importlib
from modstore_server.operational_errors import RECOVERABLE_ERRORS
from typing import Any
from modstore_server.customer_issue_delivery_contract import (
    projected_dispatch_status,
    record_team_progress,
    role_progress_state,
    team_action_state,
    team_succeeded,
)

# --- from customer_service_orchestrator_part01.py ---
"""Implementation extracted from the public facade module."""


import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def _parse_domain_clarify_reply(text: str) -> str:
    """用户短句确认归属：是平台 / 是软件 / 是定制。返回 domain 或空串。"""
    t = _facade().re.sub("\\s+", "", (text or "").strip())
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

# --- from customer_service_orchestrator_part02_part01_part02.py ---
"""Implementation extracted from the public facade module."""


from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


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


def resolve_triage_lane(intent: str) -> str:
    """intent → 分诊车道。账号/不确定 → ultimate_review（终极员工可介入）；ops_fast_fix 预留。"""
    if intent == "product_issue":
        return "product_defect"
    if intent in {"account_support", "general", "greeting"}:
        return "ultimate_review"
    if intent in {"refund", "catalog_complaint", "catalog_review", "llm_extension"}:
        return "commerce"
    return "general"


def _account_word_is_product_defect(text: str) -> bool:
    """「账号」弱信号：同句已描述产品缺陷时归 product_issue，避免硬吞建单。"""
    defect_words = ("产品问题", "功能问题", "缺陷")
    return _facade()._looks_like_product_issue(text) or any((w in text for w in defect_words))


def wants_ticket_escalation(text: str) -> bool:
    return bool(_facade().ESCALATE_RE.search(text or ""))


def should_create_ticket(
    intent: str,
    text: str,
    extracted: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
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
            (
                x in text
                for x in (
                    "模型扩展",
                    "开通模型",
                    "模型上架",
                    "不支持该模型",
                    "申请模型",
                )
            )
        )
    ):
        return "llm_extension"
    if "退款" in text or "refund" in lowered:
        return "refund"
    if any((word in text for word in ("投诉", "抄袭", "侵权", "无法下载", "举报"))):
        return "catalog_complaint"
    if any((word in text for word in ("上架", "审核", "合规", "下架"))):
        return "catalog_review"
    # 明确的产品缺陷描述优先于登录、余额等账号词；普通账号求助仍归账号支持。
    account_marks = ("会员", "权益", "额度", "登录", "余额", "钱包", "充值", "到账", "扣费", "账单")
    has_account_mark = any((word in text for word in account_marks + ("消费记录",)))
    if _account_word_is_product_defect(text) and ("账号" in text or has_account_mark):
        return "product_issue"
    if "账号" in text or has_account_mark:
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
            "triage_lane": resolve_triage_lane(rule_intent),
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
            "triage_lane": resolve_triage_lane(intent),
            "need_ticket": need_ticket,
            "confidence": float(llm.get("confidence") or 0.6),
            "source": "llm",
            "reason": str(llm.get("reason") or "")[:200],
        }
    if _facade()._looks_like_product_issue(text):
        return {
            "intent": "product_issue",
            "triage_lane": resolve_triage_lane("product_issue"),
            "need_ticket": escalate,
            "confidence": 0.62,
            "source": "rules",
            "reason": "product_issue_fallback",
        }
    return {
        "intent": "general",
        "triage_lane": resolve_triage_lane("general"),
        "need_ticket": escalate,
        "confidence": 0.55,
        "source": "rules",
        "reason": "escalate" if escalate else "default_general",
    }


def _parse_intent_json(
    content: str,
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
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
        except RECOVERABLE_ERRORS:
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


def _llm_classify_intent(
    text: str,
) -> _facade().Optional[_facade().Dict[str, _facade().Any]]:
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

        prov, mdl = resolve_platform_bench_llm()
        if not prov or not mdl:
            return None
        out = await chat_dispatch_via_platform_only(
            prov,
            mdl,
            [
                {"role": "system", "content": _facade()._INTENT_CLASSIFY_PROMPT},
                {
                    "role": "user",
                    "content": f"请分类下面这句话，只输出 JSON：\n{sample[:1500]}",
                },
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
    except RECOVERABLE_ERRORS:
        return None

# --- from customer_service_orchestrator_part02_part01_part01.py ---
"""Implementation extracted from the public facade module."""


from modstore_server.operational_errors import RECOVERABLE_ERRORS
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
    except RECOVERABLE_ERRORS:
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
                merged = {
                    **prev,
                    **{k: v for (k, v) in enriched.items() if v is not None},
                }
                row.context_json = _facade().json_dumps(merged)
            except RECOVERABLE_ERRORS:
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

# --- from customer_service_orchestrator_part02_part01.py ---
"""Implementation extracted from the public facade module."""

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

# --- from customer_service_orchestrator_part02_part02.py ---
"""Implementation extracted from the public facade module."""


from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


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
                if ident.display_name and ident.display_name not in {
                    "用户",
                    "访客",
                    "匿名访客",
                }:
                    name = ident.display_name
        except RECOVERABLE_ERRORS:
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

# --- from customer_service_orchestrator_part03.py ---
"""Implementation extracted from the public facade module."""


import importlib

from modstore_server.operational_errors import RECOVERABLE_ERRORS


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
            [
                {
                    "name": standard.name if standard else "默认客服规则",
                    "missing": missing,
                }
            ]
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
    except RECOVERABLE_ERRORS as exc:
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

# --- from customer_service_orchestrator_part04_part01_part01.py ---
"""Implementation extracted from the public facade module."""


from modstore_server.operational_errors import RECOVERABLE_ERRORS
import importlib


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def _looks_like_raw_kb_line(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return True
    if _facade()._RAW_STRUCTURE_RE.search(s):
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
        if not ln or _facade()._looks_like_raw_kb_line(ln):
            continue
        if _facade().re.match("^\\d+[\\.、]\\s*", ln):
            ln = _facade().re.sub("^\\d+[\\.、]\\s*", "", ln)
        if ". " in ln[:5]:
            ln = ln.split(". ", 1)[-1].strip()
        if len(ln) < 8 or _facade()._looks_like_raw_kb_line(ln):
            continue
        tips.append(ln[:120])
        if len(tips) >= limit:
            break
    return tips


def _display_name_for_user(
    user: _facade().Optional[_facade().User],
    *,
    db: _facade().Optional[_facade().Session] = None,
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
    except RECOVERABLE_ERRORS:
        pass
    return (address, member_hint)


def _summarize_user_issue(user_text: str, *, max_len: int = 48) -> str:
    """压缩用户原话，供兜底复述；去掉寒暄前缀。"""
    t = _facade().re.sub("\\s+", "", (user_text or "").strip())
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


def _looks_like_forbidden_privilege_request(user_text: str) -> bool:
    """用户是否在索要管理员/提权等客服绝不能代办的权限。"""
    t = _facade().re.sub("\\s+", "", (user_text or "").strip().lower())
    if len(t) < 4:
        return False
    marks = (
        "管理员权限",
        "给我管理员",
        "开通管理员",
        "设为管理员",
        "设置管理员",
        "升级管理员",
        "变成管理员",
        "改成管理员",
        "超级管理员",
        "要admin",
        "给我admin",
        "开通admin",
        "admin权限",
        "root权限",
        "提权",
        "给我权限后台",
        "开放后台权限",
        "给我后台权限",
        "is_admin",
        "升为管理员",
    )
    return any((x in t for x in marks))


def _refuse_forbidden_privilege_reply(user_text: str) -> str:
    """明确拒答：不承诺、不建提权动作、不派员工改权限。"""
    _ = user_text
    return "我是小C。这个请求我不能办理：客服与 AI 员工都无法为账号开通管理员或其它提权。管理员权限只能由平台运营在后台按合规流程配置。如果你遇到的是具体功能问题（比如页面打不开、显示异常），直接说现象和页面，我可以帮你登记排查；但不会、也不能改你的账号权限。"


def _looks_like_product_issue(user_text: str) -> bool:
    """缺陷/界面故障语义：LLM 主判；此处仅作不可用/误判 general 时的兜底。"""
    t = (user_text or "").strip()
    if len(t) < 4 or _facade().is_greeting(t):
        return False
    if _facade()._looks_like_forbidden_privilege_request(t):
        return False
    if _facade().re.fullmatch(
        "(请)?(帮我)?(提交工单|创建工单|转人工|人工客服|升级处理|要工单|找人工)(吧|一下|处理|核查)?[.!！。]?",
        t,
    ):
        return False
    defect_marks = (
        "看不清",
        "看不见",
        "看不清字",
        "浅色",
        "深色",
        "对比度",
        "自选模型",
        "打不开",
        "进不去",
        "报错",
        "白屏",
        "黑屏",
        "闪退",
        "卡住",
        "加载失败",
        "加载不出来",
        "加载不出",
        "打不开网页",
        "打不开网站",
        "首页",
        "官网",
        "没反应",
        "用不了",
        "点不了",
        "点了没用",
        "按钮无效",
        "显示异常",
        "文字看不见",
        "界面",
        "崩了",
        "bug",
        "故障",
        "坏了",
    )
    return any((x in t for x in defect_marks))


def _looks_like_concrete_issue(user_text: str) -> bool:
    """用户是否已描述具体问题（而非空话/寒暄）。"""
    t = (user_text or "").strip()
    if len(t) < 6:
        return False
    if _facade().is_greeting(t):
        return False
    if _facade()._looks_like_product_issue(t):
        return True
    if any(
        (
            x in t
            for x in (
                "看不清",
                "看不见",
                "看不清字",
                "浅色",
                "深色",
                "对比",
                "对比度",
                "按钮",
                "自选模型",
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
        )
    ):
        return True
    return len(_facade().re.sub("\\s+", "", t)) >= 10


def _ack_concrete_issue_reply(user_text: str, *, hello: str, ticketed: bool) -> str:
    """知识库无可用摘录时：复述用户问题，不再甩购买/会员开场白。"""
    summary = _facade()._summarize_user_issue(user_text)
    if ticketed:
        return f"我是小C。{hello}已记下你的问题：「{summary}」，并登记工单；你可以继续补充页面位置、截图或复现步骤，我们会尽快处理。"
    return f"我是小C。{hello}收到，你说的是「{summary}」。方便补充一下大概在哪个页面/功能、是文字还是图标按钮吗？需要正式跟进修复时，点击「提交工单」即可。"


def _xiaoc_general_reply(
    user_text: str,
    *,
    user: _facade().Optional[_facade().User] = None,
    db: _facade().Optional[_facade().Session] = None,
    ticketed: bool = False,
) -> str:
    """general 意图走小C SSOT；只输出可读话术，绝不把知识库原始结构甩给客户。"""
    address, member_hint = _facade()._display_name_for_user(user, db=db)
    hello = (
        f"{address}{member_hint}，"
        if address and address not in {"用户", "访客", "匿名访客"}
        else ""
    )
    kb = ""
    try:
        from modstore_server.xiaoc_cs_ssot import knowledge_block_for_query

        kb = knowledge_block_for_query(user_text, top_k=4, mode="market_cs")
    except RECOVERABLE_ERRORS:
        kb = ""
    tips = _facade()._human_kb_tips(kb)
    concrete = _facade()._looks_like_concrete_issue(user_text)
    if concrete:
        return _facade()._ack_concrete_issue_reply(user_text, hello=hello, ticketed=ticketed)
    if tips:
        body = "；".join(tips)
        return f"我是小C。{hello}{body} 若还要补充，直接说具体场景就行。"
    if ticketed:
        return f"我是小C。{hello}已为你登记工单；你可以继续补充材料，我们会尽快处理。"
    return f"我是小C。{hello}可以先说说你的具体问题，比如购买、会员权益、订单或余额；需要正式受理时我会帮你建工单。"


def build_reply(
    *,
    ticket: _facade().CustomerServiceTicket,
    decision: _facade().CustomerServiceDecision,
    actions: list[_facade().Any],
    extracted: _facade().Dict[str, _facade().Any],
) -> tuple[str, list[_facade().Dict[str, _facade().Any]]]:
    intent = ticket.intent or "general"
    intent_cn = {
        "refund": "退款",
        "catalog_complaint": "投诉",
        "catalog_review": "上架审核",
        "account_support": "账号权益",
        "llm_extension": "模型扩展",
        "product_issue": "功能问题",
        "general": "咨询",
    }.get(intent, "咨询")
    if intent == "account_support":
        reply = "我是小C。已记下你的账号/余额问题。请补充最近一次充值或扣费的时间、金额，或钱包页截图；发完后我会继续处理。"
    elif decision.decision == "needs_more_info":
        reply = f"我是小C。{intent_cn}已收到。{decision.rationale}直接在对话里补充即可。"
    elif decision.decision == "accepted":
        reply = f"我是小C。你的{intent_cn}已登记，正在跟进处理；还不会结案。可继续补充截图或具体页面，我们会尽快回复。"
    elif intent == "refund" and any(
        getattr(a, "action_type", "") == "refund.apply" and getattr(a, "status", "") == "failed"
        for a in actions
    ):
        reply = "我是小C。退款申请未确认提交成功，不能视为已退款。原工单继续处理中，请保留支付凭证以便核对。"
    elif actions:
        action_cn = {
            "refund.apply": "退款申请",
            "catalog.complaint.create": "投诉登记",
            "catalog.compliance.review": "合规审核",
            "llm.model_capability.propose": "模型扩展申请",
            "employee.dispatch": "转交处理",
        }
        done = "、".join(
            (
                action_cn.get(str(getattr(a, "action_type", "")), "")
                for a in actions
                if getattr(a, "status", "") in {"completed", "skipped"}
            )
        )
        done = "、".join((x for x in done.split("、") if x))
        if done:
            reply = f"我是小C。你的{intent_cn}已受理，并已完成：{done}。"
        else:
            reply = f"我是小C。你的{intent_cn}已受理，正在处理中。"
    else:
        reply = f"我是小C。你的{intent_cn}已受理。{decision.rationale}"
    life = _facade().ticket_lifecycle_payload(ticket.status, ticket.decision_status)
    cards = [
        {
            "type": "ticket",
            "title": ticket.title,
            "ticket_no": ticket.ticket_no,
            "status": ticket.status,
            "intent": ticket.intent,
            "subject_type": ticket.subject_type,
            "subject_id": ticket.subject_id,
            **life,
        },
        {
            "type": "decision",
            "decision": decision.decision,
            "rationale": decision.rationale,
            "status": ticket.status,
            **{k: life[k] for k in ("lifecycle_stage", "lifecycle_label")},
        },
    ]
    if actions:
        cards.append({"type": "actions", "items": [_facade().action_payload(a) for a in actions]})
    return (reply, cards)


def resolve_issue_domain(
    *,
    intent: str,
    text: str,
    extracted: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    context: _facade().Optional[_facade().Dict[str, _facade().Any]] = None,
    llm_domain: _facade().Any = None,
) -> _facade().Dict[str, str]:
    """判定问题归属：platform / software / custom。

    custom = 宿主入门第三步定制线交付的账号定制功能 Mod / 定制员工（非公开市场上架）。
    """
    data = extracted or {}
    ctx = context or {}
    t = (text or "").strip()
    scene = str(data.get("scene") or ctx.get("scene") or "").strip().lower()
    pkg_id = str(data.get("pkg_id") or ctx.get("pkg_id") or "").strip()
    catalog_id = data.get("catalog_id") or ctx.get("catalog_id")
    artifact = str(data.get("artifact") or ctx.get("artifact") or "").strip().lower()
    account_custom_flag = data.get("account_custom")
    if account_custom_flag is None:
        account_custom_flag = ctx.get("account_custom")
    account_custom = str(account_custom_flag or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "custom",
        "account_custom",
    }

    def _pack(domain: str, source: str) -> _facade().Dict[str, str]:
        d = domain if domain in _facade().ISSUE_DOMAINS else "platform"
        return {
            "domain": d,
            "label": _facade().ISSUE_DOMAIN_LABELS.get(d, "平台"),
            "source": source,
        }

    clarify = _facade()._parse_domain_clarify_reply(t)
    if clarify:
        return _pack(clarify, "user_clarify")
    custom_marks = (
        "客户定制",
        "账号定制",
        "定制线",
        "定制员工",
        "定制 mod",
        "定制Mod",
        "定制功能",
        "白标",
        "专属皮肤",
        "专属员工",
        "未上架员工",
    )
    if (
        account_custom
        or scene in {"custom", "account_custom", "定制"}
        or artifact in {"account_custom", "custom"}
        or any((x in t for x in custom_marks))
        or str(pkg_id).startswith(("custom_", "acct_custom_", "account_custom_"))
    ):
        return _pack("custom", "rules_custom")
    if intent in {"catalog_complaint", "catalog_review"}:
        return _pack("software", "rules_catalog_intent")
    if catalog_id not in (None, "", 0, "0") or pkg_id:
        return _pack("software", "rules_catalog_ref")
    if any((x in t for x in ("商品", "这个 mod", "这个Mod", "员工包", "扩展市场", "我买的"))):
        return _pack("software", "rules_software_text")
    llm_d = str(llm_domain or data.get("issue_domain") or "").strip().lower()
    if llm_d in _facade().ISSUE_DOMAINS:
        if llm_d == "software" and (not (catalog_id or pkg_id)):
            pass
        else:
            return _pack(llm_d, "llm")
    if intent in {"refund", "account_support", "llm_extension", "greeting"}:
        return _pack("platform", "rules_platform_intent")
    if intent == "product_issue" or _facade()._looks_like_product_issue(t):
        return _pack("platform", "rules_product_default")
    return _pack("platform", "default")

# --- from customer_service_orchestrator_part04_part01_part02.py ---
"""Implementation extracted from the public facade module."""

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

# --- from customer_service_orchestrator_part05.py ---
"""Implementation extracted from the public facade module."""


import importlib
from typing import Any

from modstore_server.customer_issue_delivery_contract import (
    projected_dispatch_status,
    record_team_progress,
    role_progress_state,
    team_action_state,
    team_succeeded,
)

CLOSED_CUSTOMER_ISSUE_STATES = frozenset({"resolved", "closed", "done", "rejected", "expired"})


def _facade():
    return importlib.import_module("modstore_server.customer_service_orchestrator")


def ticket_lifecycle_stage(status: str | None = None, decision_status: str | None = None) -> int:
    """用户侧五阶段：1已收到 → 2处理中 → 3有结果 → 4待补充 → 5已完成。"""
    s = str(status or "").strip().lower()
    d = str(decision_status or "").strip().lower()
    if s in CLOSED_CUSTOMER_ISSUE_STATES:
        return 5
    if s == "waiting_user" or d == "needs_more_info":
        return 4
    if s in {"open", "pending", "queued"}:
        return 1
    if s == "processing":
        if d in {"approved", "rejected"}:
            return 3
        return 2
    if d in {"approved", "rejected"}:
        return 3
    return 1


def _summarize_incident_team_rows(
    team_rows: list[_facade().Dict[str, _facade().Any]],
) -> str:
    """把 incident team / 员工执行行压缩成用户可读的一句进度。"""
    from modstore_server.incident_team_handler_digest import redact_text

    bits: list[str] = []
    role_cn = {"scout": "排查", "fix": "修复", "verify": "验证"}
    for row in team_rows or []:
        if not isinstance(row, dict):
            continue
        role = role_cn.get(str(row.get("role") or "").strip(), str(row.get("role") or "执行"))
        state = role_progress_state(row)
        outcome = "已完成" if state == "completed" else "未完成" if state == "failed" else "处理中"
        outputs = (row.get("handler_outputs") or {}).get("outputs", [])
        details = [
            "；".join(
                str(value)
                for value in (
                    o.get("cause"),
                    o.get("summary") or o.get("output_summary"),
                    o.get("change_summary"),
                    o.get("error") or o.get("output_error"),
                )
                if value
            )
            for o in outputs
            if isinstance(o, dict)
        ]
        detail = redact_text(
            "；".join(
                [d for d in details if d]
                + (
                    [row["handler_outputs"]["poll_error"]]
                    if (row.get("handler_outputs") or {}).get("poll_error")
                    else []
                )
            )
        )
        bits.append(f"{role}{outcome}：{detail or '尚未提供原因或处理说明'}")
    return "；".join(bits[:6]) if bits else "值班员工已接手"


def _customer_incident_progress(team_rows: list[dict[str, Any]]) -> str:
    """客户可见进度只用固定客服话术：不拼接员工输出、报错原文、路径或工具名（#2389）。"""
    role_cn = {"scout": "排查", "fix": "修复", "verify": "验证"}
    bits, failed = [], False
    for row in [r for r in team_rows or [] if isinstance(r, dict)][:6]:
        role = role_cn.get(str(row.get("role") or "").strip(), "处理")
        state = role_progress_state(row)
        failed = failed or state == "failed"
        bits.append(
            f"{role}{'已完成' if state == 'completed' else '暂未完成' if state == 'failed' else '处理中'}"
        )
    note = "处理过程中遇到内部问题，值班人员正在继续跟进，您无需操作" if failed else ""
    return "；".join(bits + [note] if note else bits) or "值班员工已接手"


def apply_customer_ticket_incident_progress(
    db: _facade().Session,
    *,
    ticket_id: int,
    event_id: int = 0,
    team_ok: bool = False,
    team_rows: _facade().Optional[list[_facade().Dict[str, _facade().Any]]] = None,
    summary_hint: str = "",
    executor: str = "incident_team",
) -> _facade().Dict[str, _facade().Any]:
    """把 AI 员工 / incident team 执行结果回写到已有客服工单。

    复用现有 ``CustomerServiceMessage`` / ``CustomerServiceAction`` / ``audit``，
    不新建旁路表：员工结果只推进到待正式交付，终态由客户运行回执判定。
    ``executor`` 标明重派或外部执行器（如 grok_bot），每次派单各记一条执行动作。
    """
    ticket = (
        db.query(_facade().CustomerServiceTicket)
        .filter(_facade().CustomerServiceTicket.id == int(ticket_id))
        .first()
    )
    if not ticket:
        return {"ok": False, "reason": "ticket_not_found"}
    ev = _facade().json_loads(ticket.evidence_json, {})
    if not isinstance(ev, dict):
        ev = {}
    delivery_managed = _facade().delivery_policy.is_delivery_managed(ticket.intent, ev)
    rows = [r for r in team_rows or [] if isinstance(r, dict)]
    team_ok = bool(team_ok) and team_succeeded(rows)
    from modstore_server.customer_delivery_receipts import canonical_sha256
    from modstore_server.customer_service_customer_view import customer_ticket

    progress_digest = canonical_sha256(
        {
            "event_id": int(event_id),
            "team_ok": team_ok,
            "rows": [
                {
                    key: row.get(key)
                    for key in (
                        "role",
                        "employee_id",
                        "ok",
                        "status",
                        "handler_outputs",
                    )
                }
                for row in rows
            ],
        }
    )
    if ticket.status in {"resolved", "closed", "expired"} or any(
        report.get("progress_sha256") == progress_digest
        for report in ev.get("employee_reports", [])
        if isinstance(report, dict)
    ):
        return {
            "ok": True,
            "replayed": True,
            "ticket_id": int(ticket.id),
            "team_ok": team_ok,
        }
    resolution = record_team_progress(ticket, ev, event_id=event_id, rows=rows, team_ok=team_ok)
    # 内部明细（含报错原文）只进 action.result_json 与审计 detail；客户消息/证据只用客服话术。
    progress = _facade()._summarize_incident_team_rows(rows)
    customer_progress = _customer_incident_progress(rows)
    progress_record = {
        "event_id": int(event_id or 0),
        "team_ok": team_ok,
        "progress": progress,
    }
    customer_record = {**progress_record, "progress": customer_progress}
    hint = str(summary_hint or ticket.summary or ticket.title or "").strip()[:120]
    if team_ok:
        reply = _facade().delivery_policy.success_reply(
            hint or ticket.ticket_no, customer_progress, delivery_managed
        )
    else:
        reply = f"我是小C。工单「{hint or ticket.ticket_no}」已有员工处理进展：{customer_progress}。我们会继续跟进，也可继续补充截图或具体页面。"
    reply += "下一步：" + (
        "等待正式版本交付后，请在原工单复验并确认。"
        if team_ok
        else (
            "等待已受理任务的处理结果，请保留原工单。"
            if resolution["state"] == "processing"
            else "继续排查或转人工处理，请保留原工单。"
        )
    )
    outputs = [o for r in rows for o in (r.get("handler_outputs") or {}).get("outputs") or []]
    outputs = [o for o in outputs if isinstance(o, dict)]
    tasks = sorted({str(o.get("para_task_id") or o.get("task_id") or "") for o in outputs} - {""})
    request = {
        "event_id": int(event_id or 0),
        "team_ok": bool(team_ok),
        "roles": resolution["team"][:8],
        "para_task_ids": tasks[:8],
        "tools": sorted({str(o.get("tool_name") or "") for o in outputs} - {""}),
        "executor": executor,
    }
    tried = [t for o in outputs for t in o.get("codex_models_tried") or [] if isinstance(t, dict)]
    if tried:
        # 内部动作记录尝试过的 Codex 模型（不进客户消息）。
        request["codex_models_tried"] = tried[:8]
    # 同一派单（同一组 Para 任务）待定→终态更新同一条；重派/外部执行是新任务，另记一条。
    action = _facade().build_action(
        db,
        ticket_id=int(ticket.id),
        user_id=int(ticket.user_id or 0),
        action_type="employee.dispatch",
        target_type="incident_team",
        target_id=f"{event_id or ''}:{','.join(tasks) or progress_digest[:16]}"[:240],
        request=request,
    )
    action.status, failed = team_action_state(rows, team_ok=team_ok)
    action.request_json = _facade().json_dumps(request)
    action.result_json = _facade().json_dumps({"ok": team_ok, **progress_record, **request})
    action.error = f"未成功角色：{'、'.join(failed)}" if failed else ""
    db.flush()
    _facade().delivery_policy.apply_ticket_outcome(ticket, team_ok, delivery_managed)
    if resolution["state"] == "processing":
        ticket.decision_status = "pending"
    reports = list(ev.get("employee_reports") or [])
    reports.append(
        {
            "type": "incident_team",
            "progress_sha256": progress_digest,
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "progress": customer_progress[:500],
            "at": _facade().datetime.now(_facade().timezone.utc).isoformat(),
        }
    )
    ev["employee_reports"] = reports[-20:]
    ticket.evidence_json = _facade().json_dumps(ev)
    assistant_msg = _facade().CustomerServiceMessage(
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        user_id=int(ticket.user_id or 0),
        role="assistant",
        content=reply,
        payload_json=_facade().json_dumps(
            {
                # 客户消息只存客户白名单工单视图：resolution 等内部证据不随消息落库。
                "ticket": customer_ticket(_facade().ticket_payload(ticket)),
                "cards": [
                    {
                        "type": "ticket",
                        "title": ticket.title,
                        "ticket_no": ticket.ticket_no,
                        "status": ticket.status,
                        "intent": ticket.intent,
                        **_facade().ticket_lifecycle_payload(ticket.status, ticket.decision_status),
                    }
                ],
                "employee_progress": customer_record,
            }
        ),
    )
    db.add(assistant_msg)
    _facade().audit(
        db,
        event_type="employee_progress",
        session_id=int(ticket.session_id),
        ticket_id=int(ticket.id),
        actor_type="system",
        detail={
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "progress": progress[:500],
            "action_id": int(action.id or 0),
        },
    )
    _facade().enqueue_customer_service_event(
        db,
        "customer_service.employee_progress",
        f"{ticket.ticket_no}:progress:{event_id or action.id}",
        {
            "ticket_id": int(ticket.id),
            "ticket_no": ticket.ticket_no,
            "event_id": int(event_id or 0),
            "team_ok": bool(team_ok),
            "lifecycle_stage": _facade().ticket_lifecycle_stage(
                ticket.status, ticket.decision_status
            ),
        },
    )
    db.flush()
    return {
        "ok": True,
        "ticket_id": int(ticket.id),
        "lifecycle_stage": _facade().ticket_lifecycle_stage(ticket.status, ticket.decision_status),
        "lifecycle_label": _facade()
        .ticket_lifecycle_payload(ticket.status, ticket.decision_status)
        .get("lifecycle_label"),
        "message_id": int(assistant_msg.id or 0),
        "action_id": int(action.id or 0),
        "team_ok": bool(team_ok),
    }


def ticket_lifecycle_payload(
    status: str | None = None, decision_status: str | None = None
) -> _facade().Dict[str, _facade().Any]:
    if status == "expired":
        return {
            "lifecycle_stage": 5,
            "lifecycle_label": "已过期不再处理",
            "lifecycle_steps": [],
        }
    stage = _facade().ticket_lifecycle_stage(status, decision_status)
    label = next(
        (name for (num, name) in _facade().TICKET_LIFECYCLE_STEPS if num == stage),
        "已收到",
    )
    return {
        "lifecycle_stage": stage,
        "lifecycle_label": label,
        "lifecycle_steps": [
            {
                "stage": num,
                "label": name,
                "state": "done" if num < stage else "current" if num == stage else "todo",
            }
            for (num, name) in _facade().TICKET_LIFECYCLE_STEPS
        ],
    }


def ticket_payload(
    row: _facade().CustomerServiceTicket,
) -> _facade().Dict[str, _facade().Any]:
    life = _facade().ticket_lifecycle_payload(row.status, row.decision_status)
    evidence = _facade().json_loads(row.evidence_json, {})
    if not isinstance(evidence, dict):
        evidence = {}
    domain = str(evidence.get("issue_domain") or "").strip().lower()
    if domain not in _facade().ISSUE_DOMAINS:
        domain = ""
    expected_completion_at = getattr(row, "expected_completion_at", None)
    if expected_completion_at is not None and expected_completion_at.tzinfo is None:
        expected_completion_at = expected_completion_at.replace(tzinfo=_facade().timezone.utc)
    return {
        "id": row.id,
        # 管理端必须用稳定的市场用户 ID 把交付工单关联到客户资料。
        "user_id": row.user_id,
        "submitter_type": getattr(row, "submitter_type", None) or "unknown",
        "assigned_admin_id": row.assigned_admin_id,
        "session_id": row.session_id,
        "ticket_no": row.ticket_no,
        "title": row.title,
        "intent": row.intent,
        "issue_domain": domain or None,
        "issue_domain_label": evidence.get("issue_domain_label")
        or _facade().ISSUE_DOMAIN_LABELS.get(domain)
        or None,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "status": row.status,
        "priority": row.priority,
        "evidence": evidence,
        "summary": row.summary,
        "decision_status": row.decision_status,
        "automation_level": row.automation_level,
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "closed_at": row.closed_at.isoformat() if row.closed_at else "",
        "expected_completion_at": (
            expected_completion_at.isoformat() if expected_completion_at else None
        ),
        **life,
    }


def decision_payload(
    row: _facade().CustomerServiceDecision,
) -> _facade().Dict[str, _facade().Any]:
    return {
        "id": row.id,
        "ticket_id": row.ticket_id,
        "standard_id": row.standard_id,
        "intent": row.intent,
        "decision": row.decision,
        "risk_level": row.risk_level,
        "confidence": row.confidence,
        "rationale": row.rationale,
        "extracted": _facade().json_loads(row.extracted_json, {}),
        "criteria": _facade().json_loads(row.criteria_json, []),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def action_payload(row: _facade().Any) -> _facade().Dict[str, _facade().Any]:
    result = _facade().json_loads(row.result_json, {})
    status = projected_dispatch_status(row.status, row.action_type, result, row.error)
    return {
        "id": row.id,
        "ticket_id": row.ticket_id,
        "decision_id": row.decision_id,
        "action_type": row.action_type,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "status": status,
        **(
            {"recorded_status": row.status, "recorded_error": row.error}
            if status != row.status
            else {}
        ),
        "request": _facade().json_loads(row.request_json, {}),
        "result": result,
        "error": row.error if status == row.status else "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def customer_issue_payload(row: _facade().CustomerServiceTicket) -> dict[str, Any]:
    evidence = _facade().json_loads(row.evidence_json, {})
    resolution = evidence.get("resolution") or {}
    state = str(resolution.get("state") or "received")
    reports = [r for r in evidence.get("employee_reports") or [] if isinstance(r, dict)]
    closed = row.status in CLOSED_CUSTOMER_ISSUE_STATES
    return {
        "id": row.id,
        "ticket_no": row.ticket_no,
        "title": row.title,
        "summary": row.summary,
        "status": row.status,
        "state": state,
        "lifecycle_label": _facade().ticket_lifecycle_payload(row.status, row.decision_status)[
            "lifecycle_label"
        ],
        "latest_result": (
            {k: reports[-1].get(k) for k in ("team_ok", "progress", "at")} if reports else None
        ),
        "last_error": str(resolution.get("last_error") or ""),
        "closed_at": row.closed_at.isoformat() if row.closed_at else "",
        "reopen_count": len(evidence.get("reopen_history") or []),
        "can_resolve": not closed,
        "can_reopen": closed or state not in {"received", "reopened"},
    }
