from __future__ import annotations

import json
from typing import Any

from app.application.agent_orchestrator.run_models import AgentArtifact, AgentRun
from app.utils.operational_errors import RECOVERABLE_ERRORS

_DOCUMENT_ARTIFACT_TYPES = {
    "pdf_document",
    "office_document",
    "document_file",
    "file_analysis",
}
_TEXT_ARTIFACT_TYPES = {
    "ocr_text",
    "excel_records",
    "excel_file",
    "file_analysis",
    "pdf_document",
    "office_document",
    "document_file",
}
_GENERIC_SUMMARIES = {"", "生成文档", "OCR 解析结果", "Excel 解析结果"}


def ingest_artifact_to_dataset(run: AgentRun, artifact: AgentArtifact) -> dict[str, Any] | None:
    """Best-effort bridge from AgentArtifact into Dataset/RAG document lifecycle."""
    if _should_skip_artifact(artifact):
        return None

    request = _build_ingest_request(run, artifact)
    if request is None:
        return None

    try:
        from app.application.dataset_rag_app_service import get_dataset_rag_app_service

        service = get_dataset_rag_app_service()
        service_request = _service_request(request)
        result = service.ingest_document(**service_request)
        if not result.get("success") and request.get("file_path") and request.get("_fallback_text"):
            fallback_request = dict(service_request)
            fallback_request.pop("file_path", None)
            fallback_request["text"] = str(request.get("_fallback_text") or "")
            fallback_request["metadata"] = {
                **dict(request.get("metadata") or {}),
                "fallback_reason": str(result.get("message") or "file ingest failed"),
            }
            result = service.ingest_document(**fallback_request)
    except RECOVERABLE_ERRORS as exc:
        result = {
            "success": False,
            "dataset_id": request["dataset_id"],
            "message": str(exc),
            "error_code": "dataset_ingest_exception",
        }

    summary = _summarize_ingest_result(artifact, result, request)
    artifact.metadata = {**dict(artifact.metadata or {}), "dataset_ingest": summary}
    _append_ingest_metadata(run, summary)
    event_type = "dataset.ingested" if summary["success"] else "dataset.ingest_failed"
    message = (
        f"Artifact 已进入 Dataset: {summary['dataset_id']}"
        if summary["success"]
        else "Artifact 进入 Dataset 失败"
    )
    run.add_event(event_type, message, summary)
    return summary


def _should_skip_artifact(artifact: AgentArtifact) -> bool:
    metadata = dict(artifact.metadata or {})
    if metadata.get("skip_dataset_ingest") is True:
        return True
    if metadata.get("dataset_ingest") is False:
        return True
    return bool(metadata.get("dataset_ingest"))


def _build_ingest_request(run: AgentRun, artifact: AgentArtifact) -> dict[str, Any] | None:
    artifact_type = str(artifact.artifact_type or "").strip()
    text = _artifact_text(artifact)
    file_path = _artifact_file_path(artifact)
    if artifact_type not in _DOCUMENT_ARTIFACT_TYPES and artifact_type not in _TEXT_ARTIFACT_TYPES:
        return None
    if not file_path and not text:
        return None

    metadata = {
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "artifact_name": artifact.name,
        "artifact_source": artifact.source,
        "agent_run_id": run.run_id,
        "user_id": run.user_id,
        "mime_type": artifact.mime_type,
        "parser_used": dict(artifact.metadata or {}).get("parser_used", ""),
    }
    source = artifact.name or artifact.uri or artifact.source or artifact.artifact_id
    request: dict[str, Any] = {
        "dataset_id": _resolve_dataset_id(run, artifact),
        "tenant_id": _resolve_tenant_id(run, artifact),
        "source": str(source or "artifact"),
        "document_id": f"artifact_{artifact.artifact_id}",
        "chunk_strategy": "fixed",
        "chunk_size": 800,
        "chunk_overlap": 80,
        "metadata": metadata,
    }
    if file_path and artifact_type in _DOCUMENT_ARTIFACT_TYPES:
        request["file_path"] = file_path
        if text:
            request["_fallback_text"] = text
    else:
        request["text"] = text
    return request


def _resolve_dataset_id(run: AgentRun, artifact: AgentArtifact) -> str:
    metadata = dict(artifact.metadata or {})
    runtime_context = run.metadata.get("runtime_context")
    context = runtime_context if isinstance(runtime_context, dict) else {}
    candidates = (
        metadata.get("dataset_id"),
        metadata.get("rag_dataset_id"),
        metadata.get("knowledge_dataset_id"),
        run.metadata.get("dataset_id"),
        context.get("dataset_id"),
        context.get("rag_dataset_id"),
        context.get("knowledge_dataset_id"),
        context.get("target_dataset_id"),
        context.get("artifact_dataset_id"),
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return f"user_{run.user_id or 'anonymous'}"


def _resolve_tenant_id(run: AgentRun, artifact: AgentArtifact) -> str:
    metadata = dict(artifact.metadata or {})
    runtime_context = run.metadata.get("runtime_context")
    context = runtime_context if isinstance(runtime_context, dict) else {}
    candidates = (
        metadata.get("tenant_id"),
        metadata.get("workspace_id"),
        context.get("tenant_id"),
        context.get("tenantId"),
        context.get("workspace_id"),
        context.get("workspace"),
        run.user_id,
    )
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return "anonymous"


def _artifact_file_path(artifact: AgentArtifact) -> str:
    uri = str(artifact.uri or "").strip()
    if not uri:
        return ""
    lowered = uri.lower()
    if "://" in lowered or lowered.startswith("/api/"):
        return ""
    return uri


def _artifact_text(artifact: AgentArtifact) -> str:
    preview = artifact.preview if isinstance(artifact.preview, dict) else {}
    metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
    parts: list[str] = []

    for value in (
        metadata.get("text"),
        metadata.get("text_preview"),
        metadata.get("ocr_text"),
        preview.get("text"),
        preview.get("text_preview"),
    ):
        text = str(value or "").strip()
        if text:
            parts.append(text)

    preview_data = preview.get("preview_data")
    if isinstance(preview_data, dict):
        compact = {
            key: preview_data.get(key)
            for key in (
                "sheet_name",
                "selected_sheet_name",
                "headers",
                "sample_rows",
                "grid_preview",
            )
            if preview_data.get(key) not in (None, "", [], {})
        }
        if compact:
            parts.append(json.dumps(compact, ensure_ascii=False, default=str))

    if artifact.fields:
        parts.append(json.dumps({"fields": artifact.fields}, ensure_ascii=False, default=str))

    summary = str(artifact.summary or "").strip()
    if len(summary) >= 16 and summary not in _GENERIC_SUMMARIES:
        parts.append(summary)

    seen: set[str] = set()
    deduped: list[str] = []
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        deduped.append(part)
    return "\n\n".join(deduped).strip()


def _summarize_ingest_result(
    artifact: AgentArtifact,
    result: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    document = result.get("document") if isinstance(result.get("document"), dict) else {}
    return {
        "success": bool(result.get("success")),
        "dataset_id": str(result.get("dataset_id") or request.get("dataset_id") or ""),
        "tenant_id": str(request.get("tenant_id") or ""),
        "document_id": str(document.get("document_id") or request.get("document_id") or ""),
        "chunk_count": int(result.get("chunk_count") or document.get("chunk_count") or 0),
        "parser": str(document.get("parser") or ""),
        "source": str(document.get("source") or request.get("source") or ""),
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type,
        "message": str(result.get("message") or ""),
        "error_code": str(result.get("error_code") or ""),
    }


def _append_ingest_metadata(run: AgentRun, summary: dict[str, Any]) -> None:
    existing = [item for item in run.metadata.get("dataset_ingests", []) if isinstance(item, dict)]
    existing.append(summary)
    run.metadata["dataset_ingests"] = existing
    run.metadata["dataset_ingest_attempt_count"] = len(existing)
    successes = [item for item in existing if item.get("success")]
    run.metadata["dataset_ingest_count"] = len(successes)
    run.metadata["dataset_ids"] = sorted(
        {
            str(item.get("dataset_id") or "")
            for item in successes
            if str(item.get("dataset_id") or "")
        }
    )


def _service_request(request: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in request.items() if not key.startswith("_")}
