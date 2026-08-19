from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any, Literal
from uuid import uuid4

from app.application.agent_orchestrator.artifact_ingestion import ingest_artifact_to_dataset
from app.application.agent_orchestrator.budget import refresh_ai_budget_metadata
from app.application.agent_orchestrator.run_models import (
    AgentArtifact,
    AgentRun,
    AgentStep,
    LLMCall,
    MemoryReference,
    RetrievalCall,
    RunStatus,
    ToolCall,
    artifact_from_dict,
    utc_now_iso,
)
from app.application.agent_orchestrator.run_repository import (
    AgentRunRepository,
    get_agent_run_repository,
)
from app.application.agent_orchestrator.task_context import apply_task_context
from app.utils.operational_errors import RECOVERABLE_ERRORS

logger = logging.getLogger(__name__)

_MAX_TRACE_STRING_CHARS = 4000
_MAX_TRACE_LIST_ITEMS = 20
_MAX_TRACE_DICT_ITEMS = 40
_LEGACY_EXECUTE_READ_DEFAULTS = {
    "business_db": ("read",),
    "customers": ("query",),
    "materials": ("query",),
    "products": ("query",),
    "shipment_records": ("query",),
}


from app.application.agent_orchestrator.chat_trace_part01 import (
    _append_llm_calls_to_final_output as _append_llm_calls_to_final_output,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _append_llm_calls_to_run as _append_llm_calls_to_run,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _append_retrieval_calls_to_final_output as _append_retrieval_calls_to_final_output,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _append_retrieval_calls_to_run as _append_retrieval_calls_to_run,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _candidate_tool_actions as _candidate_tool_actions,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _coerce_trace_float as _coerce_trace_float,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _coerce_trace_int as _coerce_trace_int,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _extract_legacy_tool_records as _extract_legacy_tool_records,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _extract_llm_calls as _extract_llm_calls,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _extract_low_risk_tool_call as _extract_low_risk_tool_call,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _extract_retrieval_calls as _extract_retrieval_calls,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _first_list_value as _first_list_value,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _has_user_memory_marker as _has_user_memory_marker,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _iter_llm_trace_payloads as _iter_llm_trace_payloads,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _iter_memory_payloads as _iter_memory_payloads,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _iter_payload_dicts as _iter_payload_dicts,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _iter_retrieval_payloads as _iter_retrieval_payloads,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _iter_tool_call_payloads as _iter_tool_call_payloads,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _llm_call_from_trace as _llm_call_from_trace,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _llm_call_signature as _llm_call_signature,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _memory_reference_signature as _memory_reference_signature,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _payload_data as _payload_data,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _payload_error_message as _payload_error_message,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _payload_status as _payload_status,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _record_llm_usage_entry as _record_llm_usage_entry,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _refresh_ai_cost_metadata as _refresh_ai_cost_metadata,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _refresh_llm_metadata as _refresh_llm_metadata,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _refresh_retrieval_metadata as _refresh_retrieval_metadata,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _resolved_user_id as _resolved_user_id,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _retrieval_call_from_payload as _retrieval_call_from_payload,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _retrieval_signature as _retrieval_signature,
)
from app.application.agent_orchestrator.chat_trace_part01 import (
    _trace_safe_value as _trace_safe_value,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _append_artifacts_to_final_output as _append_artifacts_to_final_output,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _append_artifacts_to_run as _append_artifacts_to_run,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _append_legacy_tool_records_to_run as _append_legacy_tool_records_to_run,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _append_memory_references_to_final_output as _append_memory_references_to_final_output,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _append_memory_references_to_run as _append_memory_references_to_run,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _artifact_from_excel_analysis_payload as _artifact_from_excel_analysis_payload,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _artifact_from_file_analysis_payload as _artifact_from_file_analysis_payload,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _artifact_from_generated_document_payload as _artifact_from_generated_document_payload,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _artifact_from_ocr_payload as _artifact_from_ocr_payload,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _artifact_signature as _artifact_signature,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _artifact_type_from_document as _artifact_type_from_document,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _attach_run_id as _attach_run_id,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _create_legacy_tool_records_run as _create_legacy_tool_records_run,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _create_tool_call_agent_run as _create_tool_call_agent_run,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _extract_artifacts as _extract_artifacts,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _extract_memory_references as _extract_memory_references,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _iter_explicit_artifact_payloads as _iter_explicit_artifact_payloads,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _iter_inferred_artifacts as _iter_inferred_artifacts,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _memory_reference_from_payload as _memory_reference_from_payload,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _mime_from_document_name as _mime_from_document_name,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _normalized_record_payload as _normalized_record_payload,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _refresh_artifact_metadata as _refresh_artifact_metadata,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    _refresh_memory_metadata as _refresh_memory_metadata,
)
from app.application.agent_orchestrator.chat_trace_part02 import (
    start_legacy_chat_run as start_legacy_chat_run,
)
from app.application.agent_orchestrator.chat_trace_part03 import (
    attach_chat_trace_run as attach_chat_trace_run,
)
from app.application.agent_orchestrator.chat_trace_part03 import (
    create_chat_trace_run as create_chat_trace_run,
)
from app.application.agent_orchestrator.chat_trace_part03 import (
    finalize_legacy_chat_run as finalize_legacy_chat_run,
)
# ruff: noqa: F401
