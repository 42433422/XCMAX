"""Column and form layouts used by Chinese SME workbooks.

These parsers only emit rows when a header shape is recognizable. They do not
guess a business object from free text.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from openpyxl import load_workbook

from app.application.elt.parser_structure import clean_cell_text, semantic_key
from app.application.elt.parser_types import ParsedDataset, ParsedRow

_W_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_HEADER_SKIP = {
    "日期",
    "厂名",
    "单号",
    "品名",
    "产品名称",
    "数量",
    "规格",
    "单价",
    "金额",
    "备注",
    "合计",
    "小计",
    "摘要",
    "销售应收款",
    "实收金额",
    "下欠款",
    "应付款",
    "销售额",
}


def _key(value: Any) -> str:
    return semantic_key(value)


def _rows(path: Path, *, limit: int) -> list[tuple[str, int, tuple[Any, ...]]]:
    workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    found: list[tuple[str, int, tuple[Any, ...]]] = []
    try:
        for worksheet in workbook.worksheets:
            for index, raw in enumerate(worksheet.iter_rows(values_only=True), start=1):
                found.append((worksheet.title, index, tuple(raw)))
                if len(found) >= limit:
                    return found
    finally:
        workbook.close()
    return found


def _dataset(headers: list[str], rows: list[ParsedRow], *, kind: str) -> ParsedDataset | None:
    if not rows:
        return None
    return ParsedDataset(
        headers=headers,
        rows=rows,
        source_features={"kind": kind, "structure_detection": kind, "row_count": len(rows)},
    )


def parse_factory_customers(path: Path, *, max_rows: int) -> ParsedDataset | None:
    """Read a 日期/厂名/单号 sheet as customer rows when it has no product column."""
    header: tuple[str, int, dict[str, int]] | None = None
    rows: list[ParsedRow] = []
    sheet_rows = _rows(path, limit=max_rows + 40)
    for sheet, number, values in sheet_rows:
        keys = [_key(value) for value in values[:20]]
        if header is None and "厂名" in keys and "品名" not in keys and "产品名称" not in keys:
            if "日期" in keys or "单号" in keys:
                header = (sheet, number, {"customer_name": keys.index("厂名")})
            continue
        if header is None or sheet != header[0] or number <= header[1]:
            continue
        column = header[2]["customer_name"]
        name = clean_cell_text(values[column] if column < len(values) else "")
        if not name or _key(name) in _HEADER_SKIP:
            continue
        rows.append(
            ParsedRow(
                sheet=sheet,
                row_number=number,
                values={"customer_name": name[:160]},
                provenance={
                    "sheet": sheet,
                    "row": number,
                    "source_kind": "factory_customer_column",
                },
            )
        )
        if len(rows) >= max_rows:
            break
    return _dataset(["customer_name"], rows, kind="factory_customer_column")


def parse_amount_blocks(path: Path, *, max_rows: int) -> ParsedDataset | None:
    """Read side-by-side 日期/单号/销售应收款 blocks as one customer per block."""
    rows: list[ParsedRow] = []
    seen: set[str] = set()
    workbook = load_workbook(path, read_only=False, data_only=True, keep_links=False)
    try:
        for worksheet in workbook.worksheets:
            matrix = [
                tuple(row)
                for row in worksheet.iter_rows(
                    max_row=min(worksheet.max_row or 1, max_rows),
                    max_col=min(worksheet.max_column or 1, 240),
                    values_only=True,
                )
            ]
            for index, values in enumerate(matrix):
                date_cols = [col for col, value in enumerate(values) if _key(value) == "日期"]
                if len(date_cols) < 2:
                    continue
                if not any(
                    "销售应收" in _key(value) or "应付款" in _key(value) for value in values
                ):
                    continue
                for column in date_cols:
                    title = ""
                    for above in range(index - 1, max(-1, index - 8), -1):
                        cell = matrix[above][column] if column < len(matrix[above]) else None
                        text = clean_cell_text(cell)
                        if (
                            not text
                            or _key(text) in _HEADER_SKIP
                            or not re.search(r"[\u4e00-\u9fff]", text)
                        ):
                            continue
                        title = re.split(
                            r"\d|应收|应付|欠款|金额|往来|截止|合计|销售|期末|期初",
                            text,
                            maxsplit=1,
                        )[0].strip(" ：:，,")
                        break
                    if not title or len(title) < 2 or len(title) > 12 or title in seen:
                        continue
                    seen.add(title)
                    rows.append(
                        ParsedRow(
                            sheet=worksheet.title,
                            row_number=(index + 1) * 1000 + column,
                            values={"customer_name": title[:160]},
                            provenance={
                                "sheet": worksheet.title,
                                "row": index + 1,
                                "column": column + 1,
                                "source_kind": "amount_block_customer",
                            },
                        )
                    )
    finally:
        workbook.close()
    return _dataset(["customer_name"], rows[:max_rows], kind="amount_block_customer")


def parse_production_order(path: Path, *, max_rows: int) -> ParsedDataset | None:
    """Read a 生产单 whose material header is 原材料编号 / 原料数量."""
    workbook = load_workbook(path, read_only=False, data_only=True, keep_links=False)
    rows: list[ParsedRow] = []
    try:
        for worksheet in workbook.worksheets:
            title = _key(worksheet["A1"].value)
            if "生产单" not in title and "生产单" not in _key(worksheet.title):
                continue
            unit = "生产单"
            header_row = 0
            columns: dict[str, int] = {}
            for row_number in range(1, min((worksheet.max_row or 1) + 1, 30)):
                for column in range(1, min((worksheet.max_column or 1) + 1, 8)):
                    key = _key(worksheet.cell(row_number, column).value)
                    if key == "产品编号":
                        neighbor = clean_cell_text(worksheet.cell(row_number, column + 1).value)
                        if neighbor:
                            unit = neighbor[:160]
                    if "原材料编号" in key or key == "原料编号":
                        columns["name"] = column
                        header_row = row_number
                    elif "原料数量" in key:
                        columns["description"] = column
                    elif "工艺" in key:
                        columns["specification"] = column
            if not header_row or "name" not in columns:
                continue
            for row_number in range(
                header_row + 1, min((worksheet.max_row or 1) + 1, header_row + max_rows)
            ):
                name = clean_cell_text(worksheet.cell(row_number, columns["name"]).value)
                if not name or _key(name) in _HEADER_SKIP or "原材料" in _key(name):
                    continue
                quantity = ""
                if "description" in columns:
                    quantity = clean_cell_text(
                        worksheet.cell(row_number, columns["description"]).value
                    )
                process = ""
                if "specification" in columns:
                    process = clean_cell_text(
                        worksheet.cell(row_number, columns["specification"]).value
                    )
                rows.append(
                    ParsedRow(
                        sheet=worksheet.title,
                        row_number=row_number,
                        values={
                            "unit": unit,
                            "name": name[:160],
                            "model_number": name[:160],
                            "description": quantity[:160],
                            "specification": process[:160],
                        },
                        provenance={
                            "sheet": worksheet.title,
                            "row": row_number,
                            "source_kind": "production_order",
                        },
                    )
                )
    finally:
        workbook.close()
    return _dataset(
        ["unit", "name", "model_number", "description", "specification"],
        rows,
        kind="production_order",
    )


def _docx_text(cell: ET.Element) -> str:
    return re.sub(r"\s+", "", "".join(node.text or "" for node in cell.findall(".//w:t", _W_NS)))


def parse_label_product_card(path: Path) -> ParsedDataset | None:
    """Read a one-product card laid out as 产品名称 / 产品编号 labels."""
    workbook = load_workbook(path, read_only=False, data_only=True, keep_links=False)
    rows: list[ParsedRow] = []
    try:
        for worksheet in workbook.worksheets:
            found: dict[str, str] = {}
            tabular = False
            header_tokens = {
                "产品名称",
                "产品编号",
                "产品规格",
                "数量",
                "规格",
                "单价",
                "金额",
                "品名",
            }
            for row in worksheet.iter_rows(max_row=12, max_col=6):
                row_keys = [_key(cell.value) for cell in row]
                if sum(key in header_tokens for key in row_keys) >= 2:
                    tabular = True
                    break
                for cell in row:
                    key = _key(cell.value)
                    if key not in {"产品名称", "产品编号", "产品规格"}:
                        continue
                    neighbor = clean_cell_text(worksheet.cell(cell.row, cell.column + 1).value)
                    if neighbor and _key(neighbor) not in header_tokens:
                        found[key] = neighbor[:160]
            if tabular:
                continue
            if "产品名称" not in found:
                continue
            rows.append(
                ParsedRow(
                    sheet=worksheet.title,
                    row_number=1,
                    values={
                        "unit": "未指定购买单位",
                        "name": found["产品名称"],
                        "model_number": found.get("产品编号", ""),
                        "specification": found.get("产品规格", ""),
                    },
                    provenance={
                        "sheet": worksheet.title,
                        "row": 1,
                        "source_kind": "label_product_card",
                    },
                )
            )
    finally:
        workbook.close()
    return _dataset(
        ["unit", "name", "model_number", "specification"], rows, kind="label_product_card"
    )


def parse_statement_docx(path: Path) -> ParsedDataset | None:
    """Turn a statement table into knowledge rows instead of a path pointer."""
    try:
        with zipfile.ZipFile(path) as package:
            xml = package.read("word/document.xml")
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    root = ET.fromstring(xml)
    table = root.find(".//w:tbl", _W_NS)
    if table is None:
        return None
    table_rows = table.findall("./w:tr", _W_NS)
    if len(table_rows) < 2:
        return None
    headers = [_docx_text(cell) for cell in table_rows[0].findall("./w:tc", _W_NS)]
    if not any("欠款" in header or "收款" in header for header in headers):
        return None
    party = ""
    for paragraph in root.findall(".//w:p", _W_NS)[:8]:
        text = re.sub(
            r"\s+", "", "".join(node.text or "" for node in paragraph.findall(".//w:t", _W_NS))
        )
        if (
            text
            and "欠款" not in text
            and "收款" not in text
            and _key(text) not in {"对账单", "对账", "年月"}
            and re.search(r"[\u4e00-\u9fff]", text)
        ):
            party = text[:160]
            break
    parsed: list[ParsedRow] = []
    for index, row in enumerate(table_rows[1:], start=2):
        cells = [_docx_text(cell) for cell in row.findall("./w:tc", _W_NS)]
        if not any(cells):
            continue
        pairs = [
            f"{headers[col] or f'列{col + 1}'}:{cells[col]}"
            for col in range(min(len(headers), len(cells)))
            if cells[col]
        ]
        if party:
            pairs.insert(0, f"往来单位:{party}")
        parsed.append(
            ParsedRow(
                sheet="对账单",
                row_number=index,
                values={
                    "content": "；".join(pairs)[:4000],
                    "document_path": str(path),
                    "source_key": path.name,
                },
                provenance={"sheet": "对账单", "row": index, "source_kind": "statement_docx"},
            )
        )
    if not parsed:
        return None
    content = "\n".join(str(row.values["content"]) for row in parsed)
    return _dataset(
        ["content", "document_path", "source_key"],
        [
            ParsedRow(
                sheet="对账单",
                row_number=1,
                values={
                    "content": content[:20000],
                    "document_path": str(path),
                    "source_key": path.name,
                },
                provenance={
                    "sheet": "对账单",
                    "row": 1,
                    "source_kind": "statement_docx",
                    "line_count": len(parsed),
                },
            )
        ],
        kind="statement_docx",
    )
