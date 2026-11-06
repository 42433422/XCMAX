"""Convert statement Word (.docx) into an XLSX derivative for the docking archive path.

Original .docx stays in the archive. Classification, model analyze, and confirmed
template writes run on the derived workbook. Rules may classify the derivative;
business writes still require a returned platform-model proposal.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring
from openpyxl import Workbook

from app.application.elt.errors import ReviewedExcelError
from app.application.reviewed_excel_template import MAX_BYTES, inspect_workbook

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONVERTER = "bounded docx table extractor v2"
_MAX_ROWS = 5000
_MAX_COLUMNS = 64
_MAX_TEXT = 32767


def is_docx_package(body: bytes) -> bool:
    if not body or len(body) > MAX_BYTES or not body.startswith(b"PK"):
        return False
    try:
        with ZipFile(BytesIO(body)) as package:
            return "word/document.xml" in package.namelist()
    except (BadZipFile, OSError):
        return False


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t":
            parts.append(node.text or "")
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in {f"{_W}br", f"{_W}cr"}:
            parts.append("\n")
    text = "".join(parts).strip()
    if len(text) > _MAX_TEXT:
        raise ReviewedExcelError("Word 单元格或段落超过 Excel 文本上限，未截断或导入")
    return text


def _cell_text(cell: ElementTree.Element) -> str:
    if cell.find(f".//{_W}tbl") is not None:
        raise ReviewedExcelError("Word 包含嵌套表格，无法无损派生，请先拆分表格")
    if any(
        cell.find(f"./{_W}tcPr/{_W}{name}") is not None for name in ("gridSpan", "vMerge", "hMerge")
    ):
        raise ReviewedExcelError("Word 包含合并单元格，无法保证列对应，请先拆分并确认原值")
    text = "\n".join(_paragraph_text(p) for p in cell.findall(f"./{_W}p"))
    if len(text) > _MAX_TEXT:
        raise ReviewedExcelError("Word 单元格超过 Excel 文本上限，未截断或导入")
    return text


def _read_tables(
    document_xml: bytes,
) -> tuple[list[str], list[list[list[str]]], list[tuple[int, str]]]:
    try:
        root = fromstring(document_xml)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise ReviewedExcelError("Word 正文 XML 损坏或包含不支持的实体") from exc
    bodies = root.findall(f"./{_W}body")
    if root.tag != f"{_W}document" or len(bodies) != 1:
        raise ReviewedExcelError("Word 文档缺少正文，无法派生表格")
    body = bodies[0]
    lead: list[str] = []
    tables: list[list[list[str]]] = []
    paragraphs: list[tuple[int, str]] = []
    row_count = 0
    if any(
        root.find(f".//{_W}{tag}") is not None
        for tag in (
            "drawing",
            "pict",
            "object",
            "sdt",
            "del",
            "ins",
            "customXml",
            "altChunk",
            "moveFrom",
            "moveTo",
            "footnoteReference",
            "endnoteReference",
            "sym",
        )
    ):
        raise ReviewedExcelError(
            "Word 含图片、嵌入对象、正文包装、注释或修订，无法无损派生，请先确认正文"
        )
    if any(node.tag.endswith(("}oMath", "}oMathPara")) for node in root.iter()):
        raise ReviewedExcelError("Word 含公式排版，无法保证正文完整，请先确认原值")

    def supported_children(parent, allowed):
        if any(child.tag not in {f"{_W}{name}" for name in allowed} for child in parent):
            raise ReviewedExcelError("Word 含不支持的正文或表格包装，未忽略或导入")

    supported_children(body, {"p", "tbl", "sectPr", "bookmarkStart", "bookmarkEnd"})
    for child in list(body):
        tag = child.tag
        if tag == f"{_W}p":
            text = _paragraph_text(child)
            if text:
                paragraphs.append((len(tables), text))
                if not tables:
                    lead.append(text)
                if len(paragraphs) > _MAX_ROWS:
                    raise ReviewedExcelError("Word 段落数超过安全上限，未截断或导入")
        elif tag == f"{_W}tbl":
            supported_children(child, {"tblPr", "tblGrid", "tr", "bookmarkStart", "bookmarkEnd"})
            rows: list[list[str]] = []
            for row in child.findall(f"./{_W}tr"):
                supported_children(row, {"trPr", "tc", "bookmarkStart", "bookmarkEnd"})
                if any(
                    row.find(f"./{_W}trPr/{_W}{tag}") is not None
                    for tag in ("gridBefore", "gridAfter")
                ):
                    raise ReviewedExcelError("Word 表格存在缺省列，无法保证列对应，请先整理表格")
                cells = []
                for cell in row.findall(f"./{_W}tc"):
                    supported_children(cell, {"tcPr", "p", "bookmarkStart", "bookmarkEnd", "tbl"})
                    cells.append(_cell_text(cell))
                if len(cells) > _MAX_COLUMNS:
                    raise ReviewedExcelError("Word 表格超过 64 列，未截断或导入")
                rows.append(cells)
                row_count += 1
                if row_count > _MAX_ROWS:
                    raise ReviewedExcelError("Word 表格总行数超过 5000 行，未截断或导入")
            if rows:
                tables.append(rows)
                if len(tables) > 64:
                    raise ReviewedExcelError("Word 表格数量超过安全上限，未截断或导入")
    return lead, tables, paragraphs


def _build_workbook(
    lead: list[str], tables: list[list[list[str]]], paragraphs: list[tuple[int, str]]
) -> bytes:
    def put(sheet, row: int, column: int, value: str) -> None:
        cell = sheet.cell(row, column, value or None)
        # Word text is data even when it starts with '='. Never create formulas.
        if value:
            cell.data_type = "s"

    book = Workbook()
    first = True
    if not tables:
        sheet = book.worksheets[0]
        sheet.title = "文档"
        for index, line in enumerate(lead, start=1):
            put(sheet, index, 1, line)
        first = False
    for table_index, rows in enumerate(tables, start=1):
        if first:
            sheet = book.worksheets[0]
            first = False
        else:
            sheet = book.create_sheet()
        sheet.title = "对账单" if table_index == 1 and len(tables) == 1 else f"表格{table_index}"
        row_offset = 0
        if table_index == 1 and lead:
            for index, line in enumerate(lead, start=1):
                put(sheet, index, 1, line)
            row_offset = len(lead) + 1
        for r_index, row in enumerate(rows, start=1):
            for c_index, value in enumerate(row, start=1):
                put(sheet, row_offset + r_index, c_index, value)
    if tables and any(table_index for table_index, _ in paragraphs):
        sheet = book.create_sheet("正文顺序")
        sheet.append(["此前表格数量", "正文"])
        for index, (table_index, line) in enumerate(paragraphs, start=2):
            sheet.cell(index, 1, table_index)
            put(sheet, index, 2, line)
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
            entries = [
                entry for entry in package.infolist() if entry.filename == "word/document.xml"
            ]
            if len(entries) != 1 or entries[0].file_size > MAX_BYTES:
                raise ReviewedExcelError("Word 正文重复或解压大小超过安全上限")
            with package.open(entries[0]) as source:
                document_xml = source.read(MAX_BYTES + 1)
            if len(document_xml) > MAX_BYTES:
                raise ReviewedExcelError("Word 正文解压大小超过安全上限")
    except (BadZipFile, KeyError, OSError) as exc:
        raise ReviewedExcelError("无法读取 Word 正文") from exc
    lead, tables, paragraphs = _read_tables(document_xml)
    if not tables and not lead:
        raise ReviewedExcelError("Word 文档没有可派生的正文或表格")
    converted = _build_workbook(lead, tables, paragraphs)
    review = inspect_workbook(converted)
    review["conversion_receipt"] = {
        "source_sha256": digest,
        "derived_sha256": hashlib.sha256(converted).hexdigest(),
        "converter": _CONVERTER,
        "purpose": "docking_center_word_statement",
        "print_layout_verified": False,
        "source_kind": "docx",
        "table_count": len(tables),
        "lead_paragraph_count": len(lead),
        "paragraph_count": len(paragraphs),
        "truncated": False,
        "extraction_scope": "document_body",
    }
    return converted, review
