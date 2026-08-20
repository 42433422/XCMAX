# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# isort: skip_file
"""Implementation extracted from the public facade module."""

from __future__ import annotations

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
