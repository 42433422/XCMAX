"""
Artifact extraction and ingestion trace helpers.

Split from ``chat_trace.py`` (v10 线内迭代 · 巨石拆分).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.application.agent_orchestrator.artifact_ingestion import ingest_artifact_to_dataset
from app.application.agent_orchestrator.chat_trace_common import (
    _coerce_trace_float,
    _coerce_trace_int,
    _iter_payload_dicts,
    _trace_safe_value,
)
from app.application.agent_orchestrator.run_models import (
    AgentArtifact,
    AgentRun,
    artifact_from_dict,
)


def _artifact_signature(artifact: AgentArtifact) -> tuple[str, str, str, str, str]:
    return (
        artifact.artifact_type,
        artifact.name,
        artifact.uri,
        artifact.source,
        artifact.summary[:240],
    )


def _iter_explicit_artifact_payloads(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for item in _iter_payload_dicts(payload):
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


def _artifact_from_ocr_payload(item: dict[str, Any]) -> AgentArtifact | None:
    text = str(item.get("text") or item.get("ocr_text") or "").strip()
    file_path = str(
        item.get("file_path") or item.get("image_path") or item.get("uri") or ""
    ).strip()
    has_ocr_shape = bool(text) and (
        "confidence" in item
        or "ocr_confidence" in item
        or "analysis" in item
        or "structured_data" in item
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
        "confidence": _coerce_trace_float(confidence),
        "structured_data": _trace_safe_value(structured),
        "analysis": _trace_safe_value(analysis),
    }
    fields = [
        {"name": key, "value": _trace_safe_value(value)}
        for key, value in structured.items()
        if value not in (None, "", [], {})
    ][:20]
    summary = str(item.get("message") or item.get("summary") or "OCR 解析结果").strip()
    return AgentArtifact(
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


def _artifact_from_file_analysis_payload(item: dict[str, Any]) -> AgentArtifact | None:
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
    table_columns = (
        db_meta.get("table_columns") if isinstance(db_meta.get("table_columns"), dict) else {}
    )
    fields = [
        {"name": str(table), "columns": list(columns or [])[:40]}
        for table, columns in table_columns.items()
    ][:20]
    preview = {
        "parser_used": parser_used,
        "extension": extension,
        "suggested_use": suggested_use,
        "text_preview": str(item.get("text_preview") or "")[:1000],
        "db_meta": _trace_safe_value(db_meta),
        "unit_candidates": _trace_safe_value(item.get("unit_candidates") or []),
    }
    return AgentArtifact(
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


def _artifact_from_generated_document_payload(item: dict[str, Any]) -> AgentArtifact | None:
    document = item.get("document")
    candidate = document if isinstance(document, dict) else item
    has_document_marker = isinstance(document, dict) or any(
        key in candidate
        for key in (
            "download_url",
            "pickup_token",
            "document_url",
            "doc_url",
        )
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
    mime_type = mime_type or _mime_from_document_name(name)
    artifact_type = _artifact_type_from_document(name, mime_type)
    source = str(candidate.get("source") or item.get("source") or "generated_document")
    summary = str(
        candidate.get("summary") or candidate.get("message") or item.get("message") or "生成文档"
    ).strip()
    return AgentArtifact(
        artifact_type=artifact_type,
        name=name or uri or "generated_document",
        source=source,
        uri=uri,
        mime_type=mime_type,
        summary=summary,
        preview={
            "file_name": name,
            "download_url": uri,
            "pickup_token": pickup_token,
        },
        metadata={
            "pickup_token": pickup_token,
            "success": candidate.get("success", item.get("success")),
            "generator": source,
        },
    )


def _artifact_from_excel_analysis_payload(item: dict[str, Any]) -> AgentArtifact | None:
    preview_data = item.get("preview_data")
    if not isinstance(preview_data, dict):
        return None
    if not any(
        key in preview_data
        for key in ("sample_rows", "grid_preview", "file_path", "sheet_name", "selected_sheet_name")
    ):
        return None

    fields = item.get("fields")
    if not isinstance(fields, list):
        fields = []
    record_count = _coerce_trace_int(
        item.get("record_count")
        or preview_data.get("record_count")
        or len(preview_data.get("sample_rows") or [])
    )
    file_path = str(item.get("file_path") or preview_data.get("file_path") or "").strip()
    return AgentArtifact(
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
            "preview_data": _trace_safe_value(preview_data),
        },
        metadata={"parser_used": "excel_analysis", "success": item.get("success")},
    )


def _iter_inferred_artifacts(payload: dict[str, Any]) -> Iterator[AgentArtifact]:
    for item in _iter_payload_dicts(payload):
        for key in ("ocr_result", "ocr", "recognized_text"):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _artifact_from_ocr_payload(nested)
                if artifact is not None:
                    yield artifact

        for key in ("file_analysis", "analysis_result"):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _artifact_from_file_analysis_payload(nested)
                if artifact is not None:
                    yield artifact

        for key in ("document", "generated_document", "office_document"):
            nested = item.get(key)
            if isinstance(nested, dict):
                artifact = _artifact_from_generated_document_payload({"document": nested})
                if artifact is not None:
                    yield artifact

        excel_analysis = item.get("excel_analysis")
        if isinstance(excel_analysis, dict):
            artifact = _artifact_from_excel_analysis_payload(excel_analysis)
            if artifact is not None:
                yield artifact

        for factory in (
            _artifact_from_ocr_payload,
            _artifact_from_file_analysis_payload,
            _artifact_from_generated_document_payload,
            _artifact_from_excel_analysis_payload,
        ):
            artifact = factory(item)
            if artifact is not None:
                yield artifact


def _extract_artifacts(payload: dict[str, Any]) -> list[AgentArtifact]:
    artifacts: list[AgentArtifact] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for explicit in _iter_explicit_artifact_payloads(payload):
        artifact = artifact_from_dict(explicit)
        if not artifact.artifact_type:
            continue
        signature = _artifact_signature(artifact)
        if signature in seen:
            continue
        seen.add(signature)
        artifacts.append(artifact)

    for artifact in _iter_inferred_artifacts(payload):
        if not artifact.artifact_type:
            continue
        signature = _artifact_signature(artifact)
        if signature in seen:
            continue
        seen.add(signature)
        artifacts.append(artifact)
    return artifacts


def _refresh_artifact_metadata(run: AgentRun) -> None:
    run.metadata["artifact_count"] = len(run.artifacts)
    run.metadata["artifact_types"] = sorted({artifact.artifact_type for artifact in run.artifacts})


def _append_artifacts_to_run(run: AgentRun, artifacts: list[AgentArtifact]) -> None:
    existing = {_artifact_signature(artifact) for artifact in run.artifacts}
    for artifact in artifacts:
        signature = _artifact_signature(artifact)
        if signature in existing:
            continue
        existing.add(signature)
        run.artifacts.append(artifact)
        run.add_event(
            "artifact.attached",
            f"Artifact 已附加: {artifact.artifact_type}",
            {
                "artifact_id": artifact.artifact_id,
                "artifact_type": artifact.artifact_type,
                "name": artifact.name,
                "source": artifact.source,
                "uri": artifact.uri,
            },
        )
        ingest_artifact_to_dataset(run, artifact)
    if run.artifacts:
        _refresh_artifact_metadata(run)


def _append_artifacts_to_final_output(run: AgentRun) -> None:
    if not run.artifacts:
        return
    final_output = dict(run.final_output or {})
    final_output["artifacts"] = [artifact.to_dict() for artifact in run.artifacts]
    final_output["artifact_count"] = len(run.artifacts)
    if run.metadata.get("dataset_ingests"):
        final_output["dataset_ingests"] = run.metadata["dataset_ingests"]
        final_output["dataset_ingest_count"] = run.metadata.get("dataset_ingest_count", 0)
    run.final_output = final_output

