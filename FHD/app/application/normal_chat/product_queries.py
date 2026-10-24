"""Product window and workflow adapters sharing the same query port."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from app.utils.ai_helpers import format_money, safe_float
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .query_execution import JsonObject


class ProductQuery(Protocol):
    def __call__(self, keyword: str | None, per_page: int) -> JsonObject: ...


def product_window(
    route: JsonObject, query: ProductQuery, logger: logging.Logger
) -> JsonObject | None:
    if route.get("intent") != "product_query":
        return None
    slots = route.get("slots") or {}
    unit_name = str(slots.get("unit_name") or "").strip()
    model_number = str(slots.get("model_number") or "").strip().upper()
    keyword = str(slots.get("keyword") or "").strip()
    preview_lines = []
    preview_count = 0
    try:
        result = query(keyword or model_number or None, 5) or {}
        rows = result.get("data") or []
        preview_count = len(rows)
        for row in rows[:3]:
            model = (row.get("model_number") or "").strip()
            name = (row.get("name") or row.get("product_name") or "-").strip()
            preview_lines.append(
                f"- {model or '-'} / {name} / ￥{format_money(safe_float(row.get('price')))}"
            )
    except RECOVERABLE_ERRORS as error:
        logger.warning("产品查询预览失败：%s", error, exc_info=True)
    description = []
    if unit_name:
        description.append(f"单位：{unit_name}")
    if model_number:
        description.append(f"型号：{model_number}")
    if keyword and keyword != model_number:
        description.append(f"关键词：{keyword}")
    query_desc = "，".join(description) if description else "按当前输入"
    preview = (
        f"\n预览命中 {preview_count} 条：\n" + "\n".join(preview_lines) if preview_lines else ""
    )
    return {
        "success": True,
        "message": "已在副窗打开产品查询",
        "response": f"已帮你打开产品副窗并带入「{keyword or model_number or query_desc}」。你可以直接在卡片里查看和修改。{preview}",
        "autoAction": {
            "type": "show_products_float",
            "feature": "products",
            "query": keyword or model_number,
        },
        "data": {"routing": "normal_slot_dispatch", "intent": "product_query", "slots": slots},
    }


def workflow_products(
    user_message: str,
    node_params: JsonObject | None,
    per_page: int,
    *,
    route_message: Callable[[str], JsonObject],
    query: ProductQuery,
    logger: logging.Logger,
) -> JsonObject:
    params = dict(node_params or {})
    text = (user_message or "").strip()
    route = route_message(text)
    keyword = ""
    if route.get("intent") == "product_query":
        slots = route.get("slots") or {}
        keyword = str(slots.get("keyword") or slots.get("model_number") or "").strip()
    if not keyword and route.get("intent") != "product_query":
        keyword = (
            str(params.get("keyword") or "").strip()
            or str(params.get("model_number") or "").strip().upper()
            or str(params.get("product_name") or params.get("name") or "").strip()
            or text
        )
    try:
        result = query(keyword or None, per_page) or {}
        return {
            "success": bool(result.get("success")),
            "data": result.get("data", []),
            "raw": result,
            "normal_tool_profile": True,
        }
    except RECOVERABLE_ERRORS as error:
        logger.warning("normal_profile products.query 失败：%s", error, exc_info=True)
        return {"success": False, "message": str(error), "data": [], "normal_tool_profile": True}


def product_from_message(
    message: str,
    route_message: Callable[[str], JsonObject],
    build_response: Callable[[JsonObject], JsonObject | None],
) -> JsonObject:
    route = route_message(message or "")
    body = build_response(route)
    if body is None:
        return {
            "success": False,
            "message": "当前话术未识别为普通版产品查询槽位",
            "data": {"intent": route.get("intent"), "slots": route.get("slots")},
        }
    body["normal_slot_dispatch"] = True
    return body


def shipment_preview(
    order_text: str,
    parse_order: Callable[[str], JsonObject],
    build_preview: Callable[[str, list[JsonObject], str], JsonObject],
) -> JsonObject:
    text = (order_text or "").strip()
    if not text:
        return {"success": False, "message": "缺少 order_text", "data": {}}
    parsed = parse_order(text)
    if not parsed.get("success"):
        return {
            "success": True,
            "message": "处理完成",
            "response": str(parsed.get("message") or "订单信息不完整，请补充单位/桶数/型号/规格。"),
            "data": {
                "text": parsed.get("message"),
                "action": "followup",
                "data": {"parsed_data": parsed},
            },
            "normal_slot_dispatch": True,
        }
    body = build_preview(parsed.get("unit_name", ""), parsed.get("products") or [], text)
    body["normal_slot_dispatch"] = True
    return body


def resolve_tool_execution_profile(runtime_context: JsonObject | None) -> str:
    """返回 normal | pro_default。"""
    context = dict(runtime_context or {})
    explicit = str(context.get("tool_execution_profile") or "").strip().lower()
    if explicit == "normal":
        return "normal"
    if explicit in ("pro_default", "pro", "professional"):
        return "pro_default"
    surface = str(context.get("ui_surface") or "").strip().lower()
    channel = str(context.get("intent_channel") or "pro").strip().lower()
    return "normal" if surface == "normal" and channel == "pro" else "pro_default"
