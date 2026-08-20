# mypy: disable-error-code="valid-type, attr-defined, no-any-return"
# ruff: noqa: E402, F401
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib
from typing import Literal


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.chat_trace")


from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _append_memory_references_to_final_output as _append_memory_references_to_final_output,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _append_memory_references_to_run as _append_memory_references_to_run,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _artifact_from_excel_analysis_payload as _artifact_from_excel_analysis_payload,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _artifact_from_file_analysis_payload as _artifact_from_file_analysis_payload,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _artifact_from_generated_document_payload as _artifact_from_generated_document_payload,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _artifact_from_ocr_payload as _artifact_from_ocr_payload,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _artifact_signature as _artifact_signature,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _artifact_type_from_document as _artifact_type_from_document,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _extract_memory_references as _extract_memory_references,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _iter_explicit_artifact_payloads as _iter_explicit_artifact_payloads,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _memory_reference_from_payload as _memory_reference_from_payload,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _mime_from_document_name as _mime_from_document_name,
)
from app.application.agent_orchestrator.chat_trace_part02_part01 import (
    _refresh_memory_metadata as _refresh_memory_metadata,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _append_artifacts_to_final_output as _append_artifacts_to_final_output,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _append_artifacts_to_run as _append_artifacts_to_run,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _append_legacy_tool_records_to_run as _append_legacy_tool_records_to_run,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _attach_run_id as _attach_run_id,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _create_legacy_tool_records_run as _create_legacy_tool_records_run,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _create_tool_call_agent_run as _create_tool_call_agent_run,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _extract_artifacts as _extract_artifacts,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _iter_inferred_artifacts as _iter_inferred_artifacts,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _normalized_record_payload as _normalized_record_payload,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    _refresh_artifact_metadata as _refresh_artifact_metadata,
)
from app.application.agent_orchestrator.chat_trace_part02_part02 import (
    start_legacy_chat_run as start_legacy_chat_run,
)
