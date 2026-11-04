"""Domain facade exports, loaded only for the requested capability.

Tool dispatch must not initialize unrelated reporting, desktop, printing, or
spreadsheet facades. Existing names and dotted dependency overrides remain valid."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.application.facades.ai_conversation_facade import (
        AIConversationService as AIConversationService,
    )
    from app.application.facades.conversation_facade import (
        get_conversation_service as get_conversation_service,
        get_data_analysis_service as get_data_analysis_service,
        get_user_preference_service as get_user_preference_service,
    )
    from app.application.facades.excel_facade import (
        get_ai_product_parser as get_ai_product_parser,
        get_product_import_service as get_product_import_service,
    )
    from app.application.facades.intent_facade import BertIntentClassifier as BertIntentClassifier
    from app.application.facades.inventory_facade import (
        InventoryService as InventoryService,
        PurchaseService as PurchaseService,
        ReportService as ReportService,
    )
    from app.application.facades.kitten_facade import (
        FinancialReportPlugin as FinancialReportPlugin,
        InventoryValuationPlugin as InventoryValuationPlugin,
        KittenReportExportService as KittenReportExportService,
        analysis_save_service as analysis_save_service,
        build_kitten_business_snapshot as build_kitten_business_snapshot,
        build_kitten_docx as build_kitten_docx,
        chart_service as chart_service,
        generate_office_file as generate_office_file,
        pop_document_pickup as pop_document_pickup,
    )
    from app.application.facades.mobile_relay_facade import (
        MobileRelayService as MobileRelayService,
        register_desktop_relay as register_desktop_relay,
    )
    from app.application.facades.ocr_facade import get_ocr_service as get_ocr_service
    from app.application.facades.print_facade import printer_service as printer_service
    from app.application.facades.query_facade import (
        find_product as find_product,
        find_purchase_unit as find_purchase_unit,
        get_product_names as get_product_names,
        get_purchase_units as get_purchase_units,
        query_service as query_service,
    )
    from app.application.facades.session_facade import (
        get_auth_service as get_auth_service,
        get_database_service as get_database_service,
        get_session_service as get_session_service,
        get_system_service as get_system_service,
    )
    from app.application.facades.shipment_event_primary import (
        ShipmentApplicationServiceEventPrimary as ShipmentApplicationServiceEventPrimary,
    )
    from app.application.facades.template_facade import (
        _extract_structured_excel_preview as _extract_structured_excel_preview,
        document_templates_service as document_templates_service,
    )
    from app.application.facades.tools_facade import (
        _parse_order_text as _parse_order_text,
        execute_registered_workflow_tool as execute_registered_workflow_tool,
        execute_tool_from_payload as execute_tool_from_payload,
        get_workflow_tool_registry as get_workflow_tool_registry,
        run_archive_tools_execute as run_archive_tools_execute,
        set_tool_execute_headers as set_tool_execute_headers,
    )
    from app.application.facades.tts_facade import (
        synthesize_to_data_uri as synthesize_to_data_uri,
        trigger_common_tts_warmup as trigger_common_tts_warmup,
    )
    from app.application.facades.user_cs_employee_facade import (
        EMPLOYEE_MOD_ID as EMPLOYEE_MOD_ID,
        run_user_cs_employee as run_user_cs_employee,
    )
_SERVICE_EXPORTS: dict[str, str] = {
    "AIConversationService": "ai_conversation_facade",
    "get_conversation_service": "conversation_facade",
    "get_data_analysis_service": "conversation_facade",
    "get_user_preference_service": "conversation_facade",
    "get_ai_product_parser": "excel_facade",
    "get_product_import_service": "excel_facade",
    "BertIntentClassifier": "intent_facade",
    "InventoryService": "inventory_facade",
    "PurchaseService": "inventory_facade",
    "ReportService": "inventory_facade",
    "FinancialReportPlugin": "kitten_facade",
    "InventoryValuationPlugin": "kitten_facade",
    "KittenReportExportService": "kitten_facade",
    "analysis_save_service": "kitten_facade",
    "build_kitten_business_snapshot": "kitten_facade",
    "build_kitten_docx": "kitten_facade",
    "chart_service": "kitten_facade",
    "generate_office_file": "kitten_facade",
    "pop_document_pickup": "kitten_facade",
    "MobileRelayService": "mobile_relay_facade",
    "register_desktop_relay": "mobile_relay_facade",
    "get_ocr_service": "ocr_facade",
    "printer_service": "print_facade",
    "find_product": "query_facade",
    "find_purchase_unit": "query_facade",
    "get_product_names": "query_facade",
    "get_purchase_units": "query_facade",
    "query_service": "query_facade",
    "get_auth_service": "session_facade",
    "get_database_service": "session_facade",
    "get_session_service": "session_facade",
    "get_system_service": "session_facade",
    "ShipmentApplicationServiceEventPrimary": "shipment_event_primary",
    "_extract_structured_excel_preview": "template_facade",
    "document_templates_service": "template_facade",
    "_parse_order_text": "tools_facade",
    "execute_registered_workflow_tool": "tools_facade",
    "execute_tool_from_payload": "tools_facade",
    "get_workflow_tool_registry": "tools_facade",
    "run_archive_tools_execute": "tools_facade",
    "set_tool_execute_headers": "tools_facade",
    "synthesize_to_data_uri": "tts_facade",
    "trigger_common_tts_warmup": "tts_facade",
    "EMPLOYEE_MOD_ID": "user_cs_employee_facade",
    "run_user_cs_employee": "user_cs_employee_facade",
}
_MODULE_EXPORTS = frozenset(_SERVICE_EXPORTS.values())
__all__ = [
    "ShipmentApplicationServiceEventPrimary",
    "AIConversationService",
    "BertIntentClassifier",
    "EMPLOYEE_MOD_ID",
    "InventoryService",
    "MobileRelayService",
    "PurchaseService",
    "ReportService",
    "KittenReportExportService",
    "FinancialReportPlugin",
    "InventoryValuationPlugin",
    "document_templates_service",
    "_extract_structured_excel_preview",
    "_parse_order_text",
    "execute_registered_workflow_tool",
    "execute_tool_from_payload",
    "get_workflow_tool_registry",
    "run_archive_tools_execute",
    "set_tool_execute_headers",
    "build_kitten_business_snapshot",
    "build_kitten_docx",
    "chart_service",
    "analysis_save_service",
    "generate_office_file",
    "pop_document_pickup",
    "find_product",
    "find_purchase_unit",
    "get_product_names",
    "get_purchase_units",
    "query_service",
    "get_conversation_service",
    "get_data_analysis_service",
    "get_user_preference_service",
    "get_ai_product_parser",
    "get_product_import_service",
    "get_auth_service",
    "get_database_service",
    "get_session_service",
    "get_system_service",
    "get_ocr_service",
    "printer_service",
    "register_desktop_relay",
    "run_user_cs_employee",
    "synthesize_to_data_uri",
    "trigger_common_tts_warmup",
]


def __getattr__(name: str) -> Any:
    module = _SERVICE_EXPORTS.get(name)
    if module is not None:
        return getattr(import_module(f"{__name__}.{module}"), name)
    if name in _MODULE_EXPORTS:
        value = import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SERVICE_EXPORTS.keys() | _MODULE_EXPORTS)
