"""
普通版聊天槽位路由与产品查询响应（与 unified_chat 行为一致）。

供 /api/ai/unified_chat、工作流 execute_registered_workflow_tool（tool_execution_profile=normal）
及 normal_slot_dispatch 工具复用。
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.utils.ai_helpers import format_money, safe_float
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


_PRICE_LIST_DOC_RE = re.compile(r"价格表|价目表|价目")
# 支持「XC 演示客户」「成都某某有限公司」等；允许中间空格/间隔号
_PRICE_LIST_CUSTOMER_RE = re.compile(
    r"((?:[^\s，,。]+[\s·]*){1,4}?(?:有限公司|集团有限公司|实业有限公司|公司|单位|客户|厂|店))"
)


def _extract_price_list_slots(text: str) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    customer_name_match = _PRICE_LIST_CUSTOMER_RE.search(text)
    if customer_name_match:
        name = customer_name_match.group(1).strip()
        name = re.sub(
            r"^(?:帮我|给我|请)?(?:打印|生成|导出|制作)(?:一下|一份)?",
            "",
            name,
        ).strip()
        if name:
            slots["customer_name"] = name
    keyword_match = re.search(r"的\s*([^\s，,。]+)", text)
    if keyword_match:
        kw = keyword_match.group(1).strip()
        if kw and not _PRICE_LIST_DOC_RE.search(kw):
            slots["keyword"] = kw
    return slots


def _json_safe_business_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_business_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_business_value(item) for item in value]
    return value


def route_normal_mode_message(message: str) -> dict[str, Any]:
    """
    普通版轻量槽位提取与任务分流：
    - price_list: 价格表 / 价目表 Word 导出
    - shipment: 发货单 / 开单 / 打单 / 出货单等单据语境
    - shipment_records_query: 发货/送货/出货记录查询
    - product_query: 产品库检索
    - customers_query: 客户/购买单位查询
    - inventory_alert: 库存预警
    - label_print: 标签打印
    - unknown: 未命中
    """
    text = (message or "").strip()
    lower = text.lower()

    # 价目/价格表优先于裸「打印」，避免「打印某某公司价格表」被收成发货单
    if _PRICE_LIST_DOC_RE.search(text):
        return {
            "intent": "price_list",
            "slots": _extract_price_list_slots(text),
        }

    shipment_record_keywords = ("发货记录", "送货记录", "出货记录", "业务记录")
    if any(keyword in text for keyword in shipment_record_keywords):
        unit_name = re.sub(
            r"^(?:帮我|给我|请)?\s*"
            r"(?:查询|查一下|查下|查|查看|看看|看下|搜索|找下|找|检索|列出)?"
            r"(?:一下)?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        unit_name = re.sub(
            r"\s*(?:的)?(?:最近(?:的)?)?"
            r"(?:发货记录|送货记录|出货记录|业务记录)(?:列表|明细)?"
            r"(?:是什么|有哪些|有多少|多少条)?[？?。！!\s]*$",
            "",
            unit_name,
            flags=re.IGNORECASE,
        ).strip()
        if unit_name in {"最近", "全部", "所有"}:
            unit_name = ""
        return {
            "intent": "shipment_records_query",
            "slots": {"unit_name": unit_name},
        }

    shipment_keywords = ("发货单", "送货单", "出货单", "开单", "打单", "打印")
    number_style_order = bool(
        re.search(
            r"(?:\d+|[一二两三四五六七八九十零〇]+)\s*桶\s*[0-9A-Za-z-]+\s*规格\s*\d+(?:\.\d+)?",
            text,
        )
    )
    if any(k in text for k in shipment_keywords) or number_style_order:
        return {
            "intent": "shipment",
            "slots": {"number_style_order": number_style_order},
        }

    query_keywords = ("查询", "查一下", "查下", "查", "看看", "看下", "搜索", "找下", "找", "检索")
    model_signal = bool(re.search(r"(?:型号|编号)\s*[:：]?\s*([0-9A-Za-z-]{2,})", text))
    unit_model_signal = bool(re.search(r"([^\s，,。]{2,})\s*的\s*([0-9A-Za-z-]{2,})", text))
    # 客户/购买单位查询
    customer_keywords = (
        "客户",
        "购买单位",
        "买家",
        "客户列表",
        "客户信息",
        "有哪些客户",
        "客户名单",
    )
    if any(k in text for k in customer_keywords):
        # 「有哪些客户？」是一个枚举请求，不应把「有哪些」当作名称关键词，
        # 否则会稳定地查出空列表。这里仅对完整的列表话术清空关键词；带有
        # 具体公司名的查询仍走下面的名称提取逻辑。
        normalized_customer_list_query = re.sub(r"[\s，,。！？!?：:]", "", text)
        if re.fullmatch(
            r"(?:有哪些|所有|全部)(?:的)?(?:客户|购买单位)(?:列表|名单)?"
            r"|(?:客户|购买单位)(?:有哪些|列表|名单)"
            r"|(?:查询|查找|搜索|查看|看|列出)(?:所有|全部)?(?:客户|购买单位)",
            normalized_customer_list_query,
        ):
            return {"intent": "customers_query", "slots": {"keyword": ""}}
        keyword_match = re.search(
            r"(?:查询|查找|找到|搜索|查一下|查下|查)?\s*([^\s，,。]{2,})\s*(?:的)?(?:客户|购买单位)",
            text,
        )
        return {
            "intent": "customers_query",
            "slots": {"keyword": (keyword_match.group(1) if keyword_match else "").strip()},
        }

    # 同样把纯产品列表话术识别为无关键词查询。不要把这个规则扩展到
    # 「产品价格怎么定」等开放式问题，后者仍交给正常聊天处理。
    normalized_product_list_query = re.sub(r"[\s，,。！？!?：:]", "", text)
    if re.fullmatch(
        r"(?:查|查询|查看|看|看看|列出|有哪些|所有|全部)?(?:的)?(?:产品|商品)(?:库|列表|名单)?",
        normalized_product_list_query,
    ):
        return {"intent": "product_query", "slots": {"keyword": ""}}

    # 库存预警
    inventory_keywords = ("库存", "库存预警", "低库存", "库存不足", "缺货", "原材料库存", "仓库")
    if any(k in text for k in inventory_keywords):
        return {
            "intent": "inventory_alert",
            "slots": {},
        }

    # 标签打印
    print_label_keywords = ("标签", "打标签", "打印标签", "商标", "贴标")
    if any(k in text for k in print_label_keywords):
        model_m = re.search(r"([0-9A-Za-z-]{2,})", text)
        qty_m = re.search(r"(\d+)\s*(?:张|份|个|次|条)?", text)
        return {
            "intent": "label_print",
            "slots": {
                "model_number": (model_m.group(1) if model_m else "").strip().upper(),
                "quantity": int(qty_m.group(1)) if qty_m else 1,
            },
        }

    if any(k in text for k in query_keywords) or model_signal or unit_model_signal:
        slots: dict[str, Any] = {}

        m_unit_model = re.search(r"([^\s，,。]{2,})\s*的\s*([0-9A-Za-z-]{2,})", text)
        if m_unit_model:
            slots["unit_name"] = (m_unit_model.group(1) or "").strip()
            slots["model_number"] = (m_unit_model.group(2) or "").strip().upper()

        m_model = re.search(r"(?:型号|编号)\s*[:：]?\s*([0-9A-Za-z-]{2,})", text)
        if m_model and not slots.get("model_number"):
            slots["model_number"] = (m_model.group(1) or "").strip().upper()

        if slots.get("unit_name"):
            slots["unit_name"] = re.sub(
                r"^(?:帮我|给我|请)?\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\s*",
                "",
                str(slots["unit_name"]),
                flags=re.IGNORECASE,
            ).strip()

        if not slots.get("model_number"):
            m_tail_model = re.search(r"\b([0-9A-Za-z-]{3,})\b", text)
            if m_tail_model:
                token = (m_tail_model.group(1) or "").strip().upper()
                if not re.fullmatch(r"(API|HTTP|JSON|XML)", token):
                    slots["model_number"] = token

        if not slots.get("keyword"):
            if slots.get("unit_name") and slots.get("model_number"):
                slots["keyword"] = f"{slots['unit_name']}{slots['model_number']}"
            elif slots.get("model_number"):
                tail = re.sub(
                    r"^(?:帮我|给我|请)?\s*(?:查询|查一下|查下|查|看看|看下|搜索|找下|找|检索)(?:一下)?\s*",
                    "",
                    text,
                ).strip()
                m_combo = re.search(r"([\u4e00-\u9fff]{2,})([0-9A-Za-z-]{2,})", tail)
                if m_combo:
                    slots["keyword"] = (
                        f"{m_combo.group(1).strip()}{m_combo.group(2).strip().upper()}"
                    )
                else:
                    slots["keyword"] = slots.get("model_number")
            else:
                keyword = re.sub(
                    r"(?:帮我|给我|请|查询|查一下|查下|查|看看|看下|搜索|找下|找|检索|一下|一下子)",
                    " ",
                    lower,
                )
                keyword = re.sub(r"\s+", " ", keyword).strip()
                if keyword:
                    slots["keyword"] = keyword

        return {"intent": "product_query", "slots": slots}

    return {"intent": "unknown", "slots": {}}


def build_product_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """构造与 unified_chat 产品查询分支一致的响应 dict。"""
    if route_result.get("intent") != "product_query":
        return None

    route_slots = route_result.get("slots") or {}
    unit_name = str(route_slots.get("unit_name") or "").strip()
    model_number = str(route_slots.get("model_number") or "").strip().upper()
    keyword = str(route_slots.get("keyword") or "").strip()

    preview_lines = []
    preview_count = 0
    try:
        from app.bootstrap import get_products_service

        products_service = get_products_service()
        kw_preview = (keyword or "").strip() or (model_number or "").strip()
        result = (
            products_service.get_products(
                unit_name=None,
                model_number=None,
                keyword=kw_preview or None,
                page=1,
                per_page=5,
            )
            or {}
        )
        rows = result.get("data") or []
        preview_count = len(rows)
        for row in rows[:3]:
            m = (row.get("model_number") or "").strip()
            n = (row.get("name") or row.get("product_name") or "-").strip()
            p = safe_float(row.get("price"))
            preview_lines.append(f"- {m or '-'} / {n} / ￥{format_money(p)}")
    except RECOVERABLE_ERRORS as query_err:
        logger.warning("产品查询预览失败：%s", query_err, exc_info=True)

    query_desc_bits = []
    if unit_name:
        query_desc_bits.append(f"单位：{unit_name}")
    if model_number:
        query_desc_bits.append(f"型号：{model_number}")
    if keyword and keyword != model_number:
        query_desc_bits.append(f"关键词：{keyword}")
    query_desc = "，".join(query_desc_bits) if query_desc_bits else "按当前输入"
    preview_suffix = (
        f"\n预览命中 {preview_count} 条：\n" + "\n".join(preview_lines) if preview_lines else ""
    )

    return {
        "success": True,
        "message": "已在副窗打开产品查询",
        "response": (
            f"已帮你打开产品副窗并带入「{keyword or model_number or query_desc}」。"
            "你可以直接在卡片里查看和修改。"
            f"{preview_suffix}"
        ),
        "autoAction": {
            "type": "show_products_float",
            "feature": "products",
            "query": keyword or model_number,
        },
        "data": {
            "routing": "normal_slot_dispatch",
            "intent": "product_query",
            "slots": route_slots,
        },
    }


def build_shipment_records_query_response_dict(
    route_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Build a tenant-scoped, read-only shipment record response."""

    if route_result.get("intent") != "shipment_records_query":
        return None
    unit_name = str((route_result.get("slots") or {}).get("unit_name") or "").strip()
    try:
        from app.bootstrap import get_shipment_app_service

        records = get_shipment_app_service().get_shipment_records(
            unit_name or None,
            limit=10,
        )
        records = _json_safe_business_value(records)
    except RECOVERABLE_ERRORS as query_err:
        logger.warning("发货记录查询失败：%s", query_err, exc_info=True)
        return {
            "success": False,
            "message": "发货记录查询失败",
            "response": "当前无法读取发货记录，请稍后重试。",
            "data": {
                "routing": "normal_slot_dispatch",
                "intent": "shipment_records_query",
                "slots": {"unit_name": unit_name},
                "records": [],
            },
        }

    title = f"{unit_name}最近的发货记录" if unit_name else "最近的发货记录"
    lines = [f"{title}（{len(records)} 条）："]
    total_amount = 0.0
    status_labels = {
        "pending": "待打印",
        "printed": "已打印",
        "completed": "已完成",
        "cancelled": "已取消",
    }
    for row in records:
        amount = safe_float(row.get("amount"))
        total_amount += amount
        product_name = str(row.get("product_name") or "-").strip()
        model_number = str(row.get("model_number") or "").strip()
        quantity_tins = int(safe_float(row.get("quantity_tins")))
        quantity_kg = safe_float(row.get("quantity_kg"))
        status = str(row.get("status") or "").strip()
        product_label = f"{product_name}（{model_number}）" if model_number else product_name
        quantity_bits = []
        if quantity_tins:
            quantity_bits.append(f"{quantity_tins}桶")
        if quantity_kg:
            quantity_bits.append(f"{format_money(quantity_kg)}kg")
        lines.append(
            f"- #{row.get('id')} | {product_label} | "
            f"{'/'.join(quantity_bits) or '数量未填'} | "
            f"￥{format_money(amount)} | {status_labels.get(status, status or '未标记')}"
        )
    if records:
        lines.append(f"以上记录金额合计：￥{format_money(total_amount)}。")
    else:
        lines.append("没有找到匹配记录。")
    return {
        "success": True,
        "message": "发货记录查询完成",
        "response": "\n".join(lines),
        "data": {
            "routing": "normal_slot_dispatch",
            "intent": "shipment_records_query",
            "slots": {"unit_name": unit_name},
            "records": records,
            "count": len(records),
            "total_amount": total_amount,
        },
    }


from app.application.normal_chat_actions import (
    build_customers_query_response_dict,
    build_inventory_alert_response_dict,
    build_label_print_response_dict,
    resolve_tool_execution_profile,
    run_normal_slot_product_query_from_message,
    run_normal_slot_shipment_preview,
    run_workflow_products_query_normal_profile,
)
