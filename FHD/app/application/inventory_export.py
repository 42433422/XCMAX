"""In-memory inventory workbook rendering; receives one verified SQL snapshot."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

from app.application.etl.transforms import neutralize_spreadsheet_formula

INVENTORY_COLUMNS = (
    ("product_name", "产品名称", 28),
    ("product_code", "型号", 22),
    ("warehouse_name", "仓库", 22),
    ("batch_no", "批次", 22),
    ("quantity", "库存数量", 20),
    ("available_quantity", "可用数量", 20),
    ("unit", "单位", 12),
    ("in_date", "入库日期", 16),
)


def render_inventory_workbook(rows: list[dict[str, Any]]) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("库存明细")
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:H{len(rows) + 1}"
    headers = []
    for index, (_key, title, width) in enumerate(INVENTORY_COLUMNS):
        sheet.column_dimensions[chr(ord("A") + index)].width = width
        cell = WriteOnlyCell(sheet, title)
        cell.font = Font(bold=True)
        headers.append(cell)
    sheet.append(headers)
    for row in rows:
        cells = []
        for key, _title, _width in INVENTORY_COLUMNS:
            value = neutralize_spreadsheet_formula(row.get(key))
            cell = WriteOnlyCell(sheet, value)
            if isinstance(value, str):
                # Explicit text also covers invisible-prefix strings Excel might reinterpret.
                cell.data_type = "s"
            elif key in {"quantity", "available_quantity"}:
                cell.number_format = "0.####"
            elif key == "in_date":
                cell.number_format = "yyyy-mm-dd"
            cells.append(cell)
        sheet.append(cells)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
