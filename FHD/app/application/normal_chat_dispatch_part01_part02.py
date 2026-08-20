# mypy: disable-error-code="no-any-return, valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib


def _facade():
    return importlib.import_module("app.application.normal_chat_dispatch")


def build_product_query_response_dict(
    route_result: dict[str, _facade().Any],
) -> dict[str, _facade().Any] | None:
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
                unit_name=None, model_number=None, keyword=kw_preview or None, page=1, per_page=5
            )
            or {}
        )
        rows = result.get("data") or []
        preview_count = len(rows)
        for row in rows[:3]:
            m = (row.get("model_number") or "").strip()
            n = (row.get("name") or row.get("product_name") or "-").strip()
            p = _facade().safe_float(row.get("price"))
            preview_lines.append(f"- {m or '-'} / {n} / ￥{_facade().format_money(p)}")
    except _facade().RECOVERABLE_ERRORS as query_err:
        _facade().logger.warning("产品查询预览失败：%s", query_err, exc_info=True)
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
        "response": f"已帮你打开产品副窗并带入「{keyword or model_number or query_desc}」。你可以直接在卡片里查看和修改。{preview_suffix}",
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


def run_workflow_products_query_normal_profile(
    user_message: str, node_params: dict[str, _facade().Any] | None = None, per_page: int = 20
) -> dict[str, _facade().Any]:
    node_params = dict(node_params or {})
    text = (user_message or "").strip()
    rr = _facade().route_normal_mode_message(text)
    kw_preview = ""
    if rr.get("intent") == "product_query":
        route_slots = rr.get("slots") or {}
        kw_preview = str(
            route_slots.get("keyword") or route_slots.get("model_number") or ""
        ).strip()
    if not kw_preview and rr.get("intent") != "product_query":
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
    except _facade().RECOVERABLE_ERRORS as err:
        _facade().logger.warning("normal_profile products.query 失败：%s", err, exc_info=True)
        return {"success": False, "message": str(err), "data": [], "normal_tool_profile": True}


def resolve_tool_execution_profile(runtime_context: dict[str, _facade().Any] | None) -> str:
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


def run_normal_slot_shipment_preview(order_text: str) -> dict[str, _facade().Any]:
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
        parsed.get("unit_name", ""), parsed.get("products") or [], text
    )
    body["normal_slot_dispatch"] = True
    return body


def run_normal_slot_product_query_from_message(message: str) -> dict[str, _facade().Any]:
    """normal_slot_dispatch.product_query：整段响应 dict（含 autoAction）。"""
    rr = _facade().route_normal_mode_message(message or "")
    body = _facade().build_product_query_response_dict(rr)
    if body is None:
        return {
            "success": False,
            "message": "当前话术未识别为普通版产品查询槽位",
            "data": {"intent": rr.get("intent"), "slots": rr.get("slots")},
        }
    body["normal_slot_dispatch"] = True
    return body


def _request_tenant_id(request: _facade().Any | None) -> int | None:
    """从 request 取 tenant_id（流式响应中 ContextVar 可能已被中间件 finally 清掉）。

    优先 ``request.state.tenant_id``；若为空再从 session Cookie 解析，避免市场 Bearer
    曾盖掉本地会话时中间件写入 None 导致 ORM fail-closed。
    """
    if request is None:
        return None
    try:
        value = getattr(getattr(request, "state", None), "tenant_id", None)
        if value is not None:
            return int(value)
    except (TypeError, ValueError, AttributeError):
        pass
    try:
        from app.infrastructure.auth.tenant_context import resolve_tenant_id

        return resolve_tenant_id(request)
    except _facade().RECOVERABLE_ERRORS:
        return None


def try_normal_slot_read_payload(
    message: str, *, request: _facade().Any | None = None
) -> dict[str, _facade().Any] | None:
    """普通版只读业务：命中则走确定性 Agent 工具（无 LLM 也可 tool-call）。

    客户类问题调用 customers.query 并写入 legacy_tool_records，避免 LLM 编造或误提关键词。
    StreamingResponse 迭代时显式恢复 request + tenant，避免 ContextVar 重置后租户读空。
    """
    text = str(message or "").strip()
    if not text:
        return None
    if _facade().looks_like_explicit_workflow_tool_intent(text):
        return None
    req_token = None
    if request is not None:
        try:
            from app.infrastructure.request_context import set_current_request

            req_token = set_current_request(request)
        except _facade().RECOVERABLE_ERRORS:
            req_token = None
    try:
        from app.infrastructure.tenant_scope import tenant_scope

        with tenant_scope(_facade()._request_tenant_id(request)):
            rr = _facade().route_normal_mode_message(text)
            intent = str(rr.get("intent") or "").strip()
            if intent == "customers_query":
                payload = _facade().build_customers_query_response_dict(rr, request=request)
            elif intent == "product_query":
                payload = _facade().build_product_query_response_dict(rr)
            elif intent == "inventory_alert":
                payload = _facade().build_inventory_alert_response_dict(rr)
            elif intent == "inventory_count":
                payload = _facade().build_inventory_count_response_dict(rr)
            elif intent == "mrp_production":
                payload = _facade().build_mrp_production_response_dict(rr)
            elif intent == "aging_report":
                payload = _facade().build_aging_report_response_dict(rr)
            elif intent == "label_print":
                payload = _facade().build_label_print_response_dict(rr)
            elif intent == "materials_query":
                payload = _facade().build_materials_query_response_dict(rr)
            elif intent == "shipment_records_query":
                payload = _facade().build_shipment_records_query_response_dict(rr)
            elif intent == "purchase_query":
                payload = _facade().build_purchase_query_response_dict(rr, message=text)
            elif intent == "finance_query":
                payload = _facade().build_finance_query_response_dict(rr)
            elif intent == "knowledge_query":
                payload = _facade().build_knowledge_query_response_dict(rr)
            elif intent == "sales_query":
                payload = _facade().build_sales_query_response_dict(rr)
            elif intent == "reports_query":
                payload = _facade().build_reports_query_response_dict(rr, message=text)
            elif intent == "replenishment_suggest":
                payload = _facade().build_replenishment_suggest_response_dict(rr)
            else:
                return None
    finally:
        if req_token is not None:
            try:
                from app.infrastructure.request_context import reset_current_request

                reset_current_request(req_token)
            except _facade().RECOVERABLE_ERRORS:
                pass
    if not isinstance(payload, dict):
        return None
    if payload.get("success") is False and (not payload.get("response")):
        return None
    return payload
