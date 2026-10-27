# mypy: disable-error-code="no-any-return"
"""工作流工具统一分发：路由注册表与 execute_registered_workflow_tool。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import nullcontext

from app.domain.shared_services.tools_workflow_business_db import (
    _registered_router_business_db,
)
from app.domain.shared_services.tools_workflow_common import (
    _normalize_business_db_entity,
    _remember_business_db_target,
)
from app.domain.shared_services.tools_workflow_erp import (
    _registered_router_customers,
    _registered_router_finance,
    _registered_router_inventory,
    _registered_router_normal_slot_dispatch,
    _registered_router_purchase,
    _registered_router_reports,
    _registered_router_sales,
)
from app.domain.shared_services.tools_workflow_erp_master import (
    _registered_router_materials,
    _registered_router_products,
)
from app.domain.shared_services.tools_workflow_excel_ocr import (
    _registered_router_excel_analysis,
    _registered_router_excel_vector_index,
    _registered_router_generate_office_document,
)
from app.domain.shared_services.tools_workflow_excel_ocr_ops import (
    _registered_router_excel_import,
    _registered_router_ocr,
    _registered_router_unit_products_import,
)
from app.domain.shared_services.tools_workflow_memory_rag import (
    _registered_router_dataset_rag,
    _registered_router_memory_v2,
)
from app.domain.shared_services.tools_workflow_shipments_docs import (
    _registered_router_business_docking_family,
    _registered_router_business_event,
    _registered_router_mrp,
    _registered_router_shipment_orders,
    _registered_router_shipment_records,
    _registered_router_suppliers,
    _registered_router_system_maintenance,
)
from app.domain.shared_services.tools_workflow_shipments_docs_ops import (
    _registered_router_document_template,
    _registered_router_excel_analyzer,
    _registered_router_excel_toolkit,
    _registered_router_label_template_generator,
)
from app.domain.shared_services.tools_workflow_workspace import (
    _registered_router_desktop_automation,
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
        "desktop_automation": _registered_router_desktop_automation,
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
    customer_scope = nullcontext()
    customer_tenant = None
    if tool_id == "customers" and action == "ensure_exists":
        from fastapi import HTTPException

        from app.infrastructure.auth.agent_mod_scope import (
            AgentModAuthorizationError,
            _bound_actor,
            agent_mod_execution_scope,
        )
        from app.infrastructure.auth.business_scope_gate import (
            check_owned_business_permission,
        )

        try:
            actor = _bound_actor(runtime_context)
            customer_tenant = check_owned_business_permission(actor, "customer.edit")
            if str(runtime_context.get("tenant_id")) != str(customer_tenant):
                raise AgentModAuthorizationError("企业范围与登录账号不一致")
            if set(params) - {"unit_name", "customer_name", "name"}:
                raise AgentModAuthorizationError("客户确认操作不接受身份或对象 ID 覆盖")
            for hint in ("service_source", "route_module"):
                runtime_context.pop(hint, None)
            customer_scope = agent_mod_execution_scope(runtime_context.get("_mod_authorization"))
        except (AgentModAuthorizationError, HTTPException):
            return {
                "success": False,
                "error_code": "customer_action_not_authorized",
                "message": "当前登录身份无权在此客户数据范围执行操作",
            }
    profile = resolve_tool_execution_profile(runtime_context)
    user_message = str(runtime_context.get("message") or "").strip()
    router = _REGISTERED_WORKFLOW_ROUTERS.get(tool_id)
    if router is not None:
        from app.infrastructure.tenant_scope import owned_tenant_scope

        with (
            customer_scope,
            owned_tenant_scope(customer_tenant) if customer_tenant is not None else nullcontext(),
        ):
            result = router(action, params, runtime_context, profile, user_message)
        if tool_id == "business_db" and action == "write" and isinstance(result, dict):
            payload = params.get("payload")
            if isinstance(payload, dict):
                result = _remember_business_db_target(
                    runtime_context,
                    _normalize_business_db_entity(params.get("entity"), user_message),
                    str(params.get("operation") or params.get("op") or "create").strip().lower(),
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
