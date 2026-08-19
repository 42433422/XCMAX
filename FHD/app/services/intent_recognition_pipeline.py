"""Full rule-engine recognition pipeline behind the intent-service facade."""

from __future__ import annotations

import re
from typing import Any, cast

from app.services import intent_service as facade


def recognize_intents_impl(message: str) -> dict[str, Any]:
    """
    全流程意图识别入口

    Returns:
        意图识别结果字典，包含：
        - primary_intent: 主意图 id
        - tool_key: 建议触发的工具 key
        - intent_hints: 用于上下文的 hint 列表
        - is_negated: 是否判定为否定式
        - is_greeting: 是否问候
        - is_goodbye: 是否再见
        - is_help: 是否帮助请求
        - is_likely_unclear: 短句且无任何意图匹配
        - all_matched_tools: 所有匹配到的 (intent_id, tool_key) 列表
    """
    _normalize = facade._normalize
    _make_intent_cache_key = facade._make_intent_cache_key
    _intent_cache = facade._intent_cache
    _reflex_basic_intents = facade._reflex_basic_intents
    RECOVERABLE_ERRORS = facade.RECOVERABLE_ERRORS
    logger = facade.logger
    get_rule_engine = facade.get_rule_engine
    is_negation = facade.is_negation
    _negation_action_keywords = facade._negation_action_keywords

    msg = _normalize(message)
    msg_lower = (msg or "").lower()

    cache_key = _make_intent_cache_key(message)
    cached_result = _intent_cache.get(cache_key)
    if cached_result is not None:
        return cast("dict[str, Any]", cached_result)

    result: dict[str, Any] = {
        "primary_intent": None,
        "tool_key": None,
        "intent_hints": [],
        "is_negated": False,
        "is_greeting": False,
        "is_goodbye": False,
        "is_help": False,
        "is_confirmation": False,
        "is_negation_intent": False,
        "is_likely_unclear": False,
        "all_matched_tools": [],
    }

    try:
        basic_intents = _reflex_basic_intents(message)
    except RECOVERABLE_ERRORS as exc:
        logger.warning("reflex basic intents skipped: %s", exc)
        basic_intents = {
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_confirmation": False,
            "is_negation_intent": False,
            "is_negated": False,
        }
    result.update(basic_intents)

    engine = get_rule_engine()

    tool_matches = engine.match_intents(msg)
    result["all_matched_tools"] = [(m["id"], m["tool_key"]) for m in tool_matches]

    if tool_matches:
        best = tool_matches[0]
        intent_id = best["id"]
        tool_key = best["tool_key"]
        block_if_negated = best["block_if_negated"]

        result["primary_intent"] = intent_id

        negated = (
            is_negation(message, action_keywords=best.get("keywords"))
            if block_if_negated
            else False
        )
        result["is_negated"] = negated

        if not negated:
            result["tool_key"] = tool_key

        if intent_id == "shipment_generate":
            result["intent_hints"].append("shipment_generate")
        elif intent_id == "shipment_template":
            if "template_query" not in result["intent_hints"]:
                result["intent_hints"].append("template_query")

        if "upload_file" in (m["tool_key"] for m in tool_matches):
            if "upload_file" not in result["intent_hints"]:
                result["intent_hints"].append("upload_file")

    hint_matches = engine.match_hint_intents(msg)
    for h in hint_matches:
        if h not in result["intent_hints"]:
            result["intent_hints"].append(h)

    if ("模板" in msg or "template" in msg_lower) and "template_query" not in result[
        "intent_hints"
    ]:
        result["intent_hints"].append("template_query")

    if ("生成发货单" in msg or "开发货单" in msg) and "shipment_generate" not in result[
        "intent_hints"
    ]:
        result["intent_hints"].append("shipment_generate")

    if (msg.startswith("发货单") or msg.startswith("送货单") or msg.startswith("出货单")) and len(
        msg
    ) > 5:
        order_patterns = ["桶", "规格", "公斤", "kg", "件", "箱"]
        has_order_info = any(pattern in msg for pattern in order_patterns)
        if has_order_info and not result["tool_key"]:
            result["primary_intent"] = "shipment_generate"
            result["tool_key"] = "shipment_generate"
            if "shipment_generate" not in result["intent_hints"]:
                result["intent_hints"].append("shipment_generate")

    if result["tool_key"] in (None, "products", "shipments"):
        has_container_and_spec = "桶" in msg and "规格" in msg
        has_number_like = re.search(r"(\d+|[一二三四五六七八九十零〇两]+)", msg) is not None
        if has_container_and_spec and has_number_like:
            negated = is_negation(
                message,
                action_keywords=_negation_action_keywords.get("shipment_generate", []),
            )
            if not negated:
                result["primary_intent"] = "shipment_generate"
                result["tool_key"] = "shipment_generate"
                if "shipment_generate" not in result["intent_hints"]:
                    result["intent_hints"].append("shipment_generate")

    if result["tool_key"] in (None, "products", "print_label"):
        has_print_kw = ("打印" in msg) or msg.startswith("打印")
        has_model_spec = (
            re.search(r"(\d+)\s*规格\s*(\d+(?:\.\d+)?)", msg) is not None
            or re.search(r"(\d+)\s*的\s*规格\s*(\d+(?:\.\d+)?)", msg) is not None
            or re.search(r"(\d+)规格(\d+(?:\.\d+)?)", msg) is not None
        )
        has_container_qty = any(k in msg for k in ["桶", "箱", "件", "公斤", "kg"])
        if has_print_kw and has_model_spec and not has_container_qty and not result["is_negated"]:
            negated = is_negation(
                message,
                action_keywords=_negation_action_keywords.get("shipment_generate", []),
            )
            if not negated:
                result["primary_intent"] = "shipment_generate"
                result["tool_key"] = "shipment_generate"
                if "shipment_generate" not in result["intent_hints"]:
                    result["intent_hints"].append("shipment_generate")

    if result["tool_key"] is None:
        has_order_action = any(
            k in msg for k in ["打印", "发货单", "送货单", "出货单", "开单", "打单"]
        )
        signals = 0
        if ("编号" in msg or "型号" in msg) and re.search(r"\d{3,6}", msg):
            signals += 1
        if "规格" in msg and re.search(r"(\d+|[一二三四五六七八九十零〇两]+)", msg):
            signals += 1
        if "桶" in msg and re.search(
            r"(\d+|[一二三四五六七八九十零〇两]+)\s*桶|桶\s*(\d+|[一二三四五六七八九十零〇两]+)",
            msg,
        ):
            signals += 1
        if has_order_action and signals >= 2 and not result["is_negated"]:
            if not is_negation(
                message,
                action_keywords=_negation_action_keywords.get("shipment_generate", []),
            ):
                result["primary_intent"] = "shipment_generate"
                result["tool_key"] = "shipment_generate"
                if "shipment_generate" not in result["intent_hints"]:
                    result["intent_hints"].append("shipment_generate")

    if ("上传" in msg or "导入" in msg or "upload" in msg_lower) and "upload_file" not in result[
        "intent_hints"
    ]:
        result["intent_hints"].append("upload_file")

    result["is_likely_unclear"] = (
        len(msg) <= 4
        and not result["is_greeting"]
        and not result["is_goodbye"]
        and not result["primary_intent"]
        and not result["intent_hints"]
    )

    unit_model_match = re.search(r"([^\s的]{2,10})的(\d+[A-Z]?)", msg)
    if unit_model_match:
        potential_unit = unit_model_match.group(1)
        model = unit_model_match.group(2)
        from app.infrastructure.lookups.purchase_unit_resolver import resolve_purchase_unit

        try:
            resolved = resolve_purchase_unit(potential_unit)
        except RECOVERABLE_ERRORS as exc:
            logger.warning("resolve_purchase_unit skipped: %s", exc)
            resolved = None
        if resolved:
            result["slots"] = {"unit_name": resolved.unit_name, "model_number": model}
        else:
            result["slots"] = {"unit_name": potential_unit, "model_number": model}
        if (
            result["tool_key"] is None
            and not result["primary_intent"]
            and not result["is_greeting"]
            and not result["is_goodbye"]
            and not result["is_help"]
        ):
            result["primary_intent"] = "products"
            result["tool_key"] = "products"
    elif result["tool_key"] == "products":
        result["slots"] = {"keyword": msg}
    else:
        result["slots"] = {}

    _intent_cache.set(cache_key, result)
    return result

