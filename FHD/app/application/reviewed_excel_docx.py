"""Convert statement Word (.docx) into an XLSX derivative for the docking archive path.

Original .docx stays in the archive. Classification, model analyze, and confirmed
template writes run on the derived workbook. Rules may classify the derivative;
business writes still require a returned platform-model proposal.
"""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from openpyxl import Workbook

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_template import MAX_BYTES, inspect_workbook

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONVERTER = "bounded docx table extractor v1"


def is_docx_package(body: bytes) -> bool:
    if not body or len(body) > MAX_BYTES or not body.startswith(b"PK"):
        return False
    try:
        with ZipFile(BytesIO(body)) as package:
            return "word/document.xml" in package.namelist()
    except (BadZipFile, OSError):
        return False


def _cell_text(cell: ElementTree.Element) -> str:
    parts = [node.text or "" for node in cell.findall(f".//{_W}t")]
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts = [node.text or "" for node in paragraph.findall(f".//{_W}t")]
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _read_tables(document_xml: bytes) -> tuple[list[str], list[list[list[str]]]]:
    root = ElementTree.fromstring(document_xml)
    body = root.find(f".//{_W}body")
    if body is None:
        raise ReviewedExcelError("Word 文档缺少正文，无法派生表格")
    lead: list[str] = []
    tables: list[list[list[str]]] = []
    for child in list(body):
        tag = child.tag
        if tag == f"{_W}p":
            if tables:
                continue
            text = _paragraph_text(child)
            if text:
                lead.append(text[:500])
        elif tag == f"{_W}tbl":
            rows: list[list[str]] = []
            for row in child.findall(f"./{_W}tr"):
                cells = [_cell_text(cell) for cell in row.findall(f"./{_W}tc")]
                if any(cells):
                    rows.append(cells)
            if rows:
                tables.append(rows)
    return lead, tables


def _build_workbook(lead: list[str], tables: list[list[list[str]]]) -> bytes:
    book = Workbook()
    first = True
    if not tables:
        sheet = book.active
        sheet.title = "文档"
        for index, line in enumerate(lead[:200], start=1):
            sheet.cell(index, 1, line)
        first = False
    for table_index, rows in enumerate(tables, start=1):
        if first:
            sheet = book.active
            first = False
        else:
            sheet = book.create_sheet()
        sheet.title = "对账单" if table_index == 1 and len(tables) == 1 else f"表格{table_index}"
        row_offset = 0
        if table_index == 1 and lead:
            for index, line in enumerate(lead[:20], start=1):
                sheet.cell(index, 1, line)
            row_offset = min(len(lead), 20) + 1
        for r_index, row in enumerate(rows[:5000], start=1):
            for c_index, value in enumerate(row[:64], start=1):
                sheet.cell(row_offset + r_index, c_index, value[:500] if value else None)
    if "Sheet" in book.sheetnames and len(book.sheetnames) > 1:
        book.remove(book["Sheet"])
    out = BytesIO()
    book.save(out)
    converted = out.getvalue()
    if not converted or len(converted) > MAX_BYTES:
        raise ReviewedExcelError("Word 派生副本为空或超过 20 MB")
    return converted


def convert_docx_to_xlsx_for_archive(body: bytes):
    """Return (xlsx_bytes, review) with conversion_receipt for archive-classify."""
    if not is_docx_package(body):
        raise ReviewedExcelError("文件不是有效的 Word（.docx）包")
    digest = hashlib.sha256(body).hexdigest()
    try:
        with ZipFile(BytesIO(body)) as package:
            document_xml = package.read("word/document.xml")
    except (BadZipFile, KeyError, OSError) as exc:
        raise ReviewedExcelError("无法读取 Word 正文") from exc
    lead, tables = _read_tables(document_xml)
    if not tables and not lead:
        raise ReviewedExcelError("Word 文档没有可派生的正文或表格")
    converted = _build_workbook(lead, tables)
    review = inspect_workbook(converted)
    # Docking-center Word intake is a supported product path. Provenance stays on
    # conversion_receipt; do not mark the derivative as test-only publish-blocked.
    review["usage_restrictions"] = []
    review["conversion_receipt"] = {
        "source_sha256": digest,
        "derived_sha256": hashlib.sha256(converted).hexdigest(),
        "converter": _CONVERTER,
        "purpose": "docking_center_word_statement",
        "print_layout_verified": False,
        "source_kind": "docx",
        "table_count": len(tables),
        "lead_paragraph_count": len(lead),
    }
    return converted, review
