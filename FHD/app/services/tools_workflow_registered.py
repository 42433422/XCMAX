"""已注册工作流工具：按 tool_id 路由到实现（自 tools_execution_service 拆分）。"""

from __future__ import annotations

import logging

from app.services.tools_workflow_business_db import (
    _registered_router_business_db,
)
from app.services.tools_workflow_common import (
    _BUSINESS_DB_CONTROL_FIELDS,
    _BUSINESS_DB_ENTITY_ALIASES,
    _DEFAULT_PREPARE_BUSINESS_DB_WRITE_TARGET,
    _RECENT_BUSINESS_DB_TARGETS,
    _business_db_payload_contains_key,
    _business_db_selector,
    _business_db_target_candidates,
    _business_db_update_fields,
    _normalize_business_db_entity,
    _remember_business_db_target,
    _result_record_id,
    get_recent_business_db_target,
    prepare_business_db_write_target,
)
from app.services.tools_workflow_dispatch import (
    _REGISTERED_WORKFLOW_ROUTERS,
    _WorkflowRouterMap,
    execute_registered_workflow_tool,
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
    _execute_excel_import_records,
    _ocr_artifact_payload,
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

logger = logging.getLogger(__name__)

# ruff: noqa: F401
