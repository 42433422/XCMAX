"""Attachment conversion and dataset routing for multimodal agent plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.application.agent_orchestrator.run_models import AgentArtifact, artifact_from_dict


def iter_attachment_payloads(context: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("multimodal_attachments", "attachments", "files"):
        raw = context.get(key)
        if isinstance(raw, dict):
            items.append(raw)
        elif isinstance(raw, list):
            items.extend(item for item in raw if isinstance(item, dict))
    return items


def artifact_from_attachment(item: dict[str, Any]) -> AgentArtifact | None:
    if item.get("artifact_type") or item.get("type") == "artifact":
        artifact = artifact_from_dict(item)
        return artifact if artifact.artifact_type else None

    file_path = str(
        item.get("file_path") or item.get("path") or item.get("uri") or item.get("url") or ""
    ).strip()
    name = str(
        item.get("name") or item.get("filename") or Path(file_path).name or "attachment"
    ).strip()
    mime_type = str(item.get("mime_type") or item.get("mime") or "").strip()
    text = str(
        item.get("text")
        or item.get("text_preview")
        or item.get("ocr_text")
        or item.get("transcript")
        or ""
    ).strip()
    artifact_type = guess_attachment_artifact_type(file_path, mime_type, text)
    if not artifact_type:
        return None
    fields = item.get("fields") if isinstance(item.get("fields"), list) else []
    return AgentArtifact(
        artifact_type=artifact_type,
        name=name,
        source=str(item.get("source") or "multimodal_attachment"),
        uri=file_path,
        mime_type=mime_type,
        summary=str(item.get("summary") or item.get("message") or "多模态附件").strip(),
        fields=[field for field in (fields or []) if isinstance(field, dict)][:40],
        preview={
            "text": text[:1000],
            "text_preview": text[:1000],
            "attachment": {"name": name, "file_path": file_path, "mime_type": mime_type},
        },
        metadata={
            "parser_used": str(item.get("parser_used") or "multimodal_attachment"),
            "text": text,
            "success": item.get("success", True),
        },
    )


def guess_attachment_artifact_type(file_path: str, mime_type: str, text: str) -> str:
    suffix = Path(file_path.lower()).suffix
    lowered_mime = mime_type.lower()
    if suffix == ".pdf" or lowered_mime == "application/pdf":
        return "pdf_document"
    if suffix == ".docx" or "wordprocessingml" in lowered_mime:
        return "office_document"
    if suffix in {".txt", ".md", ".csv", ".json", ".log"} or lowered_mime.startswith("text/"):
        return "document_file"
    if suffix in {".xlsx", ".xls", ".xlsm"} or "spreadsheetml" in lowered_mime:
        return "excel_records" if text else ""
    if lowered_mime.startswith("image/") or text:
        return "ocr_text"
    return ""


def resolve_dataset_id(
    user_id: str, context: dict[str, Any], artifacts: list[AgentArtifact]
) -> str:
    candidates: list[Any] = [
        context.get("dataset_id"),
        context.get("rag_dataset_id"),
        context.get("knowledge_dataset_id"),
        context.get("target_dataset_id"),
        context.get("artifact_dataset_id"),
    ]
    candidates.extend(dict(artifact.metadata or {}).get("dataset_id") for artifact in artifacts)
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return f"user_{user_id or 'anonymous'}"


def resolve_tenant_id(user_id: str, context: dict[str, Any], artifacts: list[AgentArtifact]) -> str:
    candidates: list[Any] = [
        context.get("tenant_id"),
        context.get("tenantId"),
        context.get("workspace_id"),
        context.get("workspace"),
    ]
    candidates.extend(dict(artifact.metadata or {}).get("tenant_id") for artifact in artifacts)
    candidates.append(user_id)
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return "anonymous"
