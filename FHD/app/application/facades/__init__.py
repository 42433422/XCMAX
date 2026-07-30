"""
NeuroDDD 域门面层。

该包是路由层与领域层的桥接层。聚合导出保持兼容，但具体门面按需加载，避免
``app.application`` 统一入口导入时拉起 pandas / 向量库等重依赖。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "AIConversationService": "app.application.facades.ai_conversation_facade",
    "ShipmentApplicationServiceEventPrimary": "app.application.facades.shipment_event_primary",
    "BertIntentClassifier": "app.application.facades.intent_facade",
    "EMPLOYEE_MOD_ID": "app.application.facades.user_cs_employee_facade",
    "run_user_cs_employee": "app.application.facades.user_cs_employee_facade",
    "InventoryService": "app.application.facades.inventory_facade",
    "PurchaseService": "app.application.facades.inventory_facade",
    "ReportService": "app.application.facades.inventory_facade",
    "MobileRelayService": "app.application.facades.mobile_relay_facade",
    "register_desktop_relay": "app.application.facades.mobile_relay_facade",
    "KittenReportExportService": "app.application.facades.kitten_facade",
    "FinancialReportPlugin": "app.application.facades.kitten_facade",
    "InventoryValuationPlugin": "app.application.facades.kitten_facade",
    "document_templates_service": "app.application.facades.template_facade",
    "_extract_structured_excel_preview": "app.application.facades.template_facade",
    "_parse_order_text": "app.application.facades.tools_facade",
    "execute_registered_workflow_tool": "app.application.facades.tools_facade",
    "execute_tool_from_payload": "app.application.facades.tools_facade",
    "get_workflow_tool_registry": "app.application.facades.tools_facade",
    "run_archive_tools_execute": "app.application.facades.tools_facade",
    "set_tool_execute_headers": "app.application.facades.tools_facade",
    "build_kitten_business_snapshot": "app.application.facades.kitten_facade",
    "build_kitten_docx": "app.application.facades.kitten_facade",
    "chart_service": "app.application.facades.kitten_facade",
    "analysis_save_service": "app.application.facades.kitten_facade",
    "generate_office_file": "app.application.facades.kitten_facade",
    "pop_document_pickup": "app.application.facades.kitten_facade",
    "find_product": "app.application.facades.query_facade",
    "find_purchase_unit": "app.application.facades.query_facade",
    "get_product_names": "app.application.facades.query_facade",
    "get_purchase_units": "app.application.facades.query_facade",
    "query_service": "app.application.facades.query_facade",
    "get_conversation_service": "app.application.facades.conversation_facade",
    "get_data_analysis_service": "app.application.facades.conversation_facade",
    "get_user_preference_service": "app.application.facades.conversation_facade",
    "get_ai_product_parser": "app.application.facades.excel_facade",
    "get_product_import_service": "app.application.facades.excel_facade",
    "get_auth_service": "app.application.facades.session_facade",
    "get_database_service": "app.application.facades.session_facade",
    "get_session_service": "app.application.facades.session_facade",
    "get_system_service": "app.application.facades.session_facade",
    "get_ocr_service": "app.application.facades.ocr_facade",
    "refresh_wechat_contacts_from_decrypt": "app.application.facades.wechat_facade",
    "wechat_message_source_size_payload": "app.application.facades.wechat_facade",
    "printer_service": "app.application.facades.print_facade",
    "synthesize_to_data_uri": "app.application.facades.tts_facade",
    "trigger_common_tts_warmup": "app.application.facades.tts_facade",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
