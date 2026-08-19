"""
DeepSeek 意图识别服务 v2

支持意图组合识别：
- 主意图识别
- 槽位信息提取（单位、数量、规格、联系人等）
- 复合意图理解
"""

import hashlib
import importlib
import logging
import os
import re
from typing import TYPE_CHECKING, Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.performance.cache_manager import get_intent_deepseek_cache

logger = logging.getLogger(__name__)


_intent_recognition_cache = get_intent_deepseek_cache()


def _make_intent_cache_key(message: str) -> str:
    return hashlib.sha256(f"intent_deepseek:v1:{message.strip().lower()}".encode()).hexdigest()


INTENT_DESCRIPTIONS = {
    "shipment_generate": "生成发货单、开单、打单、做出货单",
    "customers": "查看客户列表、购买单位、客户管理",
    "products": "查看产品列表、产品规格、产品库",
    "shipments": "查看发货记录、订单列表、出货记录",
    "wechat_send": "发微信、发消息给客户",
    "print_label": "打印标签、标签导出、商标打印、商标",
    "upload_file": "上传文件、导入数据、解析Excel",
    "materials": "原材料库存、材料库查询",
    "shipment_template": "发货单模板、模板设置",
    "template_extract": "提取模板、导出模板、提取Excel模板结构",
    "excel_decompose": "分解Excel、提取词条、表头提取",
    "business_docking": "业务对接、上传Excel、模板提取",
    "template_preview": "模板预览、模板列表、模板管理",
    "shipment_records": "出货记录、出货记录查询、出货记录导出",
    "wechat": "微信联系人、联系人列表、联系人缓存",
    "printer_list": "打印机列表、默认打印机",
    "settings": "系统设置、系统信息、开机启动",
    "tools_table": "工具表、工具能力列表",
    "other_tools": "其他工具",
    "ai_ecosystem": "AI生态、AI能力页",
    "show_images": "查看图片、产品图片",
    "show_videos": "查看视频",
    "greet": "问候、打招呼",
    "goodbye": "告别、再见",
    "help": "请求帮助、功能介绍",
    "negation": "否定指令、不要做某事",
    "customer_export": "导出客户列表、导出Excel",
    "customer_edit": "修改客户信息、修改设置",
    "customer_supplement": "补充客户信息、添加联系人",
}

SLOT_DEFINITIONS = {
    "unit_name": "购买单位、销售客户（如：七彩乐园、侯雪梅）",
    "model_number": "产品编号、型号（如：9803、2025）",
    "tin_spec": "产品规格、桶规格（如：28、20）",
    "quantity_tins": "产品数量、桶数（如：1桶、3桶、5桶）",
    "contact_person": "联系人姓名（如：向总、张经理）",
    "contact_phone": "联系电话、手机号",
    "contact_address": "联系地址",
    "order_no": "订单编号",
    "keyword": "搜索关键词",
}


_INTENT_SCHEMA = {
    "type": "object",
    "required": ["intent"],
    "properties": {
        "intent": {"type": "string"},
        "confidence": {"type": "number"},
        "slots": {"type": "object"},
        "reasoning": {"type": "string"},
    },
}


class DeepSeekIntentRecognizer:
    def __init__(
        self,
        api_key: str | None = None,
        confidence_threshold: float = 0.5,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        self.api_key = api_key
        self.confidence_threshold = confidence_threshold
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = None

    def _get_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            try:
                from app.utils.path_io.path_utils import get_resource_path

                config_path = get_resource_path("config", "deepseek_config.py")
                if config_path and os.path.exists(config_path):
                    import importlib.util

                    spec = importlib.util.spec_from_file_location(
                        "xcagi_deepseek_config", config_path
                    )
                    if spec and spec.loader:
                        config_module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(config_module)
                        key = getattr(config_module, "DEEPSEEK_API_KEY", "") or ""
            except RECOVERABLE_ERRORS:
                logger.debug("suppressed exception", exc_info=True)
        return key

    async def recognize(
        self, message: str, context: list[dict[str, str]] | None = None
    ) -> dict[str, Any]:
        """带槽位提取的意图识别（带缓存）"""
        cache_key = _make_intent_cache_key(message)
        cached = _intent_recognition_cache.get(cache_key)
        if cached:
            logger.info(
                "[INTENT_CACHE] 命中缓存: %s... -> %s, slots=%s",
                message[:30],
                cached.get("intent"),
                cached.get("slots"),
            )
            return cast("dict[str, Any]", cached)

        logger.info("[INTENT_CACHE] 缓存未命中，需要调用 DeepSeek API")

        intent_list = "\n".join([f"- {k}: {v}" for k, v in INTENT_DESCRIPTIONS.items()])
        slot_list = "\n".join([f"- {k}: {v}" for k, v in SLOT_DEFINITIONS.items()])

        system_prompt = f"""你是一个业务助手意图分类器。根据用户消息，识别意图和提取关键信息。

可选意图：
{intent_list}

槽位定义：
{slot_list}

分析要求：
1. 识别主意图（intent）
2. 提取所有提到的槽位信息（slots）
3. 如果是否定指令（不要、别），intent为negation，slots为空
4. 数量词需要标注真实数值

回复格式（严格JSON）：
{{"intent": "意图ID", "confidence": 0.0-1.0, "slots": {{"槽位名": "槽位值", ...}}, "reasoning": "简短分析"}}"""

        user_message = message
        if context:
            history = "\n".join([f"{m['role']}: {m['content']}" for m in context[-3:]])
            user_message = f"对话历史：\n{history}\n\n当前消息：{message}"

        from app.infrastructure.llm.structured_output import (
            StructuredOutputError,
            complete_structured,
        )

        try:
            structured = await complete_structured(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                schema=_INTENT_SCHEMA,
                max_repairs=self.max_retries - 1,
                profile="intent",
                temperature=0.1,
                max_tokens=300,
            )
        except StructuredOutputError as exc:
            logger.error("DeepSeek 意图识别最终失败: %s", exc.last_errors)
            fallback = self._fallback_result(message)
            _intent_recognition_cache.set(cache_key, fallback)
            return fallback

        parsed = self._normalize_intent_payload(structured.data, message)
        _intent_recognition_cache.set(cache_key, parsed)
        return parsed

    def _normalize_intent_payload(
        self, data: dict[str, Any], original_message: str
    ) -> dict[str, Any]:
        """complete_structured 校验通过后的收尾：意图白名单 + 槽位归一化。"""
        intent = str(data.get("intent") or "")
        if intent not in INTENT_DESCRIPTIONS and intent != "negation":
            return self._fallback_result(original_message)
        confidence = float(data.get("confidence") or 0.5)
        raw_slots = data.get("slots")
        slots = raw_slots if isinstance(raw_slots, dict) else {}
        return {
            "intent": intent,
            "confidence": min(confidence, 1.0),
            "slots": self._normalize_slots(slots, original_message),
            "reasoning": str(data.get("reasoning") or ""),
            "source": "deepseek",
        }

    def _parse_response(self, content: str, original_message: str) -> dict[str, Any]:
        import json

        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if "{" in line:
                    content = "\n".join(lines[i:])
                    break

        try:
            data = json.loads(content)
            intent = data.get("intent", "")
            confidence = float(data.get("confidence", 0.5))
            slots = data.get("slots", {})
            reasoning = data.get("reasoning", "")

            if intent in INTENT_DESCRIPTIONS or intent == "negation":
                normalized_slots = self._normalize_slots(slots, original_message)
                return {
                    "intent": intent,
                    "confidence": min(confidence, 1.0),
                    "slots": normalized_slots,
                    "reasoning": reasoning,
                    "source": "deepseek",
                }
        except json.JSONDecodeError:
            pass

        try:
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                intent = data.get("intent", "")
                confidence = float(data.get("confidence", 0.5))
                slots = data.get("slots", {})
                reasoning = data.get("reasoning", "")

                if intent in INTENT_DESCRIPTIONS or intent == "negation":
                    normalized_slots = self._normalize_slots(slots, original_message)
                    return {
                        "intent": intent,
                        "confidence": min(confidence, 1.0),
                        "slots": normalized_slots,
                        "reasoning": reasoning,
                        "source": "deepseek",
                    }
        except (json.JSONDecodeError, ValueError):
            pass

        return self._fallback_result(original_message, content)

    def _normalize_slots(self, slots: dict, message: str) -> dict[str, Any]:
        """规范化槽位值"""
        normalized: dict[str, Any] = {}

        for key, value in slots.items():
            if not value:
                continue

            value = str(value).strip()

            if key == "quantity_tins":
                match = re.search(r"(\d+|[一二两三四五六七八九十零]+)\s*桶", value) or re.search(
                    r"(\d+|[一二两三四五六七八九十零]+)\s*桶", message
                )
                if match:
                    normalized[key] = self._cn_to_number(match.group(1))
                else:
                    digits = re.search(r"\d+", value)
                    normalized[key] = int(digits.group()) if digits else value

            elif key == "tin_spec":
                match = re.search(r"规格\s*(\d+)", message)
                if match:
                    normalized[key] = float(match.group(1))
                else:
                    digits = re.search(r"\d+", value)
                    normalized[key] = float(digits.group()) if digits else value

            elif key == "unit_name":
                match = re.search(r"给\s*([^\s，,。]+)|([^\s，,。]+)\s*(?:的|发货单)", message)
                if match:
                    normalized[key] = match.group(1) or match.group(2)
                else:
                    normalized[key] = value

            elif key in ("contact_person", "contact_phone", "contact_address"):
                normalized[key] = value

            else:
                normalized[key] = value

        return normalized

    def _cn_to_number(self, cn: str) -> int:
        """中文数字转整数"""
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
            "十": 10,
        }
        try:
            if cn in cn_map:
                return cn_map[cn]
            result = 0
            for char in cn:
                if char in cn_map:
                    result = result * 10 + cn_map[char]
            return result if result > 0 else int(cn)
        except RECOVERABLE_ERRORS:
            digits = re.search(r"\d+", cn)
            return int(digits.group()) if digits else 0

    def _fallback_result(self, message: str, raw_response: str = "") -> dict[str, Any]:
        return {
            "intent": None,
            "confidence": 0.0,
            "slots": {},
            "reasoning": "DeepSeek 识别失败",
            "source": "deepseek",
            "raw_response": raw_response,
        }


_hybrid_module = importlib.import_module("app.services.deepseek_hybrid_intent")
if TYPE_CHECKING:
    from app.services.deepseek_hybrid_intent import HybridIntentWithDeepSeek
else:
    HybridIntentWithDeepSeek = _hybrid_module.HybridIntentWithDeepSeek


_deepseek_recognizer: DeepSeekIntentRecognizer | None = None
_hybrid_with_deepseek: HybridIntentWithDeepSeek | None = None


def get_deepseek_intent_recognizer(
    api_key: str | None = None, confidence_threshold: float = 0.5
) -> DeepSeekIntentRecognizer:
    global _deepseek_recognizer
    if _deepseek_recognizer is None:
        _deepseek_recognizer = DeepSeekIntentRecognizer(
            api_key=api_key, confidence_threshold=confidence_threshold
        )
    return _deepseek_recognizer


def get_hybrid_intent_with_deepseek(
    use_deepseek: bool = True,
    rule_priority: bool = True,
    confidence_threshold: float = 0.6,
    use_distilled: bool = False,
    reset: bool = False,
) -> HybridIntentWithDeepSeek:
    global _hybrid_with_deepseek
    if _hybrid_with_deepseek is None or reset:
        _hybrid_with_deepseek = HybridIntentWithDeepSeek(
            use_deepseek=use_deepseek,
            rule_priority=rule_priority,
            confidence_threshold=confidence_threshold,
            use_distilled=use_distilled,
        )
    return _hybrid_with_deepseek


def reset_deepseek_intent_services():
    global _deepseek_recognizer, _hybrid_with_deepseek
    _deepseek_recognizer = None
    _hybrid_with_deepseek = None


def get_deepseek_api_key() -> str:
    """获取 DeepSeek API Key，优先环境变量，其次配置文件"""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key
    try:
        from app.utils.path_io.path_utils import get_resource_path

        config_path = get_resource_path("config", "deepseek_config.py")
        if config_path and os.path.exists(config_path):
            import importlib.util

            spec = importlib.util.spec_from_file_location("xcagi_deepseek_config", config_path)
            if spec and spec.loader:
                config_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config_module)
                return getattr(config_module, "DEEPSEEK_API_KEY", "") or ""
    except RECOVERABLE_ERRORS:
        logger.debug("suppressed exception", exc_info=True)
    return ""


def cn_to_number(cn: str) -> int:
    """中文数字转整数"""
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
        "十": 10,
    }
    try:
        if cn in cn_map:
            return cn_map[cn]
        result = 0
        for char in cn:
            if char in cn_map:
                result = result * 10 + cn_map[char]
        return result if result > 0 else int(cn)
    except RECOVERABLE_ERRORS:
        digits = re.search(r"\d+", cn)
        return int(digits.group()) if digits else 0


# NEURO-DDD: 为 Services 层类添加 instrumentation
from app.neuro_bus.neuro_service_instrumentation import instrument_service_layer_class

instrument_service_layer_class(DeepSeekIntentRecognizer, "app.services.deepseek_intent_service")
instrument_service_layer_class(HybridIntentWithDeepSeek, "app.services.deepseek_intent_service")
