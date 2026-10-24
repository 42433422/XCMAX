"""Stable chat-trace API; compose typed recording and lifecycle services here."""

from __future__ import annotations

import logging
from typing import Any

from app.application.workflow.types import PlanGraph, WorkflowRunResult
from app.utils.operational_errors import RECOVERABLE_ERRORS

from .artifact_ingestion import ingest_artifact_to_dataset
from .budget import refresh_ai_budget_metadata
from .run_models import AgentArtifact, AgentRun, LLMCall
from .run_repository import AgentRunRepository, get_agent_run_repository
from .tool_spec import ToolActionSpecV2
from .trace_approval import resolve_legacy_approval as _resolve_approval
from .trace_artifacts import (
    _append_artifacts_to_final_output as _append_artifacts_to_final_output,
)
from .trace_artifacts import (
    _artifact_from_excel_analysis_payload as _artifact_from_excel_analysis_payload,
)
from .trace_artifacts import (
    _artifact_from_file_analysis_payload as _artifact_from_file_analysis_payload,
)
from .trace_artifacts import (
    _artifact_from_generated_document_payload as _artifact_from_generated_document_payload,
)
from .trace_artifacts import (
    _artifact_from_ocr_payload as _artifact_from_ocr_payload,
)
from .trace_artifacts import (
    _artifact_signature as _artifact_signature,
)
from .trace_artifacts import (
    _artifact_type_from_document as _artifact_type_from_document,
)
from .trace_artifacts import (
    _extract_artifacts as _extract_artifacts,
)
from .trace_artifacts import (
    _iter_explicit_artifact_payloads as _iter_explicit_artifact_payloads,
)
from .trace_artifacts import (
    _iter_inferred_artifacts as _iter_inferred_artifacts,
)
from .trace_artifacts import (
    _mime_from_document_name as _mime_from_document_name,
)
from .trace_artifacts import (
    _refresh_artifact_metadata as _refresh_artifact_metadata,
)
from .trace_memory import (
    _append_memory_references_to_final_output as _append_memory_references_to_final_output,
)
from .trace_memory import (
    _append_memory_references_to_run as _append_memory_references_to_run,
)
from .trace_memory import (
    _extract_memory_references as _extract_memory_references,
)
from .trace_memory import (
    _first_list_value as _first_list_value,
)
from .trace_memory import (
    _has_user_memory_marker as _has_user_memory_marker,
)
from .trace_memory import (
    _iter_memory_payloads as _iter_memory_payloads,
)
from .trace_memory import (
    _memory_reference_from_payload as _memory_reference_from_payload,
)
from .trace_memory import (
    _memory_reference_signature as _memory_reference_signature,
)
from .trace_memory import (
    _refresh_memory_metadata as _refresh_memory_metadata,
)
from .trace_model_usage import ModelUsageRecorder
from .trace_model_usage import (
    _extract_llm_calls as _extract_llm_calls,
)
from .trace_model_usage import (
    _iter_llm_trace_payloads as _iter_llm_trace_payloads,
)
from .trace_model_usage import (
    _llm_call_from_trace as _llm_call_from_trace,
)
from .trace_model_usage import (
    _llm_call_signature as _llm_call_signature,
)
from .trace_model_usage import (
    _record_llm_usage_entry as _record_llm_usage_entry,
)
from .trace_payloads import (
    _MAX_TRACE_DICT_ITEMS as _MAX_TRACE_DICT_ITEMS,
)
from .trace_payloads import (
    _MAX_TRACE_LIST_ITEMS as _MAX_TRACE_LIST_ITEMS,
)
from .trace_payloads import (
    _MAX_TRACE_STRING_CHARS as _MAX_TRACE_STRING_CHARS,
)
from .trace_payloads import (
    _attach_run_id as _attach_run_id,
)
from .trace_payloads import (
    _coerce_trace_float as _coerce_trace_float,
)
from .trace_payloads import (
    _coerce_trace_int as _coerce_trace_int,
)
from .trace_payloads import (
    _extract_legacy_tool_records as _extract_legacy_tool_records,
)
from .trace_payloads import (
    _iter_payload_dicts as _iter_payload_dicts,
)
from .trace_payloads import (
    _payload_data as _payload_data,
)
from .trace_payloads import (
    _payload_error_message as _payload_error_message,
)
from .trace_payloads import (
    _payload_status as _payload_status,
)
from .trace_payloads import (
    _resolved_user_id as _resolved_user_id,
)
from .trace_payloads import (
    _trace_safe_value as _trace_safe_value,
)
from .trace_recording import TraceRecorder
from .trace_retrieval import (
    _append_retrieval_calls_to_final_output as _append_retrieval_calls_to_final_output,
)
from .trace_retrieval import (
    _append_retrieval_calls_to_run as _append_retrieval_calls_to_run,
)
from .trace_retrieval import (
    _extract_retrieval_calls as _extract_retrieval_calls,
)
from .trace_retrieval import (
    _iter_retrieval_payloads as _iter_retrieval_payloads,
)
from .trace_retrieval import (
    _refresh_retrieval_metadata as _refresh_retrieval_metadata,
)
from .trace_retrieval import (
    _retrieval_call_from_payload as _retrieval_call_from_payload,
)
from .trace_retrieval import (
    _retrieval_signature as _retrieval_signature,
)
from .trace_runs import TraceRunService
from .trace_tools import (
    _candidate_tool_actions as _candidate_tool_actions,
)
from .trace_tools import (
    _extract_low_risk_tool_call as _extract_low_risk_tool_call,
)
from .trace_tools import (
    _iter_tool_call_payloads as _iter_tool_call_payloads,
)
from .trace_tools import (
    _normalized_record_payload as _normalized_record_payload,
)

logger = logging.getLogger(__name__)


def _model_usage() -> ModelUsageRecorder:
    return ModelUsageRecorder(_record_llm_usage_entry, refresh_ai_budget_metadata)


def _tool_spec(tool_id: str, action: str) -> ToolActionSpecV2 | None:
    from .tool_spec import get_tool_action_spec

    return get_tool_action_spec(tool_id, action)


def _recording() -> TraceRecorder:
    return TraceRecorder(_model_usage(), ingest_artifact_to_dataset, _tool_spec)


def _execute_observed_plan(
    *,
    repository: AgentRunRepository,
    user_id: str,
    message: str,
    plan: PlanGraph,
    runtime_context: dict[str, Any],
    auto_execute: bool,
) -> AgentRun:
    from app.application.agent_orchestrator import AgentOrchestrator

    return AgentOrchestrator(repository=repository).start_run_from_plan(
        user_id=user_id,
        message=message,
        plan=plan,
        runtime_context=runtime_context,
        auto_execute=auto_execute,
    )


def _run_service(repository: AgentRunRepository | None = None) -> TraceRunService:
    return TraceRunService(
        repository if repository is not None else get_agent_run_repository(),
        _recording(),
        _execute_observed_plan,
    )


def _refresh_ai_cost_metadata(run: AgentRun) -> None:
    _model_usage().refresh_cost(run)


def _refresh_llm_metadata(run: AgentRun) -> None:
    _model_usage().refresh(run)


def _append_llm_calls_to_run(run: AgentRun, calls: list[LLMCall]) -> None:
    _model_usage().append(run, calls)


def _append_llm_calls_to_final_output(run: AgentRun) -> None:
    _model_usage().finalize(run)


def _append_artifacts_to_run(run: AgentRun, artifacts: list[AgentArtifact]) -> None:
    _recording().append_artifacts(run, artifacts)


def _append_legacy_tool_records_to_run(
    run: AgentRun, records: list[dict[str, Any]]
) -> tuple[dict[str, Any], int]:
    return _recording().observe_tools(run, records)


def start_legacy_chat_run(
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> AgentRun:
    return _run_service().start(
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
        intent=intent,
    )


def _create_legacy_tool_records_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    user_id: str | None,
    source: str | None,
    channel: str,
    repository: AgentRunRepository,
    intent: str = "legacy_tool_chain",
) -> AgentRun | None:
    return _run_service(repository).create_observed_tools(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
        intent=intent,
    )


def _create_tool_call_agent_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None,
    user_id: str | None,
    source: str | None,
    channel: str,
    repository: AgentRunRepository,
) -> AgentRun | None:
    return _run_service(repository).create_tool_plan(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
    )


def create_chat_trace_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> AgentRun:
    return _run_service().create(
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
        intent=intent,
    )


def finalize_legacy_chat_run(
    run_id: str,
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    service = _run_service()
    run = service.repository.get(run_id)
    if run is None:
        return attach_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
            intent=intent,
        )
    return service.finalize(
        run,
        payload,
        message=message,
        runtime_context=runtime_context,
        user_id=user_id,
        source=source,
        channel=channel,
        intent=intent,
    )


def resolve_legacy_approval(
    request_id: str,
    context: dict[str, Any],
    result: WorkflowRunResult | None = None,
    *,
    run_before_restore: AgentRun | None = None,
) -> str:
    return _resolve_approval(
        request_id,
        context,
        result,
        repository=get_agent_run_repository(),
        recording=_recording(),
        run_before_restore=run_before_restore,
    )


def attach_chat_trace_run(
    payload: dict[str, Any],
    *,
    message: str,
    runtime_context: dict[str, Any] | None = None,
    user_id: str | None = None,
    source: str | None = None,
    channel: str = "compat_chat",
    intent: str = "legacy_chat_adapter",
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    data = payload.get("data")
    if isinstance(data, dict) and (data.get("run_id") or data.get("agent_run_id")):
        return payload
    if payload.get("run_id") or payload.get("agent_run_id"):
        return payload
    try:
        run = create_chat_trace_run(
            payload,
            message=message,
            runtime_context=runtime_context,
            user_id=user_id,
            source=source,
            channel=channel,
            intent=intent,
        )
    except RECOVERABLE_ERRORS:
        logger.exception("failed to attach AgentRun trace to chat response")
        return payload
    return _attach_run_id(payload, run.run_id)
