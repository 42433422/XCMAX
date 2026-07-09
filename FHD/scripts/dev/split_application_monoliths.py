#!/usr/bin/env python3
"""Split workflow/planner.py and dataset_rag_app_service.py (behavior-preserving)."""

from __future__ import annotations

from pathlib import Path

FHD = Path(__file__).resolve().parents[2]
APP = FHD / "app" / "application"


def _read(rel: str) -> str:
    return (APP / rel).read_text(encoding="utf-8")


def _write(rel: str, content: str) -> None:
    path = APP / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _lines(src: str, start: int, end: int) -> str:
    return "".join(src.splitlines(keepends=True)[start - 1 : end])


def split_planner() -> None:
    src = _read("workflow/planner.py")
    header = _lines(src, 1, 18)

    slots_body = _lines(src, 23, 221)
    slots = f'''{header}
from .types import WorkflowNode

{slots_body}'''

    executors_body = _lines(src, 224, 1201)
    executors = f'''{header}
from collections.abc import Callable
from typing import Any, cast

from app.utils.path_utils import ensure_fhd_repo_on_syspath

{executors_body}'''

    llm_body = _lines(src, 20, 21) + _lines(src, 1204, len(src.splitlines()))
    llm = f'''{header}
import uuid

from app.services import get_ai_conversation_service
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .planner_slots import (
    _extract_business_db_read_keyword,
    _extract_business_db_write_node,
    _infer_business_db_entity,
    _looks_like_business_db_write,
)
from .types import PlanGraph, WorkflowNode, validate_plan_graph

{llm_body}'''

    shim = '''"""Workflow planner — re-export shim (split into planner_*.py)."""

from __future__ import annotations

from .planner_llm import (
    LLMWorkflowPlanner,
    _filter_tool_registry_for_profile,
    _get_planner_http_client,
    _planner_http_client,
)
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
    "execute_tool",
    "get_tool_registry",
]
'''

    _write("workflow/planner_slots.py", slots)
    _write("workflow/planner_tool_executors.py", executors)
    _write("workflow/planner_llm.py", llm)
    _write("workflow/planner.py", shim)


def split_dataset_rag() -> None:
    src = _read("dataset_rag_app_service.py")
    imports = _lines(src, 1, 30)

    types_body = _lines(src, 33, 130)
    types = f'''{imports}


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


{types_body}'''

    helpers_body = _lines(src, 1467, 1954)
    helpers = f'''{imports}

from .types import (
    DATASET_ADMIN_PERMISSION,
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    DatasetAccessContext,
    DatasetDocument,
    DatasetRebuildJob,
    _utc_now_iso,
)

{helpers_body}'''

    service_body = _lines(src, 132, 1465)
    service = f'''{imports}

from .helpers import (
    _build_dataset_vector_index_backend,
    _chunk_to_dict,
    _citation_to_dict,
    _clean_key,
    _coerce_access_context,
    _default_storage_path,
    _deterministic_answer,
    _dict_to_retrieved_chunk,
    _document_from_dict,
    _embedding_metadata,
    _empty_rebuild_queue_summary,
    _ensure_dataset_permission,
    _ensure_tenant_allowed,
    _filter_chunks,
    _has_dataset_permission,
    _metadata_matches,
    _rebuild_job_from_dict,
    _rerank_chunks,
    _resolve_max_concurrent_rebuild_jobs,
    _resolve_tenant_for_access,
    _stable_document_id,
    _utc_now_iso,
)
from .types import (
    DATASET_ADMIN_PERMISSION,
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    REBUILD_TERMINAL_STATUSES,
    DatasetAccessContext,
    DatasetDocument,
    DatasetRebuildJob,
    _DatasetState,
)

{service_body}'''

    singleton = f'''{imports}

from .service import DatasetRagApplicationService

_dataset_rag_app_service: DatasetRagApplicationService | None = None
_dataset_rag_lock = threading.Lock()


def get_dataset_rag_app_service() -> DatasetRagApplicationService:
    global _dataset_rag_app_service
    if _dataset_rag_app_service is None:
        with _dataset_rag_lock:
            if _dataset_rag_app_service is None:
                _dataset_rag_app_service = DatasetRagApplicationService()
    return _dataset_rag_app_service


def reset_dataset_rag_app_service_for_tests() -> None:
    global _dataset_rag_app_service
    with _dataset_rag_lock:
        _dataset_rag_app_service = None
'''

    init_pkg = '''"""Dataset RAG application layer package."""

from __future__ import annotations
'''

    shim = '''"""Dataset RAG application service — re-export shim (split into dataset_rag/)."""

from __future__ import annotations

from .dataset_rag.helpers import (
    _build_dataset_vector_index_backend,
    _chunk_to_dict,
    _citation_to_dict,
    _clean_key,
    _coerce_access_context,
    _dataset_permission_denied,
    _default_storage_path,
    _deterministic_answer,
    _dict_to_retrieved_chunk,
    _document_from_dict,
    _embedding_metadata,
    _empty_rebuild_queue_summary,
    _ensure_dataset_permission,
    _ensure_tenant_allowed,
    _filter_chunks,
    _has_dataset_permission,
    _metadata_matches,
    _rebuild_job_from_dict,
    _rerank_chunks,
    _resolve_max_concurrent_rebuild_jobs,
    _resolve_tenant_for_access,
    _stable_document_id,
    _tokenize_for_rerank,
    _utc_now_iso,
)
from .dataset_rag.service import DatasetRagApplicationService as DatasetRagApplicationService
from .dataset_rag.singleton import (
    _dataset_rag_app_service,
    _dataset_rag_lock,
    get_dataset_rag_app_service,
    reset_dataset_rag_app_service_for_tests,
)
from .dataset_rag.types import (
    DATASET_ADMIN_PERMISSION,
    DATASET_READ_PERMISSION,
    DATASET_WRITE_PERMISSION,
    REBUILD_TERMINAL_STATUSES,
    DatasetAccessContext,
    DatasetDocument,
    DatasetRebuildJob,
    _DatasetState,
)

__all__ = [
    "DATASET_ADMIN_PERMISSION",
    "DATASET_READ_PERMISSION",
    "DATASET_WRITE_PERMISSION",
    "DatasetAccessContext",
    "DatasetDocument",
    "DatasetRagApplicationService",
    "DatasetRebuildJob",
    "REBUILD_TERMINAL_STATUSES",
    "_DatasetState",
    "_build_dataset_vector_index_backend",
    "_chunk_to_dict",
    "_citation_to_dict",
    "_clean_key",
    "_coerce_access_context",
    "_dataset_permission_denied",
    "_dataset_rag_app_service",
    "_dataset_rag_lock",
    "_default_storage_path",
    "_deterministic_answer",
    "_dict_to_retrieved_chunk",
    "_document_from_dict",
    "_embedding_metadata",
    "_empty_rebuild_queue_summary",
    "_ensure_dataset_permission",
    "_ensure_tenant_allowed",
    "_filter_chunks",
    "_has_dataset_permission",
    "_metadata_matches",
    "_rebuild_job_from_dict",
    "_rerank_chunks",
    "_resolve_max_concurrent_rebuild_jobs",
    "_resolve_tenant_for_access",
    "_stable_document_id",
    "_tokenize_for_rerank",
    "_utc_now_iso",
    "get_dataset_rag_app_service",
    "reset_dataset_rag_app_service_for_tests",
]
'''

    _write("dataset_rag/__init__.py", init_pkg)
    _write("dataset_rag/types.py", types)
    _write("dataset_rag/helpers.py", helpers)
    _write("dataset_rag/service.py", service)
    _write("dataset_rag/singleton.py", singleton)
    _write("dataset_rag_app_service.py", shim)


def main() -> None:
    split_planner()
    split_dataset_rag()
    print("split_application_monoliths: done")


if __name__ == "__main__":
    main()
