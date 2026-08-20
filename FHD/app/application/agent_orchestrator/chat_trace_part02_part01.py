# mypy: disable-error-code="valid-type"
"""Implementation extracted from the public facade module."""

from __future__ import annotations

import importlib
from typing import Literal


def _facade():
    return importlib.import_module("app.application.agent_orchestrator.chat_trace")


def _memory_reference_from_payload(
    item: dict[str, _facade().Any], *, default_query: str
) -> _facade().MemoryReference | None:
    has_marker = _facade()._has_user_memory_marker(item)
    raw_hits = _facade()._first_list_value(
        item, ("user_memory_hits", "userMemoryHits", "memory_hits", "memoryHits", "hits")
    )
    hits = [
        dict(_facade()._trace_safe_value(hit))
        for hit in raw_hits
        if isinstance(hit, dict) and isinstance(_facade()._trace_safe_value(hit), dict)
    ]
    summary = str(
        item.get("user_memory_rag_summary")
        or item.get("userMemoryRagSummary")
        or item.get("user_memory_summary")
        or item.get("userMemorySummary")
        or item.get("memory_summary")
        or item.get("summary")
        or item.get("prompt_memory")
        or ""
    )
    error = str(
        item.get("user_memory_error")
        or item.get("userMemoryError")
        or item.get("memory_error")
        or item.get("memoryError")
        or ""
    )
    if not has_marker and (not hits) and ("UserMemoryRAG" not in summary):
        return None
    if not hits and (not summary) and (not error):
        return None
    query = str(
        item.get("query") or item.get("user_message") or item.get("message") or default_query or ""
    )
    memory_type = str(item.get("memory_type") or item.get("memoryType") or "user_memory")
    source = str(
        item.get("source")
        or item.get("memory_source")
        or item.get("memorySource")
        or item.get("index_id")
        or item.get("collection")
        or "user_memory_rag"
    )
    status: Literal["completed", "failed"] = "failed" if error else "completed"
    return _facade().MemoryReference(
        query=query,
        memory_type=memory_type,
        source=source,
        hits=hits,
        summary=summary,
        status=status,
        error=error,
        metadata={
            "top_k": _facade()._coerce_trace_int(item.get("top_k") or item.get("topK")),
            "hit_count": len(hits),
            "raw_trace": _facade()._trace_safe_value(
                {
                    key: item.get(key)
                    for key in (
                        "query",
                        "user_message",
                        "source",
                        "memory_source",
                        "index_id",
                        "collection",
                        "top_k",
                        "user_memory_error",
                        "memory_error",
                    )
                    if key in item
                }
            ),
        },
    )


def _extract_memory_references(
    payload: dict[str, _facade().Any], *, query: str = ""
) -> list[_facade().MemoryReference]:
    references: list[_facade().MemoryReference] = []
    seen: set[tuple[_facade().Any, ...]] = set()
    for item in _facade()._iter_memory_payloads(payload):
        reference = _facade()._memory_reference_from_payload(item, default_query=query)
        if reference is None:
            continue
        signature = _facade()._memory_reference_signature(reference)
        if signature in seen:
            continue
        seen.add(signature)
        references.append(reference)
    return references


def _refresh_memory_metadata(run: _facade().AgentRun) -> None:
    run.metadata["memory_reference_count"] = len(run.memory_references)
    run.metadata["memory_hit_count"] = sum(
        len(reference.hits) for reference in run.memory_references
    )
    run.metadata["memory_sources"] = sorted(
        {reference.source for reference in run.memory_references if reference.source}
    )


def _append_memory_references_to_run(
    run: _facade().AgentRun, references: list[_facade().MemoryReference]
) -> None:
    existing = {
        _facade()._memory_reference_signature(reference) for reference in run.memory_references
    }
    for reference in references:
        signature = _facade()._memory_reference_signature(reference)
        if signature in existing:
            continue
        existing.add(signature)
        run.memory_references.append(reference)
        first_sources = [
            str(hit.get("source") or hit.get("chunk_id") or hit.get("id") or "")
            for hit in reference.hits[:5]
        ]
        run.add_event(
            "memory.recalled" if reference.status == "completed" else "memory.failed",
            f"记录用户记忆召回 {reference.memory_type}",
            {
                "reference_id": reference.reference_id,
                "query": reference.query,
                "memory_type": reference.memory_type,
                "source": reference.source,
                "hit_count": len(reference.hits),
                "summary_preview": reference.summary[:500],
                "hit_sources": first_sources,
                "error": reference.error,
            },
        )
    if run.memory_references:
        _facade()._refresh_memory_metadata(run)


def _append_memory_references_to_final_output(run: _facade().AgentRun) -> None:
    if not run.memory_references:
        return
    final_output = dict(run.final_output or {})
    final_output["memory_references"] = [reference.to_dict() for reference in run.memory_references]
    final_output["memory_hit_count"] = run.metadata.get("memory_hit_count", 0)
    run.final_output = final_output


def _artifact_signature(artifact: _facade().AgentArtifact) -> tuple[str, str, str, str, str]:
    return (
        artifact.artifact_type,
        artifact.name,
        artifact.uri,
        artifact.source,
        artifact.summary[:240],
    )


def _iter_explicit_artifact_payloads(
    payload: dict[str, _facade().Any],
) -> _facade().Iterator[dict[str, _facade().Any]]:
    for item in _facade()._iter_payload_dicts(payload):
        artifacts = item.get("artifacts")
        if isinstance(artifacts, dict):
            yield artifacts
        elif isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict):
                    yield artifact
        artifact = item.get("artifact")
        if isinstance(artifact, dict):
            yield artifact


def _artifact_from_ocr_payload(item: dict[str, _facade().Any]) -> _facade().AgentArtifact | None:
    text = str(item.get("text") or item.get("ocr_text") or "").strip()
    file_path = str(
        item.get("file_path") or item.get("image_path") or item.get("uri") or ""
    ).strip()
    has_ocr_shape = bool(text) and (
        "confidence" in item
        or "ocr_confidence" in item
        or "analysis" in item
        or ("structured_data" in item)
        or (isinstance(item.get("data"), dict) and "raw_text" in item.get("data", {}))
        or bool(file_path)
    )
    if not has_ocr_shape:
        return None
    structured = item.get("structured_data")
    if not isinstance(structured, dict):
        data = item.get("data")
        structured = data if isinstance(data, dict) else {}
    analysis = item.get("analysis") if isinstance(item.get("analysis"), dict) else {}
    confidence = item.get("confidence", item.get("ocr_confidence", 0))
    preview = {
        "text": text[:1000],
        "confidence": _facade()._coerce_trace_float(confidence),
        "structured_data": _facade()._trace_safe_value(structured),
        "analysis": _facade()._trace_safe_value(analysis),
    }
    fields = [
        {"name": key, "value": _facade()._trace_safe_value(value)}
        for (key, value) in structured.items()
        if value not in (None, "", [], {})
    ][:20]
    summary = str(item.get("message") or item.get("summary") or "OCR 解析结果").strip()
    return _facade().AgentArtifact(
        artifact_type="ocr_text",
        name=str(item.get("name") or item.get("filename") or "ocr_result"),
        source=str(item.get("source") or "ocr"),
        uri=file_path,
        mime_type=str(item.get("mime_type") or "image/*"),
        summary=summary,
        fields=fields,
        preview=preview,
        metadata={"parser_used": "ocr", "success": item.get("success")},
    )


def _artifact_from_file_analysis_payload(
    item: dict[str, _facade().Any],
) -> _facade().AgentArtifact | None:
    if not any(key in item for key in ("parser_used", "suggested_use", "db_meta", "extension")):
        return None
    parser_used = str(item.get("parser_used") or "").strip()
    extension = str(item.get("extension") or "").strip().lower()
    suggested_use = str(item.get("suggested_use") or "").strip()
    saved_name = str(
        item.get("saved_name") or item.get("name") or item.get("filename") or ""
    ).strip()
    if not any((parser_used, extension, suggested_use, saved_name)):
        return None
    if parser_used == "sqlite_db" or extension == ".db" or suggested_use.endswith("_db"):
        artifact_type = "database_file"
    elif extension in {".xlsx", ".xls", ".xlsm"} or "excel" in parser_used:
        artifact_type = "excel_file"
    elif extension == ".pdf" or "pdf" in parser_used:
        artifact_type = "pdf_document"
    elif extension in {".doc", ".docx", ".ppt", ".pptx"} or "office" in parser_used:
        artifact_type = "office_document"
    else:
        artifact_type = "file_analysis"
    db_meta = item.get("db_meta") if isinstance(item.get("db_meta"), dict) else {}
    if not isinstance(db_meta, dict):
        db_meta = {}
    table_columns = (
        db_meta.get("table_columns") if isinstance(db_meta.get("table_columns"), dict) else {}
    )
    fields = [
        {"name": str(table), "columns": list(columns or [])[:40]}
        for (table, columns) in (table_columns or {}).items()
    ][:20]
    preview = {
        "parser_used": parser_used,
        "extension": extension,
        "suggested_use": suggested_use,
        "text_preview": str(item.get("text_preview") or "")[:1000],
        "db_meta": _facade()._trace_safe_value(db_meta),
        "unit_candidates": _facade()._trace_safe_value(item.get("unit_candidates") or []),
    }
    return _facade().AgentArtifact(
        artifact_type=artifact_type,
        name=saved_name or str(item.get("raw_filename") or item.get("filename") or "file_analysis"),
        source=str(item.get("source") or "file_analysis"),
        uri=str(item.get("file_path") or item.get("uri") or saved_name),
        mime_type=str(item.get("mime_type") or ""),
        summary=str(item.get("ai_summary") or item.get("message") or suggested_use or parser_used),
        fields=fields,
        preview=preview,
        metadata={
            "parser_used": parser_used,
            "extension": extension,
            "suggested_use": suggested_use,
            "success": item.get("success"),
        },
    )


def _mime_from_document_name(name: str, default: str = "") -> str:
    lowered = name.lower().strip()
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lowered.endswith(".xlsx"):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if lowered.endswith(".pptx"):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    return default


def _artifact_type_from_document(name: str, mime_type: str) -> str:
    lowered_name = name.lower().strip()
    lowered_mime = mime_type.lower().strip()
    if lowered_name.endswith(".pdf") or lowered_mime == "application/pdf":
        return "pdf_document"
    if lowered_name.endswith((".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx")):
        return "office_document"
    if "officedocument" in lowered_mime:
        return "office_document"
    return "document_file"


def _artifact_from_generated_document_payload(
    item: dict[str, _facade().Any],
) -> _facade().AgentArtifact | None:
    document = item.get("document")
    candidate = document if isinstance(document, dict) else item
    has_document_marker = isinstance(document, dict) or any(
        key in candidate for key in ("download_url", "pickup_token", "document_url", "doc_url")
    )
    if not has_document_marker:
        return None
    name = str(
        candidate.get("file_name")
        or candidate.get("doc_name")
        or candidate.get("filename")
        or candidate.get("name")
        or ""
    ).strip()
    uri = str(
        candidate.get("download_url")
        or candidate.get("document_url")
        or candidate.get("doc_url")
        or candidate.get("file_path")
        or candidate.get("uri")
        or ""
    ).strip()
    pickup_token = str(candidate.get("pickup_token") or candidate.get("token") or "").strip()
    if not any((name, uri, pickup_token)):
        return None
    mime_type = str(candidate.get("mime_type") or candidate.get("mime") or "").strip()
    mime_type = mime_type or _facade()._mime_from_document_name(name)
    artifact_type = _facade()._artifact_type_from_document(name, mime_type)
    source = str(candidate.get("source") or item.get("source") or "generated_document")
    summary = str(
        candidate.get("summary") or candidate.get("message") or item.get("message") or "生成文档"
    ).strip()
    return _facade().AgentArtifact(
        artifact_type=artifact_type,
        name=name or uri or "generated_document",
        source=source,
        uri=uri,
        mime_type=mime_type,
        summary=summary,
        preview={"file_name": name, "download_url": uri, "pickup_token": pickup_token},
        metadata={
            "pickup_token": pickup_token,
            "success": candidate.get("success", item.get("success")),
            "generator": source,
        },
    )


def _artifact_from_excel_analysis_payload(
    item: dict[str, _facade().Any],
) -> _facade().AgentArtifact | None:
    preview_data = item.get("preview_data")
    if not isinstance(preview_data, dict):
        return None
    if not any(
        key in preview_data
        for key in (
            "sample_rows",
            "grid_preview",
            "file_path",
            "sheet_name",
            "selected_sheet_name",
        )
    ):
        return None
    fields = item.get("fields")
    if not isinstance(fields, list):
        fields = []
    record_count = _facade()._coerce_trace_int(
        item.get("record_count")
        or preview_data.get("record_count")
        or len(preview_data.get("sample_rows") or [])
    )
    file_path = str(item.get("file_path") or preview_data.get("file_path") or "").strip()
    return _facade().AgentArtifact(
        artifact_type="excel_records",
        name=str(item.get("name") or preview_data.get("filename") or file_path or "excel_analysis"),
        source=str(item.get("source") or "excel_analysis"),
        uri=file_path,
        mime_type=str(
            item.get("mime_type")
            or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        summary=str(item.get("summary") or "Excel 解析结果"),
        fields=[field for field in fields if isinstance(field, dict)][:40],
        preview={
            "record_count": record_count,
            "preview_data": _facade()._trace_safe_value(preview_data),
        },
        metadata={"parser_used": "excel_analysis", "success": item.get("success")},
    )
