"""把单个上传文件解析为 ArtifactRecord。"""

from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

import openpyxl

from app.application.attachment_artifacts.models import ArtifactRecord, SheetInfo

PREVIEW_ROWS = 3
_SUPPORTED_SUFFIXES = {".xlsx", ".xlsm", ".csv", ".docx"}


class AttachmentParseError(ValueError):
    """附件解析失败。"""


class UnsupportedDocument(AttachmentParseError):
    """文件类型或内容不受支持。"""


class TemporaryDocument(AttachmentParseError):
    """Office 临时文件或系统元数据文件，调用方应跳过。"""


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _build_sheet(name: str, rows: Iterable[Sequence[Any]]) -> SheetInfo:
    """首行非空行作表头，其余为数据行；预览最多 PREVIEW_ROWS 行。"""
    header: list[str] = []
    data: list[list[str]] = []
    for raw in rows:
        cells = [_cell_text(cell) for cell in raw]
        if not any(cells):
            continue
        if not header:
            while cells and not cells[-1]:
                cells.pop()
            header = cells
            continue
        data.append(cells)
    return SheetInfo(
        name=name,
        columns=header,
        row_count=len(data),
        rows_preview=data[:PREVIEW_ROWS],
        truncated=len(data) > PREVIEW_ROWS,
        rows=data,
    )


def _parse_excel(path: Path) -> list[SheetInfo]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return [
            _build_sheet(worksheet.title, worksheet.iter_rows(values_only=True))
            for worksheet in workbook.worksheets
        ]
    finally:
        workbook.close()


def _decode_csv(body: bytes) -> str:
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnsupportedDocument("CSV 编码无法识别（仅支持 UTF-8/GBK）")


def _parse_docx(path: Path) -> SheetInfo:
    try:
        import docx
        from docx.opc.exceptions import PackageNotFoundError
    except ImportError as exc:
        raise UnsupportedDocument("未安装 python-docx，无法解析 DOCX") from exc
    try:
        document = docx.Document(str(path))
    except (PackageNotFoundError, OSError, ValueError) as exc:
        raise UnsupportedDocument("DOCX 内容无法读取") from exc
    rows = [[paragraph.text.strip()] for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                rows.append(cells)
    return SheetInfo(
        name="正文",
        columns=["正文"],
        row_count=len(rows),
        rows_preview=rows[:PREVIEW_ROWS],
        truncated=len(rows) > PREVIEW_ROWS,
        rows=rows,
    )


def parse_file(path: str | Path, *, name: str | None = None) -> ArtifactRecord:
    """解析单个文件；name 为展示用原始文件名（默认为磁盘文件名）。"""
    file_path = Path(path)
    display_name = name or file_path.name
    if display_name.startswith(("~$", "._")):
        raise TemporaryDocument(f"临时文件已跳过: {display_name}")
    suffix = Path(display_name).suffix.lower()
    if suffix == ".xls":
        raise UnsupportedDocument("旧 XLS 需先转换为 XLSX")
    if suffix not in _SUPPORTED_SUFFIXES:
        raise UnsupportedDocument(f"不支持的文件类型: {suffix or '无扩展名'}")

    body = file_path.read_bytes()
    digest = hashlib.sha1(body, usedforsecurity=False).hexdigest()
    if suffix in {".xlsx", ".xlsm"}:
        sheets = _parse_excel(file_path)
    elif suffix == ".csv":
        rows = csv.reader(io.StringIO(_decode_csv(body)))
        sheets = [_build_sheet(Path(display_name).stem, rows)]
    else:
        sheets = [_parse_docx(file_path)]

    return ArtifactRecord(
        id=digest,
        name=display_name,
        suffix=suffix,
        size=len(body),
        sha1=digest,
        created_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        sheets=sheets,
    )
