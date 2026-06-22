from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.application.agent_orchestrator.run_models import AgentArtifact, artifact_from_dict
from app.application.workflow.types import PlanGraph, WorkflowNode

_DOCUMENT_EXPORT_ARTIFACT_TYPES = {"pdf_document", "office_document", "document_file"}


def build_multimodal_autonomous_plan(
    *,
    user_id: str,
    message: str,
    runtime_context: dict[str, Any] | None,
) -> PlanGraph | None:
    context = dict(runtime_context or {})
    artifacts = _collect_artifacts(context)
    if not artifacts:
        return None

    dataset_id = _resolve_dataset_id(user_id, context, artifacts)
    tenant_id = _resolve_tenant_id(user_id, context, artifacts)
    query = _resolve_query(message, context, artifacts)
    top_k = _coerce_int(context.get("dataset_top_k") or context.get("rag_top_k"), default=5)
    include_answer = _coerce_bool(context.get("include_answer"), default=True)
    rerank = _coerce_bool(context.get("rerank") or context.get("rag_rerank"), default=False)

    artifact_payloads: list[dict[str, Any]] = []
    artifact_types: list[str] = []
    for artifact in artifacts:
        metadata = dict(artifact.metadata or {})
        metadata.setdefault("dataset_id", dataset_id)
        metadata.setdefault("tenant_id", tenant_id)
        metadata.setdefault("multimodal_autonomous", True)
        artifact.metadata = metadata
        artifact_payloads.append(artifact.to_dict())
        if artifact.artifact_type not in artifact_types:
            artifact_types.append(artifact.artifact_type)

    excel_import_records = _resolve_excel_import_records(context, artifacts, message)
    if excel_import_records and _looks_like_excel_import_intent(message, context):
        return PlanGraph(
            plan_id=f"plan_multimodal_excel_{uuid.uuid4().hex[:12]}",
            intent="multimodal_excel_import_to_db",
            todo_steps=[
                "将 Excel Artifact 附加到 AgentRun 并进入 Dataset/RAG 审计",
                "等待用户确认后把解析出的 Excel 记录写入业务数据库",
            ],
            nodes=[
                WorkflowNode(
                    node_id="import_excel_records",
                    tool_id="excel_import",
                    action="import_records",
                    params={
                        "records": excel_import_records,
                        "source": "multimodal_autonomous_planner",
                    },
                    risk="medium",
                    idempotent=False,
                    description="Import parsed Excel records into the controlled business database.",
                )
            ],
            risk_level="medium",
            metadata={
                "source": "multimodal_autonomous_planner",
                "multimodal_autonomous": True,
                "dataset_id": dataset_id,
                "tenant_id": tenant_id,
                "artifact_count": len(artifact_payloads),
                "artifact_types": artifact_types,
                "artifacts": artifact_payloads,
                "excel_import_record_count": len(excel_import_records),
            },
        )

    if _has_document_export_artifact(artifacts) and _looks_like_document_export_intent(
        message, context
    ):
        output_format = _resolve_document_output_format(message, context)
        user_request = _build_document_export_request(message, context, artifacts)
        return PlanGraph(
            plan_id=f"plan_multimodal_doc_export_{uuid.uuid4().hex[:12]}",
            intent="multimodal_document_export",
            todo_steps=[
                "将 PDF/Office Artifact 进入 Dataset/RAG 作为生成依据",
                "等待用户确认后生成可下载 Office 文档",
            ],
            nodes=[
                WorkflowNode(
                    node_id="generate_document_from_artifacts",
                    tool_id="generate_office_document",
                    action="execute",
                    params={
                        "user_request": user_request,
                        "output_format": output_format,
                    },
                    risk="medium",
                    idempotent=False,
                    description="Generate an Office document from attached multimodal artifacts after user approval.",
                )
            ],
            risk_level="medium",
            metadata={
                "source": "multimodal_autonomous_planner",
                "multimodal_autonomous": True,
                "dataset_id": dataset_id,
                "tenant_id": tenant_id,
                "artifact_count": len(artifact_payloads),
                "artifact_types": artifact_types,
                "artifacts": artifact_payloads,
                "document_export": {
                    "output_format": output_format,
                    "source_artifact_count": len(artifacts),
                    "request_excerpt": user_request[:500],
                    "requires_user_confirmation": True,
                },
            },
        )

    params: dict[str, Any] = {
        "dataset_id": dataset_id,
        "query": query,
        "tenant_id": tenant_id,
        "top_k": max(1, min(top_k, 20)),
        "include_answer": include_answer,
        "rerank": rerank,
    }
    version = str(context.get("dataset_version") or context.get("version") or "").strip()
    if version:
        params["version"] = version
    metadata_filter = context.get("metadata_filter")
    if isinstance(metadata_filter, dict) and metadata_filter:
        params["metadata_filter"] = metadata_filter

    return PlanGraph(
        plan_id=f"plan_multimodal_{uuid.uuid4().hex[:12]}",
        intent="multimodal_artifact_rag",
        todo_steps=[
            "将多模态 Artifact 进入 Dataset/RAG",
            "检索刚入库的证据并生成带引用答案",
        ],
        nodes=[
            WorkflowNode(
                node_id="query_multimodal_artifacts",
                tool_id="dataset_rag",
                action="query",
                params=params,
                risk="low",
                idempotent=True,
                description="Query Dataset/RAG after multimodal artifact ingestion.",
            )
        ],
        risk_level="low",
        metadata={
            "source": "multimodal_autonomous_planner",
            "multimodal_autonomous": True,
            "dataset_id": dataset_id,
            "tenant_id": tenant_id,
            "artifact_count": len(artifact_payloads),
            "artifact_types": artifact_types,
            "artifacts": artifact_payloads,
        },
    )


def _collect_artifacts(context: dict[str, Any]) -> list[AgentArtifact]:
    artifacts: list[AgentArtifact] = []

    # Keep artifact extraction identical to chat trace attachment handling.
    try:
        from app.application.agent_orchestrator.chat_trace import _extract_artifacts

        artifacts.extend(_extract_artifacts(context))
    except ImportError:
        artifacts = []

    for item in _iter_attachment_payloads(context):
        artifact = _artifact_from_attachment(item)
        if artifact is not None:
            artifacts.append(artifact)

    seen: set[tuple[str, str, str, str, str]] = set()
    unique: list[AgentArtifact] = []
    for artifact in artifacts:
        if not artifact.artifact_type:
            continue
        signature = (
            artifact.artifact_type,
            artifact.name,
            artifact.uri,
            artifact.source,
            artifact.summary[:240],
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(artifact)
    return unique


def _iter_attachment_payloads(context: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("multimodal_attachments", "attachments", "files"):
        raw = context.get(key)
        if isinstance(raw, dict):
            items.append(raw)
        elif isinstance(raw, list):
            items.extend(item for item in raw if isinstance(item, dict))
    return items


def _artifact_from_attachment(item: dict[str, Any]) -> AgentArtifact | None:
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
    artifact_type = _guess_attachment_artifact_type(file_path, mime_type, text)
    if not artifact_type:
        return None

    preview: dict[str, Any] = {
        "text": text[:1000],
        "text_preview": text[:1000],
        "attachment": {
            "name": name,
            "file_path": file_path,
            "mime_type": mime_type,
        },
    }
    fields = item.get("fields") if isinstance(item.get("fields"), list) else []
    metadata = {
        "parser_used": str(item.get("parser_used") or "multimodal_attachment"),
        "text": text,
        "success": item.get("success", True),
    }
    return AgentArtifact(
        artifact_type=artifact_type,
        name=name,
        source=str(item.get("source") or "multimodal_attachment"),
        uri=file_path,
        mime_type=mime_type,
        summary=str(item.get("summary") or item.get("message") or "多模态附件").strip(),
        fields=[field for field in fields if isinstance(field, dict)][:40],
        preview=preview,
        metadata=metadata,
    )


def _guess_attachment_artifact_type(file_path: str, mime_type: str, text: str) -> str:
    lowered_path = file_path.lower()
    lowered_mime = mime_type.lower()
    suffix = Path(lowered_path).suffix
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


def _resolve_dataset_id(
    user_id: str,
    context: dict[str, Any],
    artifacts: list[AgentArtifact],
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


def _resolve_tenant_id(
    user_id: str,
    context: dict[str, Any],
    artifacts: list[AgentArtifact],
) -> str:
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


def _resolve_query(
    message: str,
    context: dict[str, Any],
    artifacts: list[AgentArtifact],
) -> str:
    for key in ("dataset_query", "rag_query", "multimodal_query", "question"):
        value = str(context.get(key) or "").strip()
        if value:
            return value
    text = str(message or "").strip()
    if text:
        return text
    names = ", ".join(artifact.name for artifact in artifacts if artifact.name)
    return "Summarize evidence from " + (names or "attached artifacts")


def _looks_like_excel_import_intent(message: str, context: dict[str, Any]) -> bool:
    if context.get("excel_import") is True or context.get("excel_import_to_db") is True:
        return True
    text = str(
        message
        or context.get("message")
        or context.get("user_message")
        or context.get("question")
        or ""
    ).strip()
    if not text:
        return False
    markers = (
        "加入数据库",
        "导入数据库",
        "加入业务库",
        "导入业务库",
        "写入数据库",
        "写进数据库",
        "入库",
        "保存到数据库",
        "import",
        "import_records",
    )
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _has_document_export_artifact(artifacts: list[AgentArtifact]) -> bool:
    return any(artifact.artifact_type in _DOCUMENT_EXPORT_ARTIFACT_TYPES for artifact in artifacts)


def _looks_like_document_export_intent(message: str, context: dict[str, Any]) -> bool:
    if any(
        context.get(key) is True
        for key in (
            "document_export",
            "generate_document",
            "generate_office_document",
            "office_export",
        )
    ):
        return True

    text = str(
        message
        or context.get("message")
        or context.get("user_message")
        or context.get("question")
        or ""
    ).strip()
    if not text:
        return False
    lowered = text.lower()
    export_markers = (
        "导出",
        "生成",
        "做成",
        "转成",
        "输出",
        "下载",
        "整理成",
        "形成",
        "create",
        "generate",
        "export",
        "download",
    )
    document_markers = (
        "word",
        "docx",
        "xlsx",
        "office",
        "文档",
        "报告",
        "合同",
        "报价单",
        "表格",
        "文件",
        "摘要文档",
        "summary document",
        "report",
        "contract",
        "spreadsheet",
    )
    return any(marker in lowered for marker in export_markers) and any(
        marker in lowered for marker in document_markers
    )


def _resolve_document_output_format(message: str, context: dict[str, Any]) -> str:
    raw = str(context.get("output_format") or context.get("document_output_format") or "").lower()
    if raw in {"docx", "xlsx"}:
        return raw
    lowered = str(message or context.get("message") or "").lower()
    if any(marker in lowered for marker in ("xlsx", "excel", "spreadsheet", "表格")):
        return "xlsx"
    return "docx"


def _build_document_export_request(
    message: str,
    context: dict[str, Any],
    artifacts: list[AgentArtifact],
) -> str:
    explicit = str(
        context.get("document_request")
        or context.get("office_document_request")
        or context.get("generate_document_request")
        or ""
    ).strip()
    request = explicit or str(message or context.get("message") or "").strip()
    if not request:
        request = "请基于附件内容生成一份结构化文档。"

    evidence_lines: list[str] = []
    for index, artifact in enumerate(artifacts[:8], start=1):
        if artifact.artifact_type not in _DOCUMENT_EXPORT_ARTIFACT_TYPES:
            continue
        name = artifact.name or artifact.uri or f"artifact-{index}"
        line = f"{index}. {name} ({artifact.artifact_type})"
        summary = str(artifact.summary or "").strip()
        if summary:
            line = f"{line}: {summary[:240]}"
        text = _artifact_text_preview(artifact)
        if text:
            line = f"{line}\n   证据摘录: {text[:1200]}"
        evidence_lines.append(line)

    if not evidence_lines:
        return request
    return (
        f"用户请求：{request}\n\n"
        "请只基于以下已解析附件内容生成文档，保留关键事实、来源文件名和可核验条目；"
        "不确定的内容请标注待确认。\n"
        "附件证据：\n" + "\n".join(evidence_lines)
    )[:6000]


def _artifact_text_preview(artifact: AgentArtifact) -> str:
    preview = artifact.preview if isinstance(artifact.preview, dict) else {}
    metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
    candidates = (
        metadata.get("text"),
        metadata.get("text_preview"),
        metadata.get("ocr_text"),
        preview.get("text"),
        preview.get("text_preview"),
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return " ".join(text.split())
    return ""


def _resolve_excel_import_records(
    context: dict[str, Any],
    artifacts: list[AgentArtifact],
    message: str,
) -> list[dict[str, Any]]:
    for key in ("excel_import_records", "import_records"):
        records = _coerce_record_list(context.get(key))
        if records:
            return records

    excel_candidates: list[dict[str, Any]] = []
    excel_analysis = context.get("excel_analysis")
    if isinstance(excel_analysis, dict):
        excel_candidates.append(dict(excel_analysis))

    for artifact in artifacts:
        if artifact.artifact_type not in {"excel_records", "excel_file"}:
            continue
        preview = artifact.preview if isinstance(artifact.preview, dict) else {}
        preview_data = preview.get("preview_data")
        if isinstance(preview_data, dict):
            excel_candidates.append(
                {
                    "name": artifact.name,
                    "file_path": artifact.uri,
                    "fields": list(artifact.fields or []),
                    "preview_data": dict(preview_data),
                    "record_count": preview.get("record_count"),
                    "summary": artifact.summary,
                }
            )

    for candidate in excel_candidates:
        records = _extract_excel_records_with_existing_parser(candidate, context, message)
        if records:
            return records
    return []


def _coerce_record_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _extract_excel_records_with_existing_parser(
    excel_analysis: dict[str, Any],
    context: dict[str, Any],
    message: str,
) -> list[dict[str, Any]]:
    try:
        from app.application import get_ai_chat_app_service

        service = get_ai_chat_app_service()
        extractor = getattr(service, "_extract_excel_import_records", None)
        if not callable(extractor):
            return []
        records, error = extractor(excel_analysis, context, user_message=message)
        if error:
            return []
        return _coerce_record_list(records)
    except (ImportError, AttributeError, TypeError, ValueError):
        return []


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
