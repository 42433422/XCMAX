"""已注册工作流工具：按 tool_id 路由到实现（自 tools_execution_service 拆分）。"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)


from app.services.tools_workflow_registered_part01 import (
    _registered_router_customers as _registered_router_customers,
)
from app.services.tools_workflow_registered_part01 import (
    _registered_router_finance as _registered_router_finance,
)
from app.services.tools_workflow_registered_part01 import (
    _registered_router_inventory as _registered_router_inventory,
)
from app.services.tools_workflow_registered_part01 import (
    _registered_router_materials as _registered_router_materials,
)
from app.services.tools_workflow_registered_part01 import (
    _registered_router_normal_slot_dispatch as _registered_router_normal_slot_dispatch,
)
from app.services.tools_workflow_registered_part01 import (
    _registered_router_products as _registered_router_products,
)
from app.services.tools_workflow_registered_part01 import (
    _registered_router_purchase as _registered_router_purchase,
)
from app.services.tools_workflow_registered_part01 import (
    _registered_router_reports as _registered_router_reports,
)
from app.services.tools_workflow_registered_part01 import (
    _registered_router_sales as _registered_router_sales,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_business_docking_family as _registered_router_business_docking_family,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_business_event as _registered_router_business_event,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_document_template as _registered_router_document_template,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_excel_analyzer as _registered_router_excel_analyzer,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_excel_toolkit as _registered_router_excel_toolkit,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_label_template_generator as _registered_router_label_template_generator,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_mrp as _registered_router_mrp,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_shipment_orders as _registered_router_shipment_orders,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_shipment_records as _registered_router_shipment_records,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_suppliers as _registered_router_suppliers,
)
from app.services.tools_workflow_registered_part02 import (
    _registered_router_system_maintenance as _registered_router_system_maintenance,
)
from app.services.tools_workflow_registered_part03 import (
    _business_db_payload_contains_key as _business_db_payload_contains_key,
)
from app.services.tools_workflow_registered_part03 import (
    _business_db_selector as _business_db_selector,
)
from app.services.tools_workflow_registered_part03 import (
    _business_db_target_candidates as _business_db_target_candidates,
)
from app.services.tools_workflow_registered_part03 import (
    _normalize_business_db_entity as _normalize_business_db_entity,
)
from app.services.tools_workflow_registered_part03 import (
    _registered_router_employee as _registered_router_employee,
)
from app.services.tools_workflow_registered_part03 import (
    _registered_router_print as _registered_router_print,
)
from app.services.tools_workflow_registered_part03 import (
    _registered_router_printer_list as _registered_router_printer_list,
)
from app.services.tools_workflow_registered_part03 import (
    _registered_router_settings as _registered_router_settings,
)
from app.services.tools_workflow_registered_part03 import (
    _registered_router_template_preview as _registered_router_template_preview,
)
from app.services.tools_workflow_registered_part03 import (
    _remember_business_db_target as _remember_business_db_target,
)
from app.services.tools_workflow_registered_part03 import (
    _result_record_id as _result_record_id,
)
from app.services.tools_workflow_registered_part03 import (
    get_recent_business_db_target as get_recent_business_db_target,
)
from app.services.tools_workflow_registered_part03 import (
    prepare_business_db_write_target as prepare_business_db_write_target,
)
from app.services.tools_workflow_registered_part04 import (
    _DEFAULT_PREPARE_BUSINESS_DB_WRITE_TARGET as _DEFAULT_PREPARE_BUSINESS_DB_WRITE_TARGET,
)
from app.services.tools_workflow_registered_part04 import (
    _business_db_update_fields as _business_db_update_fields,
)
from app.services.tools_workflow_registered_part04 import (
    _ocr_artifact_payload as _ocr_artifact_payload,
)
from app.services.tools_workflow_registered_part04 import (
    _registered_router_business_db as _registered_router_business_db,
)
from app.services.tools_workflow_registered_part04 import (
    _registered_router_dataset_rag as _registered_router_dataset_rag,
)
from app.services.tools_workflow_registered_part04 import (
    _registered_router_excel_analysis as _registered_router_excel_analysis,
)
from app.services.tools_workflow_registered_part04 import (
    _registered_router_excel_vector_index as _registered_router_excel_vector_index,
)
from app.services.tools_workflow_registered_part04 import (
    _registered_router_generate_office_document as _registered_router_generate_office_document,
)
from app.services.tools_workflow_registered_part04 import (
    _registered_router_memory_v2 as _registered_router_memory_v2,
)
from app.services.tools_workflow_registered_part05 import (
    _execute_excel_import_records as _execute_excel_import_records,
)
from app.services.tools_workflow_registered_part05 import (
    _registered_router_excel_import as _registered_router_excel_import,
)
from app.services.tools_workflow_registered_part05 import (
    _registered_router_ocr as _registered_router_ocr,
)
from app.services.tools_workflow_registered_part05 import (
    _registered_router_unit_products_import as _registered_router_unit_products_import,
)
from app.services.tools_workflow_registered_part05 import (
    _WorkflowRouterMap as _WorkflowRouterMap,
)
from app.services.tools_workflow_registered_part05 import (
    execute_registered_workflow_tool as execute_registered_workflow_tool,
)

# ruff: noqa: F401

_BUSINESS_DB_ENTITY_ALIASES = {
    "customer": "customers",
    "customers": "customers",
    "purchase_unit": "customers",
    "purchase_units": "customers",
    "客户": "customers",
    "单位": "customers",
    "购买单位": "customers",
    "product": "products",
    "products": "products",
    "产品": "products",
    "物料": "materials",
    "原材料": "materials",
    "material": "materials",
    "materials": "materials",
    "shipment": "shipment_records",
    "shipments": "shipment_records",
    "shipment_record": "shipment_records",
    "shipment_records": "shipment_records",
    "出货": "shipment_records",
    "发货": "shipment_records",
    "发货单": "shipment_records",
}

_BUSINESS_DB_CONTROL_FIELDS = frozenset(
    {"selector", "changes", "fields", "force", "confirm", "_selector_field", "_resolved_target"}
)

_RECENT_BUSINESS_DB_TARGETS: dict[str, dict[str, Any]] = {}


def _registered_router_erp_hr(
    action: str, params: dict, runtime_context: dict, profile: str, user_message: str
) -> dict:
    del profile, user_message
    from app.application.erp_hr_management_app_service import execute_erp_hr_management
    from app.infrastructure.tenant_scope import current_tenant_id, tenant_scope

    if current_tenant_id() is not None:
        return execute_erp_hr_management(action, params)
    trusted_tenant_id = runtime_context.get("tenant_id")
    if trusted_tenant_id in (None, ""):
        return {
            "success": False,
            "message": "缺少已认证租户上下文，拒绝 ERP 人员管理操作",
            "error_code": "erp_hr_tenant_context_missing",
        }
    with tenant_scope(int(trusted_tenant_id)):
        return execute_erp_hr_management(action, params)


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
        "erp_hr": _registered_router_erp_hr,
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
