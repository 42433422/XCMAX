"""LLM 意图闸：规则路由未命中时，用配置的平台模型做一次轻量分类。

分层策略（行业共识的 hybrid routing）：
1. 关键词/正则路由（route_normal_mode_message）命中 → 直接返回，免费快路径；
2. 未命中 → 本模块调一次平台模型（complete_structured，JSON+置信度）；
3. 置信度达标且意图在确定性白名单内 → 合成路由结果，复用既有确定性 builders；
4. 任何异常/离线/低置信/含写操作动词 → 返回 None，行为与改造前完全一致（fail-open）。

设计约束：
- 只映射到「有只读/预览 builder」的意图，绝不让 LLM 直接触发删除/写入类路由；
- 结果按消息文本做短 TTL 缓存（同一条消息在链路中会被多次路由）；
- 测试环境默认关闭（PYTEST_CURRENT_TEST），避免真实网络调用；
- 离线模式（resolve_mode()==offline）直接跳过。
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

from app.utils.operational_errors import BOUNDARY_ERRORS, RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

# LLM 意图 → route_normal_mode_message 的 intent 词表（仅确定性有 builder 的）。
_LLM_TO_ROUTE: dict[str, str] = {
    "shipment_generate": "shipment",
    "customers": "customers_query",
    "products": "product_query",
    "materials": "materials_query",
    "print_label": "label_print",
    "shipment_records": "shipment_records_query",
    "shipments": "shipment_records_query",
    "sales_query": "sales_query",
    "reports_query": "reports_query",
    "replenishment_suggest": "replenishment_suggest",
    "inventory_alert": "inventory_alert",
    "knowledge_query": "knowledge_query",
}

_ROUTE_INTENTS = "\n".join(
    [
        "- shipment_generate: 开单/做发货单/出货单/给某客户出某产品某规格（会先出预览确认卡）",
        "- customers: 查看/搜索客户名单、某客户的信息、谁买过什么",
        "- products: 查看产品、某型号/规格的参数价格、有没有货（产品库）",
        "- materials: 原材料/物料/库存余量、要不要补货",
        "- print_label: 打印标签/商标/贴标（含数量）",
        "- shipment_records: 查发货记录/出货历史/上个月发了多少",
        "- sales_query: 销售订单/报价单/收款/开票情况",
        "- reports_query: 报表/汇总/经营看板/统计",
        "- replenishment_suggest: 补货建议/该采购什么",
        "- inventory_alert: 库存预警/缺货/低库存",
        "- knowledge_query: 怎么用、帮助文档、操作手册",
    ]
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["intent", "confidence"],
    "properties": {
        "intent": {"type": "string"},
        "confidence": {"type": "number"},
        "slots": {"type": "object"},
    },
}

_SYSTEM_PROMPT = f"""你是业务助手的意图分类器。用户消息已经过关键词规则筛选未命中，请判断其真实意图。

可选意图（只能从中选一个；都不像则 intent 填 "none"）：
{_ROUTE_INTENTS}

槽位（尽量提取，没有就不填）：
- unit_name: 客户/购买单位名称（如 太阳鸟、七彩乐园）
- model_number: 产品编号/型号（如 9803、A-100）
- tin_spec: 规格（如 28、20）
- quantity_tins: 桶数（数字）
- keyword: 搜索关键词（如人名、产品名）

要求：
1. 换说法、口语化、省略动词的表达也要归类（如「王总那家电话多少」→ customers）。
2. 明确表达删除/新增/修改/入库等写操作的，intent 填 "none"（交给专门链路）。
3. 纯寒暄、与业务无关的，intent 填 "none"。
4. confidence 为你对该分类的把握（0-1）。

严格只输出 JSON，例如：
{{"intent": "customers", "confidence": 0.9, "slots": {{"keyword": "王总"}}}}"""

# 写操作动词：命中则不走 LLM 路由（保持既有 planner/确认链路语义）。
_MUTATION_RE = re.compile(
    r"(新增|新建|添加|创建|写入|入库|导入|修改|更新|改为|改成|删除|移除|删掉|删了)"
)

_CONFIDENCE_MIN = 0.7
_CACHE_TTL_SECONDS = 120.0
_CACHE_MAX = 256
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


def _gate_enabled() -> bool:
    flag = (os.environ.get("XCAGI_LLM_INTENT_GATE") or "auto").strip().lower()
    if flag in ("0", "off", "false"):
        return False
    if flag in ("1", "on", "true"):
        return True
    # auto：测试环境默认关闭，避免真实网络调用；离线模式关闭。
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    try:
        from app.infrastructure.llm.client import resolve_mode

        if resolve_mode() == "offline":
            return False
    except RECOVERABLE_ERRORS:
        return False
    return True


def _cached(message: str) -> dict[str, Any] | None:
    entry = _cache.get(message)
    if not entry:
        return None
    ts, value = entry
    if time.monotonic() - ts > _CACHE_TTL_SECONDS:
        _cache.pop(message, None)
        return None
    return value


def _put_cache(message: str, value: dict[str, Any] | None) -> None:
    if len(_cache) >= _CACHE_MAX:
        _cache.clear()
    _cache[message] = (time.monotonic(), value)


def _normalize_slots(intent: str, raw_slots: dict[str, Any]) -> dict[str, Any]:
    slots = {k: str(v).strip() for k, v in raw_slots.items() if v is not None and str(v).strip()}
    if intent == "label_print":
        qty = slots.get("quantity_tins") or ""
        digits = re.search(r"\d+", qty)
        return {
            "model_number": (slots.get("model_number") or "").upper(),
            "quantity": int(digits.group()) if digits else 1,
        }
    if intent == "product_query":
        return {
            "unit_name": slots.get("unit_name", ""),
            "model_number": (slots.get("model_number") or "").upper(),
            "keyword": slots.get("keyword")
            or slots.get("unit_name")
            or slots.get("model_number", ""),
        }
    if intent in ("customers_query", "materials_query", "shipment_records_query", "sales_query"):
        keyword = slots.get("keyword") or slots.get("unit_name") or ""
        return {"keyword": keyword}
    return {}


def llm_route_message(message: str) -> dict[str, Any] | None:
    """规则未命中时的 LLM 分类。返回 route_normal_mode_message 形状的结果或 None。"""
    text = str(message or "").strip()
    if len(text) < 2 or not _gate_enabled():
        return None
    if _MUTATION_RE.search(text):
        return None
    try:
        from app.services.intent_service import recognize_intents

        flags = recognize_intents(text)
        if flags.get("is_negated") or flags.get("is_negation_intent"):
            return None
    except RECOVERABLE_ERRORS:
        pass

    cached = _cached(text)
    if cached is not None:
        return dict(cached) if cached.get("intent") != "unknown" else None

    result = _classify(text)
    _put_cache(text, result)
    return dict(result) if result and result.get("intent") != "unknown" else None


def _classify(text: str) -> dict[str, Any]:
    unknown: dict[str, Any] = {"intent": "unknown", "slots": {}, "llm_routed": False}
    try:
        from app.infrastructure.llm.structured_output import complete_structured_sync

        structured = complete_structured_sync(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            schema=_SCHEMA,
            max_repairs=0,
            profile="intent",
            temperature=0.1,
            max_tokens=160,
            timeout_seconds=10.0,
        )
    except BOUNDARY_ERRORS as exc:  # 闸层是适配器隔离边界：任何 LLM 失败都回退规则语义
        logger.info("[LLM_INTENT_GATE] skipped: %s", type(exc).__name__)
        return unknown

    data = structured.data if hasattr(structured, "data") else {}
    intent = str(data.get("intent") or "")
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    route_intent = _LLM_TO_ROUTE.get(intent)
    if not route_intent or confidence < _CONFIDENCE_MIN:
        logger.info("[LLM_INTENT_GATE] miss intent=%s conf=%.2f", intent or "none", confidence)
        return unknown
    raw_slots = data.get("slots")
    slots = _normalize_slots(route_intent, raw_slots if isinstance(raw_slots, dict) else {})
    logger.info(
        "[LLM_INTENT_GATE] hit %s -> %s conf=%.2f slots=%s", intent, route_intent, confidence, slots
    )
    return {"intent": route_intent, "slots": slots, "llm_routed": True, "confidence": confidence}


__all__ = ["llm_route_message"]
