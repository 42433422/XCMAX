"""
全流程意图层 v2 - 基于规则引擎

统一意图定义、否定检测、问候/再见/模糊判断，供 AI 对话系统使用。
支持从配置文件加载意图规则，热更新无需重启服务。

流程：
1. 问候/再见 -> 直接回复，不进入工具
2. 否定式指令 -> 不触发对应工具，走 AI 或友好提示
3. 工具意图 -> 关键词匹配 + 优先级，考虑否定
4. 仅模板查询 -> intent_hints 兜底模板直答
5. 模糊/短句/未知 -> 走 AI 兜底或引导

本模块现在委托给 domain.services.intent 下的策略类处理具体检测逻辑
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from app.domain.neuro.reflex_arc import ReflexType, get_reflex_arc
from app.services.intent_recognition_pipeline import (
    recognize_intents_impl as _recognize_intents_impl,
)
from app.services.intent_slot_helpers import (
    extract_multi_unit_names as _extract_multi_unit_names,
)
from app.services.intent_slot_helpers import (
    extract_name_before_quantity as _extract_name_before_quantity,  # noqa: F401
)
from app.services.rule_engine import get_rule_engine as get_rule_engine
from app.services.rule_engine import reload_rule_engine
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.performance.cache_manager import get_intent_rule_cache
from resources.config.intent_config import get_intent_config, reload_intent_config

_intent_cache = get_intent_rule_cache()

_reflex_arc = get_reflex_arc()

logger = logging.getLogger(__name__)

_quick_command_map: dict[str, str] = {}
_quick_intent_patterns: list[tuple[str, str]] = []
_context_inherit_patterns: list[tuple[str, str]] = []
_append_keywords: list[str] = []
_negation_action_keywords: dict[str, list[str]] = {}


def _load_intent_runtime_rules() -> None:
    """从配置加载快路径/否定动作等运行时规则。"""
    global \
        _quick_command_map, \
        _quick_intent_patterns, \
        _context_inherit_patterns, \
        _append_keywords, \
        _negation_action_keywords

    config = get_intent_config()
    quick_rules = config.get("quick_rules", {}) or {}

    # command_map: { "开单": "shipment_generate", ...}
    _quick_command_map = quick_rules.get("command_map", {}) or {}

    # intent_patterns:
    # - YAML:  [{pattern: "...", intent: "..."}]
    # - Python default: [(pattern, intent), ...]
    _quick_intent_patterns = []
    for item in quick_rules.get("intent_patterns", []) or []:
        if isinstance(item, dict):
            pattern = item.get("pattern")
            intent = item.get("intent")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            pattern, intent = item
        else:
            continue
        if pattern and intent:
            _quick_intent_patterns.append((pattern, intent))

    # context_inherit_patterns: 同上（dict 或 tuple）
    _context_inherit_patterns = []
    for item in quick_rules.get("context_inherit_patterns", []) or []:
        if isinstance(item, dict):
            pattern = item.get("pattern")
            action = item.get("action")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            pattern, action = item
        else:
            continue
        if pattern and action:
            _context_inherit_patterns.append((pattern, action))

    _append_keywords = quick_rules.get("append_keywords", []) or []

    # negation_action_keywords: { "shipment_generate": [...], ...}
    _negation_action_keywords = config.get("negation_action_keywords", {}) or {}


_load_intent_runtime_rules()


def _make_intent_cache_key(message: Any) -> str:
    normalized = _normalize(message if isinstance(message, str) else str(message or ""))
    return hashlib.md5(normalized.lower().encode()).hexdigest()


def _normalize(msg: str | None) -> str:
    """标准化消息字符串"""
    if not isinstance(msg, str):
        return ""
    return (msg or "").strip()


def reload_intent_service() -> None:
    """重新加载意图服务（热更新）"""
    global _intent_cache
    _intent_cache.clear()
    reload_intent_config()
    global _reflex_arc
    _reflex_arc = get_reflex_arc()
    reload_rule_engine()
    _load_intent_runtime_rules()


def _reflex_basic_intents(message: str) -> dict[str, bool]:
    """通过 NeuroDDD 反射弧检测基础意图（问候/否定/确认/帮助/告别）"""
    rr = _reflex_arc.process(message)
    msg_lower = (message or "").strip().lower()
    result = {
        "is_greeting": (rr.reflex_type == ReflexType.GREETING and rr.triggered)
        or any(w in msg_lower for w in ("你好", "您好", "hello", "hi", "嗨")),
        "is_goodbye": (rr.reflex_type == ReflexType.EMERGENCY_STOP and rr.triggered)
        or any(w in msg_lower for w in ("再见", "拜拜", "bye", "先这样")),
        "is_help": (rr.reflex_type == ReflexType.HELP and rr.triggered)
        or any(w in msg_lower for w in ("你能做什么", "怎么用", "帮助", "help")),
        "is_confirmation": (rr.reflex_type == ReflexType.CONFIRMATION and rr.triggered)
        or any(w in msg_lower for w in ("好的", "可以", "确认", "是的", "ok", "yes")),
        "is_negation_intent": rr.reflex_type == ReflexType.DENIAL and rr.triggered,
        "is_negated": rr.reflex_type == ReflexType.DENIAL and rr.triggered,
    }
    return result


def is_negation(message: str, action_keywords: list[str] | None = None) -> bool:
    """判断是否为否定式指令"""
    rr = _reflex_arc.process(message)
    if rr.reflex_type == ReflexType.DENIAL and rr.triggered:
        if action_keywords:
            msg_lower = message.lower()
            return any(kw.lower() in msg_lower for kw in action_keywords)
        return True
    if action_keywords:
        negation_words = ["不要", "别", "不用", "不需要", "no", "not", "别开", "不要开"]
        msg_lower = message.lower()
        has_neg = any(nw in msg_lower for nw in negation_words)
        if has_neg:
            return any(kw.lower() in msg_lower for kw in action_keywords)
    msg_lower = message.lower()
    return any(nw in msg_lower for nw in ("不要", "别", "不用", "不需要", "no", "not"))


def is_greeting(message: str) -> bool:
    """判断是否为问候语"""
    rr = _reflex_arc.process(message)
    if rr.reflex_type == ReflexType.GREETING and rr.triggered:
        return True
    msg_lower = (message or "").lower()
    return any(w in msg_lower for w in ("你好", "您好", "hello", "hi", "嗨"))


def is_goodbye(message: str) -> bool:
    """判断是否为告别语"""
    rr = _reflex_arc.process(message)
    if rr.reflex_type == ReflexType.EMERGENCY_STOP and rr.triggered:
        return True
    msg_lower = message.lower()
    return any(w in msg_lower for w in ("再见", "拜拜", "bye", "先这样"))


def is_help_request(message: str) -> bool:
    """判断是否为帮助请求"""
    rr = _reflex_arc.process(message)
    if rr.reflex_type == ReflexType.HELP and rr.triggered:
        return True
    msg_lower = message.lower()
    return any(w in msg_lower for w in ("你能做什么", "怎么用", "帮助", "help"))


def is_confirmation(message: str) -> bool:
    """判断是否为确认意图"""
    rr = _reflex_arc.process(message)
    if rr.reflex_type == ReflexType.CONFIRMATION and rr.triggered:
        return True
    msg_lower = (message or "").lower()
    return any(w in msg_lower for w in ("好的", "可以", "确认", "是的", "ok", "yes"))


def is_negation_intent(message: str) -> bool:
    """判断是否为否定意图"""
    rr = _reflex_arc.process(message)
    if rr.reflex_type == ReflexType.DENIAL and rr.triggered:
        return True
    msg_lower = message.lower()
    if any(w in msg_lower for w in ("算了", "取消", "不用了")):
        return True
    return is_negation(message)


QUICK_COMMAND_MAP = {
    "开单": "shipment_generate",
    "开发货单": "shipment_generate",
    "生成发货单": "shipment_generate",
    "打单": "shipment_generate",
    "查产品": "products",
    "产品列表": "products",
    "查客户": "customers",
    "客户列表": "customers",
    "发货单模板": "shipment_template",
    "当前模板": "shipment_template",
    "出货记录": "shipment_records",
    "发货记录": "shipments",
    "发微信": "wechat_send",
    "发送微信": "wechat_send",
    "打印标签": "print_label",
    "打印": "print_label",
    "上传": "upload_file",
    "导入": "upload_file",
    "导出": "upload_file",
    "材料": "materials",
    "原材料": "materials",
    "库存": "materials",
    "分解": "excel_decompose",
    "分解excel": "excel_decompose",
    "提取模板": "template_extract",
    "导出模板": "template_extract",
    "业务对接": "business_docking",
    "模板预览": "template_preview",
    "微信联系人": "wechat",
    "联系人列表": "wechat",
    "打印机列表": "printer_list",
    "系统设置": "settings",
    "工具表": "tools_table",
    "其他工具": "other_tools",
    "ai生态": "ai_ecosystem",
    "AI生态": "ai_ecosystem",
}

QUICK_INTENT_PATTERNS = [
    (r"^发货单[^\s]{2,10}\s*\d+[桶箱件个]", "shipment_generate"),
    (r"^送货单[^\s]{2,10}\s*\d+[桶箱件个]", "shipment_generate"),
    (r"^出货单[^\s]{2,10}\s*\d+[桶箱件个]", "shipment_generate"),
    (r"发货单.*桶.*规格", "shipment_generate"),
    (r"开单.*[一二三四五六七八九十零〇\d]+.*桶", "shipment_generate"),
    (r"打印.*\d+.*规格", "shipment_generate"),
]

_CONTEXT_INHERIT_PATTERNS = [
    (r"^再[一1]份$", "repeat_last"),
    (r"^再.*[一1]份$", "repeat_last"),
    (r"^同样$", "repeat_last"),
    (r"^一样$", "repeat_last"),
    (r"^按上次的$", "repeat_last"),
    (r"^和上次一样$", "repeat_last"),
]

_APPEND_KEYWORDS = ["再加", "还要", "再加1", "再来", "继续加", "再补", "追加", "额外", "加上"]


def recognize_intents(message: str) -> dict[str, Any]:
    """对外接口：全流程意图识别入口（带异常兜底）"""
    try:
        return _recognize_intents_impl(message)
    except RECOVERABLE_ERRORS as e:
        logger.exception("recognize_intents failed: %s", e)
        return {
            "primary_intent": None,
            "tool_key": None,
            "intent_hints": [],
            "is_negated": False,
            "is_greeting": False,
            "is_goodbye": False,
            "is_help": False,
            "is_confirmation": False,
            "is_negation_intent": False,
            "is_likely_unclear": True,
            "all_matched_tools": [],
            "slots": {},
        }


def get_tool_key_with_negation_check(message: str) -> str | None:
    """对外接口：在考虑否定后，返回应触发的 tool_key"""
    r = recognize_intents(message)
    return r.get("tool_key")


_MULTI_UNIT_PATTERN = r"([^\s，,、和]+)(?:[和、,]([^\s，,、]+))+"
_MULTI_UNIT_SEPARATORS = ["和", "、", ",", "，"]


def quick_recognize(message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    快速意图识别通道

    流程：
    1. 快捷命令匹配 -> 直接返回
    2. 明确意图关键词匹配 -> 快速返回
    3. 上下文继承检测 -> 使用上下文意图
    4. 不匹配 -> 返回 None（走完整识别）

    Args:
        message: 用户消息
        context: 对话上下文

    Returns:
        快速识别结果
    """
    import time

    start_time = time.time()

    msg = _normalize(message)
    msg_lower = msg.lower()

    result: dict[str, Any] = {
        "fast_path": True,
        "primary_intent": None,
        "tool_key": None,
        "slots": {},
        "context_inherited": False,
        "source": "quick_recognize",
        "elapsed_ms": 0,
    }

    if not msg:
        result["elapsed_ms"] = round((time.time() - start_time) * 1000, 2)
        return result

    for cmd, intent in _quick_command_map.items():
        if msg == cmd or msg_lower == cmd.lower():
            result["primary_intent"] = intent
            result["tool_key"] = intent
            result["source"] = "quick_command"
            result["elapsed_ms"] = round((time.time() - start_time) * 1000, 2)
            return result

    for pattern, intent in _quick_intent_patterns:
        if re.search(pattern, msg):
            result["primary_intent"] = intent
            result["tool_key"] = intent
            result["source"] = "quick_pattern"
            result["elapsed_ms"] = round((time.time() - start_time) * 1000, 2)
            return result

    if context:
        for append_kw in _append_keywords:
            if msg.startswith(append_kw) or f"^{append_kw}" in msg:
                pending = context.get("pending_confirmation")
                if pending:
                    pending_intent = pending.get("intent") or pending.get("tool_key")
                    pending_slots = pending.get("slots", {}).copy() if pending.get("slots") else {}
                    result["primary_intent"] = pending_intent
                    result["tool_key"] = pending_intent
                    result["slots"] = pending_slots
                    result["context_inherited"] = True
                    result["source"] = "append_inherit"
                    result["is_append"] = True
                    result["elapsed_ms"] = round((time.time() - start_time) * 1000, 2)
                    return result

                last_intent = context.get("current_intent") or context.get("last_intent")
                last_tool = context.get("current_tool_key") or context.get("last_tool_key")
                last_slots = (
                    context.get("last_slots", {}).copy() if context.get("last_slots") else {}
                )
                if last_intent or last_tool:
                    result["primary_intent"] = last_intent
                    result["tool_key"] = last_tool
                    result["slots"] = last_slots
                    result["context_inherited"] = True
                    result["source"] = "append_inherit"
                    result["is_append"] = True
                    result["elapsed_ms"] = round((time.time() - start_time) * 1000, 2)
                    return result

        for pattern, action in _context_inherit_patterns:
            if re.search(pattern, msg):
                if action == "repeat_last":
                    last_intent = context.get("current_intent") or context.get("last_intent")
                    last_tool = context.get("current_tool_key") or context.get("last_tool_key")
                    last_slots = context.get("last_slots", {})
                    if last_intent or last_tool:
                        result["primary_intent"] = last_intent
                        result["tool_key"] = last_tool
                        result["slots"] = last_slots.copy() if last_slots else {}
                        result["context_inherited"] = True
                        result["source"] = "context_inherit"
                        result["elapsed_ms"] = round((time.time() - start_time) * 1000, 2)
                        return result

        if context.get("pending_confirmation"):
            pending = context["pending_confirmation"]
            pending_intent = pending.get("intent") or pending.get("tool_key")
            if pending_intent:
                pending_slots = pending.get("slots", {})
                result["primary_intent"] = pending_intent
                result["tool_key"] = pending_intent
                result["slots"] = pending_slots.copy() if pending_slots else {}
                result["context_inherited"] = True
                result["source"] = "context_pending"
                result["elapsed_ms"] = round((time.time() - start_time) * 1000, 2)
                return result

    result["elapsed_ms"] = round((time.time() - start_time) * 1000, 2)
    return result


def quick_slot_extraction(message: str, intent: str) -> dict[str, Any]:
    """
    快速槽位提取

    针对明确意图快速提取槽位信息

    Args:
        message: 用户消息
        intent: 识别的意图

    Returns:
        槽位字典
    """
    msg = _normalize(message)
    slots: dict[str, Any] = {}

    if intent == "shipment_generate":
        unit_names = _extract_multi_unit_names(msg)
        if unit_names:
            if len(unit_names) == 1:
                slots["unit_name"] = unit_names[0]
            else:
                slots["unit_name"] = unit_names

        quantity_match = re.search(r"(\d+|[一二三四五六七八九十零〇两]+)\s*[桶箱件个]", msg)
        if quantity_match:
            slots["quantity"] = quantity_match.group(0)

        spec_match = re.search(r"规格\s*(\d+)", msg)
        if spec_match:
            slots["spec"] = spec_match.group(1)

        model_match = re.search(r"型号?\s*(\d+)", msg)
        if model_match:
            slots["model_number"] = model_match.group(1)

    elif intent == "products" or intent == "customers":
        if msg:
            slots["keyword"] = msg

    return slots
