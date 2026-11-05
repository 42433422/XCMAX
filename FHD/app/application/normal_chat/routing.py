"""Deterministic routing policy with explicit optional-planner ports."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.utils.operational_errors import RECOVERABLE_ERRORS

_MAX_ROUTING_MESSAGE_CHARS = 4096
_OVERSIZED_SALES_WRITE_MARKERS = ("卖给", "销售给", "出售给")
_MODEL_CHARS = frozenset("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-")
_CHINESE_QUANTITY_CHARS = frozenset("一二两三四五六七八九十零〇")


def _has_print_spec_order(text: str) -> bool:
    """Recognize a model followed by 规格 and an integer using a linear scan."""
    search_from = 0
    while (spec_index := text.find("规格", search_from)) >= 0:
        cursor = spec_index - 1
        while cursor >= 0 and text[cursor].isspace():
            cursor -= 1
        if cursor >= 0 and text[cursor] == "的":
            cursor -= 1
            while cursor >= 0 and text[cursor].isspace():
                cursor -= 1
        end = cursor + 1
        while cursor >= 0 and text[cursor] in _MODEL_CHARS:
            cursor -= 1
        model = text[cursor + 1 : end]
        boundary_ok = cursor < 0 or text[cursor] not in _MODEL_CHARS
        digit_index = spec_index + len("规格")
        while digit_index < len(text) and text[digit_index].isspace():
            digit_index += 1
        if model and boundary_ok and digit_index < len(text) and text[digit_index].isdigit():
            return True
        search_from = spec_index + 1
    return False


def _has_number_style_order(text: str) -> bool:
    """Recognize quantity 桶 + model + 规格 number without nested repeats."""
    search_from = 0
    while (bucket_index := text.find("桶", search_from)) >= 0:
        cursor = bucket_index - 1
        while cursor >= 0 and text[cursor].isspace():
            cursor -= 1
        quantity_end = cursor + 1
        allowed = _CHINESE_QUANTITY_CHARS | frozenset("0123456789")
        while cursor >= 0 and text[cursor] in allowed:
            cursor -= 1
        quantity = text[cursor + 1 : quantity_end]
        boundary_ok = cursor < 0 or not (
            text[cursor].isdigit() or text[cursor] in _CHINESE_QUANTITY_CHARS
        )
        if quantity and boundary_ok:
            model_start = bucket_index + 1
            while model_start < len(text) and text[model_start].isspace():
                model_start += 1
            model_end = model_start
            while model_end < len(text) and text[model_end] in _MODEL_CHARS:
                model_end += 1
            if model_end > model_start:
                spec_start = model_end
                while spec_start < len(text) and text[spec_start].isspace():
                    spec_start += 1
                if text.startswith("规格", spec_start):
                    number_start = spec_start + 2
                    while number_start < len(text) and text[number_start].isspace():
                        number_start += 1
                    if number_start < len(text) and text[number_start].isdigit():
                        return True
        search_from = bucket_index + 1
    return False


class NegationCheck(Protocol):
    def __call__(self, text: str, /, *, action_keywords: list[str]) -> bool: ...


@dataclass(frozen=True)
class RoutingPorts:
    database_maintenance: Callable[[str], object | None]
    desktop_action: Callable[[str], dict[str, Any] | None]
    is_negation: NegationCheck
    is_negated_action: Callable[[str], bool]
    sales_write: Callable[[str], dict[str, Any] | None]
    label_slots: Callable[[str], dict[str, Any]]
    is_full_product_list: Callable[[str], bool]
    llm_route: Callable[[str], dict[str, Any] | None]
    logger: logging.Logger


_ARTIFACT_REQUEST_PATTERNS = (
    # 「表格文件 / 可下载的表格 / 导出成 Excel」等**产物**诉求
    r"(?:表格|报表|清单|文档|文件|excel|csv)[^，,。]{0,12}"
    r"(?:文件|下载|导出|发我|给我|生成|整理|保存|另存)",
    r"(?:下载|导出|生成|整理|保存|另存)[^，,。]{0,12}"
    r"(?:表格|报表|清单|文档|文件|excel|csv)",
)

# 客户类实体之外的业务实体：与客户类实体同句出现即视为**多实体**请求。
_OTHER_BUSINESS_ENTITIES = (
    "产品",
    "商品",
    "物料",
    "原材料",
    "货物",
    "订单",
    "单据",
    "发货单",
    "送货单",
    "采购单",
    "库存",
    "仓库",
    "员工",
)


def _is_artifact_request(text: str) -> bool:
    """用户是否明确索要**产物**（可下载的表格 / 报表文件）。"""
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in _ARTIFACT_REQUEST_PATTERNS)


def _mentions_other_business_entity(text: str) -> bool:
    return any(k in text for k in _OTHER_BUSINESS_ENTITIES)


def _requires_llm_planning(text: str, entity_markers: tuple[str, ...]) -> bool:
    """具体实体的产物或跨实体任务交给规划；单实体查询保留槽位路由。"""
    has_entity = any(k in text for k in entity_markers) or _mentions_other_business_entity(text)
    if not has_entity:
        return False
    if _is_artifact_request(text):
        return True
    return (
        bool(entity_markers)
        and any(k in text for k in entity_markers)
        and _mentions_other_business_entity(text)
    )


def route_message(message: str, ports: RoutingPorts) -> dict[str, Any]:
    """普通版轻量槽位提取与任务分流。"""
    text = (message or "").strip()
    if len(text) > _MAX_ROUTING_MESSAGE_CHARS:
        # Keep oversized messages off the general regex/LLM path, while allowing
        # the bounded linear sales parser to recognize an explicit write request.
        # This preserves whitespace-heavy legacy requests without reopening the
        # unbounded downstream routing surface.
        if any(marker in text for marker in _OVERSIZED_SALES_WRITE_MARKERS):
            sales_write_payload = ports.sales_write(text)
            if sales_write_payload is not None:
                return {
                    "intent": "sales_write",
                    "action": "execute_closed_loop",
                    "payload": sales_write_payload,
                }
        return {"intent": "unknown", "slots": {}}
    lower = text.lower()

    if ports.database_maintenance(text) is not None:
        return {"intent": "workflow", "slots": {}}
    desktop = ports.desktop_action(text)
    if desktop is not None:
        return {"intent": "desktop", "slots": desktop}
    if ports.is_negation(text, action_keywords=["打印", "标签", "贴标", "商标"]):
        return {"intent": "unknown", "slots": {}}
    shipment_keywords = ("发货单", "送货单", "出货单", "开单", "打单")
    print_spec_order = (
        "打印" in text
        and not any(word in text for word in ("标签", "商标", "贴标"))
        and _has_print_spec_order(text)
    )
    number_style_order = _has_number_style_order(text)
    template_preview = bool(
        re.search("(?:预览|看看|看下)[^，,。]{0,12}模板|模板[^，,。]{0,8}预览", text)
    )
    if ports.is_negated_action(text) or re.search(
        r"(?:不要|别|禁止|不准)[^，,。；;]{0,30}(?:出货|发货|送货)", text
    ):
        return {"intent": "unknown", "slots": {}}
    if re.search(r"(?:出货|发货)(?:记录|历史|列表|查询|明细)", text):
        if any(k in text for k in ("创建", "新增", "添加", "写入", "保存", "修改", "更新", "删除")):
            return {"intent": "unknown", "slots": {}}
        return {"intent": "shipment_records_query", "slots": {"keyword": ""}}
    if re.search(r"人工审批|手动审批|(?:客户|单位)名称\s*(?:仍为|为|是|[:：])", text):
        return {"intent": "workflow", "slots": {}}
    if (
        any(k in text for k in shipment_keywords) or number_style_order or print_spec_order
    ) and not template_preview:
        return {"intent": "shipment", "slots": {"number_style_order": number_style_order}}
    if template_preview:
        return {"intent": "unknown", "slots": {}}
    if any(k in text for k in ("出货", "发货", "送货")):
        return {"intent": "workflow", "slots": {}}
    sales_write_payload = ports.sales_write(text)
    if sales_write_payload is not None:
        return {
            "intent": "sales_write",
            "action": "execute_closed_loop",
            "payload": sales_write_payload,
        }
    query_keywords = ("查询", "查一下", "查下", "查", "看看", "看下", "搜索", "找下", "找", "检索")
    m_model = re.search(r"(?:型号|编号)\s*(?:[:：]\s*)?([0-9A-Za-z-]{2,})", text)
    model_signal = bool(m_model)
    m_unit_model = re.search(r"(?<![^\s，,。])([^\s，,。]{2,})\s*的\s*([0-9A-Za-z-]{2,})", text)
    unit_model_signal = bool(m_unit_model)
    customer_entity_markers = ("客户", "购买单位", "买家")
    if _requires_llm_planning(text, customer_entity_markers):
        return {"intent": "unknown", "slots": {}}
    if any(k in text for k in customer_entity_markers):
        customer_slots = {"keyword": ""}
        id_marker = r"(?<![A-Za-z0-9_])(?:ID|编号|#)"
        if re.search(id_marker, text, re.I):
            ids = re.findall(id_marker + r"\s*[:：为是]?\s*([A-Za-z0-9_.+-]+)", text, re.I)
            customer_slots["id"] = ids[0] if len(ids) == 1 else ""
        return {"intent": "customers_query", "slots": customer_slots}
    delete_keywords = ("删除", "移除", "删掉", "删了")
    if any(k in text for k in delete_keywords):
        del_target = ""
        target_match = re.search("(?:删除|移除|删掉|删了)\\s*([^\\s，,。]{2,})", text)
        if target_match:
            del_target = target_match.group(1).strip()
        return {"intent": "delete_entity", "slots": {"keyword": del_target}}
    # 产物请求仍走规划器，单实体汇总保留报表查询。
    if _requires_llm_planning(text, ()):
        return {"intent": "unknown", "slots": {}}
    for keywords, intent, route_slots in (
        (
            "报表 销售报表 库存报表 采购报表 汇总 经营看板 数据看板 统计",
            "reports_query",
            {"keyword": ""},
        ),
        (
            "库存盘点 盘点 实盘",
            "inventory_count",
            {"product_id": "", "warehouse_id": "", "actual_quantity": ""},
        ),
        ("库存 库存预警 低库存 库存不足 缺货 原材料库存 仓库", "inventory_alert", {}),
        ("标签 打标签 打印标签 商标 贴标", "label_print", {}),
        ("物料 原材料 材料", "materials_query", {"keyword": ""}),
        ("补货 补货建议 采购建议 建议采购 补多少", "replenishment_suggest", {}),
        ("生产工单 生产 工单 BOM 领料 完工", "mrp_production", {"order_id": "", "bom_id": ""}),
        ("采购 供应商 进货 采购单 采购订单 采购入库", "purchase_query", {"keyword": ""}),
        ("账龄 应收账龄 应付账龄", "aging_report", {"account_type": "应收", "days": 30}),
        ("财务 凭证 收支 应收 应付 交易流水 资金 对账 总账 记账", "finance_query", {}),
        (
            "销售订单 报价单 销售单 下单 收款 开票 发货单确认 销售明细",
            "sales_query",
            {"keyword": ""},
        ),
        ("知识库 资料库 帮助文档 使用文档 操作手册 帮助中心", "knowledge_query", {}),
    ):
        if any(keyword in text for keyword in keywords.split()):
            if intent == "label_print":
                route_slots = ports.label_slots(text)
            return {"intent": intent, "slots": route_slots}
    product_subject = any(word in text for word in ("产品", "商品", "货品"))
    model_token = bool(
        re.search(
            r"(?<![0-9A-Za-z])(?:\d{2,6}[A-Za-z][A-Za-z0-9-]*|\d{3,6})(?![0-9A-Za-z])",
            text,
        )
    ) or any(
        any(char.isdecimal() for char in match.group())
        or (match.end() < len(text) and text[match.end()].isdecimal())
        for match in re.finditer(r"(?<![0-9A-Za-z])[A-Za-z][A-Za-z0-9-]*", text)
    )
    if not _is_artifact_request(text) and (
        any(k in text for k in query_keywords)
        and (product_subject or model_token)
        or model_signal
        or unit_model_signal
    ):
        slots: dict[str, Any] = {}
        if m_unit_model:
            slots["unit_name"] = (m_unit_model.group(1) or "").strip()
            slots["model_number"] = (m_unit_model.group(2) or "").strip().upper()
        if m_model and (not slots.get("model_number")):
            slots["model_number"] = (m_model.group(1) or "").strip().upper()
        if slots.get("unit_name"):
            slots["unit_name"] = re.sub(
                "^(?:帮我|给我|请)?\\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\\s*",
                "",
                str(slots["unit_name"]),
                flags=re.IGNORECASE,
            ).strip()
        if not slots.get("model_number"):
            m_tail_model = re.search("\\b([0-9A-Za-z-]{3,})\\b", text)
            if m_tail_model:
                token = (m_tail_model.group(1) or "").strip().upper()
                if not re.fullmatch("(API|HTTP|JSON|XML)", token):
                    slots["model_number"] = token
        if not slots.get("keyword"):
            if slots.get("unit_name") and slots.get("model_number"):
                slots["keyword"] = f"{slots['unit_name']}{slots['model_number']}"
            elif slots.get("model_number"):
                tail = re.sub(
                    "^(?:帮我|给我|请)?\\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\\s*",
                    "",
                    text,
                ).strip()
                m_combo = re.search("([\\u4e00-\\u9fff]{2,})([0-9A-Za-z-]{2,})", tail)
                if m_combo:
                    slots["keyword"] = (
                        f"{m_combo.group(1).strip()}{m_combo.group(2).strip().upper()}"
                    )
                else:
                    slots["keyword"] = slots.get("model_number")
            else:
                keyword = re.sub(
                    "(?:帮我|给我|请|查询|查一下|查下|查|看看|看下|搜索|找下|找|检索|一下|一下子)",
                    " ",
                    lower,
                )
                keyword = re.sub("\\s+", " ", keyword).strip()
                keyword = "" if ports.is_full_product_list(keyword) else keyword
                if keyword:
                    slots["keyword"] = keyword
        return {"intent": "product_query", "slots": slots}
    # 规则全部未命中：走一次 LLM 意图闸（平台模型；离线/测试/失败自动回退 unknown）。
    try:
        llm_route = ports.llm_route(text)
        if llm_route is not None:
            return llm_route
    except RECOVERABLE_ERRORS:
        ports.logger.debug("LLM 意图闸跳过", exc_info=True)
    return {"intent": "unknown", "slots": {}}
