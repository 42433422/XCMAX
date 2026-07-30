"""Extracted compatibility functions for an existing public module."""

from __future__ import annotations

from app.utils.mixin_module_sync import sync_module_functions


def unified_chat_single_payload(
    message: str,
    requested_user_id: str,
    remote_addr: str,
    source: str,
    mode: Any,
    context: dict[str, Any] | None = None,
    *,
    authenticated_owner_user_id: int | None = None,
) -> dict[str, Any]:
    from app.utils.ai_helpers import is_pro_source, is_professional_mode, is_qclaw_source

    if (is_pro_source(source) or is_professional_mode(mode)) and not is_qclaw_source(source):
        return {
            "success": False,
            "message": "专业版请求禁止使用 /api/ai/unified_chat，请改用 /api/ai/chat",
            "mode_guard": "normal_only",
            "_http_status": 400,
        }

    text = str(message or "").strip()
    excel_analysis = (context or {}).get("excel_analysis") if isinstance(context, dict) else None
    if isinstance(excel_analysis, dict) and any(
        k in text for k in ("数据库", "入库", "导入", "添加到库", "加入")
    ):
        from app.application import get_ai_chat_app_service

        ai_chat_service = get_ai_chat_app_service()
        result = ai_chat_service.process_chat(
            user_id=_resolve_mode_scoped_user_id(requested_user_id, remote_addr, "normal"),
            message=message,
            context=context,
            source="normal",
            file_context={},
            authenticated_owner_user_id=authenticated_owner_user_id,
        )
        return result

    from app.application.normal_chat_dispatch import (
        build_product_query_response_dict,
        build_shipment_records_query_response_dict,
        route_normal_mode_message,
    )

    route_result = route_normal_mode_message(message)
    route_intent = route_result.get("intent")

    if route_intent == "shipment":
        try:
            from app.application.facades.tools_facade import _parse_order_text

            parsed_retry = _parse_order_text(message)
            if parsed_retry.get("success"):
                body = build_shipment_preview_response_dict(
                    parsed_retry.get("unit_name", ""),
                    parsed_retry.get("products") or [],
                    message,
                    order_number=parsed_retry.get("order_number"),
                    order_number_provenance=(
                        parsed_retry.get("order_number_provenance")
                        if isinstance(parsed_retry.get("order_number_provenance"), dict)
                        else None
                    ),
                    authenticated_owner_user_id=authenticated_owner_user_id,
                )
                return body

            local_msg = parsed_retry.get("message", "订单信息不完整，请补充单位/桶数/型号/规格。")
            return {
                "success": True,
                "message": "处理完成",
                "response": local_msg,
                "data": {
                    "text": local_msg,
                    "action": "followup",
                    "data": {"parsed_data": parsed_retry},
                },
            }
        except RECOVERABLE_ERRORS as local_parse_err:
            logger.error("普通版本地编号解析异常：%s", local_parse_err, exc_info=True)
            return {
                "success": False,
                "message": f"编号模式处理失败：{str(local_parse_err)}",
                "_http_status": 500,
            }

    if route_intent == "shipment_records_query":
        body = build_shipment_records_query_response_dict(route_result)
        if body:
            return body

    if route_intent == "product_query":
        body = build_product_query_response_dict(route_result)
        if body:
            return body

    return {
        "success": True,
        "message": "处理完成",
        "response": (
            "普通版里这是两套独立能力，请分开描述："
            "① 发货单/开单：用编号或口语描述订单（说法里常带「发货单、开单、打印」等）。"
            "② 产品库查询：查型号、价格（例如「查询七彩乐园的9803」），不会生成发货单。"
        ),
        "data": {
            "text": "普通版：发货单开单 与 产品库查询 为两套独立能力，请分开描述。",
            "action": "followup",
            "data": {"mode": "normal_slot_dispatch"},
        },
    }


sync_module_functions(
    target=globals(),
    source_module="app.application.ai_chat_helpers",
    function_names=("unified_chat_single_payload",),
)
