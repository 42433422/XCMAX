"""Workflow planner — re-export shim (split into planner_*.py)."""

from __future__ import annotations

import httpx

from app.services import get_ai_conversation_service as get_ai_conversation_service
from app.utils.path_utils import ensure_fhd_repo_on_syspath as ensure_fhd_repo_on_syspath

from .planner_llm import LLMWorkflowPlanner, _filter_tool_registry_for_profile
from .planner_slots import (
    _clean_db_slot_value,
    _extract_business_db_read_keyword,
    _extract_business_db_write_node,
    _extract_named_slot,
    _infer_business_db_entity,
    _looks_like_business_db_write,
)
from .planner_tool_executors import (
    _WORKFLOW_TOOL_HANDLERS,
    _execute_business_db_read_tool,
    _execute_business_db_write_tool,
    _execute_customers_ensure_exists_tool,
    _execute_customers_tool,
    _execute_employee_execute_tool,
    _execute_employee_list_tool,
    _execute_excel_analysis_tool,
    _execute_excel_decompose_tool,
    _execute_excel_schema_tool,
    _execute_import_excel_tool,
    _execute_materials_tool,
    _execute_price_list_tool,
    _execute_print_label_tool,
    _execute_products_tool,
    _execute_shipment_generate_tool,
    _execute_shipment_records_tool,
    _execute_template_extract_tool,
    _execute_wechat_preview_tool,
    execute_tool,
    get_tool_registry,
)
from .types import PlanGraph as PlanGraph
from .types import WorkflowNode as WorkflowNode

# 同步规划 LLM 复用 Client，减轻短时多次 DeepSeek 连接失败
_planner_http_client: httpx.Client | None = None


def _get_planner_http_client() -> httpx.Client:
    global _planner_http_client
    if _planner_http_client is None:
        _planner_http_client = httpx.Client(
            timeout=httpx.Timeout(20.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
            trust_env=False,
        )
    return _planner_http_client


__all__ = [
    "LLMWorkflowPlanner",
    "PlanGraph",
    "WorkflowNode",
    "_WORKFLOW_TOOL_HANDLERS",
    "_clean_db_slot_value",
    "_execute_business_db_read_tool",
    "_execute_business_db_write_tool",
    "_execute_customers_ensure_exists_tool",
    "_execute_customers_tool",
    "_execute_employee_execute_tool",
    "_execute_employee_list_tool",
    "_execute_excel_analysis_tool",
    "_execute_excel_decompose_tool",
    "_execute_excel_schema_tool",
    "_execute_import_excel_tool",
    "_execute_materials_tool",
    "_execute_price_list_tool",
    "_execute_print_label_tool",
    "_execute_products_tool",
    "_execute_shipment_generate_tool",
    "_execute_shipment_records_tool",
    "_execute_template_extract_tool",
    "_execute_wechat_preview_tool",
    "_extract_business_db_read_keyword",
    "_extract_business_db_write_node",
    "_extract_named_slot",
    "_filter_tool_registry_for_profile",
    "_get_planner_http_client",
    "_infer_business_db_entity",
    "_looks_like_business_db_write",
    "_planner_http_client",
    "ensure_fhd_repo_on_syspath",
    "execute_tool",
    "get_ai_conversation_service",
    "get_tool_registry",
]
