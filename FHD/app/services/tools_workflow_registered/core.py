"""Workflow router map and execute dispatcher."""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.services.tools_workflow_registered._facade import facade_attr
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class _WorkflowRouterMap(dict):
    _hidden_keys = {"employee", "business_db"}

    def keys(self):
        return [key for key in super().keys() if key not in self._hidden_keys]


_REGISTERED_WORKFLOW_ROUTERS: dict[str, str] = _WorkflowRouterMap(
    {
        "normal_slot_dispatch": "_registered_router_normal_slot_dispatch",
        "customers": "_registered_router_customers",
        "products": "_registered_router_products",
        "materials": "_registered_router_materials",
        "inventory": "_registered_router_inventory",
        "purchase": "_registered_router_purchase",
        "finance": "_registered_router_finance",
        "shipment_records": "_registered_router_shipment_records",
        "shipment_orders": "_registered_router_shipment_orders",
        "business_event": "_registered_router_business_event",
        "system_maintenance": "_registered_router_system_maintenance",
        "business_docking": "_registered_router_business_docking_family",
        "template_extract": "_registered_router_business_docking_family",
        "excel_analyzer": "_registered_router_excel_analyzer",
        "excel_toolkit": "_registered_router_excel_toolkit",
        "label_template_generator": "_registered_router_label_template_generator",
        "document_template": "_registered_router_document_template",
        "template_preview": "_registered_router_template_preview",
        "wechat": "_registered_router_wechat",
        "print": "_registered_router_print",
        "printer_list": "_registered_router_printer_list",
        "settings": "_registered_router_settings",
        "employee": "_registered_router_employee",
        "business_db": "_registered_router_business_db",
        "dataset_rag": "_registered_router_dataset_rag",
        "memory_v2": "_registered_router_memory_v2",
        "excel_analysis": "_registered_router_excel_analysis",
        "generate_office_document": "_registered_router_generate_office_document",
        "excel_vector_index": "_registered_router_excel_vector_index",
        "ocr": "_registered_router_ocr",
        "excel_import": "_registered_router_excel_import",
        "unit_products_import": "_registered_router_unit_products_import",
    }
)


def _resolve_router(attr_name: str) -> Callable[..., dict]:
    router = facade_attr(attr_name)
    if router is not None:
        return router
    import app.services.tools_workflow_registered as facade

    return getattr(facade, attr_name)


def execute_registered_workflow_tool(tool_id: str, action: str, params: dict | None = None) -> dict:
    """统一 dispatcher（供 WorkflowEngine 与 /api/tools/execute 复用）。"""
    from app.application.normal_chat_dispatch import resolve_tool_execution_profile

    params = dict(params or {})
    runtime_context = dict(params.pop("_runtime_context", None) or {})
    profile = resolve_tool_execution_profile(runtime_context)
    user_message = str(runtime_context.get("message") or "").strip()

    router_name = _REGISTERED_WORKFLOW_ROUTERS.get(tool_id)
    if router_name is not None:
        router = _resolve_router(router_name)
        return router(action, params, runtime_context, profile, user_message)
    try:
        from app.mod_sdk.employee_tool_registry import execute_employee_tool, is_employee_tool

        if is_employee_tool(tool_id):
            workspace_root = runtime_context.get("workspace_root")
            raw = execute_employee_tool(
                tool_id,
                {**params, "task": params.get("task") or user_message},
                str(workspace_root) if workspace_root else None,
            )
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"success": False, "message": raw}
    except RECOVERABLE_ERRORS:
        logger.debug("employee tool direct dispatch skipped tool=%s", tool_id, exc_info=True)
    return {"success": False, "message": f"未注册的工具动作: {tool_id}.{action}"}
