"""把授权目录中的本机文档读成纯文本，供知识库入库。

dataset_rag 的解析器只接受 uploads/应用数据目录下的文件；这里在已通过
``resolve_authorized_path`` 校验后自行读取内容，再以 text 形式入库。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".json", ".log"}
_TABLE_SUFFIXES = {".xlsx", ".xls"}


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8"


def _legacy_text(path: Path) -> tuple[str, str, dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        text, encoding = _decode(path.read_bytes())
        return text, "text_file", {"extension": suffix, "encoding": encoding}
    if suffix in _TABLE_SUFFIXES:
        return _read_excel(path), "excel", {"extension": suffix}
    if suffix == ".pdf":
        return _read_pdf(path), "pdf", {"extension": suffix}
    if suffix == ".docx":
        return _read_docx(path), "docx", {"extension": suffix}
    if suffix == ".pptx":
        return _read_pptx(path), "pptx", {"extension": suffix}
    raise ValueError(f"unsupported document type: {suffix or '<none>'}")


def _read_excel(path: Path) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for sheet in workbook.worksheets:
            lines.append(f"# sheet:{sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if value is None else str(value) for value in row]
                if any(cells):
                    lines.append(" | ".join(cells))
    finally:
        workbook.close()
    return "\n".join(lines)


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def _read_docx(path: Path) -> str:
    from docx import Document

    document = Document(str(path))
    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _read_pptx(path: Path) -> str:
    from pptx import Presentation

    presentation = Presentation(str(path))
    parts: list[str] = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            text = getattr(shape, "text", "")
            if text and str(text).strip():
                parts.append(str(text))
    return "\n".join(parts)


def extract_text(path: Path) -> tuple[str, str, dict[str, Any]]:
    """返回 (文本, 解析器, 元数据)；复杂文档优先 Docling，失败回退轻量解析。"""
    from app.infrastructure.document_parsing.router import parse_document

    return parse_document(path, lambda: _legacy_text(path))
