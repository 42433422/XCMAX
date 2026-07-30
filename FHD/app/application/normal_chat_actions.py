"""Extracted compatibility functions for an existing public module."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


def run_workflow_products_query_normal_profile(
    user_message: str,
    node_params: dict[str, Any] | None = None,
    per_page: int = 20,
) -> dict[str, Any]:
    """工作流 products.query 在普通工具画像下：与普通版 product_query 相同 keyword 策略。"""
    node_params = dict(node_params or {})
    text = (user_message or "").strip()
    rr = route_normal_mode_message(text)
    kw_preview = ""
    if rr.get("intent") == "product_query":
        route_slots = rr.get("slots") or {}
        keyword = str(route_slots.get("keyword") or "").strip()
        model_number = str(route_slots.get("model_number") or "").strip().upper()
        kw_preview = (keyword or "").strip() or (model_number or "").strip()
    if not kw_preview:
        kw_preview = (
            str(node_params.get("keyword") or "").strip()
            or str(node_params.get("model_number") or "").strip().upper()
            or str(node_params.get("product_name") or node_params.get("name") or "").strip()
            or text
        )
    try:
        from app.bootstrap import get_products_service

        svc = get_products_service()
        result = (
            svc.get_products(
                unit_name=None,
                model_number=None,
                keyword=kw_preview or None,
                page=1,
                per_page=per_page,
            )
            or {}
        )
        return {
            "success": bool(result.get("success")),
            "data": result.get("data", []),
            "raw": result,
            "normal_tool_profile": True,
        }
    except RECOVERABLE_ERRORS as err:
        logger.warning("normal_profile products.query 失败：%s", err, exc_info=True)
        return {"success": False, "message": str(err), "data": [], "normal_tool_profile": True}


def resolve_tool_execution_profile(runtime_context: dict[str, Any] | None) -> str:
    """返回 normal | pro_default。"""
    rc = dict(runtime_context or {})
    explicit = str(rc.get("tool_execution_profile") or "").strip().lower()
    if explicit == "normal":
        return "normal"
    if explicit in ("pro_default", "pro", "professional"):
        return "pro_default"
    us = str(rc.get("ui_surface") or "").strip().lower()
    ic = str(rc.get("intent_channel") or "pro").strip().lower()
    if us == "normal" and ic == "pro":
        return "normal"
    return "pro_default"


def run_normal_slot_shipment_preview(
    order_text: str,
    *,
    authenticated_owner_user_id: int | None = None,
) -> dict[str, Any]:
    """
    normal_slot_dispatch.shipment_preview：与普通版 unified_chat shipment 分支同源（编号解析 + 预览任务）。
    延迟导入避免循环依赖。
    """
    text = (order_text or "").strip()
    if not text:
        return {"success": False, "message": "缺少 order_text", "data": {}}

    from app.application.facades.tools_facade import _parse_order_text

    parsed = _parse_order_text(text)
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

    from app.application import ai_chat_helpers as ai_chat_mod

    body = ai_chat_mod.build_shipment_preview_response_dict(
        parsed.get("unit_name", ""),
        parsed.get("products") or [],
        text,
        order_number=parsed.get("order_number"),
        order_number_provenance=(
            parsed.get("order_number_provenance")
            if isinstance(parsed.get("order_number_provenance"), dict)
            else None
        ),
        authenticated_owner_user_id=authenticated_owner_user_id,
    )
    body["normal_slot_dispatch"] = True
    return body


def run_normal_slot_product_query_from_message(message: str) -> dict[str, Any]:
    """normal_slot_dispatch.product_query：整段响应 dict（含 autoAction）。"""
    rr = route_normal_mode_message(message or "")
    body = build_product_query_response_dict(rr)
    if body is None:
        return {
            "success": False,
            "message": "当前话术未识别为普通版产品查询槽位",
            "data": {"intent": rr.get("intent"), "slots": rr.get("slots")},
        }
    body["normal_slot_dispatch"] = True
    return body


def build_customers_query_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """客户查询槽位响应。"""
    if route_result.get("intent") != "customers_query":
        return None
    keyword = str((route_result.get("slots") or {}).get("keyword") or "").strip()
    try:
        # 统一经当前请求 Mod 上下文感知的应用服务读取。历史上这里引用了
        # 不存在的 ``app.services.customers_service``，导致本地槽位命中后反而
        # 降级为“服务不可用”。这个路径只调用 get_all，不会产生写入。
        from app.bootstrap import get_customer_app_service

        result = get_customer_app_service().get_all(
            keyword=keyword or None,
            page=1,
            per_page=20,
        )
        if not isinstance(result, dict) or not result.get("success"):
            raise RuntimeError(
                str(result.get("message") if isinstance(result, dict) else "客户查询失败")
            )
        customers = result.get("data") or []
        if not isinstance(customers, list):
            customers = []
        total = int(result.get("total") or len(customers))
        if not customers:
            msg = f"未找到关键词「{keyword}」相关的客户。" if keyword else "暂无客户数据。"
        else:
            lines = [
                f"- {c.get('customer_name', '')} {c.get('contact_person', '')}"
                for c in customers[:10]
            ]
            msg = f"共找到 {total} 位客户：\n" + "\n".join(lines)
        return {
            "success": True,
            "response": msg,
            "data": {
                "intent": "customers_query",
                "customers": customers[:20],
                "total": total,
            },
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("customers_query 失败: %s", e)
        return {
            "success": False,
            "response": "客户查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_inventory_alert_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """库存预警槽位响应（聚合 materials low-stock + inventory alert）。"""
    if route_result.get("intent") != "inventory_alert":
        return None
    try:
        from app.application import get_material_application_service

        result = get_material_application_service().get_low_stock_materials()
        items = result.get("data") or []
        if not items:
            msg = "当前没有低库存原材料，库存状态正常。"
        else:
            lines = [
                f"- {m.get('name', '')} 当前库存 {m.get('quantity', 0)} {m.get('unit', '')}"
                for m in items[:10]
            ]
            msg = f"⚠️ 发现 {len(items)} 种低库存原材料：\n" + "\n".join(lines)
        return {
            "success": True,
            "response": msg,
            "data": {"intent": "inventory_alert", "low_stock_items": items[:20]},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("inventory_alert 失败: %s", e)
        return {
            "success": False,
            "response": "库存查询服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


def build_label_print_response_dict(route_result: dict[str, Any]) -> dict[str, Any] | None:
    """标签打印槽位响应。"""
    if route_result.get("intent") != "label_print":
        return None
    slots = route_result.get("slots") or {}
    model_number = str(slots.get("model_number") or "").strip()
    quantity = max(1, int(slots.get("quantity") or 1))
    if not model_number:
        return {
            "success": False,
            "response": "请告诉我要打印哪款产品的标签？例如「打印 A001 标签 2 张」",
            "data": {"intent": "label_print"},
            "normal_slot_dispatch": True,
        }
    try:
        from app.application.print_app_service import get_print_application_service

        result = get_print_application_service().print_single_label(
            product_name=model_number,
            model_number=model_number,
            quantity=quantity,
        )
        if result.get("success"):
            msg = f"已发送打印任务：{model_number} × {quantity} 张。"
        else:
            msg = f"打印失败：{result.get('message', '未知错误')}。请检查打印机连接。"
        return {
            "success": result.get("success", False),
            "response": msg,
            "data": {"intent": "label_print", **result},
            "normal_slot_dispatch": True,
        }
    except RECOVERABLE_ERRORS as e:
        logger.warning("label_print 失败: %s", e)
        return {
            "success": False,
            "response": "标签打印服务暂时不可用，请稍后重试。",
            "data": {},
            "normal_slot_dispatch": True,
        }


sync_module_functions(
    target=globals(),
    source_module="app.application.normal_chat_dispatch",
    function_names=(
        "run_workflow_products_query_normal_profile",
        "resolve_tool_execution_profile",
        "run_normal_slot_shipment_preview",
        "run_normal_slot_product_query_from_message",
        "build_customers_query_response_dict",
        "build_inventory_alert_response_dict",
        "build_label_print_response_dict",
    ),
)
