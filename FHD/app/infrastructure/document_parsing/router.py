"""文档解析路由：按格式选择 Docling 或现有轻量解析器。"""

from __future__ import annotations

import hashlib
import importlib.metadata
import logging
import os
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.utils.operational_errors import BOUNDARY_ERRORS

logger = logging.getLogger(__name__)

# 只把版式复杂的文档路由给 Docling；表格类继续走 openpyxl，保证模板能力不回退。
_DOCLING_SUFFIXES = frozenset({".pdf", ".docx", ".pptx"})
_VALID_MODES = frozenset({"auto", "legacy", "docling"})


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    parser: str
    metadata: dict[str, Any] = field(default_factory=dict)


def parser_mode() -> str:
    raw = (os.environ.get("XCAGI_DOC_PARSER") or "auto").strip().lower()
    return raw if raw in _VALID_MODES else "auto"


def docling_available() -> bool:
    try:
        import docling  # noqa: F401
    except ImportError:
        return False
    return True


def parse_with_docling(path: Path) -> ParsedDocument:
    """Keep Docling's native structured export; Markdown is a derived view."""
    from docling.document_converter import DocumentConverter

    from app.domain.tabular_facts import make_source_ref, new_document
    from app.infrastructure.document_parsing.native import MAX_SOURCE_BYTES

    with path.open("rb") as handle:
        raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Docling input exceeds the source byte budget")
    if path.suffix.lower() in {".docx", ".pptx"}:
        from app.infrastructure.document_parsing.archive_safety import inspect_office_archive

        inspect_office_archive(raw)
    source_sha = hashlib.sha256(raw).hexdigest()
    del raw
    result = DocumentConverter().convert(str(path))
    document = getattr(result, "document", None)
    if document is None:
        raise ValueError("Docling 未返回 document")

    text = ""
    for method in ("export_to_markdown", "export_to_text"):
        exporter = getattr(document, method, None)
        if callable(exporter):
            text = str(exporter() or "")
            if text.strip():
                break
    if not text.strip():
        raise ValueError("Docling 未提取到文本")

    pages = getattr(document, "pages", None)
    tables = getattr(document, "tables", None)
    metadata: dict[str, Any] = {
        "extension": path.suffix.lower(),
        "page_count": len(pages) if isinstance(pages, dict) or isinstance(pages, list) else 0,
        "table_count": len(tables) if isinstance(tables, list) else 0,
        "parser_backend": "docling",
    }
    with path.open("rb") as handle:
        verified = handle.read(MAX_SOURCE_BYTES + 1)
    if len(verified) > MAX_SOURCE_BYTES or hashlib.sha256(verified).hexdigest() != source_sha:
        raise ValueError("Document changed while Docling was reading it")
    facts = new_document(
        make_source_ref(
            source_sha256=source_sha,
            source_format=path.suffix.lower().lstrip("."),
            parser="docling",
            parser_version=importlib.metadata.version("docling"),
        )
    )
    exporter = getattr(document, "export_to_dict", None)
    if callable(exporter):
        native = exporter()
        if not isinstance(native, dict):
            raise ValueError("Docling structured export must be an object")
        facts["native_extensions"] = {"docling_document": native}
        facts["capabilities"].update({"native_provenance": True, "semantic_recognition": "unknown"})
        for item in native.get("tables", []):
            facts["tables"].append(
                {
                    "native_object": item,
                    "source_ref": {
                        "document_id": facts["document_id"],
                        "native_ref": item.get("self_ref"),
                    },
                }
            )
        for item in native.get("texts", []):
            facts["regions"].append(
                {
                    "native_object": item,
                    "source_ref": {
                        "document_id": facts["document_id"],
                        "native_ref": item.get("self_ref"),
                    },
                }
            )
        page_data = native.get("pages", {})
        facts["pages"] = (
            [{"page": key, "native_object": value} for key, value in page_data.items()]
            if isinstance(page_data, dict)
            else page_data
        )
        status = str(getattr(result, "status", "unknown")).lower()
        if status not in {"success", "conversionstatus.success"}:
            facts["status"] = "partial"
            facts["warnings"].append({"code": "docling_conversion_status", "status": status})
    else:
        facts["status"] = "partial"
        facts["warnings"].append({"code": "docling_structured_export_unavailable"})
        facts["capabilities"]["native_provenance"] = False
    metadata["document_facts"] = facts
    return ParsedDocument(text=text, parser="docling", metadata=metadata)


def _legacy_result(path: Path, legacy_parser: Callable) -> tuple[str, str, dict[str, Any]]:
    if path.suffix.lower() in {".docx", ".pptx"}:
        from app.infrastructure.document_parsing.archive_safety import inspect_office_archive

        # The text compatibility parser also opens the native package. Admission
        # must precede that first load, not merely the later structured adapter.
        # The shared guard checks the file length before reading archive data.
        inspect_office_archive(path)
    text, parser, metadata = legacy_parser()
    from app.infrastructure.document_parsing.native import NATIVE_SUFFIXES, read_native_document

    if path.suffix.lower() not in NATIVE_SUFFIXES:
        return text, parser, metadata
    try:
        facts = read_native_document(path)
    except (ImportError, OSError, ValueError, zipfile.BadZipFile) as exc:
        # A text fallback is useful, but is never a successful structure result.
        metadata = {
            **metadata,
            "structure_status": "blocked",
            "structure_error": f"{type(exc).__name__}: {exc}"[:240],
        }
    else:
        metadata = {**metadata, "document_facts": facts, "structure_status": facts["status"]}
    return text, parser, metadata


def parse_pdf_bytes_with_docling(raw: bytes) -> str | None:
    """聊天附件用：字节流写临时文件后交给 Docling，失败返回 None 由调用方回退。"""
    if parser_mode() == "legacy" or not docling_available():
        return None
    import tempfile

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(raw)
            tmp_path = Path(handle.name)
        return parse_with_docling(tmp_path).text
    except BOUNDARY_ERRORS as exc:
        logger.warning("docling pdf bytes parse failed: %s", exc)
        return None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def parse_document(
    path: Path,
    legacy_parser: Callable[[], tuple[str, str, dict[str, Any]]],
) -> tuple[str, str, dict[str, Any]]:
    """路由入口：Docling 可用时解析复杂文档，否则回退 legacy。

    ``XCAGI_DOC_PARSER``:
    - ``auto``: 有 Docling 就用，失败回退 legacy（默认）
    - ``legacy``: 始终使用现有解析器
    - ``docling``: 强制 Docling，未安装或失败直接报错
    """
    mode = parser_mode()
    suffix = path.suffix.lower()
    if mode == "legacy" or suffix not in _DOCLING_SUFFIXES:
        return _legacy_result(path, legacy_parser)

    if not docling_available():
        if mode == "docling":
            raise RuntimeError("XCAGI_DOC_PARSER=docling，但未安装 docling")
        text, parser, metadata = _legacy_result(path, legacy_parser)
        return text, parser, {**metadata, "docling_skipped": "not_installed"}

    try:
        parsed = parse_with_docling(path)
    except BOUNDARY_ERRORS as exc:
        if mode == "docling":
            raise
        logger.warning("docling parse failed, fallback to legacy: %s: %s", path.name, exc)
        text, parser, metadata = _legacy_result(path, legacy_parser)
        return text, parser, {**metadata, "docling_error": str(exc)[:200]}

    return parsed.text, parsed.parser, parsed.metadata


__all__ = [
    "ParsedDocument",
    "docling_available",
    "parse_document",
    "parse_pdf_bytes_with_docling",
    "parse_with_docling",
    "parser_mode",
]
