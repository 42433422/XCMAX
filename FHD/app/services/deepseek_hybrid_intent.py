"""Hybrid rule, distilled-model, and DeepSeek intent orchestration."""

from __future__ import annotations

import logging
from typing import Any, cast

from app.services.deepseek_intent_service import DeepSeekIntentRecognizer
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class HybridIntentWithDeepSeek:
    """混合意图识别（规则 + DeepSeek/BERT + 槽位）"""

    def __init__(
        self,
        use_deepseek: bool = True,
        deepseek_api_key: str | None = None,
        rule_priority: bool = True,
        confidence_threshold: float = 0.5,
        use_distilled: bool = False,
    ):
        self.use_deepseek = use_deepseek
        self.deepseek_api_key = deepseek_api_key
        self.rule_priority = rule_priority
        self.confidence_threshold = confidence_threshold
        self.deepseek_recognizer = None
        self.distilled_recognizer = None
        self.use_distilled = use_distilled

        if self.use_distilled:
            try:
                from .distilled_intent_service import get_distilled_recognizer

                self.distilled_recognizer = get_distilled_recognizer()
                if self.distilled_recognizer.is_available():
                    logger.info("使用蒸馏模型进行意图识别")
                else:
                    logger.warning("蒸馏模型不可用，切换到 DeepSeek")
                    self.use_distilled = False
            except RECOVERABLE_ERRORS as e:
                logger.warning("无法加载蒸馏模型: %s", e)
                self.use_distilled = False

        if self.use_deepseek:
            self.deepseek_recognizer = DeepSeekIntentRecognizer(
                api_key=deepseek_api_key, confidence_threshold=confidence_threshold
            )

    async def recognize(
        self, message: str, context: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        from .intent_service import recognize_intents as rule_recognize

        rule_result = cast("dict[str, Any]", rule_recognize(message))
        rule_result["sources_used"] = ["rule"]
        logger.info(
            "[HYBRID] 规则识别结果: intent=%s, tool_key=%s, is_greeting=%s, slots=%s",
            rule_result.get("primary_intent"),
            rule_result.get("tool_key"),
            rule_result.get("is_greeting"),
            rule_result.get("slots"),
        )

        if (
            rule_result.get("is_greeting")
            or rule_result.get("is_goodbye")
            or rule_result.get("is_help")
        ):
            rule_result["final_intent"] = rule_result.get("primary_intent") or rule_result.get(
                "primary_intent"
            )
            rule_result["intent_source"] = "rule"
            rule_result["slots"] = self._extract_slots_from_rule(message, rule_result)
            logger.info("[HYBRID] 简单意图，直接返回: %s", rule_result.get("primary_intent"))
            return rule_result

        if rule_result.get("primary_intent") and rule_result.get("primary_intent") != "unk":
            rule_result["final_intent"] = rule_result["primary_intent"]
            rule_result["intent_source"] = "rule"
            rule_result["slots"] = self._extract_slots_from_rule(message, rule_result)
            logger.info("[HYBRID] 规则已命中，跳过 DeepSeek: %s", rule_result.get("primary_intent"))
            return rule_result

        if (
            self.use_distilled
            and self.distilled_recognizer
            and self.distilled_recognizer.is_available()
        ):
            try:
                distilled_result = self.distilled_recognizer.recognize(message)
                distilled_intent = distilled_result.get("intent")
                distilled_confidence = float(distilled_result.get("confidence", 0.0) or 0.0)
                distilled_slots = distilled_result.get("slots", {}) or {}

                rule_result["distilled_intent"] = distilled_intent
                rule_result["distilled_confidence"] = distilled_confidence
                rule_result["distilled_slots"] = distilled_slots
                rule_result["sources_used"].append("distilled")

                if (
                    distilled_intent
                    and distilled_intent != "unk"
                    and distilled_confidence >= self.confidence_threshold
                ):
                    rule_result["final_intent"] = distilled_intent
                    rule_result["tool_key"] = distilled_intent
                    rule_result["intent_source"] = "distilled"
                    rule_result["intent_confidence"] = distilled_confidence
                    rule_result["slots"] = distilled_slots
                    return rule_result

                if not self.use_deepseek or not self.deepseek_recognizer:
                    rule_result["final_intent"] = distilled_intent or rule_result.get(
                        "primary_intent"
                    )
                    rule_result["tool_key"] = distilled_intent or rule_result.get("tool_key")
                    rule_result["intent_source"] = (
                        "distilled_low_confidence" if distilled_intent else "rule"
                    )
                    rule_result["intent_confidence"] = distilled_confidence
                    rule_result["slots"] = distilled_slots or self._extract_slots_from_rule(
                        message, rule_result
                    )
                    return rule_result
            except RECOVERABLE_ERRORS as e:
                logger.warning("蒸馏意图识别失败，降级到 DeepSeek: %s", e)

        if not self.use_deepseek or not self.deepseek_recognizer:
            rule_result["final_intent"] = rule_result.get("primary_intent")
            rule_result["intent_source"] = "rule"
            rule_result["slots"] = self._extract_slots_from_rule(message, rule_result)
            return rule_result

        try:
            deepseek_result = await self.deepseek_recognizer.recognize(message, context)
            rule_result["deepseek_intent"] = deepseek_result.get("intent")
            rule_result["deepseek_confidence"] = deepseek_result.get("confidence", 0.0)
            rule_result["deepseek_slots"] = deepseek_result.get("slots", {})
            rule_result["deepseek_reasoning"] = deepseek_result.get("reasoning", "")
            rule_result["sources_used"].append("deepseek")

            if deepseek_result.get("confidence", 0.0) >= self.confidence_threshold:
                rule_result["final_intent"] = deepseek_result.get("intent")
                rule_result["tool_key"] = deepseek_result.get("intent")
                rule_result["intent_source"] = "deepseek"
                rule_result["intent_confidence"] = deepseek_result.get("confidence", 0.0)
                rule_result["slots"] = deepseek_result.get("slots", {})
            else:
                rule_result["final_intent"] = deepseek_result.get("intent")
                rule_result["tool_key"] = deepseek_result.get("intent")
                rule_result["intent_source"] = "deepseek_low_confidence"
                rule_result["intent_confidence"] = deepseek_result.get("confidence", 0.0)
                rule_result["slots"] = deepseek_result.get("slots", {})

        except RECOVERABLE_ERRORS as e:
            logger.error("DeepSeek 意图识别失败: %s", e)
            rule_result["final_intent"] = rule_result.get("primary_intent")
            rule_result["intent_source"] = "rule"
            rule_result["slots"] = self._extract_slots_from_rule(message, rule_result)

        return rule_result

    def _extract_slots_from_rule(self, message: str, rule_result: dict) -> dict[str, Any]:
        """从规则匹配结果中提取槽位"""
        slots = {}
        import re

        invalid_unit_names = {
            "生成",
            "发货",
            "发货单",
            "开单",
            "打单",
            "单",
            "给",
            "的",
            "我",
            "你",
            "他",
            "她",
            "它",
            "请",
            "问",
        }

        if "给" in message:
            idx = message.index("给")
            after_give = message[idx + 1 :].strip()
            if after_give:
                parts = re.split(r"[，,。\s]", after_give)
                if parts:
                    unit = parts[0].strip()
                    if unit and len(unit) > 1 and unit not in invalid_unit_names:
                        slots["unit_name"] = unit
        elif "帮" in message:
            idx = message.index("帮")
            after_help = message[idx + 1 :].strip()
            if after_help:
                unit_match = re.search(r"打([^\s，,。]+?)(?:的|货)", after_help)
                if unit_match:
                    unit = unit_match.group(1)
                    if unit and len(unit) > 1 and unit not in invalid_unit_names:
                        slots["unit_name"] = unit
                else:
                    parts = re.split(r"[，,。\s]", after_help)
                    if parts:
                        unit = parts[0].strip().lstrip("打")
                        if unit and len(unit) > 1 and unit not in invalid_unit_names:
                            slots["unit_name"] = unit
        else:
            unit_match = re.search(r"([^\s，,。]+?)\s*(?:的|发货单)", message)
            if unit_match:
                unit = unit_match.group(1)
                if unit and len(unit) > 1 and unit not in invalid_unit_names:
                    slots["unit_name"] = unit

        if "unit_name" not in slots:
            ship_match = re.search(r"^发货单([^\s，,。]{2,})", message)
            if ship_match:
                unit = ship_match.group(1)
                if unit and unit not in invalid_unit_names:
                    slots["unit_name"] = unit

        if "unit_name" not in slots:
            ship_match = re.search(r"^送货单([^\s，,。]{2,})", message)
            if ship_match:
                unit = ship_match.group(1)
                if unit and unit not in invalid_unit_names:
                    slots["unit_name"] = unit

        if "unit_name" not in slots:
            ship_match = re.search(r"^出货单([^\s，,。]{2,})", message)
            if ship_match:
                unit = ship_match.group(1)
                if unit and unit not in invalid_unit_names:
                    slots["unit_name"] = unit

        qty_match = re.search(r"(\d+|[一二两三四五六七八九十零]+)\s*桶", message)
        if qty_match:
            cn_map = {
                "零": 0,
                "〇": 0,
                "一": 1,
                "二": 2,
                "两": 2,
                "三": 3,
                "四": 4,
                "五": 5,
                "六": 6,
                "七": 7,
                "八": 8,
                "九": 9,
            }
            qty_str = qty_match.group(1)
            if qty_str in cn_map:
                slots["quantity_tins"] = cn_map[qty_str]
            else:
                slots["quantity_tins"] = int(qty_str)

        spec_match = re.search(r"规格\s*(\d+)", message)
        if spec_match:
            slots["tin_spec"] = float(spec_match.group(1))

        product_model_pattern = r"(\d{4}[A-Z]?)\s*(?:规格\s*(\d+(?:\.\d+)?))?"
        product_matches = re.findall(product_model_pattern, message)
        if product_matches:
            products = []
            for model, spec in product_matches:
                product_info = {"model": model}
                if spec:
                    product_info["spec"] = float(spec)
                products.append(product_info)
            if len(products) == 1:
                slots["product_model"] = products[0]["model"]
                if "tin_spec" not in slots and "spec" in products[0]:
                    slots["tin_spec"] = products[0]["spec"]
            elif len(products) > 1:
                slots["products"] = products

        logger.info("[SLOT_EXTRACTION_START] slots=%s", slots)

        # 处理 DeepSeek 可能返回的 contact_person 作为 unit_name
        if "contact_person" in slots and "unit_name" not in slots:
            contact = slots.pop("contact_person")
            slots["unit_name"] = contact
            logger.info("[SLOT_EXTRACTION] converted contact_person to unit_name: %s", contact)

        invalid_unit_patterns = ["帮我", "查询", "请问", "请帮", "什么", "哪个"]
        if "unit_name" in slots:
            unit_name = slots["unit_name"]
            needs_fix = any(p in unit_name for p in invalid_unit_patterns) or len(unit_name) > 6
            logger.info("[SLOT_EXTRACTION] unit_name=%s, needs_fix=%s", unit_name, needs_fix)
            if needs_fix and "keyword" in slots:
                keyword = slots["keyword"]
                unit_match = re.search(r"([^\s 的]{2,6}) 的 (\d{4}[A-Z]?)", keyword)
                logger.info("[SLOT_EXTRACTION] keyword=%s, unit_match=%s", keyword, unit_match)
                if unit_match:
                    potential_unit = unit_match.group(1)
                    model = unit_match.group(2)
                    from app.infrastructure.lookups.purchase_unit_resolver import (
                        resolve_purchase_unit,
                    )

                    resolved = resolve_purchase_unit(potential_unit)
                    logger.info("[SLOT_EXTRACTION] resolved=%s", resolved)
                    if resolved:
                        slots["unit_name"] = resolved.unit_name
                        slots["model_number"] = model
                    else:
                        slots["unit_name"] = potential_unit
                        slots["model_number"] = model
            else:
                from app.infrastructure.lookups.purchase_unit_resolver import resolve_purchase_unit

                resolved = resolve_purchase_unit(unit_name)
                logger.info("[SLOT_EXTRACTION] resolved unit_name=%s", resolved)
                if resolved:
                    slots["unit_name"] = resolved.unit_name

        if "keyword" in slots and "unit_name" not in slots:
            keyword = slots["keyword"]
            logger.info("[SLOT_EXTRACTION_KEYWORD] keyword=%s", keyword)
            unit_match = re.search(r"([^\s 的]{2,6}) 的 (\d{4}[A-Z]?)", keyword)
            logger.info("[SLOT_EXTRACTION_KEYWORD] unit_match=%s", unit_match)
            if unit_match:
                potential_unit = unit_match.group(1)
                model = unit_match.group(2)
                logger.info(
                    "[SLOT_EXTRACTION_KEYWORD] potential_unit=%s, model=%s", potential_unit, model
                )
                from app.infrastructure.lookups.purchase_unit_resolver import resolve_purchase_unit

                resolved = resolve_purchase_unit(potential_unit)
                logger.info("[SLOT_EXTRACTION_KEYWORD] resolved=%s", resolved)
                if resolved:
                    slots["unit_name"] = resolved.unit_name
                    slots["model_number"] = model
                else:
                    slots["unit_name"] = potential_unit
                    slots["model_number"] = model

        if "keyword" in slots and "model_number" not in slots:
            keyword = slots["keyword"]
            model_match = re.search(r"(\d{4}[A-Z]?)$", keyword)
            if model_match:
                slots["model_number"] = model_match.group(1)

        logger.info("[SLOT_EXTRACTION_END] final_slots=%s", slots)
        return slots

    def recognize_sync(self, message: str) -> dict[str, Any]:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return asyncio.run(self.recognize(message))
            else:
                return asyncio.run(self.recognize(message))
        except RECOVERABLE_ERRORS as e:
            logger.error("混合意图识别失败: %s", e)
            from .intent_service import recognize_intents

            rule_result = cast("dict[str, Any]", recognize_intents(message))
            rule_result["slots"] = self._extract_slots_from_rule(message, rule_result)
            return rule_result
