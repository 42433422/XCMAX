"""文档解析路由：按格式选择 Docling 或现有轻量解析器。"""
from __future__ import annotations

import logging
import os
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
    """用 Docling 解析单个文档，返回 Markdown 文本。"""
    from docling.document_converter import DocumentConverter

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
    return ParsedDocument(text=text, parser="docling", metadata=metadata)


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
        return legacy_parser()

    if not docling_available():
        if mode == "docling":
            raise RuntimeError("XCAGI_DOC_PARSER=docling，但未安装 docling")
        text, parser, metadata = legacy_parser()
        return text, parser, {**metadata, "docling_skipped": "not_installed"}

    try:
        parsed = parse_with_docling(path)
    except BOUNDARY_ERRORS as exc:
        if mode == "docling":
            raise
        logger.warning("docling parse failed, fallback to legacy: %s: %s", path.name, exc)
        text, parser, metadata = legacy_parser()
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