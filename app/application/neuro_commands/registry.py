"""Central registry for NeuroBus command services (ex-V2 app services)."""

from __future__ import annotations

from typing import Any

NEURO_COMMAND_DOMAINS: tuple[str, ...] = (
    "ai_chat",
    "auth",
    "conversation",
    "customer",
    "excel_vector",
    "extract_log",
    "file_analysis",
    "inventory",
    "material",
    "ocr",
    "order",
    "print",
    "product",
    "product_import",
    "purchase",
    "shipment",
    "template",
    "unit_products_import",
    "user",
    "user_memory_vector",
    "user_preference",
    "wechat_contact",
    "wechat_task",
)

_LOADERS: dict[str, str] = {
    "ai_chat": "app.application.neuro_commands.ai_chat:get_ai_chat_app_service_v2",
    "auth": "app.application.neuro_commands.auth:get_auth_app_service_v2",
    "conversation": "app.application.neuro_commands.conversation:get_conversation_app_service_v2",
    "customer": "app.application.neuro_commands.customer:get_customer_app_service_v2",
    "excel_vector": "app.application.neuro_commands.excel_vector:get_excel_vector_app_service_v2",
    "extract_log": "app.application.neuro_commands.extract_log:get_extract_log_app_service_v2",
    "file_analysis": "app.application.neuro_commands.file_analysis:get_file_analysis_app_service_v2",
    "inventory": "app.application.neuro_commands.inventory:get_inventory_app_service_v2",
    "material": "app.application.neuro_commands.material:get_material_app_service_v2",
    "ocr": "app.application.neuro_commands.ocr:get_ocr_app_service_v2",
    "order": "app.application.neuro_commands.order:get_order_app_service_v2",
    "print": "app.application.neuro_commands.print:get_print_app_service_v2",
    "product": "app.application.neuro_commands.product:get_product_app_service_v2",
    "product_import": "app.application.neuro_commands.product_import:get_product_import_app_service_v2",
    "purchase": "app.application.neuro_commands.purchase:get_purchase_app_service_v2",
    "shipment": "app.application.neuro_commands.shipment:get_shipment_app_service_v2",
    "template": "app.application.neuro_commands.template:get_template_app_service_v2",
    "unit_products_import": "app.application.neuro_commands.unit_products_import:get_unit_products_import_app_service_v2",
    "user": "app.application.neuro_commands.user:get_user_app_service_v2",
    "user_memory_vector": "app.application.neuro_commands.user_memory_vector:get_user_memory_vector_app_service_v2",
    "user_preference": "app.application.neuro_commands.user_preference:get_user_preference_app_service_v2",
    "wechat_contact": "app.application.neuro_commands.wechat_contact:get_wechat_contact_app_service_v2",
    "wechat_task": "app.application.neuro_commands.wechat_task:get_wechat_task_app_service_v2",
}

_instances: dict[str, Any] = {}


def get_neuro_command_service(domain: str) -> Any:
    """Return lazily constructed neuro command service for *domain*."""
    key = str(domain or "").strip()
    if key not in _LOADERS:
        raise KeyError(f"Unknown neuro command domain: {domain!r}")
    if key not in _instances:
        mod_path, _, attr = _LOADERS[key].partition(":")
        import importlib

        mod = importlib.import_module(mod_path)
        factory = getattr(mod, attr)
        _instances[key] = factory()
    return _instances[key]


def reset_neuro_command_services() -> None:
    _instances.clear()
