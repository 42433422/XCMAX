# mypy: disable-error-code="no-any-return"
"""工作流工具统一分发：路由注册表与 execute_registered_workflow_tool。"""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.services.tools_workflow_business_db import (
    _registered_router_business_db,
)
from app.services.tools_workflow_common import (
    _normalize_business_db_entity,
    _remember_business_db_target,
)
from app.services.tools_workflow_erp import (
    _registered_router_customers,
    _registered_router_finance,
    _registered_router_inventory,
    _registered_router_normal_slot_dispatch,
    _registered_router_purchase,
    _registered_router_reports,
    _registered_router_sales,
)
from app.services.tools_workflow_erp_master import (
    _registered_router_materials,
    _registered_router_products,
)
from app.services.tools_workflow_excel_ocr import (
    _registered_router_excel_analysis,
    _registered_router_excel_vector_index,
    _registered_router_generate_office_document,
)
from app.services.tools_workflow_excel_ocr_ops import (
    _registered_router_excel_import,
    _registered_router_ocr,
    _registered_router_unit_products_import,
)
from app.services.tools_workflow_memory_rag import (
    _registered_router_dataset_rag,
    _registered_router_memory_v2,
)
from app.services.tools_workflow_shipments_docs import (
    _registered_router_business_docking_family,
    _registered_router_business_event,
    _registered_router_mrp,
    _registered_router_shipment_orders,
    _registered_router_shipment_records,
    _registered_router_suppliers,
    _registered_router_system_maintenance,
)
from app.services.tools_workflow_shipments_docs_ops import (
    _registered_router_document_template,
    _registered_router_excel_analyzer,
    _registered_router_excel_toolkit,
    _registered_router_label_template_generator,
)
from app.services.tools_workflow_workspace import (
    _registered_router_employee,
    _registered_router_print,
    _registered_router_printer_list,
    _registered_router_settings,
    _registered_router_template_preview,
)
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


class _WorkflowRouterMap(dict):
    _hidden_keys = {"employee", "business_db"}

    def keys(self):
        return [key for key in super().keys() if key not in self._hidden_keys]


_REGISTERED_WORKFLOW_ROUTERS: dict[str, Callable[..., dict]] = _WorkflowRouterMap(
    {
        "normal_slot_dispatch": _registered_router_normal_slot_dispatch,
        "customers": _registered_router_customers,
        "products": _registered_router_products,
        "materials": _registered_router_materials,
        "inventory": _registered_router_inventory,
        "purchase": _registered_router_purchase,
        "sales": _registered_router_sales,
        "reports": _registered_router_reports,
        "finance": _registered_router_finance,
        "mrp": _registered_router_mrp,
        "suppliers": _registered_router_suppliers,
        "shipment_records": _registered_router_shipment_records,
        "shipment_orders": _registered_router_shipment_orders,
        "business_event": _registered_router_business_event,
        "system_maintenance": _registered_router_system_maintenance,
        "business_docking": _registered_router_business_docking_family,
        "template_extract": _registered_router_business_docking_family,
        "excel_analyzer": _registered_router_excel_analyzer,
        "excel_toolkit": _registered_router_excel_toolkit,
        "label_template_generator": _registered_router_label_template_generator,
        "document_template": _registered_router_document_template,
        "template_preview": _registered_router_template_preview,
        "print": _registered_router_print,
        "printer_list": _registered_router_printer_list,
        "settings": _registered_router_settings,
        "employee": _registered_router_employee,
        "business_db": _registered_router_business_db,
        "dataset_rag": _registered_router_dataset_rag,
        "memory_v2": _registered_router_memory_v2,
        "excel_analysis": _registered_router_excel_analysis,
        "generate_office_document": _registered_router_generate_office_document,
        "excel_vector_index": _registered_router_excel_vector_index,
        "ocr": _registered_router_ocr,
        "excel_import": _registered_router_excel_import,
        "unit_products_import": _registered_router_unit_products_import,
    }
)


def execute_registered_workflow_tool(tool_id: str, action: str, params: dict | None = None) -> dict:
    """统一 dispatcher（供 WorkflowEngine 与 /api/tools/execute 复用）。"""
    from app.application.normal_chat_dispatch import resolve_tool_execution_profile

    params = dict(params or {})
    runtime_context = dict(params.pop("_runtime_context", None) or {})
    profile = resolve_tool_execution_profile(runtime_context)
    user_message = str(runtime_context.get("message") or "").strip()
    router = _REGISTERED_WORKFLOW_ROUTERS.get(tool_id)
    if router is not None:
        result = router(action, params, runtime_context, profile, user_message)
        if tool_id == "business_db" and action == "write" and isinstance(result, dict):
            payload = params.get("payload")
            if isinstance(payload, dict):
                result = _remember_business_db_target(
                    runtime_context,
                    _normalize_business_db_entity(params.get("entity"), user_message),
                    str(params.get("operation") or params.get("op") or "create").strip().lower(),
                    payload,
                    result,
                )
        return result
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
