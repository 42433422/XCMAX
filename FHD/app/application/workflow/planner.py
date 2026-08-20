# ruff: noqa: E402, F401
from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from typing import Any, cast

import httpx

from app.application.chat_tool_intent import (
    attach_explicit_tenant_id as _attach_explicit_tenant_id,
)
from app.application.chat_tool_intent import (
    looks_like_business_db_write as _looks_like_business_db_write,
)
from app.application.workflow.types import normalize_workflow_risk
from app.services import get_ai_conversation_service
from app.services.tools_workflow_registered import execute_registered_workflow_tool
from app.utils.operational_errors import RECOVERABLE_ERRORS
from app.utils.path_io.path_utils import ensure_fhd_repo_on_syspath

from .clarification_node import build_clarify_node, needs_clarification
from .planner_llm_gateway import request_planner_completion
from .types import Branch, PlanGraph, WorkflowNode, validate_plan_graph

logger = logging.getLogger(__name__)

# 同步规划 LLM 复用 Client，减轻短时多次 DeepSeek 连接失败
_planner_http_client: httpx.Client | None = None


def close_planner_http_client() -> None:
    """Close the reusable planner HTTP client during application shutdown."""
    global _planner_http_client
    client = _planner_http_client
    _planner_http_client = None
    if client is not None and not client.is_closed:
        client.close()


from app.application.workflow.planner_part01 import (
    _changes_for_business_db_message as _changes_for_business_db_message,
)
from app.application.workflow.planner_part01 import (
    _clean_db_slot_value as _clean_db_slot_value,
)
from app.application.workflow.planner_part01 import (
    _execute_customers_ensure_exists_tool as _execute_customers_ensure_exists_tool,
)
from app.application.workflow.planner_part01 import (
    _execute_customers_tool as _execute_customers_tool,
)
from app.application.workflow.planner_part01 import (
    _execute_price_list_tool as _execute_price_list_tool,
)
from app.application.workflow.planner_part01 import (
    _execute_products_tool as _execute_products_tool,
)
from app.application.workflow.planner_part01 import (
    _execute_shipment_generate_tool as _execute_shipment_generate_tool,
)
from app.application.workflow.planner_part01 import (
    _extract_business_db_id as _extract_business_db_id,
)
from app.application.workflow.planner_part01 import (
    _extract_business_db_read_keyword as _extract_business_db_read_keyword,
)
from app.application.workflow.planner_part01 import (
    _extract_business_db_write_node as _extract_business_db_write_node,
)
from app.application.workflow.planner_part01 import (
    _extract_marked_value as _extract_marked_value,
)
from app.application.workflow.planner_part01 import (
    _extract_named_slot as _extract_named_slot,
)
from app.application.workflow.planner_part01 import (
    _extract_number as _extract_number,
)
from app.application.workflow.planner_part01 import (
    _infer_business_db_entity as _infer_business_db_entity,
)
from app.application.workflow.planner_part01 import (
    _infer_business_db_operation as _infer_business_db_operation,
)
from app.application.workflow.planner_part01 import (
    _selector_for_business_db_message as _selector_for_business_db_message,
)
from app.application.workflow.planner_part01 import (
    execute_tool as execute_tool,
)
from app.application.workflow.planner_part01 import (
    get_tool_registry as get_tool_registry,
)
from app.application.workflow.planner_part02 import (
    _execute_business_db_read_tool as _execute_business_db_read_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_business_db_write_tool as _execute_business_db_write_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_employee_execute_tool as _execute_employee_execute_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_employee_list_tool as _execute_employee_list_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_excel_analysis_tool as _execute_excel_analysis_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_excel_decompose_tool as _execute_excel_decompose_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_excel_schema_tool as _execute_excel_schema_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_import_excel_tool as _execute_import_excel_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_materials_tool as _execute_materials_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_print_label_tool as _execute_print_label_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_shipment_records_tool as _execute_shipment_records_tool,
)
from app.application.workflow.planner_part02 import (
    _execute_template_extract_tool as _execute_template_extract_tool,
)

# 与 get_tool_registry / execute_tool 默认 action 对齐；(tool_id, action) -> 实现函数
_WORKFLOW_TOOL_HANDLERS: dict[tuple[str, str], Callable[[dict[str, Any]], dict[str, Any]]] = {
    ("price_list", "export"): _execute_price_list_tool,
    ("products", "query"): _execute_products_tool,
    ("customers", "query"): _execute_customers_tool,
    ("customers", "ensure_exists"): _execute_customers_ensure_exists_tool,
    ("shipment_generate", "generate"): _execute_shipment_generate_tool,
    ("shipment_records", "query"): _execute_shipment_records_tool,
    ("shipments", "query"): _execute_shipment_records_tool,
    ("materials", "query"): _execute_materials_tool,
    ("print_label", "generate"): _execute_print_label_tool,
    ("excel_decompose", "decompose"): _execute_excel_decompose_tool,
    ("template_extract", "extract"): _execute_template_extract_tool,
    ("excel_schema", "analyze"): _execute_excel_schema_tool,
    ("excel_analysis", "analyze"): _execute_excel_analysis_tool,
    ("import_excel", "import"): _execute_import_excel_tool,
    ("employee", "list"): _execute_employee_list_tool,
    ("employee", "execute"): _execute_employee_execute_tool,
    ("business_db", "read"): _execute_business_db_read_tool,
    ("business_db", "write"): _execute_business_db_write_tool,
}


from app.application.workflow.planner_llmworkflowplanner_mixin01 import (
    _LLMWorkflowPlannerPart01Mixin,
)
from app.application.workflow.planner_llmworkflowplanner_mixin02 import (
    _LLMWorkflowPlannerPart02Mixin,
)
from app.application.workflow.planner_part03 import (
    _filter_tool_registry_for_profile as _filter_tool_registry_for_profile,
)
from app.application.workflow.planner_part03 import (
    _get_planner_http_client as _get_planner_http_client,
)
from app.application.workflow.planner_part04 import (
    LLMWorkflowPlanner as LLMWorkflowPlanner,
)
